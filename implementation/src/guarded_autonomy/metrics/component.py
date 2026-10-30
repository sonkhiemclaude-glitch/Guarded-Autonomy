"""Aggregation of abstract-model result rows into the quantities reported in Sec. 6
(Tables 4-6, A.9, Fig. 3). All values are computed from result rows; nothing is hard-coded.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from .stats import t_interval, wilcoxon_signed_rank

Row = Mapping[str, Any]


def safe_ratio(num: float, den: float) -> float:
    """num/den, NaN when den == 0."""
    return num / den if den else float("nan")


def group_rows(rows: Iterable[Row], keys: Sequence[str]) -> Dict[Tuple[Any, ...], List[Row]]:
    g: Dict[Tuple[Any, ...], List[Row]] = defaultdict(list)
    for r in rows:
        g[tuple(_norm(r[k]) for k in keys)].append(r)
    return g


def _norm(v: Any) -> Any:
    if isinstance(v, str):
        try:
            f = float(v)
            return int(f) if f.is_integer() and "." not in v else f
        except ValueError:
            return v
    return v


def column(rows: Sequence[Row], key: str) -> List[float]:
    """Values of ``key`` ordered by seed (pairing across configurations)."""
    return [float(r[key]) for r in sorted(rows, key=lambda r: int(float(r["seed"])))]


def total(rows: Sequence[Row], key: str) -> int:
    return sum(int(float(r[key])) for r in rows)


def mean_ci(rows: Sequence[Row], key: str) -> Tuple[float, float]:
    return t_interval(column(rows, key))


def rejected_useful(rows: Sequence[Row]) -> Tuple[float, float]:
    """(share of useful proposals rejected, share rejected at routeless nodes), pooled (Sec. 6.2)."""
    us = total(rows, "useful_safe")
    return (safe_ratio(total(rows, "useful_safe_rejected"), us),
            safe_ratio(total(rows, "useful_safe_rejected_routeless"), us))


def violation_totals(rows: Iterable[Row]) -> Dict[str, int]:
    out: Dict[str, int] = defaultdict(int)
    for r in rows:
        for k, v in json.loads(r.get("viol_counts") or "{}").items():
            out[k] += int(v)
    return dict(out)


def paired_difference(base: Sequence[Row], other: Sequence[Row], key: str) -> Dict[str, float]:
    """Mean paired difference (other - base) with t-interval and exact Wilcoxon p."""
    base_seeds = [int(float(r["seed"])) for r in base]
    other_seeds = [int(float(r["seed"])) for r in other]
    if len(set(base_seeds)) != len(base_seeds) or len(set(other_seeds)) != len(other_seeds):
        raise ValueError("duplicate seeds in paired groups")
    if set(base_seeds) != set(other_seeds):
        raise ValueError("paired groups must have identical seed ids")
    b, o = column(base, key), column(other, key)
    if len(b) != len(o):
        raise ValueError("unpaired groups")
    diffs = [y - x for x, y in zip(b, o)]
    m, h = t_interval(diffs)
    _, p, n = wilcoxon_signed_rank(b, o)
    return {"mean_diff": m, "ci95": h, "wilcoxon_p": p, "n_nonzero": float(n)}


def summarise_cc(rows: Sequence[Row]) -> Dict[str, Any]:
    """Headline component-check quantities in the form used by Sec. 6 (computed, not copied)."""
    out: Dict[str, Any] = {}
    cc1 = [r for r in rows if r["suite"] == "cc1"]
    if cc1:
        sh = [r for r in cc1 if r["mode"] == "shielded"]
        un = [r for r in cc1 if r["mode"] == "unshielded"]
        out["cc1_runs"] = len(cc1)
        out["cc1_shielded_runs"] = len(sh)
        out["cc1_shielded_proposals"] = total(sh, "proposals")
        out["cc1_shielded_loop_creating_proposals"] = total(sh, "loop_creating")
        out["cc1_shielded_loop_creating_committed"] = total(sh, "loop_creating_committed")
        out["cc1_shielded_steps_with_loop"] = sum(round(float(r["loop_step_frac"]) * int(float(r["steps"]))) for r in sh)
        out["cc1_unshielded_proposals"] = total(un, "proposals")
        out["cc1_unshielded_loop_creating_committed"] = total(un, "loop_creating_committed")
        g = group_rows(sh, ("vmax", "n", "proposer"))
        per = {k: rejected_useful(v) for k, v in g.items() if k[2] != "stable"}
        if per:
            out["cc1_rejected_useful_range"] = [min(a for a, _ in per.values()), max(a for a, _ in per.values())]
            out["cc1_rejected_useful_routeless_range"] = [min(b for _, b in per.values()), max(b for _, b in per.values())]
        lat = [float(r["lat_median_us"]) for r in sh if r.get("lat_median_us") not in (None, "", "None")]
        if lat:
            out["cc1_latency_median_us_range"] = [min(lat), max(lat)]
        gb = group_rows([r for r in cc1 if r["mode"] == "base"], ("vmax", "n"))
        gs = group_rows([r for r in sh if r["proposer"] == "stable"], ("vmax", "n"))
        out["cc1_stable_vs_feasibility_rule"] = {f"v{k[0]}_n{k[1]}": paired_difference(gb[k], gs[k], "valid_frac")
                                                for k in gb if k in gs and len(gb[k]) == len(gs[k]) and len(gb[k]) > 1}
    for suite in ("cc2", "cc3"):
        sub = [r for r in rows if r["suite"] == suite]
        if not sub:
            continue
        keys = ("attack", "adv_frac", "mode", "cfg") if suite == "cc2" else ("wd_err", "trust_max_isolate", "mode")
        res = {}
        for k, v in group_rows(sub, keys).items():
            entry = {c: mean_ci(v, c)[0] for c in ("adv_traverse_frac", "valid_frac", "loop_step_frac")
                     if c in v[0]}
            if "adv_direct_frac" in v[0]:
                entry["adv_direct_frac"] = mean_ci(v, "adv_direct_frac")[0]
            if suite == "cc3":
                for c in ("iso_honest_prop", "iso_honest_commit", "iso_adv_prop", "iso_adv_commit"):
                    entry[c] = total(v, c)
            res["|".join(str(x) for x in k)] = entry
        out[suite] = res
    return _clean(out)


def _clean(obj: Any) -> Any:
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj
