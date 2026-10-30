"""Build the manuscript tables, figure and a JSON summary from raw component-check CSVs.

Every number in Section 6 of the manuscript is produced here from results/raw_cc*.csv.
Usage: python3 make_outputs.py <results_dir> <manuscript_dir>
"""
import csv
import json
import math
import os
import statistics as st
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RES, MAN = sys.argv[1], sys.argv[2]
T95 = {9: 2.262}  # two-sided t quantile, df = 9 (10 seeds)


def load(name):
    with open(os.path.join(RES, name)) as fh:
        return list(csv.DictReader(fh))


def ci(vals):
    m = st.mean(vals)
    if len(vals) < 2:
        return m, 0.0
    return m, T95.get(len(vals) - 1, 1.96) * st.stdev(vals) / math.sqrt(len(vals))


def fmt(m, h, pct=True):
    if pct:
        return f"{100*m:.1f} $\\pm$ {100*h:.1f}"
    return f"{m:.2f} $\\pm$ {h:.2f}"


def wilcoxon_exact_p(diffs):
    """Two-sided exact Wilcoxon signed-rank p-value (zeros dropped, average ranks for ties)."""
    d = [x for x in diffs if abs(x) > 1e-12]
    n = len(d)
    if n == 0:
        return 1.0
    a = sorted(range(n), key=lambda i: abs(d[i]))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(abs(d[a[j + 1]]) - abs(d[a[i]])) < 1e-12:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[a[k]] = r
        i = j + 1
    w_plus = sum(r for r, x in zip(ranks, d) if x > 0)
    # exact distribution by enumeration over sign assignments (n <= 20)
    from itertools import product
    tot = sum(ranks)
    obs = min(w_plus, tot - w_plus)
    cnt = 0
    allc = 0
    for signs in product((0, 1), repeat=n):
        w = sum(r for r, s in zip(ranks, signs) if s)
        allc += 1
        if min(w, tot - w) <= obs + 1e-9:
            cnt += 1
    return cnt / allc


summary = {}
os.makedirs(os.path.join(MAN, "tables"), exist_ok=True)
os.makedirs(os.path.join(MAN, "figures"), exist_ok=True)

# ------------------------------------------------------------------ CC1
cc1 = load("raw_cc1.csv")
g = defaultdict(list)
for r in cc1:
    g[(float(r["vmax"]), int(r["n"]), r["mode"], r["proposer"])].append(r)
props = ["rand", "greedy", "adv", "stable"]
pname = {"rand": "Random", "greedy": "Greedy", "adv": "Adversarial", "stable": "Stable-link"}


def col(L, k):
    return [float(x[k]) for x in sorted(L, key=lambda x: int(x["seed"]))]


def tot(L, k):
    return sum(int(x[k]) for x in L)


lines = []
for vmax in (5.0, 20.0):
    for n in (20, 50, 100):
        base = g[(vmax, n, "base", "none")]
        bv = ci(col(base, "valid_frac"))
        for p in props:
            u, s_ = g[(vmax, n, "unshielded", p)], g[(vmax, n, "shielded", p)]
            lu, ls = ci(col(u, "loop_step_frac")), ci(col(s_, "loop_step_frac"))
            vu, vs = ci(col(u, "valid_frac")), ci(col(s_, "valid_frac"))
            us, usr = tot(s_, "useful_safe"), tot(s_, "useful_safe_rejected")
            usrl = tot(s_, "useful_safe_rejected_routeless")
            cons = usr / us if us else float("nan")
            consr = usrl / us if us else float("nan")
            lines.append((vmax, n, p, lu, ls, bv, vu, vs, (cons, consr), tot(s_, "loop_creating"), tot(s_, "loop_creating_committed")))

