"""Agent observation schema (Sec. 3.1, Sec. 7.1 'Observation schema').

The observation is what the (untrusted) agent reads. It includes neighbour-supplied free-text
``status`` fields, which are the prompt-injection channel (attack T4). The shield never reads the
observation; it reads the daemon's LocalView (principle D2).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional

from ..schemas import INF_HOPS, LocalView

OBSERVATION_VERSION = 1


def build_observation(v: LocalView, status_fields: Optional[Mapping[int, str]] = None,
                      rssi_dbm: Optional[Mapping[int, float]] = None,
                      link_age_s: Optional[Mapping[int, float]] = None,
                      recent_events: Iterable[Mapping[str, Any]] = (),
                      route_lifetime_s: Optional[Mapping[int, float]] = None) -> Dict[str, Any]:
    """Serialise a node's view into the fixed observation schema (docs/data_format.md)."""
    status_fields = status_fields or {}
    rssi_dbm = rssi_dbm or {}
    link_age_s = link_age_s or {}
    route_lifetime_s = route_lifetime_s or {}
    neighbours = []
    for j in sorted(v.neighbours):
        adv = {str(d): {"seq": rec[0], "hops": rec[1]} for d, recs in sorted(v.adv.items())
               for nb, rec in recs.items() if nb == j}
        entry: Dict[str, Any] = {"id": j, "trust": round(v.trust.get(j, 0.5), 4),
                                 "observations": v.obs_count.get(j, 0), "isolated": j in v.isolated,
                                 "advertised": adv}
        if j in rssi_dbm:
            entry["rssi_dbm"] = rssi_dbm[j]
        if j in link_age_s:
            entry["link_age_s"] = link_age_s[j]
        if j in status_fields:
            entry["status"] = status_fields[j]          # untrusted free text (T4 channel)
        neighbours.append(entry)
    routes = []
    for d, e in sorted(v.routes.items()):
        routes.append({"dest": d, "seq": e.seq, "hops": None if e.hops >= INF_HOPS else e.hops,
                       "next_hop": e.next_hop, "valid": e.valid,
                       **({"lifetime_s": route_lifetime_s[d]} if d in route_lifetime_s else {})})
    return {"version": OBSERVATION_VERSION, "node": v.node_id, "time_s": v.now,
            "neighbours": neighbours, "routes": routes,
            "residual_energy_j": v.energy_j, "tx_power_dbm": v.power_dbm,
            "recent_events": [dict(e) for e in recent_events]}
