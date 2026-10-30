"""Fixed local proposers for matched no-LLM controls; no access to simulator truth."""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Mapping, Optional

from ..config import ShieldConfig
from .llm import AgentReply, LLMAgent, LLMEndpointConfig

POLICY_VERSION = "local-full-action-v2"


def defer_policy(observation: dict[str, Any]) -> AgentReply:
    return AgentReply('{"type":"defer"}', 0.0)


class LocalHeuristic:
    """Evidence-based isolation/reinstatement, stable routes and bounded power adaptation."""

    def __init__(self, config: ShieldConfig) -> None:
        self.config = config

    def __call__(self, observation: dict[str, Any]) -> AgentReply:
        start = time.perf_counter()
        cfg = self.config
        routes = {int(r["dest"]): r for r in observation.get("routes", [])}
        active = sorted(int(d) for d in observation.get("active_destinations", []))
        if not active:
            active = sorted({int(e["dest"]) for e in observation.get("recent_events", []) if "dest" in e})
        choices: list[tuple[tuple[float, ...], dict[str, Any]]] = []
        for dest in active:
            old = routes.get(dest, {})
            old_key = (int(old.get("seq", 0)), -int(old.get("hops") or 65535))
            for neighbor in observation.get("neighbours", []):
                node = int(neighbor["id"])
                if neighbor.get("isolated") or node == observation.get("node") or dest == observation.get("node"):
                    continue
                count = int(neighbor.get("observations", 0))
                trust = float(neighbor.get("trust", .5))
                if count >= cfg.min_obs_route and trust < cfg.trust_min_route:
                    continue
                advertisement = neighbor.get("advertised", {}).get(str(dest))
                if not advertisement:
                    continue
                seq, hops = int(advertisement["seq"]), int(advertisement["hops"]) + 1
                if (seq, -hops) <= old_key:
                    continue
                # Fewer hops are secondary to observed stability and evidence-backed trust.
                score = (trust if count >= cfg.min_obs_route else .5,
                         float(neighbor.get("rssi_trend_db_per_s", 0.0)),
                         float(neighbor.get("link_margin_db", 0.0)), -float(hops), float(seq), -float(node), -float(dest))
                choices.append((score, {"type": "route_change", "dest": dest, "next_hop": node}))
        neighbors = list(observation.get("neighbours", []))
        bad = [n for n in neighbors if not n.get("isolated")
               and int(n.get("observations", 0)) >= cfg.min_obs_isolate
               and float(n.get("trust", .5)) < cfg.trust_max_isolate]
        recovered = [n for n in neighbors if n.get("isolated")
                     and int(n.get("observations", 0)) >= cfg.min_obs_isolate
                     and float(n.get("trust", .5)) >= cfg.trust_min_route]
        if bad:
            target = min(bad, key=lambda n: (float(n.get("trust", .5)), int(n["id"])))
            action = {"type": "isolate", "node": int(target["id"])}
        elif recovered:
            action = {"type": "reinstate", "node": min(int(n["id"]) for n in recovered)}
        elif choices:
            action = max(choices, key=lambda item: item[0])[1]
        else:
            power = float(observation.get("tx_power_dbm", 16.0))
            energy = float(observation.get("residual_energy_j", 0.0))
            unavailable = any(not routes.get(d, {}).get("valid", False) for d in active)
            current = {int(r["next_hop"]) for d, r in routes.items()
                       if d in active and r.get("valid") and r.get("next_hop") is not None}
            margins = {int(n["id"]): float(n["link_margin_db"]) for n in neighbors if "link_margin_db" in n}
            risky = any(margins.get(j, -float("inf")) < 6 for j in current)
            if active and (unavailable or risky) and energy >= cfg.energy_floor_j and power < cfg.p_max_dbm:
                action = {"type": "set_power", "power_dbm": min(cfg.p_max_dbm, power + 2.0)}
            elif active and not unavailable and current and power > 16.0 and all(
                    margins.get(j, -float("inf")) >= min(2.0, power - 16.0) + 3.0 for j in current):
                action = {"type": "set_power", "power_dbm": max(16.0, power - 2.0)}
            else:
                action = {"type": "defer"}
        return AgentReply(json.dumps(action, sort_keys=True), (time.perf_counter() - start) * 1000)


def make_proposer(block: Mapping[str, Any]) -> Optional[Callable[[dict[str, Any]], AgentReply]]:
    kind = block.get("proposer_kind", "llm" if block.get("agent") else "none")
    if kind == "none":
        return None
    if kind == "defer":
        return defer_policy
    if kind == "heuristic":
        return LocalHeuristic(ShieldConfig.from_mapping(block.get("shield", {})))
    if kind == "llm":
        return LLMAgent(LLMEndpointConfig(**block["agent"])).propose
    raise ValueError(f"unknown proposer kind {kind!r}")