# main-text table: N = 50, both speeds
with open(os.path.join(MAN, "tables", "cc1_main.tex"), "w") as fh:
    for vmax in (5.0, 20.0):
        fh.write(f"\\multicolumn{{7}}{{@{{}}l}}{{\\emph{{$v_{{\\max}}={int(vmax)}$~m/s, $N=50$}}}} \\\\\n")
        for (vm, n, p, lu, ls, bv, vu, vs, cons, lc, lcc) in lines:
            if vm != vmax or n != 50:
                continue
            c0, c1 = cons
            fh.write(f"{pname[p]} & {fmt(*lu)} & {fmt(*ls)} & {fmt(*bv)} & {fmt(*vu)} & {fmt(*vs)} & "
                     + (f"{100*c0:.1f} / {100*c1:.1f}" if c0 == c0 else "n/a") + " \\\\\n")
        if vmax == 5.0:
            fh.write("\\midrule\n")
# appendix table: all N
with open(os.path.join(MAN, "tables", "cc1_full.tex"), "w") as fh:
    for (vm, n, p, lu, ls, bv, vu, vs, cons, lc, lcc) in lines:
        c0, c1 = cons
        fh.write(f"{int(vm)} & {n} & {pname[p]} & {100*lu[0]:.1f} & {100*ls[0]:.1f} & {100*bv[0]:.1f} & {100*vu[0]:.1f} & {100*vs[0]:.1f} & "
                 + (f"{100*c0:.1f} & {100*c1:.1f}" if c0 == c0 else "n/a & n/a") + f" & {lc} & {lcc} \\\\\n")

# aggregates
sh = [r for r in cc1 if r["mode"] == "shielded"]
un = [r for r in cc1 if r["mode"] == "unshielded"]
summary["cc1_runs"] = len(cc1)
summary["cc1_shielded_loop_steps_total"] = sum(round(float(r["loop_step_frac"]) * int(r["steps"])) for r in sh)
summary["cc1_shielded_loop_creating_proposals"] = tot(sh, "loop_creating")
summary["cc1_shielded_loop_creating_committed"] = tot(sh, "loop_creating_committed")
summary["cc1_unshielded_loop_creating_committed"] = tot(un, "loop_creating_committed")
summary["cc1_shielded_proposals"] = tot(sh, "proposals")
cons_by_p = {}
for p in ("rand", "greedy", "adv"):
    L = [r for r in sh if r["proposer"] == p]
    cons_by_p[p] = tot(L, "useful_safe_rejected") / tot(L, "useful_safe")
summary["cc1_conservativeness_by_proposer"] = cons_by_p
rng_all = [c[0] for (vm, n, p, lu, ls, bv, vu, vs, c, lc, lcc) in lines if p != "stable"]
rng_rl = [c[1] for (vm, n, p, lu, ls, bv, vu, vs, c, lc, lcc) in lines if p != "stable"]
summary["cc1_conservativeness_per_setting_range"] = [min(rng_all), max(rng_all)]
summary["cc1_conservativeness_routeless_per_setting_range"] = [min(rng_rl), max(rng_rl)]
summary["cc1_shielded_runs"] = len(sh)
summary["cc1_unshielded_proposals"] = tot(un, "proposals")
avail_gap = []
for vmax in (5.0, 20.0):
    for n in (20, 50, 100):
        b = st.mean(col(g[(vmax, n, "base", "none")], "valid_frac"))
        for p in ("rand", "greedy", "adv"):
            avail_gap.append(abs(st.mean(col(g[(vmax, n, "shielded", p)], "valid_frac")) - b))
summary["cc1_shielded_vs_base_max_abs_gap"] = max(avail_gap)
lat = [float(r["lat_median_us"]) for r in sh if r["lat_median_us"]]
lat99 = [float(r["lat_p99_us"]) for r in sh if r["lat_p99_us"]]
summary["cc1_latency_median_us_range"] = [min(lat), max(lat)]
summary["cc1_latency_p99_us_max"] = max(lat99)
stb = [r for r in sh if r["proposer"] == "stable"]
summary["cc1_stable_accepted"] = tot(stb, "accepted")
summary["cc1_stable_diff_base"] = tot(stb, "accepted_diff_base")
# paired test: stable-shielded vs base, availability, per (vmax, n)
paired = {}
for vmax in (5.0, 20.0):
    for n in (20, 50, 100):
        b = col(g[(vmax, n, "base", "none")], "valid_frac")
        s_ = col(g[(vmax, n, "shielded", "stable")], "valid_frac")
        diffs = [y - x for x, y in zip(b, s_)]
        m, h = ci(diffs)
        paired[f"v{int(vmax)}_n{n}"] = dict(mean_diff=m, ci95=h, wilcoxon_p=wilcoxon_exact_p(diffs))
