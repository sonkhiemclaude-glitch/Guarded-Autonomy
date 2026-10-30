"""Trust-aware AODV without an LLM (Sec. 7.3): the base ranking filtered by I1, I2 and the same
watchdog-trust guard I3 the shield uses. Implemented directly from the paper's definition.
"""
from __future__ import annotations

from typing import Optional

from ..config import ShieldConfig
from ..invariants import check_route_change
from ..schemas import LocalView, RouteChange
from .aodv import rank_candidates


def trust_aware_update(v: LocalView, dest: int, cfg: Optional[ShieldConfig] = None) -> Optional[RouteChange]:
    """Adopt the highest-ranked candidate admitted by I1, I2 and I3; no agent involved."""
    c = cfg if cfg is not None else ShieldConfig()
    for b in rank_candidates(v, dest):
        if not check_route_change(v, b, c):
            rec = v.adv[dest][b.next_hop]
            e = v.entry(dest)
            e.seq, e.hops, e.next_hop, e.valid = rec[0], rec[1] + 1, b.next_hop, True
            return b
    return None
