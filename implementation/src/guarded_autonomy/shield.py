"""The Guarded Autonomy shield: Algorithm 1 (p13), Sec. 4.4.

Three-tier commit:
  1. the agent's proposal, if it parses (I0) and violates no guard;
  2. otherwise the highest-ranked base-protocol candidate that violates no guard;
  3. otherwise the null action (no state change).
Every decision is appended to the hash-chained log when one is attached (Sec. 4.5).
"""
from __future__ import annotations

import time
from typing import Any, Iterable, List, Optional, Sequence

from .config import ShieldConfig
from .decision_log import HashChainLog
from .invariants import IsolationBudget, ReviewObligationMonitor, violations
from .schemas import (
    Action,
    Decision,
    Defer,
    Isolate,
    LocalView,
    Reinstate,
    RouteChange,
    SetPower,
    Tier,
    action_to_dict,
    parse_action,
)


class Shield:
    """Per-node runtime shield. Reads and writes only the daemon's :class:`LocalView`."""

    def __init__(self, view: LocalView, cfg: Optional[ShieldConfig] = None,
                 log: Optional[HashChainLog] = None) -> None:
        self.v = view
        self.cfg = cfg if cfg is not None else ShieldConfig()
        self.log = log
        self.budget = IsolationBudget()
        self.m1 = ReviewObligationMonitor(deadline_s=self.cfg.review_deadline_s)

    # ------------------------------------------------------------------ guards
    def violations(self, action: Optional[Action]) -> List[str]:
        """Violated invariants of a parsed action (``None`` = parse failure -> I0)."""
        return violations(self.v, action, self.cfg, self.budget)

    # ------------------------------------------------------------------ commit
    def apply(self, a: Action) -> None:
        """Commit an admitted action to the daemon state."""
        v = self.v
        if isinstance(a, RouteChange):
            rec = v.adv.get(a.dest, {}).get(a.next_hop)
            e = v.entry(a.dest)
            if rec is not None:                    # EQ-ADOPT: (s, h+1, j, true)
                e.seq, e.hops = rec[0], rec[1] + 1
            e.next_hop, e.valid = a.next_hop, True
        elif isinstance(a, Isolate):
            v.isolated.add(a.node)
            self.budget.record(v.now)
            self.m1.on_isolate(a.node, v.now)
            for e in v.routes.values():            # A4: invalidation strictly increases seq
                if e.valid and e.next_hop == a.node:
                    e.invalidate()
        elif isinstance(a, Reinstate):
            v.isolated.discard(a.node)
            self.m1.on_review(a.node, v.now)
        elif isinstance(a, SetPower):
            v.power_dbm = a.power_dbm

    def decide(self, raw_proposal: Any, base_candidates: Sequence[Action] | Iterable[Action] = ()) -> Decision:
        """Algorithm 1. ``raw_proposal`` is the agent's raw output (dict/JSON/None)."""
        t0 = time.perf_counter()
        cpu0 = time.thread_time_ns()
        a: Optional[Action] = parse_action(raw_proposal) if raw_proposal is not None else Defer()
        viol = self.violations(a)                                   # line 2: Viol
        chosen: Optional[Action] = None
        if a is not None and not isinstance(a, Defer) and not viol:  # line 3
            chosen, tier = a, Tier.AGENT
        else:                                                       # lines 5-9
            tier = Tier.NULL
            if self.cfg.tier2_enabled:
                for b in base_candidates:
                    if not self.violations(b):
                        chosen, tier = b, Tier.BASE
                        break
        if chosen is not None:
            self.apply(chosen)                                      # line 10
        cpu_us = (time.thread_time_ns() - cpu0) / 1e3
        lat = (time.perf_counter() - t0) * 1e6
        reported = viol if (a is None or not isinstance(a, Defer)) else []
        if self.log is not None:                                    # line 11
            self.log.append({"t": self.v.now, "node": self.v.node_id, "raw": raw_proposal,
                             "proposal": action_to_dict(a),
                             "violated": reported, "tier": tier.value, "committed": action_to_dict(chosen)})
        return Decision(tier=tier, action=chosen, violated=reported, latency_us=lat, proposal=a, cpu_us=cpu_us)