summary["cc1_stable_vs_base_availability"] = paired
gap = {}
for vmax in (5.0, 20.0):
    for n in (20, 50, 100):
        b = col(g[(vmax, n, "base", "none")], "valid_frac")
        u = col(g[(vmax, n, "unshielded", "greedy")], "valid_frac")
        gap[f"v{int(vmax)}_n{n}"] = [st.mean(b), st.mean(u)]
summary["cc1_base_vs_unshielded_greedy_availability"] = gap

# figure: N = 50 and N = 100 at vmax 20, loop incidence and availability
BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#52514e"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.edgecolor": "#8a8984", "axes.linewidth": 0.6,
                     "xtick.color": "#52514e", "ytick.color": "#52514e"})
fig, axes = plt.subplots(2, 2, figsize=(7.0, 4.6), sharex=True)
for c, n in enumerate((50, 100)):
    for r_, (metric, ylabel) in enumerate((("loop_step_frac", "Steps with a loop (%)"),
                                            ("valid_frac", "Nodes with loop-free route (%)"))):
        ax = axes[r_][c]
        xs = range(len(props))
        w = 0.36
        for k, (mode, colr, hatch, lab) in enumerate((("unshielded", ORANGE, "////", "Unshielded"),
                                                      ("shielded", BLUE, "", "Shielded"))):
            ms, hs = [], []
            for p in props:
                m, h = ci(col(g[(20.0, n, mode, p)], metric))
                ms.append(100 * m)
                hs.append(100 * h)
            pos = [x + (k - 0.5) * (w + 0.03) for x in xs]
            ax.bar(pos, ms, w, color=colr, edgecolor="white", linewidth=0.8, hatch=hatch, label=lab, zorder=2)
            ax.errorbar(pos, ms, yerr=hs, fmt="none", ecolor="#0b0b0b", elinewidth=0.7, capsize=2, zorder=3)
            for x_, m_ in zip(pos, ms):
                if m_ < 0.05:
                    ax.text(x_, 1.5, "0", ha="center", va="bottom", fontsize=7, color="#52514e")
        if metric == "valid_frac":
            bm, _ = ci(col(g[(20.0, n, "base", "none")], metric))
            ax.axhline(100 * bm, color=GRAY, linestyle="--", linewidth=1.0, zorder=1, label="Feasibility rule only (no agent)")
            ax.set_ylim(0, 105)
        else:
            ax.set_ylim(0, 105)
        ax.set_xticks(list(xs))
        ax.set_xticklabels(["Random", "Greedy", "Adversarial", "Stable-link"])
        ax.yaxis.grid(True, color="#e6e5e0", linewidth=0.5, zorder=0)
        ax.set_axisbelow(True)
        if c == 0:
            ax.set_ylabel(ylabel)
        if r_ == 0:
            ax.set_title(f"N = {n}, $v_{{max}}$ = 20 m/s", fontsize=8.5, color="#0b0b0b")
h0, l0 = axes[0][0].get_legend_handles_labels()
h1, l1 = axes[1][0].get_legend_handles_labels()
hb = [h for h, l in zip(h1, l1) if l.startswith("Feasibility")]
fig.legend(h0 + hb, l0 + ["Feasibility rule only (no agent)"], frameon=False, loc="upper center", ncol=3, fontsize=7.5,
           bbox_to_anchor=(0.5, 1.0))
