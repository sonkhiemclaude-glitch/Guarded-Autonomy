"""Figures generated from result CSVs only.

* ``plot_cc1``: the layout of the paper's Fig. 3 (loop incidence and route availability per
  proposer, unshielded vs shielded, feasibility-rule reference line) for any CC1 raw file.
* ``plot_system``: per-configuration bars for a system-level table.
Synthetic inputs get a visible "synthetic smoke-test output, not a paper result" banner.
Palette: blue #2a78d6 / orange #eb6834 (validated categorical pair), hatch as secondary encoding.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from ..metrics.component import column, group_rows  # noqa: E402
from ..metrics.stats import t_interval  # noqa: E402
from ..utils.provenance import SYNTHETIC_LABEL  # noqa: E402

BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#52514e"
PROPS = ("rand", "greedy", "adv", "stable")
LABELS = {"rand": "Random", "greedy": "Greedy", "adv": "Adversarial", "stable": "Stable-link"}


def _style() -> None:
    plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.edgecolor": "#8a8984", "axes.linewidth": 0.6})


def _banner(fig: Any, synthetic: bool) -> None:
    if synthetic:
        fig.text(0.5, 0.005, SYNTHETIC_LABEL.upper(), ha="center", va="bottom", color="#b3261e", fontsize=9,
                 fontweight="bold")


def plot_cc1(rows: Sequence[Mapping[str, Any]], out: Path, vmax: float, ns: Sequence[int], synthetic: bool) -> Path:
    _style()
    g = group_rows([r for r in rows if r["suite"] == "cc1"], ("vmax", "n", "mode", "proposer"))
    fig, axes = plt.subplots(2, len(ns), figsize=(max(3.5 * len(ns), 6.0), 4.6), sharex=True, squeeze=False)
    for c, n in enumerate(ns):
        for r_, (metric, ylabel) in enumerate((("loop_step_frac", "Steps with a loop (%)"),
                                                ("valid_frac", "Nodes with loop-free route (%)"))):
            ax = axes[r_][c]
            props = [p for p in PROPS if (vmax, n, "shielded", p) in g]
            w = 0.36
            for k, (mode, colr, hatch, lab) in enumerate((("unshielded", ORANGE, "////", "Unshielded"),
                                                          ("shielded", BLUE, "", "Shielded"))):
                ms, hs = [], []
                for p in props:
                    vals = column(g.get((vmax, n, mode, p), []), metric)
                    m, h = t_interval(vals) if len(vals) > 1 else ((vals[0], 0.0) if vals else (float("nan"), 0.0))
                    ms.append(100 * m)
                    hs.append(100 * h if h == h else 0.0)
                pos = [x + (k - 0.5) * (w + 0.03) for x in range(len(props))]
                ax.bar(pos, ms, w, color=colr, edgecolor="white", linewidth=0.8, hatch=hatch, label=lab, zorder=2)
                ax.errorbar(pos, ms, yerr=hs, fmt="none", ecolor="#0b0b0b", elinewidth=0.7, capsize=2, zorder=3)
                for x_, m_ in zip(pos, ms):
                    if m_ < 0.05:
                        ax.text(x_, 1.5, "0", ha="center", va="bottom", fontsize=7, color=GRAY)
            if metric == "valid_frac" and (vmax, n, "base", "none") in g:
                bv = column(g[(vmax, n, "base", "none")], metric)
                ax.axhline(100 * sum(bv) / len(bv), color=GRAY, linestyle="--", linewidth=1.0, zorder=1,
                           label="Feasibility rule only (no agent)")
            ax.set_ylim(0, 105)
            ax.set_xticks(range(len(props)))
            ax.set_xticklabels([LABELS[p] for p in props])
            ax.yaxis.grid(True, color="#e6e5e0", linewidth=0.5, zorder=0)
            ax.set_axisbelow(True)
            if c == 0:
                ax.set_ylabel(ylabel)
            if r_ == 0:
                ax.set_title(f"N = {n}, $v_{{max}}$ = {vmax:g} m/s", fontsize=8.5)
    h0, l0 = axes[0][0].get_legend_handles_labels()
    h1, l1 = axes[1][0].get_legend_handles_labels()
    extra = [(h, lab) for h, lab in zip(h1, l1) if lab.startswith("Feasibility")]
    fig.legend(h0 + [e[0] for e in extra], l0 + [e[1] for e in extra], frameon=False, loc="upper center",
               ncol=3, fontsize=7.5, bbox_to_anchor=(0.5, 1.0))
    _banner(fig, synthetic)
    fig.tight_layout(rect=(0, 0.03 if synthetic else 0, 1, 0.95))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    return out


def plot_system(table: Sequence[Mapping[str, Any]], out: Path, metric: str, ylabel: str, synthetic: bool) -> Path:
    _style()
    fig, ax = plt.subplots(figsize=(4.2, 3.0))
    names = [str(r["configuration"]) for r in table]
    vals = [float(r[metric]) for r in table]
    errs = [float(r.get(f"{metric}_ci95") or 0.0) for r in table]
    errs = [e if e == e else 0.0 for e in errs]
    ax.bar(range(len(names)), vals, 0.6, color=BLUE, edgecolor="white", zorder=2)
    ax.errorbar(range(len(names)), vals, yerr=errs, fmt="none", ecolor="#0b0b0b", elinewidth=0.7, capsize=2, zorder=3)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, rotation=20, ha="right")
    ax.set_ylabel(ylabel)
    ax.yaxis.grid(True, color="#e6e5e0", linewidth=0.5, zorder=0)
    _banner(fig, synthetic)
    fig.tight_layout(rect=(0, 0.06 if synthetic else 0, 1, 1))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    return out
