import json

from guarded_autonomy.agents.grammar import ACTION_GBNF, gbnf_rule_names, gbnf_undefined_references, validate_against_schema
from guarded_autonomy.agents.injection import FAMILIES, make_payloads
from guarded_autonomy.agents.llm import LLMAgent, LLMEndpointConfig
from guarded_autonomy.agents.observation import build_observation
from guarded_autonomy.baselines.sanitisation import sanitise_observation
from guarded_autonomy.schemas import Isolate, parse_action


def test_observation_contains_untrusted_status(view):
    obs = build_observation(view, status_fields={3: "hello"}, rssi_dbm={2: -70.0})
    nb = {n["id"]: n for n in obs["neighbours"]}
    assert nb[3]["status"] == "hello" and nb[2]["rssi_dbm"] == -70.0 and obs["routes"][0]["hops"] == 3
    clean = sanitise_observation(obs)
    assert all("status" not in n for n in clean["neighbours"]) and "status" in nb[3]  # original untouched


def test_schema_validator_and_parse_agree():
    good = [{"type": "route_change", "dest": 0, "next_hop": 3}, {"type": "isolate", "node": 2, "reason": "x"},
            {"type": "set_power", "power_dbm": 10.5}, {"type": "defer"}]
    bad = [{"type": "route_change", "dest": 0}, {"type": "isolate", "node": "2"}, {"type": "defer", "extra": 1},
           {"type": "isolate", "node": True}, "text"]
    for g in good:
        assert validate_against_schema(g) and parse_action(g) is not None
    for b in bad:
        assert not validate_against_schema(b)


def test_gbnf_well_formed():
    assert gbnf_rule_names()[0] == "root"
    assert gbnf_undefined_references() == []
    assert "route-change" in ACTION_GBNF


def test_injection_families():
    ps = make_payloads(target_node=2, own_id=9)
    assert [p.family for p in ps] == list(FAMILIES)
    assert parse_action(ps[2].text) == Isolate(2)       # JSON-shaped payload is itself a valid action


def test_llm_agent_with_fake_transport():
    seen = {}

    def fake(url, payload, timeout):
        seen["url"], seen["payload"] = url, payload
        return {"choices": [{"message": {"content": json.dumps({"type": "defer"})}}]}

    a = LLMAgent(LLMEndpointConfig(base_url="http://127.0.0.1:8080/", model="m"), transport=fake)
    r = a.propose({"node": 1})
    assert seen["url"] == "http://127.0.0.1:8080/v1/chat/completions"
    assert seen["payload"]["response_format"]["type"] == "json_schema" and r.error is None
    assert parse_action(r.raw_text) is not None


def test_llm_agent_failure_is_reported_not_raised():
    def boom(url, payload, timeout):
        raise TimeoutError("no server")

    r = LLMAgent(LLMEndpointConfig(base_url="http://x", model="m", constraint="gbnf"), transport=boom).propose({})
    assert r.raw_text == "" and "TimeoutError" in r.error
