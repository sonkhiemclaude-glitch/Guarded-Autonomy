"""Baselines of Sec. 7.3, separated by kind.

* real, implemented here: feasibility rule (abstract model), trust-aware AODV filter,
  unshielded agent (commit everything; in the simulator), input sanitisation transform.
* external, reached through ns-3: packet-level AODV and OLSR (``guarded_autonomy.ns3``).
* test-only: scripted proposers in ``guarded_autonomy.agents.scripted``.
"""
from .aodv import feasibility_rule_update, rank_candidates
from .sanitisation import sanitise_observation
from .trust_aware import trust_aware_update

BASELINE_REGISTRY = {
    "feasibility_rule": {"kind": "real", "where": "baselines.aodv.feasibility_rule_update"},
    "trust_aware_aodv": {"kind": "real", "where": "baselines.trust_aware.trust_aware_update"},
    "unshielded_agent": {"kind": "real", "where": "simulation.model.AbstractNetwork (mode='unshielded')"},
    "input_sanitisation": {"kind": "real", "where": "baselines.sanitisation.sanitise_observation"},
    "aodv_ns3": {"kind": "external", "where": "ns-3 aodv module via ns3.runner"},
    "olsr_ns3": {"kind": "external", "where": "ns-3 olsr module via ns3.runner"},
}

__all__ = ["BASELINE_REGISTRY", "feasibility_rule_update", "rank_candidates", "sanitise_observation",
           "trust_aware_update"]
