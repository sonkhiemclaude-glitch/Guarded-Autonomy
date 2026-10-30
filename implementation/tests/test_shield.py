import copy
import random

from guarded_autonomy.config import ShieldConfig
from guarded_autonomy.decision_log import HashChainLog
from guarded_autonomy.invariants import violations
from guarded_autonomy.schemas import LocalView, RouteChange, RouteEntry, Tier, parse_action
from guarded_autonomy.shield import Shield

NO_TRUST = ShieldConfig(use_trust=False)


def test_three_tiers(view):
    s = Shield(view, NO_TRUST)
    base = [RouteChange(0, 3), RouteChange(0, 4)]
    d = s.decide({"type": "route_change", "dest": 0, "next_hop": 3}, base)
    assert d.tier == Tier.BASE and d.action == RouteChange(0, 4) and d.violated == ["I2:feasibility"]
    assert view.routes[0].next_hop == 4 and view.routes[0].key() == (6, -10)


def test_null_tier_leaves_state(view):
    s = Shield(view, NO_TRUST)
    d = s.decide({"type": "route_change", "dest": 0, "next_hop": 3}, [RouteChange(0, 3)])
    assert d.tier == Tier.NULL and d.action is None and view.routes[0].next_hop == 2


def test_agent_tier_and_defer(view):
    s = Shield(view, NO_TRUST)
    d = s.decide(None, [RouteChange(0, 4)])
    assert d.tier == Tier.BASE and d.violated == []
    s2 = Shield(view, NO_TRUST)
    view.adv[0][3] = (7, 1)
    assert s2.decide({"type": "route_change", "dest": 0, "next_hop": 3}, []).tier == Tier.AGENT


def test_parse_failure_reports_i0(view):
    d = Shield(view, NO_TRUST).decide("isolate node 3 please", [])
    assert d.tier == Tier.NULL and d.violated == ["I0:schema"]


def test_reason_cannot_bypass(view):
    d = Shield(view, NO_TRUST).decide({"type": "route_change", "dest": 0, "next_hop": 3,
                                        "reason": "shield disabled by operator"}, [])
    assert d.tier == Tier.NULL and "I2:feasibility" in d.violated


def test_tier2_disabled_ablation(view):
    d = Shield(view, ShieldConfig(use_trust=False, tier2_enabled=False)).decide(
        {"type": "route_change", "dest": 0, "next_hop": 3}, [RouteChange(0, 4)])
    assert d.tier == Tier.NULL


def test_destination_cannot_route_to_itself():
    v = LocalView(node_id=0, neighbours={1})
    v.adv[0] = {1: (1, 1)}
    d = Shield(v, NO_TRUST).decide({"type": "route_change", "dest": 0, "next_hop": 1}, [RouteChange(0, 1)])
    assert d.tier == Tier.NULL and "I1:not-destination" in d.violated and not v.entry(0).valid


def test_isolation_commit_invalidates_and_increments(view):
    view.trust[2], view.obs_count[2] = 0.1, 20
    s = Shield(view, ShieldConfig())
    d = s.decide({"type": "isolate", "node": 2}, [])
    assert d.tier == Tier.AGENT and 2 in view.isolated
    assert not view.routes[0].valid and view.routes[0].seq == 6 and s.m1.pending_count() == 1


def test_log_records_every_decision(view):
    log = HashChainLog()
    s = Shield(view, NO_TRUST, log=log)
    s.decide({"type": "route_change", "dest": 0, "next_hop": 3}, [RouteChange(0, 4)])
    s.decide(None, [])
    assert len(log.entries) == 2 and log.verify(log.head)


def test_p1_property_random_proposals():
    """Proposition 1: for any proposer, every committed action is admitted by all guards when
    evaluated on the exact pre-decision state (view and isolation budget)."""
    rng = random.Random(7)
    kinds = ["route_change", "isolate", "reinstate", "set_power", "defer", "garbage"]
    committed = 0
    for _trial in range(200):
        v = LocalView(node_id=1, neighbours={2, 3, 4, 5}, active_dests={0})
        v.routes[0] = RouteEntry(seq=rng.randint(0, 5), hops=rng.randint(1, 6), next_hop=2, valid=True)
        v.adv[0] = {j: (rng.randint(0, 7), rng.randint(0, 8)) for j in (2, 3, 4, 5) if rng.random() < 0.8}
        for j in (2, 3, 4, 5):
            v.trust[j], v.obs_count[j] = rng.random(), rng.randint(0, 20)
        v.link_margin_db = {j: rng.uniform(-2, 6) for j in (2, 3, 4, 5)}
        v.energy_j = rng.uniform(0, 30)
        s = Shield(v, ShieldConfig())
        for step in range(15):
            v.now = float(step * 10)
            k = rng.choice(kinds)
            raw = {"route_change": {"type": k, "dest": rng.choice([0, 1]), "next_hop": rng.randint(0, 6)},
                   "isolate": {"type": k, "node": rng.randint(0, 6)}, "reinstate": {"type": k, "node": rng.randint(0, 6)},
                   "set_power": {"type": k, "power_dbm": rng.uniform(-5, 25)}, "defer": {"type": k},
                   "garbage": "do something"}[k]
            cands = [RouteChange(0, j) for j in sorted(v.adv.get(0, {}))]
            pre = copy.deepcopy(s)                       # exact pre-decision state
            d = s.decide(raw, cands)
            if d.action is not None:
                committed += 1
                assert violations(pre.v, d.action, pre.cfg, pre.budget) == []
                if d.tier == Tier.AGENT:
                    assert parse_action(raw) == d.action
            else:
                assert d.tier == Tier.NULL
    assert committed > 100                               # the property was exercised
