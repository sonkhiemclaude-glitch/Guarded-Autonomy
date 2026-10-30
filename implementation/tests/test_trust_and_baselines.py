import pytest

from guarded_autonomy.baselines import BASELINE_REGISTRY
from guarded_autonomy.baselines.aodv import feasibility_rule_update, rank_candidates
from guarded_autonomy.baselines.trust_aware import trust_aware_update
from guarded_autonomy.trust import WatchdogTrust, beta_trust


def test_beta_trust():
    assert beta_trust(0, 0) == 0.5 and beta_trust(8, 0) == 0.9 and beta_trust(0, 8) == 0.1
    with pytest.raises(ValueError):
        beta_trust(-1, 0)
    w = WatchdogTrust()
    for d in (False, False, True):
        w.observe(7, d)
    assert w.observations(7) == 3 and w.trust(7) == pytest.approx(3 / 5) and w.trust(99) == 0.5


def test_rank_and_feasibility_rule(view):
    assert [c.next_hop for c in rank_candidates(view, 0)] == [4, 2, 3]   # freshest seq first, then hops, then id
    view.isolated.add(4)
    assert [c.next_hop for c in rank_candidates(view, 0)] == [2, 3]
    assert feasibility_rule_update(view, 0) is None                       # (5,2)+1 = 3 hops, not shorter than 3


def test_trust_aware_filters_low_trust(view):
    view.trust[4], view.obs_count[4] = 0.2, 20
    b = trust_aware_update(view, 0)
    assert b is None or b.next_hop != 4
    view.trust[4], view.obs_count[4] = 0.9, 20
    assert trust_aware_update(view, 0).next_hop == 4
    assert view.routes[0].key() == (6, -10)


def test_registry_tags():
    assert {"real", "external"} >= {e["kind"] for e in BASELINE_REGISTRY.values()}
