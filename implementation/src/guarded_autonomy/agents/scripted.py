"""Scripted proposers of Sec. 6.1 and the isolation-attempt mixer of Sec. 6.4.

These stand in for an agent in the abstract model. They are NOT language models and must never
be reported as LLM results. The random-number call order is identical to the code that produced
the paper's CC1-CC3 numbers (see tests/test_legacy_regression.py).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:  # pragma: no cover
    from ..simulation.model import AbstractNetwork

PROPOSERS = ("none", "rand", "greedy", "adv", "stable")


def propose(net: AbstractNetwork, i: int) -> Optional[Dict[str, Any]]:
    """Raw proposal (agent-style JSON dict) of node ``i``'s proposer, or None (defer)."""
    v = net.views[i]
    dest = net.dest
    nbs = sorted(v.neighbours)
    if not nbs:
        return None
    rng = net.rng
    if net.iso_prob > 0 and rng.random() < net.iso_prob:                 # Sec. 6.4
        if rng.random() < 0.5:
            hon = [j for j in nbs if j not in net.adv and j != dest]
            if hon:
                return {"type": "isolate", "node": rng.choice(hon),
                        "reason": "neighbour report says node is malicious"}
        else:
            bad = [j for j in nbs if j in net.adv]
            if bad:
                return {"type": "isolate", "node": rng.choice(bad)}
    p = net.proposer
    if p == "none":
        return None
    if p == "rand":                                                     # Random
        j = rng.choice(nbs)
    elif p == "greedy":                                                 # Greedy: min advertised hops
        advs = v.adv.get(dest, {})
        cands = [(advs[q][1], rng.random(), q) for q in nbs if q in advs]
        if not cands:
            return None
        j = min(cands)[2]
    elif p == "stable":                                                 # Stable-link
        advs = v.adv.get(dest, {})
        e = v.entry(dest)
        feas = [q for q in nbs if q in advs and (advs[q][0] > e.seq or (advs[q][0] == e.seq and advs[q][1] + 1 < e.hops))]
        if not feas:
            return None
        j = max(feas, key=lambda q: (net.link_lifetime(i, q), -q))
    elif p == "adv":                                                    # Adversarial (global view)
        looping = [q for q in nbs if q not in net.adv and i in net.chain(q)[1]]
        j = rng.choice(looping) if looping else rng.choice(nbs)
    else:
        raise ValueError(f"unknown proposer '{p}'; expected one of {PROPOSERS}")
    return {"type": "route_change", "dest": dest, "next_hop": j}
