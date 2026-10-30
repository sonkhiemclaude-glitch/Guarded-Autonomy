"""AODV-side base protocol pieces (Sec. 4.4, Sec. 6.1).

* ``rank_candidates``: the base protocol's own ranking (freshest first, then shortest, then id).
* ``feasibility_rule_update``: the abstract model's "feasibility rule" baseline (DSDV-style use of
  the AODV feasibility condition, applied by a node without an agent and without the shield).

These are *real* baselines fully specified by the paper. Packet-level AODV is ns-3's and is reached
through the bridge (``guarded_autonomy.ns3``).
"""
from __future__ import annotations

from typing import List, Optional

from ..invariants import is_feasible
from ..schemas import LocalView, RouteChange


def rank_candidates(v: LocalView, dest: int) -> List[RouteChange]:
    """Ranked base candidates for ``dest``: neighbours with a record, not isolated,
    ordered by (-seq, hops, id)."""
    advs = v.adv.get(dest, {})
    ranked = sorted((j for j in v.neighbours if j in advs and j not in v.isolated),
                    key=lambda j: (-advs[j][0], advs[j][1], j))
    return [RouteChange(dest=dest, next_hop=j) for j in ranked]


def feasibility_rule_update(v: LocalView, dest: int) -> Optional[RouteChange]:
    """Adopt the highest-ranked advertisement that satisfies I2 (no trust filter)."""
    e = v.entry(dest)
    advs = v.adv.get(dest, {})
    for b in rank_candidates(v, dest):
        rec = advs[b.next_hop]
        if is_feasible(rec, e):
            e.seq, e.hops, e.next_hop, e.valid = rec[0], rec[1] + 1, b.next_hop, True
            return b
    return None
