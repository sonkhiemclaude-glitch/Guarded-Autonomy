"""Input-sanitisation contrast baseline (Sec. 7.3 ablation): strip neighbour-supplied free-text
fields from the agent's observation instead of shielding its output.

This follows the *defence family* of AIOpsShield (Pasquini et al., USENIX Security 2026) as cited
in the paper; it is NOT a reimplementation of AIOpsShield, whose code is not used here.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Iterable

FREE_TEXT_FIELDS = ("status", "name", "description", "note")


def sanitise_observation(obs: Dict[str, Any], fields: Iterable[str] = FREE_TEXT_FIELDS) -> Dict[str, Any]:
    """Return a deep copy of ``obs`` with free-text fields removed from every neighbour entry
    and from ``recent_events``."""
    out = copy.deepcopy(obs)
    drop = set(fields)
    for nb in out.get("neighbours", []):
        for f in list(nb):
            if f in drop:
                del nb[f]
    if "recent_events" in out:
        out["recent_events"] = [{k: val for k, val in ev.items() if k not in drop}
                                for ev in out["recent_events"] if isinstance(ev, dict)]
    return out
