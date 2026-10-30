"""Abstract component-level model of Sec. 6.1 and Appendix A (Table A.8).

A discrete-time, graph-level MANET model running the sequence-numbered distance-vector
feasibility rule towards one destination, with scripted proposers and a global oracle.

It is NOT a packet-level simulation, an ns-3 run, or an evaluation of a language model.
The step semantics and random-number call order reproduce the code that produced the paper's
CC1-CC3 numbers exactly (verified by tests/test_legacy_regression.py).
"""
from __future__ import annotations

import json
import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..agents.scripted import PROPOSERS, propose
from ..baselines.aodv import feasibility_rule_update, rank_candidates
from ..baselines.trust_aware import trust_aware_update
from ..config import ShieldConfig
from ..schemas import Isolate, LocalView, RouteChange, Tier, parse_action
from ..shield import Shield

MODES = ("base", "unshielded", "shielded", "trust_aware")
ATTACKS = ("inflate", "shortcut")


@dataclass(frozen=True)
class ModelParams:
    """Parameters of one abstract-model run (Table A.8 defaults)."""

    n: int = 50
    seed: int = 0
    mode: str = "shielded"
    proposer: str = "greedy"
    adv_frac: float = 0.0
    p_dec: float = 0.1
    range_m: float = 250.0
    iso_prob: float = 0.0
    delta_seq: int = 5
    vmax: float = 20.0
    attack: str = "inflate"
    wd_err: float = 0.05
    frame: float = 0.0
    steps: int = 300

    def __post_init__(self) -> None:
        if self.n < 3:
            raise ValueError("n must be >= 3")
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if self.proposer not in PROPOSERS:
            raise ValueError(f"proposer must be one of {PROPOSERS}")
        if self.attack not in ATTACKS:
            raise ValueError(f"attack must be one of {ATTACKS}")
        for name in ("adv_frac", "p_dec", "iso_prob", "wd_err", "frame"):
            val = getattr(self, name)
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.vmax < 1.0:
            raise ValueError("vmax must be >= 1 m/s (speeds are drawn from U[1, vmax])")


@dataclass
class _Counters:
    steps: int = 0
    loop_steps: int = 0
    looping_frac: List[float] = field(default_factory=list)
    valid_frac: List[float] = field(default_factory=list)
    adv_traverse_frac: List[float] = field(default_factory=list)
    adv_direct_frac: List[float] = field(default_factory=list)
    proposals: int = 0
    loop_creating: int = 0
    loop_creating_committed: int = 0
    useful_safe: int = 0
    useful_safe_rejected: int = 0
    useful_safe_rejected_routeless: int = 0
    accepted: int = 0
    accepted_diff_base: int = 0
    latency_us: List[float] = field(default_factory=list)
    iso_honest_prop: int = 0
    iso_honest_commit: int = 0
    iso_adv_prop: int = 0
    iso_adv_commit: int = 0
    viol_counts: Dict[str, int] = field(default_factory=dict)


