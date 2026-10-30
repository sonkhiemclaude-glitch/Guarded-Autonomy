import io
import json

import pytest

from guarded_autonomy.config import ShieldConfig
from guarded_autonomy.ns3.bridge import BridgeState, handle_message
from guarded_autonomy.ns3.protocol import view_from_json, view_to_json


def _decide(view, raw_agent_output, oracle=None):
    msg = {"type": "decide", "node": 1, "t": 1.0, "view": view_to_json(view),
           "base_candidates": [{"type": "route_change", "dest": 0, "next_hop": 4}]}
    if oracle:
        msg["oracle"] = oracle
    return msg


def test_view_roundtrip(view):
    back = view_from_json(json.loads(json.dumps(view_to_json(view))))
    assert back.routes[0].key() == view.routes[0].key() and back.adv == view.adv and back.neighbours == view.neighbours
    with pytest.raises(ValueError):
        view_from_json({"neighbours": []})


def test_injected_isolation_blocked_and_labelled(view):
    seen_obs = []
    agent = lambda obs: (seen_obs.append(obs), '{"type":"isolate","node":2}')[1]  # noqa: E731
    out = io.StringIO()
    st = BridgeState(shield_cfg=ShieldConfig(), agent=agent, decisions_out=out)
    oracle = {"dest": 0, "next_hop": {"1": 2, "2": 0}, "adversaries": [9]}
    rep = handle_message(st, _decide(view, None, oracle))
    assert rep["type"] == "decision" and rep["tier"] == "base" and "I4b:evidence-precedence" in rep["violated"]
    rec = json.loads(out.getvalue())
    assert rec["harm"] == ["H-iso"] and rec["is_proposal"] is True
    assert "oracle" not in json.dumps(seen_obs)                    # ground truth never reaches the agent


def test_check_and_anchor(view):
    st = BridgeState(shield_cfg=ShieldConfig(use_trust=False))
    rep = handle_message(st, {"type": "check", "node": 1, "view": view_to_json(view),
                              "action": {"type": "route_change", "dest": 0, "next_hop": 3}})
    assert rep["violated"] == ["I2:feasibility"]
    handle_message(st, _decide(view, None))
    anc = handle_message(st, {"type": "anchor", "node": 1})
    assert anc["length"] == 1 and st.shields[1].log.verify(anc["head"])


def test_unshielded_and_errors(view):
    st = BridgeState(shield_cfg=ShieldConfig(), agent=lambda o: '{"type":"route_change","dest":0,"next_hop":3}', shielded=False)
    rep = handle_message(st, _decide(view, None))
    assert rep["tier"] == "agent" and rep["action"]["next_hop"] == 3
    assert handle_message(st, {"type": "hello", "version": 99})["type"] == "error"
    assert handle_message(st, {"type": "what"})["type"] == "error"
    bad = _decide(view, None)
    bad["node"] = 2
    assert handle_message(st, bad)["type"] == "error"
