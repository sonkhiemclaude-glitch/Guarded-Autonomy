"""Bridge protocol between an ns-3 scenario (C++) and the Python shield/agent process (Sec. 7.1).

Transport: one JSON object per line over a local TCP socket (ns3-gym style coupling). Messages
from ns-3 to the bridge:

* ``hello``  {"type":"hello","version":1,"run_id":str,"nodes":int}
* ``decide`` {"type":"decide","node":int,"t":float,"view":VIEW,"observation":OBS,
              "base_candidates":[ACTION,...],"oracle":SNAPSHOT?}
    agent decision point; the bridge queries the agent, runs Algorithm 1 on VIEW and returns the
    committed action. ``oracle`` is simulation ground truth used ONLY for offline harm labels;
    it is stripped before the agent or the shield see anything.
* ``check``  {"type":"check","node":int,"t":float,"view":VIEW,"action":ACTION}
    guard-only check for the base protocol's own route updates (assumption A4).
* ``anchor`` {"type":"anchor","node":int}  returns the node's log head (Sec. 4.5).
* ``bye``

Replies: ``decision`` {"tier","action","violated","latency_us","agent_latency_ms","agent_error"},
``check_result`` {"violated":[...]}, ``anchor`` {"head","length"}, ``error`` {"message"}.
VIEW is the JSON form of :class:`LocalView` (``view_to_json`` / ``view_from_json``).
"""
from __future__ import annotations

from typing import Any, Dict

from ..schemas import LocalView, RouteEntry

PROTOCOL_VERSION = 1


def view_to_json(v: LocalView) -> Dict[str, Any]:
    return {
        "node_id": v.node_id, "neighbours": sorted(v.neighbours),
        "adv": {str(d): {str(j): list(rec) for j, rec in recs.items()} for d, recs in v.adv.items()},
        "routes": {str(d): {"seq": e.seq, "hops": e.hops, "next_hop": e.next_hop, "valid": e.valid}
                   for d, e in v.routes.items()},
        "trust": {str(k): val for k, val in v.trust.items()},
        "obs_count": {str(k): val for k, val in v.obs_count.items()},
        "isolated": sorted(v.isolated), "energy_j": v.energy_j, "power_dbm": v.power_dbm, "now": v.now,
        "link_margin_db": {str(k): val for k, val in v.link_margin_db.items()},
        "active_dests": sorted(v.active_dests),
        "topology": {str(k): sorted(s) for k, s in v.topology.items()},
    }


def view_from_json(o: Dict[str, Any]) -> LocalView:
    """Parse a VIEW object; raises ValueError with a clear message on malformed input."""
    try:
        v = LocalView(node_id=int(o["node_id"]))
        v.neighbours = {int(x) for x in o.get("neighbours", [])}
        v.adv = {int(d): {int(j): (int(r[0]), int(r[1])) for j, r in recs.items()}
                 for d, recs in o.get("adv", {}).items()}
        v.routes = {int(d): RouteEntry(seq=int(e["seq"]), hops=int(e["hops"]),
                                       next_hop=None if e.get("next_hop") is None else int(e["next_hop"]),
                                       valid=bool(e["valid"])) for d, e in o.get("routes", {}).items()}
        v.trust = {int(k): float(x) for k, x in o.get("trust", {}).items()}
        v.obs_count = {int(k): int(x) for k, x in o.get("obs_count", {}).items()}
        v.isolated = {int(x) for x in o.get("isolated", [])}
        v.energy_j = float(o.get("energy_j", 100.0))
        v.power_dbm = float(o.get("power_dbm", 16.0))
        v.now = float(o.get("now", 0.0))
        v.link_margin_db = {int(k): float(x) for k, x in o.get("link_margin_db", {}).items()}
        v.active_dests = {int(x) for x in o.get("active_dests", [])}
        v.topology = {int(k): {int(x) for x in s} for k, s in o.get("topology", {}).items()}
        return v
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise ValueError(f"malformed VIEW object: {exc}") from exc
