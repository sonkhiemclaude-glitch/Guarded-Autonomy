"""Guarded Autonomy shield: reference implementation (Python, abstract model).

This is a reference implementation of the per-node shield described in the
manuscript. It is not an ns-3 module. It operates on an abstract per-node view
that the trusted routing daemon maintains (routing entries, last received
advertisements, watchdog trust, residual energy, transmit power).

Design principles implemented here:
  D1  Every committed action is checked; fallback is three-tier
      (agent proposal -> highest-ranked permitted base-protocol candidate -> null).
  D2  Checks read only daemon-maintained state; fields supplied by the agent
      (e.g. a "reason" string) are never used in a decision.
  D3  Invariants are safety properties: each is a predicate over the current
      state plus a bounded past (window counters), so a check is O(1) per slice.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

INF = 10 ** 9

# ---------------------------------------------------------------------------
# Actions (the agent's output schema). Anything else is rejected by I0.
# ---------------------------------------------------------------------------
ACTION_TYPES = {"route_change", "isolate", "reinstate", "set_power", "defer"}


def parse_action(raw) -> Optional[dict]:
    """I0 (schema): accept only a dict with a known type and typed fields.

    Returns a normalised action or None. Free text, extra fields used for
    decisions, or unknown types are rejected; a 'reason' field is ignored (D2).
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if not isinstance(raw, dict) or raw.get("type") not in ACTION_TYPES:
        return None
    t = raw["type"]
    try:
        if t == "route_change":
            return {"type": t, "dest": int(raw["dest"]), "next_hop": int(raw["next_hop"])}
        if t in ("isolate", "reinstate"):
            return {"type": t, "node": int(raw["node"])}
        if t == "set_power":
            return {"type": t, "power_dbm": float(raw["power_dbm"])}
        return {"type": "defer"}
    except (KeyError, ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Daemon-maintained local view (trusted)
# ---------------------------------------------------------------------------
@dataclass
class RouteEntry:
    seq: int = 0          # stored destination sequence number (kept across invalidation)
    hops: int = INF       # stored hop count
    next_hop: Optional[int] = None
    valid: bool = False

    def key(self) -> Tuple[int, int]:
        return (self.seq, -self.hops)


@dataclass
class LocalView:
    node_id: int
    neighbours: set = field(default_factory=set)            # current symmetric neighbours
    adv: Dict[int, Dict[int, Tuple[int, int]]] = field(default_factory=dict)  # dest -> nbr -> (seq, hops)
    routes: Dict[int, RouteEntry] = field(default_factory=dict)
    trust: Dict[int, float] = field(default_factory=dict)   # watchdog trust in [0,1]
    obs_count: Dict[int, int] = field(default_factory=dict)
    isolated: set = field(default_factory=set)
    energy_j: float = 100.0
    power_dbm: float = 16.0
    now: float = 0.0
    link_margin_db: Dict[int, float] = field(default_factory=dict)  # est. margin at current power
    active_dests: set = field(default_factory=set)

    def entry(self, d: int) -> RouteEntry:
        return self.routes.setdefault(d, RouteEntry())


@dataclass
class ShieldConfig:
    trust_min_route: float = 0.7     # I3: next hop must have trust >= this ...
    min_obs_route: int = 5           # ... once at least this many observations exist
    trust_max_isolate: float = 0.5   # I4a: isolate only if trust <= this
    min_obs_isolate: int = 10        # I4b: evidence precedence (>= m observations)
    iso_window_s: float = 60.0       # I4c: at most k isolations per window
    iso_max_in_window: int = 2
    p_min_dbm: float = 0.0           # I5a
    p_max_dbm: float = 20.0
    energy_floor_j: float = 10.0     # I6: no power increase below floor
    use_loop: bool = True
    use_trust: bool = True
    use_isolation: bool = True
    use_power: bool = True


@dataclass
class Decision:
    tier: str                 # "agent" | "base" | "null"
    action: Optional[dict]
    violated: List[str]       # invariants violated by the agent proposal (empty if accepted)
    latency_us: float


class HashChainLog:
    """Append-only hash-chained decision log (tamper-evident w.r.t. an anchored head)."""

    def __init__(self):
        self.entries: List[dict] = []
        self.head = "0" * 64

    def append(self, record: dict) -> str:
        body = json.dumps(record, sort_keys=True)
        h = hashlib.sha256((self.head + body).encode()).hexdigest()
        self.entries.append({"prev": self.head, "body": body, "hash": h})
        self.head = h
        return h

    def verify(self, anchored_head: Optional[str] = None) -> bool:
        prev = "0" * 64
        for e in self.entries:
            if e["prev"] != prev:
                return False
            if hashlib.sha256((prev + e["body"]).encode()).hexdigest() != e["hash"]:
                return False
            prev = e["hash"]
        return anchored_head is None or prev == anchored_head


class Shield:
    def __init__(self, view: LocalView, cfg: ShieldConfig = ShieldConfig(), log: Optional[HashChainLog] = None):
        self.v = view
        self.cfg = cfg
        self.log = log
        self.iso_times: List[float] = []

    # ---------------- invariants (each returns list of violated ids) ----------
    def _check_route_change(self, a: dict) -> List[str]:
        v, c = self.v, self.cfg
        d, j = a["dest"], a["next_hop"]
        bad = []
        if d == v.node_id:
            bad.append("I1:not-destination")   # the destination never installs a route to itself
            return bad
        if j not in v.neighbours or j == v.node_id:
            bad.append("I1:symmetric-neighbour")
            return bad
        if j in v.isolated:
            bad.append("I1:not-isolated")
        if c.use_loop:
            rec = v.adv.get(d, {}).get(j)          # D2: daemon record, never agent claims
            if rec is None:
                bad.append("I2:no-advertisement")
            else:
                s_j, h_j = rec
                e = v.entry(d)
                feasible = (s_j > e.seq) or (s_j == e.seq and h_j + 1 < e.hops)
                if not feasible:
                    bad.append("I2:feasibility")
        if c.use_trust and v.obs_count.get(j, 0) >= c.min_obs_route and v.trust.get(j, 0.5) < c.trust_min_route:
            bad.append("I3:trust-next-hop")
        return bad

    def _check_isolate(self, a: dict) -> List[str]:
        v, c = self.v, self.cfg
        x = a["node"]
        bad = []
        if x == v.node_id or x not in v.neighbours:
            bad.append("I4:target")
            return bad
        if x in v.isolated:
            bad.append("I4:already-isolated")
            return bad
        if not c.use_isolation:
            return bad
        if v.trust.get(x, 0.5) > c.trust_max_isolate:
            bad.append("I4a:trust-threshold")
        if v.obs_count.get(x, 0) < c.min_obs_isolate:
            bad.append("I4b:evidence-precedence")
        # isolations strictly before now within the window; list pruned to at most k entries
        self.iso_times = [t for t in self.iso_times if v.now - t < c.iso_window_s][-c.iso_max_in_window:]
        if len(self.iso_times) >= c.iso_max_in_window:
            bad.append("I4c:rate-limit")
        return bad

    def _check_power(self, a: dict) -> List[str]:
        v, c = self.v, self.cfg
        p = a["power_dbm"]
        bad = []
        if not c.use_power:
            return bad
        if not (c.p_min_dbm <= p <= c.p_max_dbm):
            bad.append("I5a:power-range")
        if p > v.power_dbm and v.energy_j < c.energy_floor_j:
            bad.append("I6:energy-floor")
        if p < v.power_dbm:
            drop = v.power_dbm - p
            for d in v.active_dests:
                e = v.routes.get(d)
                if e and e.valid and e.next_hop is not None and v.link_margin_db.get(e.next_hop, 0.0) - drop < 0:
                    bad.append("I5b:keep-active-links")
                    break
        return bad

    def violations(self, a: Optional[dict]) -> List[str]:
        if a is None:
            return ["I0:schema"]
        t = a["type"]
        if t == "route_change":
            return self._check_route_change(a)
        if t == "isolate":
            return self._check_isolate(a)
        if t == "reinstate":
            return [] if a["node"] in self.v.isolated else ["I4:reinstate-precedence"]
        if t == "set_power":
            return self._check_power(a)
        return []  # defer

    # ---------------- commit ---------------------------------------------------
    def _apply(self, a: dict):
        v = self.v
        t = a["type"]
        if t == "route_change":
            d, j = a["dest"], a["next_hop"]
            rec = v.adv.get(d, {}).get(j)
            e = v.entry(d)
            if rec is not None:
                e.seq, e.hops = rec[0], rec[1] + 1
            e.next_hop, e.valid = j, True
        elif t == "isolate":
            v.isolated.add(a["node"])
            self.iso_times.append(v.now)
            for e in v.routes.values():
                if e.valid and e.next_hop == a["node"]:
                    e.valid, e.next_hop = False, None
                    e.seq += 1  # RFC 3561 6.11: increment on invalidation
        elif t == "reinstate":
            v.isolated.discard(a["node"])
        elif t == "set_power":
            v.power_dbm = a["power_dbm"]

    def decide(self, raw_proposal, base_candidates: List[dict]) -> Decision:
        """Three-tier commit. base_candidates: base protocol's ranked actions."""
        t0 = time.perf_counter()
        a = parse_action(raw_proposal) if raw_proposal is not None else {"type": "defer"}
        viol = self.violations(a)
        if a is not None and a["type"] != "defer" and not viol:
            chosen, tier = a, "agent"
        else:
            chosen, tier = None, "null"
            for b in base_candidates:
                if not self.violations(b):
                    chosen, tier = b, "base"
                    break
        if chosen is not None:
            self._apply(chosen)
        lat = (time.perf_counter() - t0) * 1e6
        if self.log is not None:
            self.log.append({"t": self.v.now, "node": self.v.node_id, "proposal": a, "violated": viol,
                             "tier": tier, "committed": chosen})
        return Decision(tier, chosen, viol if (a is None or a["type"] != "defer") else [], lat)
