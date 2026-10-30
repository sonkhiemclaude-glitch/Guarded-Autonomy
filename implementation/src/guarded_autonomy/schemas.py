"""Data schemas for Guarded Autonomy.

Paper: Sec. 3.1 (action schema, observation), Sec. 4.2 (daemon-maintained local view,
freshness key), Algorithm 1 (decision record).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Set, Tuple, Union

INF_HOPS = 10**9
"""Hop count used for 'no route'. A stored key (s, -INF_HOPS) is below any real route."""

Advertisement = Tuple[int, int]
"""(sequence number, hop count) recorded by the daemon from a received control message."""


def freshness_key(seq: int, hops: int) -> Tuple[int, int]:
    """Freshness key kappa = (s, -h), ordered lexicographically (Sec. 4.2, p9-10)."""
    return (seq, -hops)


# --------------------------------------------------------------------------- actions
class ActionType(str, Enum):
    ROUTE_CHANGE = "route_change"
    ISOLATE = "isolate"
    REINSTATE = "reinstate"
    SET_POWER = "set_power"
    DEFER = "defer"


@dataclass(frozen=True)
class RouteChange:
    """route_change(d, j): use neighbour j as next hop towards destination d (Sec. 3.1)."""

    dest: int
    next_hop: int
    type: ActionType = ActionType.ROUTE_CHANGE


@dataclass(frozen=True)
class Isolate:
    """isolate(x): stop using neighbour x for forwarding (Sec. 3.1)."""

    node: int
    type: ActionType = ActionType.ISOLATE


@dataclass(frozen=True)
class Reinstate:
    """reinstate(x): resume using neighbour x (Sec. 3.1)."""

    node: int
    type: ActionType = ActionType.REINSTATE


@dataclass(frozen=True)
class SetPower:
    """set_power(p): set transmit power to p dBm (Sec. 3.1)."""

    power_dbm: float
    type: ActionType = ActionType.SET_POWER


@dataclass(frozen=True)
class Defer:
    """defer: no action; the base protocol decides (Sec. 3.1)."""

    type: ActionType = ActionType.DEFER


Action = Union[RouteChange, Isolate, Reinstate, SetPower, Defer]


def action_to_dict(a: Optional[Action]) -> Optional[Dict[str, Any]]:
    """Serialise an action to the JSON shape of the action grammar."""
    if a is None:
        return None
    if isinstance(a, RouteChange):
        return {"type": a.type.value, "dest": a.dest, "next_hop": a.next_hop}
    if isinstance(a, (Isolate, Reinstate)):
        return {"type": a.type.value, "node": a.node}
    if isinstance(a, SetPower):
        return {"type": a.type.value, "power_dbm": a.power_dbm}
    return {"type": ActionType.DEFER.value}


def parse_action(raw: Any) -> Optional[Action]:
    """Invariant I0 (schema), Table 2 and Algorithm 1 line 1.

    Accepts a dict or a JSON string with a known ``type`` and correctly typed fields.
    Returns ``None`` ("fail") for free text, unknown types, missing or ill-typed fields,
    and non-finite power values. A ``reason`` field, or any other extra field, is
    discarded and never reaches a guard (design principle D2).
    """
    if isinstance(raw, (Isolate, Reinstate, RouteChange, SetPower, Defer)):
        raw = action_to_dict(raw)
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if not isinstance(raw, dict):
        return None
    t = raw.get("type")
    try:
        if t == "route_change":
            return RouteChange(dest=_as_int(raw["dest"]), next_hop=_as_int(raw["next_hop"]))
        if t == "isolate":
            return Isolate(node=_as_int(raw["node"]))
        if t == "reinstate":
            return Reinstate(node=_as_int(raw["node"]))
        if t == "set_power":
            value = raw["power_dbm"]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            p = float(value)
            if not math.isfinite(p):
                return None
            return SetPower(power_dbm=p)
        if t == "defer":
            return Defer()
    except (KeyError, ValueError, TypeError, OverflowError):
        return None
    return None


def _as_int(x: Any) -> int:
    """Accept JSON integer node identifiers without coercion or truncation."""
    if type(x) is not int:
        raise TypeError("node id must be an integer")
    return x


# --------------------------------------------------------------------------- daemon state
@dataclass
class RouteEntry:
    """Per-destination routing entry; the stored key persists across invalidation (A1)."""

    seq: int = 0
    hops: int = INF_HOPS
    next_hop: Optional[int] = None
    valid: bool = False

    def key(self) -> Tuple[int, int]:
        return freshness_key(self.seq, self.hops)

    def invalidate(self) -> bool:
        """Invalidation (Assumption 2, A4): clear next hop, strictly increase seq, keep hops.

        Returns True if the entry changed. Invalidating an already invalid entry is a no-op
        (math_to_code_audit.md, EQ-INVAL).
        """
        if not self.valid:
            return False
        self.valid = False
        self.next_hop = None
        self.seq += 1
        return True


@dataclass
class LocalView:
    """Daemon-maintained, trusted local state of node i (Sec. 4.2 notation)."""

    node_id: int
    neighbours: Set[int] = field(default_factory=set)
    adv: Dict[int, Dict[int, Advertisement]] = field(default_factory=dict)  # dest -> nbr -> (s, h)
    routes: Dict[int, RouteEntry] = field(default_factory=dict)
    trust: Dict[int, float] = field(default_factory=dict)
    obs_count: Dict[int, int] = field(default_factory=dict)
    isolated: Set[int] = field(default_factory=set)
    energy_j: float = 100.0
    power_dbm: float = 16.0
    now: float = 0.0
    link_margin_db: Dict[int, float] = field(default_factory=dict)
    active_dests: Set[int] = field(default_factory=set)
    # OLSR topology base: node -> set of symmetric neighbours known to this node (Sec. 4.6)
    topology: Dict[int, Set[int]] = field(default_factory=dict)

    def entry(self, d: int) -> RouteEntry:
        return self.routes.setdefault(d, RouteEntry())


# --------------------------------------------------------------------------- decisions
class Tier(str, Enum):
    """Commit tiers of Algorithm 1."""

    AGENT = "agent"
    BASE = "base"
    NULL = "null"


@dataclass
class Decision:
    """Output of Algorithm 1: tier, committed action (or None), violated guards, latency."""

    tier: Tier
    action: Optional[Action]
    violated: list[str]
    latency_us: float
    proposal: Optional[Action] = None
    cpu_us: float = 0.0
