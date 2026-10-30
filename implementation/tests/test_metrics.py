import math

import pytest

from guarded_autonomy.metrics.component import paired_difference, rejected_useful, safe_ratio, summarise_cc
from guarded_autonomy.metrics.harm import LabelledDecision, harm_breakdown, shield_metrics
from guarded_autonomy.metrics.network import (
    FailureEvent,
    PacketRecord,
    delay_stats,
    normalised_routing_overhead,
    pdr,
    recovery_times,
)
from guarded_autonomy.metrics.stats import t_cdf, t_interval, t_ppf, wilcoxon_signed_rank
from guarded_autonomy.schemas import Tier


@pytest.mark.parametrize("df,q", [(9, 2.2621571628), (1, 12.7062047362), (4, 2.7764451052), (30, 2.0422724563)])
def test_t_ppf_known_values(df, q):
    assert abs(t_ppf(0.975, df) - q) < 1e-6
    assert abs(t_cdf(q, df) - 0.975) < 1e-9


def test_t_ppf_approaches_normal():
    assert abs(t_ppf(0.975, 1e6) - 1.959964) < 1e-4


def test_t_interval():
    m, h = t_interval([1.0, 2.0, 3.0, 4.0])
    assert m == 2.5 and abs(h - 3.182446305 * math.sqrt(5 / 3) / 2) < 1e-6
    m1, h1 = t_interval([3.0])
    assert m1 == 3.0 and math.isnan(h1)
    with pytest.raises(ValueError):
        t_interval([])


def test_wilcoxon_exact():
    x = [0.0] * 10
    y = [0.1 * (k + 1) for k in range(10)]
    w, p, n = wilcoxon_signed_rank(x, y)
    assert n == 10 and w == 55 and abs(p - 2 / 1024) < 1e-12        # smallest two-sided p for n=10
    _, p0, n0 = wilcoxon_signed_rank([1, 2], [1, 2])
    assert p0 == 1.0 and n0 == 0
    _, pt, nt = wilcoxon_signed_rank([0, 0, 0, 0], [1, -1, 2, 0])  # zero dropped, ties averaged
    assert nt == 3 and 0 < pt <= 1


def test_wilcoxon_normal_branch():
    x = [0.0] * 30
    y = [float(k + 1) for k in range(30)]
    _, p, n = wilcoxon_signed_rank(x, y)
    assert n == 30 and p < 1e-4
    with pytest.raises(ValueError):
        wilcoxon_signed_rank([1], [1, 2])


def test_network_metrics():
    pk = [PacketRecord(0, 0, 0.0, 0.1), PacketRecord(0, 1, 1.0, None), PacketRecord(1, 0, 0.0, 0.3),
          PacketRecord(0, 2, 6.0, 6.5)]
    assert pdr(pk) == 0.75
    ds = delay_stats(pk)
    assert abs(ds["median_s"] - 0.3) < 1e-12
    assert math.isnan(pdr([])) and math.isnan(delay_stats([PacketRecord(0, 0, 0, None)])["p95_s"])
    assert normalised_routing_overhead(30, 3) == 10.0 and math.isnan(normalised_routing_overhead(5, 0))
    with pytest.raises(ValueError):
        normalised_routing_overhead(1, 1, mode="bytes")
    rec = recovery_times(pk, [FailureEvent(5.0, [0, 1])])
    assert rec["n_recovered"] == 1 and rec["n_censored"] == 1 and abs(rec["mean_s"] - 1.5) < 1e-12


def test_shield_metrics():
    ds = [LabelledDecision(Tier.AGENT, True, {"H-loop"}), LabelledDecision(Tier.BASE, True, {"H-iso"}),
          LabelledDecision(Tier.AGENT, True, set()), LabelledDecision(Tier.NULL, True, set()),
          LabelledDecision(Tier.BASE, False, set())]
    m = shield_metrics(ds)
    assert m["harmful_proposals"] == 2 and m["blocked_fraction"] == 0.5 and m["residual_harm"] == 1
    assert m["false_positive_rate"] == 0.5 and m["tier_share_base"] == 0.4
    assert harm_breakdown(ds) == {"H-loop": 1, "H-iso": 1}
    assert math.isnan(shield_metrics([])["blocked_fraction"])


def _row(seed, mode, prop, valid, n=20, vmax=20.0, **kw):
    base = dict(suite="cc1", seed=seed, mode=mode, proposer=prop, n=n, vmax=vmax, valid_frac=valid, loop_step_frac=0.0,
                steps=10, proposals=4, loop_creating=1, loop_creating_committed=0, useful_safe=4,
                useful_safe_rejected=2, useful_safe_rejected_routeless=1, lat_median_us=5.0, viol_counts="{}")
    base.update(kw)
    return base


def test_component_aggregation():
    rows = [_row(s, "base", "none", 0.5 + 0.01 * s) for s in range(3)]
    rows += [_row(s, "shielded", "stable", 0.52 + 0.01 * s) for s in range(3)]
    rows += [_row(s, "shielded", "rand", 0.5) for s in range(3)]
    assert rejected_useful(rows[3:6]) == (0.5, 0.25)
    pdiff = paired_difference(rows[:3], rows[3:6], "valid_frac")
    assert abs(pdiff["mean_diff"] - 0.02) < 1e-12
    s = summarise_cc(rows)
    assert s["cc1_shielded_loop_creating_proposals"] == 6 and s["cc1_shielded_loop_creating_committed"] == 0
    assert math.isnan(safe_ratio(1, 0))
