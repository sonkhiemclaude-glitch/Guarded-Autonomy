"""Resolve the effective bridge settings for one immutable planned system run."""
from __future__ import annotations

import copy
from typing import Any, Mapping

from ..config import ShieldConfig

NO_AGENT = {"aodv", "olsr", "trust_aware_aodv"}
LOCAL_PROPOSERS = {"shielded_defer": "defer", "shielded_heuristic": "heuristic"}


def resolve_bridge(block: Mapping[str, Any], params: Mapping[str, Any]) -> dict[str, Any]:
    config = str(params.get("configuration", "shielded"))
    known = NO_AGENT | set(LOCAL_PROPOSERS) | {"unshielded", "shielded", "shielded_no_I3", "shielded_no_I4c",
                        "shielded_no_tier2", "sanitised_unshielded"}
    if config not in known:
        raise ValueError(f"unknown system configuration: {config}")
    bridge = copy.deepcopy(dict(block.get("bridge", {})))
    shield = ShieldConfig.from_mapping(bridge.get("shield", {})).to_dict()
    bridge["shielded"] = config not in {"aodv", "olsr", "unshielded", "sanitised_unshielded"}
    bridge["sanitise_inputs"] = config == "sanitised_unshielded"
    shield["use_trust"] = config != "shielded_no_I3"
    shield["use_rate_limit"] = config != "shielded_no_I4c"
    shield["tier2_enabled"] = config != "shielded_no_tier2"
    bridge["proposer_kind"] = LOCAL_PROPOSERS.get(config, "none" if config in NO_AGENT else "llm")
    if config in NO_AGENT or config in LOCAL_PROPOSERS:
        bridge.pop("agent", None)
        if config == "trust_aware_aodv":
            shield.update(use_loop=False, use_isolation=False, use_power=False)
    else:
        model = str(params.get("model", ""))
        model_config = block.get("models", {}).get(model)
        if block.get("models") and model_config is None:
            raise ValueError(f"no provisioned endpoint for model {model!r}")
        agent = dict(bridge.get("agent", {}))
        if model_config:
            agent.update(model_config)
        if model:
            agent["model"] = model
        if "temperature" in params:
            agent["temperature"] = float(params["temperature"])
        agent.setdefault("extra", {})
        agent["extra"] = {**agent["extra"], "seed": int(params.get("seed", 0))}
        if not agent.get("base_url") or not agent.get("model") or "TODO" in str(agent):
            raise ValueError("agent endpoint and exact model must be provisioned")
        bridge["agent"] = agent
    bridge["shield"] = shield
    return bridge
