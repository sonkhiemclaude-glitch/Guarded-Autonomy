"""Invariant guards of Table 2 (p10), the OLSR structural invariant (Sec. 4.6) and the M1
obligation monitor.

Every guard reads only daemon-maintained state in :class:`LocalView` (principle D2) and
returns the list of violated invariant labels; an empty list means the action is admitted.
Labels are stable strings used in logs and metrics.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

from .config import ShieldConfig
from .schemas import Action, Advertisement, Defer, Isolate, LocalView, Reinstate, RouteChange, RouteEntry, SetPower

UNOBSERVED_TRUST = 0.5
"""Trust of a neighbour with no observations: (0+1)/(0+0+2), consistent with EQ-TRUST."""


def is_feasible(rec: Advertisement, entry: RouteEntry) -> bool:
    """AODV feasibility condition, invariant I2 (Table 2): (s, -(h+1)) > kappa_i(d).

    Equivalent expanded form: s > s_i, or s == s_i and h + 1 < h_i.
    """
    s, h = rec
    return s > entry.seq or (s == entry.seq and h + 1 < entry.hops)


class IsolationBudget:
    """State for I4c: timestamps of earlier isolations, capped at k entries (Prop. 3)."""

    def __init__(self) -> None:
        self.times: List[float] = []

    def prune(self, now: float, window_s: float, k: int) -> None:
        self.times = [t for t in self.times if now - t < window_s][-k:] if k > 0 else []

    def count(self) -> int:
        return len(self.times)

    def record(self, now: float) -> None:
        self.times.append(now)


def check_route_change(v: LocalView, a: RouteChange, cfg: ShieldConfig) -> List[str]:
    """I1 (neighbour, not destination, not isolated), I2 (feasibility) or the OLSR downhill
    invariant, and I3 (evidence-based next-hop trust)."""
    bad: List[str] = []
    d, j = a.dest, a.next_hop
    if d == v.node_id:
        bad.append("I1:not-destination")
        return bad
    if j not in v.neighbours or j == v.node_id:
        bad.append("I1:symmetric-neighbour")
        return bad
    if j in v.isolated:
        bad.append("I1:not-isolated")
    if cfg.use_olsr_downhill:
        bad.extend(olsr_downhill_violations(v, d, j))
    elif cfg.use_loop:
        rec = v.adv.get(d, {}).get(j)  # D2: the daemon's record, never a value claimed by the agent
        if rec is None:
            bad.append("I2:no-advertisement")
        elif not is_feasible(rec, v.entry(d)):
            bad.append("I2:feasibility")
    if (cfg.use_trust and v.obs_count.get(j, 0) >= cfg.min_obs_route
            and v.trust.get(j, UNOBSERVED_TRUST) < cfg.trust_min_route):
        bad.append("I3:trust-next-hop")
    return bad


def check_isolate(v: LocalView, a: Isolate, cfg: ShieldConfig, budget: IsolationBudget) -> List[str]:
    """I4a (evidence, not already isolated), I4b (evidence precedence), I4c (budget)."""
    bad: List[str] = []
    x = a.node
    if x == v.node_id or x not in v.neighbours:
        bad.append("I4:target")
        return bad
    if x in v.isolated:
        bad.append("I4:already-isolated")
        return bad
    if not cfg.use_isolation:
        return bad
    if v.trust.get(x, UNOBSERVED_TRUST) > cfg.trust_max_isolate:
        bad.append("I4a:trust-threshold")
    if v.obs_count.get(x, 0) < cfg.min_obs_isolate:
        bad.append("I4b:evidence-precedence")
    if cfg.use_rate_limit:
        budget.prune(v.now, cfg.iso_window_s, cfg.iso_max_in_window)
        if budget.count() >= cfg.iso_max_in_window:
            bad.append("I4c:rate-limit")
    return bad


def check_reinstate(v: LocalView, a: Reinstate) -> List[str]:
    """I4d: reinstate(x) only if x is currently isolated (implies Declare precedence)."""
    return [] if a.node in v.isolated else ["I4:reinstate-precedence"]


def check_set_power(v: LocalView, a: SetPower, cfg: ShieldConfig) -> List[str]:
    """I5a (range), I6 (energy floor for increases), I5b (keep active links for decreases).

    I5b uses mu_i(n_i(d)) - (p_i - p) >= 0; a missing margin estimate is treated as 0 dB,
    so any decrease is rejected for an active next hop without an estimate (conservative).
    """
    bad: List[str] = []
    if not cfg.use_power:
        return bad
    p = a.power_dbm
    if not (cfg.p_min_dbm <= p <= cfg.p_max_dbm):
        bad.append("I5a:power-range")
    if p > v.power_dbm and v.energy_j < cfg.energy_floor_j:
        bad.append("I6:energy-floor")
    if p < v.power_dbm:
        drop = v.power_dbm - p
        for d in sorted(v.active_dests):
            e = v.routes.get(d)
            if e and e.valid and e.next_hop is not None and v.link_margin_db.get(e.next_hop, 0.0) - drop < 0:
                bad.append("I5b:keep-active-links")
                break
    return bad


def violations(v: LocalView, a: Optional[Action], cfg: ShieldConfig, budget: IsolationBudget) -> List[str]:
    """Violated invariants for a parsed action; ``None`` (parse failure) violates I0."""
    if a is None:
        return ["I0:schema"]
    if isinstance(a, RouteChange):
        return check_route_change(v, a, cfg)
    if isinstance(a, Isolate):
        return check_isolate(v, a, cfg, budget)
    if isinstance(a, Reinstate):
        return check_reinstate(v, a)
    if isinstance(a, SetPower):
        return check_set_power(v, a, cfg)
    if isinstance(a, Defer):
        return []
    return ["I0:schema"]


# --------------------------------------------------------------------------- OLSR (Sec. 4.6)
def topology_distances(topology: Dict[int, set], dest: int) -> Dict[int, int]:
    """Hop distances to ``dest`` by breadth-first search over a node's own topology base."""
    dist = {dest: 0}
    frontier: Deque[int] = deque([dest])
    while frontier:
        u = frontier.popleft()
        for w in topology.get(u, set()):
            if w not in dist:
                dist[w] = dist[u] + 1
                frontier.append(w)
    return dist


