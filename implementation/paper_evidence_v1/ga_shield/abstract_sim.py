"""Abstract component-level conformance check for the Guarded Autonomy shield.

WHAT THIS IS: a discrete-time, graph-level model of a MANET running a
sequence-numbered distance-vector route-selection rule (the AODV/DSDV
feasibility rule) toward one destination, with scripted action proposers in
place of an LLM, and a global oracle that inspects the full next-hop graph.

WHAT THIS IS NOT: a packet-level simulation, an ns-3 run, or an evaluation of
any language model. No PHY/MAC, no packet loss model beyond link existence,
no control-message overhead. Results characterise the shield's invariant
checks (soundness and conservativeness of local checks), nothing more.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
from typing import Dict, List, Optional

from core import INF, LocalView, Shield, ShieldConfig

DEST = 0


class Sim:
    def __init__(self, n: int, seed: int, mode: str, proposer: str, adv_frac: float = 0.0,
                 cfg: Optional[ShieldConfig] = None, p_dec: float = 0.1, r: float = 250.0,
                 iso_prob: float = 0.0, delta_seq: int = 5, vmax: float = 20.0, attack: str = "inflate",
                 wd_err: float = 0.05, frame: float = 0.0):
        self.n, self.mode, self.proposer = n, mode, proposer
        self.rng = random.Random(seed + 100003)        # decisions, watchdog
        self.rng_mob = random.Random(seed)             # mobility and adversary placement (paired across configs)
        self.attack = attack
        self.wd_err = wd_err      # watchdog observation error
        self.frame = frame        # probability that an honest neighbour of an adversary is observed dropping (framing)
        self.r = r
        self.L = 1000.0 * math.sqrt(n / 50.0)          # constant mean density across n
        self.p_dec = p_dec
        self.iso_prob = iso_prob
        self.delta = delta_seq
        self.vmax = vmax
        k = int(round(adv_frac * n))
        cand = list(range(1, n))
        self.rng_mob.shuffle(cand)
        self.adv = set(cand[:k])
        self.honest = [i for i in range(n) if i not in self.adv]
        self.pos = [(self.rng_mob.uniform(0, self.L), self.rng_mob.uniform(0, self.L)) for _ in range(n)]
        self.wp = [self._new_wp() for _ in range(n)]
        self.seq_d = 1
        self.req = 1
        self.cfg = cfg or ShieldConfig()
        self.views: Dict[int, LocalView] = {i: LocalView(node_id=i, active_dests={DEST}) for i in self.honest}
        self.shields = {i: Shield(self.views[i], self.cfg) for i in self.honest}
        self.alpha = {i: {} for i in self.honest}
        self.beta = {i: {} for i in self.honest}
        self.t = 0
        self.m = dict(steps=0, loop_steps=0, looping_frac=[], valid_frac=[], adv_traverse_frac=[], adv_direct_frac=[],
                      proposals=0, loop_creating=0, loop_creating_committed=0,
                      useful_safe=0, useful_safe_rejected=0, useful_safe_rejected_routeless=0, accepted=0, accepted_diff_base=0,
                      latency_us=[], iso_honest_prop=0, iso_honest_commit=0, iso_adv_prop=0,
                      iso_adv_commit=0, viol_counts={})

    # ------------------------------------------------------------- mobility
    def _new_wp(self):
        return (self.rng_mob.uniform(0, self.L), self.rng_mob.uniform(0, self.L), self.rng_mob.uniform(1.0, self.vmax))

    def move(self):
        for i in range(self.n):
            x, y = self.pos[i]
            tx, ty, sp = self.wp[i]
            dx, dy = tx - x, ty - y
            dist = math.hypot(dx, dy)
            if dist <= sp:
                self.pos[i] = (tx, ty)
                self.wp[i] = self._new_wp()
            else:
                self.pos[i] = (x + sp * dx / dist, y + sp * dy / dist)

    def links(self):
        nb = {i: set() for i in range(self.n)}
        for i in range(self.n):
            xi, yi = self.pos[i]
            for j in range(i + 1, self.n):
                xj, yj = self.pos[j]
                if (xi - xj) ** 2 + (yi - yj) ** 2 <= self.r ** 2:
                    nb[i].add(j)
                    nb[j].add(i)
        return nb

    # ------------------------------------------------------------- graph oracle
    def chain(self, start: int, extra: Optional[tuple] = None):
        """Follow honest next hops from start. Returns (outcome, path).
        outcome in {'dest','loop','adv','dead'}. extra=(i,j) overrides i's next hop."""
        seen, path, u = set(), [], start
        while True:
            if u == DEST:
                return "dest", path
            if u in self.adv:
                return "adv", path
            if u in seen:
                return "loop", path
            seen.add(u)
            path.append(u)
            if extra is not None and u == extra[0]:
                nh = extra[1]
            else:
                e = self.views[u].routes.get(DEST)
                nh = e.next_hop if (e is not None and e.valid) else None
            if nh is None:
                return "dead", path
            u = nh

    # ------------------------------------------------------------- trust
    def watchdog(self, nb):
        for i in self.honest:
            v = self.views[i]
            for j in nb[i]:
                if self.rng.random() > 0.5:
                    continue
                if j in self.adv:
                    dropped = self.rng.random() < 0.5            # gray hole
                elif j == DEST:
                    dropped = False
                else:
                    e = self.views[j].routes.get(DEST)
                    if not (e is not None and e.valid):
                        continue                                 # no route: receives no transit traffic
                    dropped = False
                    if self.frame > 0 and any(a in nb[j] for a in self.adv) and self.rng.random() < self.frame:
                        dropped = True                           # framed: adversary drops packets attributed to j
                if self.rng.random() < self.wd_err:              # watchdog error
                    dropped = not dropped
                a = self.alpha[i].get(j, 0) + (0 if dropped else 1)
                b = self.beta[i].get(j, 0) + (1 if dropped else 0)
                self.alpha[i][j], self.beta[i][j] = a, b
                v.trust[j] = (a + 1.0) / (a + b + 2.0)
                v.obs_count[j] = a + b

    def velocity(self, i):
        x, y = self.pos[i]
        tx, ty, sp = self.wp[i]
        d = math.hypot(tx - x, ty - y)
        return (0.0, 0.0) if d == 0 else (sp * (tx - x) / d, sp * (ty - y) / d)

    def link_lifetime(self, i, j):
        """Predicted time until |p_i - p_j| > r assuming constant velocities."""
        (xi, yi), (xj, yj) = self.pos[i], self.pos[j]
        (ui, wi), (uj, wj) = self.velocity(i), self.velocity(j)
        dx, dy, du, dw = xj - xi, yj - yi, uj - ui, wj - wi
        a = du * du + dw * dw
        b = 2 * (dx * du + dy * dw)
        c = dx * dx + dy * dy - self.r ** 2
        if a < 1e-12:
            return 1e9
        disc = b * b - 4 * a * c
        if disc < 0:
            return 0.0
        return max(0.0, (-b + math.sqrt(disc)) / (2 * a))

    # ------------------------------------------------------------- proposers
    def propose(self, i: int) -> Optional[dict]:
        v = self.views[i]
        nbs = sorted(v.neighbours)
        if not nbs:
            return None
        if self.iso_prob > 0 and self.rng.random() < self.iso_prob:
            if self.rng.random() < 0.5:
                hon = [j for j in nbs if j not in self.adv and j != DEST]
                if hon:
                    return {"type": "isolate", "node": self.rng.choice(hon), "reason": "neighbour report says node is malicious"}
            else:
                bad = [j for j in nbs if j in self.adv]
                if bad:
                    return {"type": "isolate", "node": self.rng.choice(bad)}
        p = self.proposer
        if p == "none":
            return None
        if p == "rand":
            j = self.rng.choice(nbs)
        elif p == "greedy":
            advs = v.adv.get(DEST, {})
            cands = [(advs[j][1], self.rng.random(), j) for j in nbs if j in advs]
            if not cands:
                return None
            j = min(cands)[2]
        elif p == "stable":
            # Stand-in for a competent agent: among neighbours it believes feasible from its
            # observation (own stored key and received advertisements), pick the most stable link.
            advs = v.adv.get(DEST, {})
            e = v.entry(DEST)
            feas = [j for j in nbs if j in advs and (advs[j][0] > e.seq or (advs[j][0] == e.seq and advs[j][1] + 1 < e.hops))]
            if not feas:
                return None
            j = max(feas, key=lambda q: (self.link_lifetime(i, q), -q))
        elif p == "adv":
            looping = [j for j in nbs if j not in self.adv and i in self.chain(j)[1]]
            j = self.rng.choice(looping) if looping else self.rng.choice(nbs)
        else:
            raise ValueError(p)
        return {"type": "route_change", "dest": DEST, "next_hop": j}

    def base_candidates(self, i: int) -> List[dict]:
        v = self.views[i]
        advs = v.adv.get(DEST, {})
        ranked = sorted((j for j in v.neighbours if j in advs and j not in v.isolated),
                        key=lambda j: (-advs[j][0], advs[j][1], j))
        return [{"type": "route_change", "dest": DEST, "next_hop": j} for j in ranked]

    def base_plain(self, i: int):
        """Plain AODV rule (no trust): adopt highest-ranked strictly-fresher advertisement."""
        v = self.views[i]
        e = v.entry(DEST)
        advs = v.adv.get(DEST, {})
        for b in self.base_candidates(i):
            s, h = advs[b["next_hop"]]
            if s > e.seq or (s == e.seq and h + 1 < e.hops):
                e.seq, e.hops, e.next_hop, e.valid = s, h + 1, b["next_hop"], True
                return b
        return None

    def commit_unshielded(self, i: int, a: dict):
        v = self.views[i]
        if a["type"] == "route_change":
            e = v.entry(DEST)
            rec = v.adv.get(DEST, {}).get(a["next_hop"])
            if rec is not None:
                e.seq, e.hops = rec[0], rec[1] + 1
            e.next_hop, e.valid = a["next_hop"], True
        elif a["type"] == "isolate":
            v.isolated.add(a["node"])
            e = v.entry(DEST)
            if e.valid and e.next_hop == a["node"]:
                e.valid, e.next_hop, e.seq = False, None, e.seq + 1

    # ------------------------------------------------------------- step
    def step(self):
        self.t += 1
        self.move()
        nb = self.links()
        # snapshot of advertisements from end of previous step (one-step delay)
        snap = {}
        for j in range(self.n):
            if j == DEST:
                snap[j] = (self.seq_d, 0)
            elif j in self.adv:
                # forged advertisement: inflated freshness, or a one-hop shortcut at current freshness
                snap[j] = (self.seq_d + self.delta, 1) if self.attack == "inflate" else (self.seq_d, 1)
            else:
                e = self.views[j].routes.get(DEST)
                if e is not None and e.valid:
                    snap[j] = (e.seq, e.hops)
        for i in self.honest:
            v = self.views[i]
            v.now = float(self.t)
            v.neighbours = set(nb[i])
            v.adv[DEST] = {j: snap[j] for j in nb[i] if j in snap}
            e = v.entry(DEST)
            if i != DEST and e.valid and (e.next_hop not in nb[i] or e.next_hop in v.isolated):
                e.valid, e.next_hop = False, None
                e.seq += 1
                self.req = max(self.req, e.seq)
        self.seq_d = max(self.seq_d, self.req)
        if self.adv or self.iso_prob > 0 or self.cfg.use_trust:
            self.watchdog(nb)
        order = [i for i in self.honest if i != DEST]
        self.rng.shuffle(order)
        for i in order:
            v = self.views[i]
            e = v.entry(DEST)
            was_valid = e.valid
            dec_point = (not e.valid) or (self.rng.random() < self.p_dec)
            prop = self.propose(i) if (dec_point and self.mode != "base") else None
            if prop is not None:
                self.m["proposals"] += 1
                if prop["type"] == "route_change":
                    jo, jp = self.chain(prop["next_hop"])
                    creates_loop = prop["next_hop"] == i or i in jp      # i -> j closes a cycle through i
                    useful_safe = (not creates_loop) and jo == "dest"   # loop-free path to destination
                    self.m["loop_creating"] += int(creates_loop)
                    self.m["useful_safe"] += int(useful_safe)
                elif prop["type"] == "isolate":
                    if prop["node"] in self.adv:
                        self.m["iso_adv_prop"] += 1
                    else:
                        self.m["iso_honest_prop"] += 1
            if self.mode == "base" or prop is None and self.mode == "unshielded":
                self.base_plain(i)
                continue
            if self.mode == "unshielded":
                self.commit_unshielded(i, prop)
                self.m["accepted"] += 1
                if prop["type"] == "route_change":
                    self.m["loop_creating_committed"] += int(creates_loop)
                elif prop["type"] == "isolate":
                    self.m["iso_adv_commit" if prop["node"] in self.adv else "iso_honest_commit"] += 1
                if not v.entry(DEST).valid:
                    self.req = max(self.req, v.entry(DEST).seq)
                continue
            # shielded
            base_first = None
            if prop is not None:
                bc = [b for b in self.base_candidates(i) if not self.shields[i].violations(b)]
                base_first = bc[0]["next_hop"] if bc else None
            d = self.shields[i].decide(prop, self.base_candidates(i))
            if not v.entry(DEST).valid:
                self.req = max(self.req, v.entry(DEST).seq)   # routeless node requests a fresher sequence number
            self.m["latency_us"].append(d.latency_us)
            for vv in d.violated:
                self.m["viol_counts"][vv] = self.m["viol_counts"].get(vv, 0) + 1
            if prop is not None:
                if d.tier == "agent":
                    self.m["accepted"] += 1
                    if prop["type"] == "route_change":
                        self.m["loop_creating_committed"] += int(creates_loop)
                        self.m["accepted_diff_base"] += int(prop["next_hop"] != base_first)
                    elif prop["type"] == "isolate":
                        self.m["iso_adv_commit" if prop["node"] in self.adv else "iso_honest_commit"] += 1
                elif prop["type"] == "route_change" and useful_safe:
                    self.m["useful_safe_rejected"] += 1
                    self.m["useful_safe_rejected_routeless"] += int(not was_valid)
        self.measure()

    def measure(self):
        hs = [i for i in self.honest if i != DEST]
        outs = [self.chain(i)[0] for i in hs]
        nloop = sum(o == "loop" for o in outs)
        self.m["steps"] += 1
        self.m["loop_steps"] += int(nloop > 0)
        self.m["looping_frac"].append(nloop / len(hs))
        self.m["valid_frac"].append(sum(o == "dest" for o in outs) / len(hs))
        self.m["adv_traverse_frac"].append(sum(o == "adv" for o in outs) / len(hs))
        direct = 0
        for i, o in zip(hs, outs):
            e = self.views[i].routes.get(DEST)
            if o == "adv" and e is not None and e.valid and e.next_hop in self.adv:
                direct += 1
        self.m["adv_direct_frac"].append(direct / len(hs))   # next hop itself is an adversary

    def run(self, steps: int):
        for _ in range(steps):
            self.step()
        m = self.m
        res = dict(steps=m["steps"], loop_step_frac=m["loop_steps"] / m["steps"],
                   looping_frac=statistics.mean(m["looping_frac"]),
                   valid_frac=statistics.mean(m["valid_frac"]),
                   adv_traverse_frac=statistics.mean(m["adv_traverse_frac"]),
                   adv_direct_frac=statistics.mean(m["adv_direct_frac"]),
                   proposals=m["proposals"], loop_creating=m["loop_creating"],
                   loop_creating_committed=m["loop_creating_committed"],
                   useful_safe=m["useful_safe"], useful_safe_rejected=m["useful_safe_rejected"],
                   useful_safe_rejected_routeless=m["useful_safe_rejected_routeless"],
                   accepted=m["accepted"], accepted_diff_base=m["accepted_diff_base"],
                   lat_median_us=statistics.median(m["latency_us"]) if m["latency_us"] else None,
                   lat_p99_us=(sorted(m["latency_us"])[int(0.99 * (len(m["latency_us"]) - 1))] if m["latency_us"] else None),
                   iso_honest_prop=m["iso_honest_prop"], iso_honest_commit=m["iso_honest_commit"],
                   iso_adv_prop=m["iso_adv_prop"], iso_adv_commit=m["iso_adv_commit"],
                   viol_counts=json.dumps(m["viol_counts"], sort_keys=True))
        return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=["cc1", "cc2", "cc3", "all"], default="all")
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    rows = []
    loop_only = ShieldConfig(use_trust=False, use_isolation=True)
    full = ShieldConfig()

    def run(suite, n, seed, mode, prop, cfg, **kw):
        r = Sim(n, seed, mode, prop, cfg=cfg, **kw).run(args.steps)
        r.update(suite=suite, n=n, seed=seed, mode=mode, proposer=prop,
                 cfg=("loop" if not cfg.use_trust else "loop+trust"), adv_frac=kw.get("adv_frac", 0.0),
                 iso_prob=kw.get("iso_prob", 0.0), vmax=kw.get("vmax", 20.0), attack=kw.get("attack", ""),
                 trust_max_isolate=cfg.trust_max_isolate, wd_err=kw.get("wd_err", 0.05), frame=kw.get("frame", 0.0))
        rows.append(r)
        print(suite, n, seed, mode, prop, r["cfg"], round(r["loop_step_frac"], 3), round(r["valid_frac"], 3), file=sys.stderr)

    if args.suite in ("cc1", "all"):
        for vmax in (5.0, 20.0):
            for n in (20, 50, 100):
                for s in range(args.seeds):
                    run("cc1", n, s, "base", "none", loop_only, vmax=vmax)
                    for p in ("rand", "greedy", "adv", "stable"):
                        run("cc1", n, s, "unshielded", p, loop_only, vmax=vmax)
                        run("cc1", n, s, "shielded", p, loop_only, vmax=vmax)
    if args.suite in ("cc2", "all"):
        for attack in ("inflate", "shortcut"):
            for f in (0.1, 0.2):
                for s in range(args.seeds):
                    kw = dict(adv_frac=f, attack=attack)
                    run("cc2", 50, s, "base", "none", loop_only, **kw)
                    run("cc2", 50, s, "unshielded", "greedy", loop_only, **kw)
                    run("cc2", 50, s, "shielded", "greedy", loop_only, **kw)
                    run("cc2", 50, s, "shielded", "greedy", full, **kw)
    if args.suite in ("cc3", "all"):
        for wd_err, frame in ((0.05, 0.0), (0.15, 0.3)):
            for tiso in (0.3, 0.5, 0.7):
                cfg3 = ShieldConfig(trust_max_isolate=tiso)
                for s in range(args.seeds):
                    kw = dict(adv_frac=0.1, iso_prob=0.3, attack="shortcut", wd_err=wd_err, frame=frame)
                    if tiso == 0.3:
                        run("cc3", 50, s, "unshielded", "greedy", cfg3, **kw)
                    run("cc3", 50, s, "shielded", "greedy", cfg3, **kw)
    import os
    os.makedirs(args.out, exist_ok=True)
    keys = list(rows[0].keys())
    with open(os.path.join(args.out, f"raw_{args.suite}.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
