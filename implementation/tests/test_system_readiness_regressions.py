import json
import math

import pytest

from guarded_autonomy.agents.grammar import validate_against_schema
from guarded_autonomy.data.synthetic import write_synthetic_run
from guarded_autonomy.experiments.tables import system_table
from guarded_autonomy.metrics.component import paired_difference
from guarded_autonomy.ns3.adapters import summarise_run
from guarded_autonomy.ns3.runner import plan
from guarded_autonomy.ns3.settings import resolve_bridge
from guarded_autonomy.schemas import Isolate, RouteChange, SetPower, parse_action


@pytest.mark.parametrize("value", [2.9, True, "2", 2.0])
def test_node_ids_are_not_coerced(value):
    assert parse_action({"type": "isolate", "node": value}) is None
    assert parse_action(Isolate(value)) is None
    assert parse_action(RouteChange(0, value)) is None


@pytest.mark.parametrize("value", [True, "2", float("nan"), float("inf")])
def test_power_requires_finite_json_number(value):
    assert parse_action({"type": "set_power", "power_dbm": value}) is None
    assert parse_action(SetPower(value)) is None
    assert not validate_against_schema({"type": "set_power", "power_dbm": value})


def test_conditions_and_seed_duplicates():
    row = {"experiment": "E1", "configuration": "shielded", "model": "a", "seed": 0, "pdr": .2}
    table = system_table([row, {**row, "model": "b", "pdr": .8}])
    assert len(table) == 2 and all(r["n_runs"] == 1 for r in table)
    with pytest.raises(ValueError, match="duplicate seed"):
        system_table([row, row])


def test_unknown_harm_is_not_evidence_of_safety(tmp_path):
    run = write_synthetic_run(tmp_path, "shielded", 0)
    records = [json.loads(line) for line in (run / "decisions.jsonl").read_text().splitlines()]
    for record in records:
        record["harm"] = None
    (run / "decisions.jsonl").write_text("\n".join(json.dumps(r) for r in records))
    row = summarise_run(run)
    assert not row["harm_labels_available"] and row["unknown_harm_proposals"] > 0
    assert math.isnan(row["harmful_proposals"]) and math.isnan(row["false_positive_rate"])


def test_pairing_requires_exact_seed_identity():
    with pytest.raises(ValueError, match="seed ids"):
        paired_difference([{"seed": 0, "x": 1}], [{"seed": 1, "x": 2}], "x")


def test_replanning_cannot_erase_finished_status(tmp_path):
    block = {"experiments": {"E": {"n_seeds": 1, "axes": {"configuration": ["aodv"]}}}}
    directory = plan(block, tmp_path)[0]
    path = directory / "run_config.json"
    cfg = json.loads(path.read_text())
    cfg["status"] = "finished"
    path.write_text(json.dumps(cfg))
    with pytest.raises(FileExistsError):
        plan(block, tmp_path)
    assert json.loads(path.read_text())["status"] == "finished"


@pytest.mark.parametrize("config", ["aodv", "olsr", "trust_aware_aodv", "unshielded", "shielded",
                                    "shielded_no_I3", "shielded_no_I4c", "shielded_no_tier2", "sanitised_unshielded"])
def test_each_configuration_resolves_its_actual_behavior(config):
    block = {"bridge": {"agent": {"base_url": "http://127.0.0.1:18081", "model": "draft"}}}
    actual = resolve_bridge(block, {"configuration": config, "model": "pinned", "seed": 3})
    assert actual["sanitise_inputs"] == (config == "sanitised_unshielded")
    if config in {"aodv", "olsr", "trust_aware_aodv"}:
        assert "agent" not in actual
    else:
        assert actual["agent"]["model"] == "pinned" and actual["agent"]["extra"]["seed"] == 3
    assert actual["shield"]["tier2_enabled"] == (config != "shielded_no_tier2")
    assert actual["shield"]["use_trust"] == (config != "shielded_no_I3")