class AbstractNetwork:
    """One run of the abstract model. Node 0 is the destination."""

    dest = 0

    def __init__(self, params: ModelParams, cfg: Optional[ShieldConfig] = None) -> None:
        p = params
        self.params = p
        self.n, self.mode, self.proposer = p.n, p.mode, p.proposer
        self.rng = random.Random(p.seed + 100003)       # decisions, watchdog
        self.rng_mob = random.Random(p.seed)            # mobility and adversary placement (paired)
        self.attack, self.wd_err, self.frame = p.attack, p.wd_err, p.frame
        self.r = p.range_m
        self.L = 1000.0 * math.sqrt(p.n / 50.0)         # constant mean density across n
        self.p_dec, self.iso_prob, self.delta, self.vmax = p.p_dec, p.iso_prob, p.delta_seq, p.vmax
        k = int(round(p.adv_frac * p.n))
        cand = list(range(1, p.n))
        self.rng_mob.shuffle(cand)
        self.adv: Set[int] = set(cand[:k])
        self.honest = [i for i in range(p.n) if i not in self.adv]
        self.pos = [(self.rng_mob.uniform(0, self.L), self.rng_mob.uniform(0, self.L)) for _ in range(p.n)]
        self.wp = [self._new_wp() for _ in range(p.n)]
        self.seq_d = 1
        self.req = 1
        self.cfg = cfg if cfg is not None else ShieldConfig()
        self.views: Dict[int, LocalView] = {i: LocalView(node_id=i, active_dests={self.dest}) for i in self.honest}
        self.shields = {i: Shield(self.views[i], self.cfg) for i in self.honest}
        self.alpha: Dict[int, Dict[int, int]] = {i: {} for i in self.honest}
        self.beta: Dict[int, Dict[int, int]] = {i: {} for i in self.honest}
        self.t = 0
        self.m = _Counters()

    # ------------------------------------------------------------------ mobility (RWP)
    def _new_wp(self) -> Tuple[float, float, float]:
        return (self.rng_mob.uniform(0, self.L), self.rng_mob.uniform(0, self.L), self.rng_mob.uniform(1.0, self.vmax))

    def move(self) -> None:
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

    def links(self) -> Dict[int, Set[int]]:
        """Unit-disk symmetric links."""
        nb: Dict[int, Set[int]] = {i: set() for i in range(self.n)}
        r2 = self.r ** 2
        for i in range(self.n):
            xi, yi = self.pos[i]
            for j in range(i + 1, self.n):
                xj, yj = self.pos[j]
                if (xi - xj) ** 2 + (yi - yj) ** 2 <= r2:
                    nb[i].add(j)
                    nb[j].add(i)
        return nb

    # ------------------------------------------------------------------ oracle
    def chain(self, start: int, extra: Optional[Tuple[int, int]] = None) -> Tuple[str, List[int]]:
        """Follow honest next hops from ``start``: outcome in {'dest','loop','adv','dead'} and the
        honest path visited. ``extra=(i, j)`` overrides i's next hop (hypothetical commit)."""
        seen: Set[int] = set()
        path: List[int] = []
        u: Optional[int] = start
        while True:
            assert u is not None
            if u == self.dest:
                return "dest", path
            if u in self.adv:
                return "adv", path
            if u in seen:
                return "loop", path
            seen.add(u)
            path.append(u)
            if extra is not None and u == extra[0]:
                nh: Optional[int] = extra[1]
            else:
                e = self.views[u].routes.get(self.dest)
                nh = e.next_hop if (e is not None and e.valid) else None
            if nh is None:
                return "dead", path
            u = nh

    # ------------------------------------------------------------------ watchdog trust (Sec. 6.4)
    def watchdog(self, nb: Dict[int, Set[int]]) -> None:
        for i in self.honest:
            v = self.views[i]
            for j in nb[i]:
                if self.rng.random() > 0.5:
                    continue
                if j in self.adv:
                    dropped = self.rng.random() < 0.5                     # gray hole
                elif j == self.dest:
                    dropped = False
                else:
                    e = self.views[j].routes.get(self.dest)
                    if not (e is not None and e.valid):
                        continue                                          # no transit traffic
                    dropped = False
                    if self.frame > 0 and any(a in nb[j] for a in self.adv) and self.rng.random() < self.frame:
                        dropped = True                                    # framing
                if self.rng.random() < self.wd_err:                       # observation error
                    dropped = not dropped
                a = self.alpha[i].get(j, 0) + (0 if dropped else 1)
                b = self.beta[i].get(j, 0) + (1 if dropped else 0)
                self.alpha[i][j], self.beta[i][j] = a, b
                v.trust[j] = (a + 1.0) / (a + b + 2.0)                    # EQ-TRUST
                v.obs_count[j] = a + b

    # ------------------------------------------------------------------ stable-link helper
    def velocity(self, i: int) -> Tuple[float, float]:
        x, y = self.pos[i]
        tx, ty, sp = self.wp[i]
        d = math.hypot(tx - x, ty - y)
        return (0.0, 0.0) if d == 0 else (sp * (tx - x) / d, sp * (ty - y) / d)

    def link_lifetime(self, i: int, j: int) -> float:
        """Predicted time until |p_i - p_j| > r under constant velocities."""
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

    # ------------------------------------------------------------------ unshielded commit
    def commit_unshielded(self, i: int, raw: Any) -> None:
        """Unshielded agent: commit whatever parses (paper Sec. 6.1). Without a record the stored
        key is kept (paper silent; legacy behaviour, see math_to_code_audit.md item 3)."""
        v = self.views[i]
        a = parse_action(raw)
        if isinstance(a, RouteChange):
            e = v.entry(a.dest)
            rec = v.adv.get(a.dest, {}).get(a.next_hop)
            if rec is not None:
                e.seq, e.hops = rec[0], rec[1] + 1
            e.next_hop, e.valid = a.next_hop, True
        elif isinstance(a, Isolate):
            v.isolated.add(a.node)
            e = v.entry(self.dest)
            if e.valid and e.next_hop == a.node:
                e.invalidate()

    # ------------------------------------------------------------------ step
    def step(self) -> None:
        d = self.dest
        m = self.m
        self.t += 1
        self.move()
        nb = self.links()
        snap: Dict[int, Tuple[int, int]] = {}                             # one-step-stale adverts
        for j in range(self.n):
            if j == d:
                snap[j] = (self.seq_d, 0)
            elif j in self.adv:
                snap[j] = (self.seq_d + self.delta, 1) if self.attack == "inflate" else (self.seq_d, 1)
            else:
                e = self.views[j].routes.get(d)
                if e is not None and e.valid:
                    snap[j] = (e.seq, e.hops)
        for i in self.honest:
            v = self.views[i]
            v.now = float(self.t)
            v.neighbours = set(nb[i])
            v.adv[d] = {j: snap[j] for j in nb[i] if j in snap}
            e = v.entry(d)
            if i != d and e.valid and (e.next_hop not in nb[i] or e.next_hop in v.isolated):
                e.invalidate()
                self.req = max(self.req, e.seq)
        self.seq_d = max(self.seq_d, self.req)
        if self.adv or self.iso_prob > 0 or self.cfg.use_trust:
            self.watchdog(nb)
        order = [i for i in self.honest if i != d]
        self.rng.shuffle(order)
        for i in order:
            v = self.views[i]
            e = v.entry(d)
            was_valid = e.valid
            dec_point = (not e.valid) or (self.rng.random() < self.p_dec)
            prop = propose(self, i) if (dec_point and self.mode not in ("base", "trust_aware")) else None
            parsed = parse_action(prop) if prop is not None else None
            creates_loop = useful_safe = False
            if prop is not None:
                m.proposals += 1
                if isinstance(parsed, RouteChange):
                    jo, jp = self.chain(parsed.next_hop)
                    creates_loop = parsed.next_hop == i or i in jp
                    useful_safe = (not creates_loop) and jo == "dest"
                    m.loop_creating += int(creates_loop)
                    m.useful_safe += int(useful_safe)
                elif isinstance(parsed, Isolate):
                    if parsed.node in self.adv:
                        m.iso_adv_prop += 1
                    else:
                        m.iso_honest_prop += 1
            if self.mode == "base" or (prop is None and self.mode == "unshielded"):
                feasibility_rule_update(v, d)
                continue
            if self.mode == "trust_aware":
                trust_aware_update(v, d, self.cfg)
                continue
            if self.mode == "unshielded":
                self.commit_unshielded(i, prop)
                m.accepted += 1
                if isinstance(parsed, RouteChange):
                    m.loop_creating_committed += int(creates_loop)
                elif isinstance(parsed, Isolate):
                    if parsed.node in self.adv:
                        m.iso_adv_commit += 1
                    else:
                        m.iso_honest_commit += 1
                if not v.entry(d).valid:
                    self.req = max(self.req, v.entry(d).seq)
                continue
            # shielded (Algorithm 1)
            base_first: Optional[int] = None
            cands = rank_candidates(v, d)
            if prop is not None:
                bc = [b for b in cands if not self.shields[i].violations(b)]
                base_first = bc[0].next_hop if bc else None
            dec = self.shields[i].decide(prop, rank_candidates(v, d))
            if not v.entry(d).valid:
                self.req = max(self.req, v.entry(d).seq)
            m.latency_us.append(dec.latency_us)
            for vv in dec.violated:
                m.viol_counts[vv] = m.viol_counts.get(vv, 0) + 1
            if prop is not None:
                if dec.tier == Tier.AGENT:
                    m.accepted += 1
                    if isinstance(parsed, RouteChange):
                        m.loop_creating_committed += int(creates_loop)
                        m.accepted_diff_base += int(parsed.next_hop != base_first)
                    elif isinstance(parsed, Isolate):
                        if parsed.node in self.adv:
                            m.iso_adv_commit += 1
                        else:
                            m.iso_honest_commit += 1
                elif isinstance(parsed, RouteChange) and useful_safe:
                    m.useful_safe_rejected += 1
                    m.useful_safe_rejected_routeless += int(not was_valid)
        self.measure()

    def measure(self) -> None:
        d = self.dest
        hs = [i for i in self.honest if i != d]
        outs = [self.chain(i)[0] for i in hs]
        nloop = sum(o == "loop" for o in outs)
        m = self.m
        m.steps += 1
        m.loop_steps += int(nloop > 0)
        m.looping_frac.append(nloop / len(hs))
        m.valid_frac.append(sum(o == "dest" for o in outs) / len(hs))
        m.adv_traverse_frac.append(sum(o == "adv" for o in outs) / len(hs))
        direct = 0
        for i, o in zip(hs, outs):
            e = self.views[i].routes.get(d)
            if o == "adv" and e is not None and e.valid and e.next_hop in self.adv:
                direct += 1
        m.adv_direct_frac.append(direct / len(hs))

    def run(self, steps: Optional[int] = None) -> Dict[str, Any]:
        """Run ``steps`` (default: params.steps) and return one result row."""
        for _ in range(self.params.steps if steps is None else steps):
            self.step()
        return self.result_row()

    def result_row(self) -> Dict[str, Any]:
        m = self.m
        if m.steps == 0:
            raise RuntimeError("no steps executed")
        lat = m.latency_us
        return dict(
            steps=m.steps, loop_step_frac=m.loop_steps / m.steps,
            looping_frac=statistics.mean(m.looping_frac), valid_frac=statistics.mean(m.valid_frac),
            adv_traverse_frac=statistics.mean(m.adv_traverse_frac),
            adv_direct_frac=statistics.mean(m.adv_direct_frac),
            proposals=m.proposals, loop_creating=m.loop_creating,
            loop_creating_committed=m.loop_creating_committed, useful_safe=m.useful_safe,
            useful_safe_rejected=m.useful_safe_rejected,
            useful_safe_rejected_routeless=m.useful_safe_rejected_routeless,
            accepted=m.accepted, accepted_diff_base=m.accepted_diff_base,
            lat_median_us=statistics.median(lat) if lat else None,
            lat_p99_us=(sorted(lat)[int(0.99 * (len(lat) - 1))] if lat else None),
            iso_honest_prop=m.iso_honest_prop, iso_honest_commit=m.iso_honest_commit,
            iso_adv_prop=m.iso_adv_prop, iso_adv_commit=m.iso_adv_commit,
            viol_counts=json.dumps(m.viol_counts, sort_keys=True))

    # ------------------------------------------------------------------ invariant checker (P2)
    def key_order_violations(self) -> List[Tuple[int, int]]:
        """Edges (i, j) of the honest next-hop graph with kappa_i >= kappa_j (should be empty
        under the shield; Proposition 2)."""
        bad: List[Tuple[int, int]] = []
        for i in self.honest:
            if i == self.dest:
                continue
            e = self.views[i].routes.get(self.dest)
            if e and e.valid and e.next_hop is not None and e.next_hop not in self.adv and e.next_hop != self.dest:
                f = self.views[e.next_hop].routes.get(self.dest)
                if f is None or not e.key() < f.key():
                    bad.append((i, e.next_hop))
        return bad
