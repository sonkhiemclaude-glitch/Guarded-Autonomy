from guarded_autonomy.config import ShieldConfig
from guarded_autonomy.invariants import (
    IsolationBudget,
    ReviewObligationMonitor,
    check_isolate,
    check_route_change,
    check_set_power,
    is_feasible,
    olsr_downhill_violations,
    violations,
)
from guarded_autonomy.schemas import Isolate, LocalView, Reinstate, RouteChange, RouteEntry, SetPower

NO_TRUST = ShieldConfig(use_trust=False)


def test_i0_parse_failure():
    assert violations(LocalView(node_id=1), None, NO_TRUST, IsolationBudget()) == ["I0:schema"]


def test_i1(view):
    assert check_route_change(view, RouteChange(1, 2), NO_TRUST) == ["I1:not-destination"]
    assert check_route_change(view, RouteChange(0, 9), NO_TRUST) == ["I1:symmetric-neighbour"]
    assert check_route_change(view, RouteChange(0, 1), NO_TRUST) == ["I1:symmetric-neighbour"]
    view.isolated.add(4)
    assert "I1:not-isolated" in check_route_change(view, RouteChange(0, 4), NO_TRUST)


def test_i2_feasibility_equal_seq_requires_strictly_shorter(view):
    assert not is_feasible((5, 2), view.routes[0])                 # 2+1 == 3, not < 3
    assert is_feasible((6, 9), view.routes[0])                     # fresher seq, any hops
    assert is_feasible((5, 1), view.routes[0])                     # 1+1 < 3
    assert check_route_change(view, RouteChange(0, 3), NO_TRUST) == ["I2:feasibility"]
    del view.adv[0][3]
    assert check_route_change(view, RouteChange(0, 3), NO_TRUST) == ["I2:no-advertisement"]


def test_concept_rule_admits_two_node_loop_but_i2_does_not():
    a, b = RouteEntry(5, 4, 9, True), RouteEntry(5, 2, 9, True)       # Fig. 2 values
    concept = lambda own, adv: adv[0] >= own.seq  # noqa: E731
    assert concept(a, (b.seq, b.hops)) and concept(b, (a.seq, a.hops - 1))
    assert is_feasible((b.seq, b.hops), a)                         # a -> b accepted
    a2 = RouteEntry(5, 3, None, True)                              # a after adopting b: (5, 3)
    assert not is_feasible((a2.seq, a2.hops), b)                   # b -> a rejected


def test_i3_evidence_based(view):
    cfg = ShieldConfig()
    view.trust[3], view.obs_count[3] = 0.2, 3                       # too few observations: admitted
    view.adv[0][3] = (6, 1)
    assert check_route_change(view, RouteChange(0, 3), cfg) == []
    view.obs_count[3] = 5
    assert check_route_change(view, RouteChange(0, 3), cfg) == ["I3:trust-next-hop"]


def test_i4_isolation(view):
    cfg = ShieldConfig(iso_max_in_window=1)
    b = IsolationBudget()
    view.trust.update({2: 0.9, 3: 0.1, 4: 0.1})
    view.obs_count.update({2: 10, 3: 10, 4: 2})
    assert check_isolate(view, Isolate(1), cfg, b) == ["I4:target"]
    assert check_isolate(view, Isolate(9), cfg, b) == ["I4:target"]
    assert "I4a:trust-threshold" in check_isolate(view, Isolate(2), cfg, b)
    assert "I4b:evidence-precedence" in check_isolate(view, Isolate(4), cfg, b)
    assert check_isolate(view, Isolate(3), cfg, b) == []
    b.record(view.now)
    view.isolated.add(3)
    assert check_isolate(view, Isolate(3), cfg, b) == ["I4:already-isolated"]
    view.obs_count[4] = 10
    assert "I4c:rate-limit" in check_isolate(view, Isolate(4), cfg, b)
    view.now = 61.0
    assert check_isolate(view, Isolate(4), cfg, b) == []


def test_isolation_budget_buffer_capped():
    b = IsolationBudget()
    for t in range(10):
        b.record(float(t))
    b.prune(now=10.0, window_s=60.0, k=2)
    assert b.count() == 2                                           # Prop. 3: at most k timestamps


def test_i4d_reinstate(view):
    assert violations(view, Reinstate(3), NO_TRUST, IsolationBudget()) == ["I4:reinstate-precedence"]
    view.isolated.add(3)
    assert violations(view, Reinstate(3), NO_TRUST, IsolationBudget()) == []


def test_i5_i6_power(view):
    cfg = ShieldConfig()
    view.link_margin_db = {2: 3.0}
    view.energy_j = 5.0
    assert "I6:energy-floor" in check_set_power(view, SetPower(18), cfg)
    assert "I5b:keep-active-links" in check_set_power(view, SetPower(12), cfg)
    assert check_set_power(view, SetPower(14), cfg) == []
    assert "I5a:power-range" in check_set_power(view, SetPower(30), cfg)
    view.link_margin_db = {}                                        # unknown margin: conservative reject
    assert "I5b:keep-active-links" in check_set_power(view, SetPower(15.5), cfg)


def test_olsr_downhill():
    v = LocalView(node_id=1)
    # line topology 0 - 2 - 1 - 3 as known by node 1
    v.topology = {0: {2}, 2: {0, 1}, 1: {2, 3}, 3: {1}}
    assert olsr_downhill_violations(v, 0, 2) == []
    assert olsr_downhill_violations(v, 0, 3) == ["OLSR:downhill"]
    assert olsr_downhill_violations(v, 0, 5) == ["OLSR:symmetric-neighbour"]
    v.topology[3] = set()                                           # asymmetric link
    assert olsr_downhill_violations(v, 0, 3) == ["OLSR:symmetric-neighbour"]
    assert olsr_downhill_violations(v, 7, 2) == ["OLSR:unreachable"]
    v.neighbours = {2, 3}
    assert check_route_change(v, RouteChange(0, 2), ShieldConfig(use_trust=False, use_olsr_downhill=True)) == []


def test_m1_obligation_monitor():
    m = ReviewObligationMonitor(deadline_s=10)
    m.on_isolate(3, now=0.0)
    assert m.pending_count() == 1 and m.overdue(5.0) == []
    assert [o.node for o in m.overdue(11.0)] == [3]
    m.on_review(3, now=12.0)
    assert m.pending_count() == 0 and m.closed[0].closed_at == 12.0