def olsr_downhill_violations(v: LocalView, d: int, j: int) -> List[str]:
    """OLSR structural invariant (Sec. 4.6): j is a symmetric one-hop neighbour whose
    distance to d in the node's own topology base is strictly smaller than the node's.

    Loop freedom follows only when honest topology bases agree (Sec. 4.6, Sec. 5 limits).
    """
    sym = v.topology.get(v.node_id, set())
    if j not in sym or v.node_id not in v.topology.get(j, set()):
        return ["OLSR:symmetric-neighbour"]
    dist = topology_distances(v.topology, d)
    if j not in dist or v.node_id not in dist:
        return ["OLSR:unreachable"]
    if not dist[j] < dist[v.node_id]:
        return ["OLSR:downhill"]
    return []


# --------------------------------------------------------------------------- M1 (Table 2)
@dataclass
class Obligation:
    node: int
    opened_at: float
    deadline: float
    closed_at: Optional[float] = None


@dataclass
class ReviewObligationMonitor:
    """M1: G(isolate(x) -> F review(x)) (Declare *response*). Monitored only, never blocks (D3).

    The paper gives no deadline; ``deadline_s`` is a configuration choice. ``reinstate`` or an
    explicit ``review`` event closes the obligation.
    """

    deadline_s: float = 120.0
    open: Dict[int, Obligation] = field(default_factory=dict)
    closed: List[Obligation] = field(default_factory=list)

    def on_isolate(self, node: int, now: float) -> None:
        self.open[node] = Obligation(node, now, now + self.deadline_s)

    def on_review(self, node: int, now: float) -> None:
        ob = self.open.pop(node, None)
        if ob is not None:
            ob.closed_at = now
            self.closed.append(ob)

    def overdue(self, now: float) -> List[Obligation]:
        return [o for o in self.open.values() if now > o.deadline]

    def pending_count(self) -> int:
        return len(self.open)
