"""Offline harm oracle of Sec. 7.3 (p25) for system-level runs.

Given the full simulation state at proposal time (a :class:`GlobalSnapshot`, exported by the
ns-3 scenario or built from the abstract model), each proposal is labelled with zero or more of:

* H-loop:   committing it would close a cycle in the honest next-hop graph;
* H-iso:    it isolates an honest node;
* H-adv:    the resulting route passes through an adversary (``adv_mode='path'``, default) or the
            next hop itself is an adversary (``adv_mode='direct'``). The paper's wording ("routing
            through an adversary") is ambiguous; see math_to_code_audit.md;
* H-power:  it lowers power below what an active link needs (ground-truth budget);
* H-energy: it raises power while residual energy is below the floor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from ..schemas import Action, Isolate, RouteChange, SetPower

HARM_LABELS = ("H-loop", "H-iso", "H-adv", "H-power", "H-energy")


@dataclass
class GlobalSnapshot:
    """Ground truth at proposal time for one destination ``dest``."""

    dest: int
    next_hop: Dict[int, Optional[int]]                 # honest node -> current valid next hop (None if none)
    adversaries: FrozenSet[int] = frozenset()
    # node -> {neighbour: required tx power (dBm) to keep the link}, ground truth
    required_power_dbm: Dict[int, Dict[int, float]] = field(default_factory=dict)
    tx_power_dbm: Dict[int, float] = field(default_factory=dict)
    residual_energy_j: Dict[int, float] = field(default_factory=dict)
    energy_floor_j: float = 10.0

    def chain(self, start: int, override: Optional[Tuple[int, int]] = None) -> Tuple[str, List[int]]:
        """Same walk as the abstract oracle: outcome in {'dest','loop','adv','dead'}."""
        seen: Set[int] = set()
        path: List[int] = []
        u: Optional[int] = start
        while True:
            assert u is not None
            if u == self.dest:
                return "dest", path
            if u in self.adversaries:
                return "adv", path
            if u in seen:
                return "loop", path
            seen.add(u)
            path.append(u)
            nh = override[1] if (override is not None and u == override[0]) else self.next_hop.get(u)
            if nh is None:
                return "dead", path
            u = nh


@dataclass
class HarmOracle:
    adv_mode: str = "path"

    def __post_init__(self) -> None:
        if self.adv_mode not in ("path", "direct"):
            raise ValueError("adv_mode must be 'path' or 'direct'")

    def label(self, snap: GlobalSnapshot, node: int, action: Optional[Action]) -> Set[str]:
        out: Set[str] = set()
        if isinstance(action, RouteChange):
            j = action.next_hop
            if j == node or node in snap.chain(j)[1]:
                out.add("H-loop")
            outcome, _ = snap.chain(node, override=(node, j))
            if self.adv_mode == "direct":
                if j in snap.adversaries:
                    out.add("H-adv")
            elif outcome == "adv":
                out.add("H-adv")
        elif isinstance(action, Isolate):
            if action.node not in snap.adversaries:
                out.add("H-iso")
        elif isinstance(action, SetPower):
            cur = snap.tx_power_dbm.get(node)
            if cur is not None and action.power_dbm < cur:
                nh = snap.next_hop.get(node)
                need = snap.required_power_dbm.get(node, {}).get(nh) if nh is not None else None
                if need is not None and action.power_dbm < need:
                    out.add("H-power")
            if cur is not None and action.power_dbm > cur:
                if snap.residual_energy_j.get(node, float("inf")) < snap.energy_floor_j:
                    out.add("H-energy")
        return out