def test_bridge_persists_base_and_unshielded_decisions(tmp_path):
    from guarded_autonomy.config import ShieldConfig
    from guarded_autonomy.decision_log import HashChainLog
    from guarded_autonomy.ns3.bridge import BridgeState, handle_message
    from guarded_autonomy.ns3.protocol import view_to_json
    from guarded_autonomy.schemas import LocalView
    view = LocalView(node_id=1, neighbours={2})
    view.adv[0] = {2: (6, 1)}
    state = BridgeState(ShieldConfig(use_trust=False), run_dir=tmp_path)
    decision = handle_message(state, {"type": "base_commit", "node": 1, "view": view_to_json(view),
                                      "action": {"type": "route_change", "dest": 0, "next_hop": 2}})
    assert decision["tier"] == "base" and not decision["agent_called"]
    handle_message(state, {"type": "anchor", "node": 1})
    anchors = json.loads((tmp_path / "chain_anchors.json").read_text())
    assert anchors["1"]["length"] == 1
    assert HashChainLog.load_jsonl(tmp_path / "chain-node-1.jsonl").verify(anchors["1"]["head"])


def test_deferred_commit_revalidates_without_calling_model_twice(view):
    from guarded_autonomy.config import ShieldConfig
    from guarded_autonomy.ns3.bridge import BridgeState, handle_message
    from guarded_autonomy.ns3.protocol import view_to_json
    calls = []
    def agent(observation):
        calls.append(observation)
        return '{"type":"route_change","dest":0,"next_hop":4}'
    state = BridgeState(ShieldConfig(use_trust=False), agent=agent)
    prepared = handle_message(state, {"type": "propose", "node": 1, "view": view_to_json(view)})
    assert len(calls) == 1 and state.shields[1].log.anchor()["length"] == 0
    view.neighbours.discard(4)
    result = handle_message(state, {"type": "decide", "node": 1, "view": view_to_json(view),
                                     "raw_proposal": prepared["raw_proposal"], "base_candidates": []})
    assert result["tier"] == "null" and "I1:symmetric-neighbour" in result["violated"]
    assert len(calls) == 1


def test_no_tier2_still_checks_and_accepts_native_protocol_commits(tmp_path):
    from guarded_autonomy.config import ShieldConfig
    from guarded_autonomy.ns3.bridge import BridgeState, handle_message
    from guarded_autonomy.ns3.protocol import view_to_json
    from guarded_autonomy.schemas import LocalView
    view = LocalView(node_id=1, neighbours={2})
    view.adv[0] = {2: (6, 1)}
    state = BridgeState(ShieldConfig(use_trust=False, tier2_enabled=False), run_dir=tmp_path)
    reply = handle_message(state, {"type": "base_commit", "node": 1, "view": view_to_json(view),
                                    "action": {"type": "route_change", "dest": 0, "next_hop": 2}})
    assert reply["tier"] == "base" and reply["action"]["next_hop"] == 2


def test_archived_outputs_remain_readable_and_verifiable(tmp_path):
    import gzip

    from guarded_autonomy.decision_log import HashChainLog
    from guarded_autonomy.ns3.adapters import collect
    run = write_synthetic_run(tmp_path, "shielded", 0)
    original = summarise_run(run)
    for name in ["packets.csv", "control.csv", "decisions.jsonl", "failures.csv"]:
        path = run / name
        with gzip.open(str(path) + ".gz", "wb") as stream:
            stream.write(path.read_bytes())
        path.unlink()
    archived = summarise_run(run)
    assert archived["pdr"] == original["pdr"] and archived["proposal_count"] == original["proposal_count"]
    assert len(collect(tmp_path)) == 1
    chain = HashChainLog()
    chain.append({"committed": "action"})
    path = tmp_path / "chain.jsonl"
    chain.save_jsonl(path)
    with gzip.open(str(path) + ".gz", "wb") as stream:
        stream.write(path.read_bytes())
    path.unlink()
    assert HashChainLog.load_jsonl(path).verify(chain.head)


def test_censor_aware_recovery_keeps_unrecovered_flows():
    from guarded_autonomy.metrics.network import FailureEvent, PacketRecord, recovery_times
    result = recovery_times([PacketRecord(0, 0, 6, 7)], [FailureEvent(5, [0, 1])], horizon_s=15)
    assert result["n_recovered"] == 1 and result["n_censored"] == 1
    assert result["mean_s"] == 2 and result["rmst_s"] == 6 and result["recovered_fraction"] == .5


@pytest.mark.parametrize("value", [10 ** 500, -(10 ** 500)])
def test_unrepresentable_power_cannot_crash_schema_guard(value):
    assert parse_action({"type": "set_power", "power_dbm": value}) is None
    assert not validate_against_schema({"type": "set_power", "power_dbm": value})