fig.tight_layout(rect=(0, 0, 1, 0.95))
fig.savefig(os.path.join(MAN, "figures", "cc1_results.pdf"))
fig.savefig(os.path.join(MAN, "figures", "cc1_results.png"), dpi=300)

# ------------------------------------------------------------------ CC2
cc2 = load("raw_cc2.csv")
g2 = defaultdict(list)
for r in cc2:
    g2[(r["attack"], float(r["adv_frac"]), r["mode"], r["cfg"])].append(r)
rows2 = [("base", "loop", "Feasibility rule, no agent"), ("unshielded", "loop", "Unshielded greedy agent"),
         ("shielded", "loop", "Shield, I2 without I3"), ("shielded", "loop+trust", "Shield, full $\\Phi$")]
with open(os.path.join(MAN, "tables", "cc2.tex"), "w") as fh:
    for mode, cfg, lab in rows2:
        cells = []
        for attack in ("inflate", "shortcut"):
            for f in (0.1, 0.2):
                L = g2[(attack, f, mode, cfg)]
                cells.append(fmt(*ci(col(L, "adv_traverse_frac"))))
        fh.write(lab + " & " + " & ".join(cells) + " \\\\\n")
summary["cc2"] = {f"{a}_{f}_{m}_{c}": dict(adv=st.mean(col(L, "adv_traverse_frac")), valid=st.mean(col(L, "valid_frac")),
                                          adv_direct=st.mean(col(L, "adv_direct_frac")),
                                          loop=st.mean(col(L, "loop_step_frac")))
                  for (a, f, m, c), L in g2.items()}

# ------------------------------------------------------------------ CC3
cc3 = load("raw_cc3.csv")
g3 = defaultdict(list)
for r in cc3:
    g3[(float(r["wd_err"]), float(r["trust_max_isolate"]), r["mode"])].append(r)
with open(os.path.join(MAN, "tables", "cc3.tex"), "w") as fh:
    for wd, wlab in ((0.05, "Watchdog error 5\\%, no framing"), (0.15, "Watchdog error 15\\%, framing 0.3")):
        fh.write(f"\\multicolumn{{7}}{{@{{}}l}}{{\\emph{{{wlab}}}}} \\\\\n")
        for tiso, mode, lab in ((0.3, "unshielded", "Unshielded"), (0.3, "shielded", "Shielded"), (0.5, "shielded", "Shielded"), (0.7, "shielded", "Shielded")):
            L = g3[(wd, tiso, mode)]
            hp, hc = tot(L, "iso_honest_prop"), tot(L, "iso_honest_commit")
            ap, ac = tot(L, "iso_adv_prop"), tot(L, "iso_adv_commit")
            tl = f"{tiso:.1f}" if mode == "shielded" else "--"
            fh.write(f"{lab} & {tl} & {hp} & {hc} ({100*hc/hp:.1f}\\%) & {ap} & {ac} ({100*ac/ap:.1f}\\%) & "
                     f"{fmt(*ci(col(L, 'adv_traverse_frac')))} \\\\\n")
        if wd == 0.05:
            fh.write("\\midrule\n")
summary["cc3"] = {f"wd{w}_t{t}_{m}": dict(hp=tot(L, "iso_honest_prop"), hc=tot(L, "iso_honest_commit"),
                                         ap=tot(L, "iso_adv_prop"), ac=tot(L, "iso_adv_commit"),
                                         adv=st.mean(col(L, "adv_traverse_frac")), valid=st.mean(col(L, "valid_frac")))
                  for (w, t, m), L in g3.items()}
viol = defaultdict(int)
for r in cc3:
    if r["mode"] == "shielded" and float(r["wd_err"]) == 0.05:
        for k, v in json.loads(r["viol_counts"]).items():
            viol[k] += v
summary["cc3_violation_counts_wd005"] = dict(viol)

with open(os.path.join(RES, "summary.json"), "w") as fh:
    json.dump(summary, fh, indent=1)
print(json.dumps(summary, indent=1))
