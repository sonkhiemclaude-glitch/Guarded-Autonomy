"""Watchdog trust estimate (Table A.8, p40): tau = (a + 1) / (a + b + 2).

a: observed forwards, b: observed drops. This is the paper's own choice of estimator; the
watchdog concept follows Marti et al. (2000).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple


def beta_trust(forwards: int, drops: int) -> float:
    """Trust estimate (a+1)/(a+b+2); 0.5 for no observations."""
    if forwards < 0 or drops < 0:
        raise ValueError("counts must be non-negative")
    return (forwards + 1.0) / (forwards + drops + 2.0)


@dataclass
class WatchdogTrust:
    """Per-neighbour forward/drop counts maintained by the routing daemon of one node."""

    counts: Dict[int, Tuple[int, int]] = field(default_factory=dict)

    def observe(self, neighbour: int, dropped: bool) -> Tuple[float, int]:
        a, b = self.counts.get(neighbour, (0, 0))
        a, b = (a, b + 1) if dropped else (a + 1, b)
        self.counts[neighbour] = (a, b)
        return beta_trust(a, b), a + b

    def trust(self, neighbour: int) -> float:
        a, b = self.counts.get(neighbour, (0, 0))
        return beta_trust(a, b)

    def observations(self, neighbour: int) -> int:
        a, b = self.counts.get(neighbour, (0, 0))
        return a + b
