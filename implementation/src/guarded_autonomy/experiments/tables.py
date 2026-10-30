"""Tables generated from result files only (no hard-coded numbers).

* Component check: CSV and LaTeX bodies with the structure of the paper's Tables 4 (CC1 at N=50),
  5 (CC2) and 6 (CC3), and A.9 (CC1 all settings).
* System level: Table 7 shape (configuration x PDR, delay p95, harmful proposals, blocked, FPR).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from ..metrics.component import group_rows, mean_ci, rejected_useful, total
from ..metrics.stats import t_interval
from ..utils.io import write_csv

NAMES = {"rand": "Random", "greedy": "Greedy", "adv": "Adversarial", "stable": "Stable-link"}


def _pm(m: float, h: float, pct: bool = True) -> str:
    if pct:
        return f"{100 * m:.1f} $\\pm$ {100 * h:.1f}" if math.isfinite(h) else f"{100 * m:.1f}"
    return f"{m:.2f} $\\pm$ {h:.2f}" if math.isfinite(h) else f"{m:.2f}"


def cc1_table(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    g = group_rows([r for r in rows if r["suite"] == "cc1"], ("vmax", "n", "mode", "proposer"))
    out = []
    for (vmax, n, mode, prop), sh in sorted(g.items()):
        if mode != "shielded":
            continue
        un, base = g.get((vmax, n, "unshielded", prop), []), g.get((vmax, n, "base", "none"), [])
        a, b = rejected_useful(sh)
        out.append({"vmax": vmax, "n": n, "proposer": prop,
                    "loop_unshielded": mean_ci(un, "loop_step_frac")[0] if un else float("nan"),
                    "loop_shielded": mean_ci(sh, "loop_step_frac")[0],
                    "avail_feasibility_rule": mean_ci(base, "valid_frac")[0] if base else float("nan"),
                    "avail_unshielded": mean_ci(un, "valid_frac")[0] if un else float("nan"),
                    "avail_shielded": mean_ci(sh, "valid_frac")[0],
                    "rejected_useful": a, "rejected_useful_routeless": b,
                    "loop_creating": total(sh, "loop_creating"),
                    "loop_creating_committed": total(sh, "loop_creating_committed"),
                    "n_seeds": len(sh)})
    return out


def cc1_latex(rows: Sequence[Mapping[str, Any]], n: int = 50) -> str:
    """Body rows in the layout of the paper's Table 4."""
    g = group_rows([r for r in rows if r["suite"] == "cc1"], ("vmax", "n", "mode", "proposer"))
    lines: List[str] = []
    for vmax in sorted({k[0] for k in g}):
        lines.append(f"\\multicolumn{{7}}{{@{{}}l}}{{\\emph{{$v_{{\\max}}={vmax:g}$~m/s, $N={n}$}}}} \\\\")
        for prop in ("rand", "greedy", "adv", "stable"):
            sh, un = g.get((vmax, n, "shielded", prop)), g.get((vmax, n, "unshielded", prop))
            base = g.get((vmax, n, "base", "none"))
            if not (sh and un and base):
                continue
            a, b = rejected_useful(sh)
            rej = f"{100 * a:.1f} / {100 * b:.1f}" if math.isfinite(a) else "n/a"
            lines.append(f"{NAMES[prop]} & {_pm(*mean_ci(un, 'loop_step_frac'))} & {_pm(*mean_ci(sh, 'loop_step_frac'))} & "
                         f"{_pm(*mean_ci(base, 'valid_frac'))} & {_pm(*mean_ci(un, 'valid_frac'))} & "
                         f"{_pm(*mean_ci(sh, 'valid_frac'))} & {rej} \\\\")
    return "\n".join(lines) + "\n"


def cc2_table(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    g = group_rows([r for r in rows if r["suite"] == "cc2"], ("attack", "adv_frac", "mode", "cfg"))
    return [{"attack": k[0], "adv_frac": k[1], "mode": k[2], "cfg": k[3],
             "adv_traverse": mean_ci(v, "adv_traverse_frac")[0], "adv_traverse_ci95": mean_ci(v, "adv_traverse_frac")[1],
             "adv_direct": mean_ci(v, "adv_direct_frac")[0] if "adv_direct_frac" in v[0] else float("nan"),
             "availability": mean_ci(v, "valid_frac")[0], "loop_step": mean_ci(v, "loop_step_frac")[0],
             "n_seeds": len(v)} for k, v in sorted(g.items())]


def cc3_table(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    g = group_rows([r for r in rows if r["suite"] == "cc3"], ("wd_err", "frame", "trust_max_isolate", "mode"))
    out = []
    for k, v in sorted(g.items()):
        hp, hc, ap, ac = (total(v, c) for c in ("iso_honest_prop", "iso_honest_commit", "iso_adv_prop", "iso_adv_commit"))
        out.append({"wd_err": k[0], "frame": k[1], "tau_iso": k[2], "mode": k[3],
                    "honest_proposed": hp, "honest_committed": hc, "honest_committed_share": hc / hp if hp else float("nan"),
                    "adv_proposed": ap, "adv_committed": ac, "adv_committed_share": ac / ap if ap else float("nan"),
                    "via_adversary": mean_ci(v, "adv_traverse_frac")[0], "n_seeds": len(v)})
    return out


def write_component_tables(rows: Sequence[Mapping[str, Any]], out_dir: Path) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, Path] = {}
    for name, fn in (("cc1_table", cc1_table), ("cc2_table", cc2_table), ("cc3_table", cc3_table)):
        t = fn(rows)
        if t:
            paths[name] = write_csv(out_dir / f"{name}.csv", t)
    if any(r["suite"] == "cc1" for r in rows):
        p = out_dir / "cc1_main.tex"
        p.write_text(cc1_latex(rows))
        paths["cc1_main_tex"] = p
    return paths


def system_table(run_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate seeds within an identical experiment condition, preserving missingness."""
    design = ("experiment", "configuration", "model", "attack", "adv_frac", "n", "vmax", "mobility",
              "flows", "sim_time_s", "warmup_s", "timing", "injection_family", "temperature", "condition_json")
    keys = tuple(k for k in design if any(k in row for row in run_rows))
    rows = [{**dict.fromkeys(keys, ""), **r} for r in run_rows]
    groups = group_rows(rows, keys)
    out = []
    metrics = ("pdr", "delay_p95_s", "delay_median_s", "routing_overhead", "recovery_mean_s",
               "recovery_n_censored", "harmful_proposals", "harmful_proposal_rate", "proposal_count",
               "blocked_fraction", "false_positive_rate", "residual_harm", "agent_latency_ms_mean",
               "agent_calls", "agent_errors", "unknown_harm_proposals")
    for condition, values in sorted(groups.items(), key=lambda item: str(item[0])):
        seeds = [r.get("seed") for r in values if "seed" in r]
        if seeds and len(set(seeds)) != len(seeds):
            raise ValueError(f"duplicate seed in system condition {condition}")
        rec: Dict[str, Any] = {**dict(zip(keys, condition)), "n_runs": len(values),
                               "synthetic": all(str(r.get("synthetic")).lower() == "true" for r in values)}
        for key in metrics:
            samples = [float(r[key]) for r in values
                       if r.get(key) not in (None, "") and math.isfinite(float(r[key]))]
            rec[f"{key}_n_valid"] = len(samples)
            rec[f"{key}_n_missing"] = len(values) - len(samples)
            rec[key], rec[f"{key}_ci95"] = (t_interval(samples) if len(samples) > 1 else
                                           (samples[0], float("nan")) if samples else
                                           (float("nan"), float("nan")))
        out.append(rec)
    return out
