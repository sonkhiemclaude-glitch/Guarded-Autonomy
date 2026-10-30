import importlib

MODULES = [
    "guarded_autonomy", "guarded_autonomy.cli", "guarded_autonomy.schemas", "guarded_autonomy.config",
    "guarded_autonomy.invariants", "guarded_autonomy.shield", "guarded_autonomy.decision_log", "guarded_autonomy.trust",
    "guarded_autonomy.baselines", "guarded_autonomy.agents.scripted", "guarded_autonomy.agents.llm",
    "guarded_autonomy.agents.grammar", "guarded_autonomy.agents.injection", "guarded_autonomy.agents.observation",
    "guarded_autonomy.simulation.model", "guarded_autonomy.simulation.suites", "guarded_autonomy.simulation.harm",
    "guarded_autonomy.metrics.stats", "guarded_autonomy.metrics.component", "guarded_autonomy.metrics.network",
    "guarded_autonomy.metrics.harm", "guarded_autonomy.ns3.protocol", "guarded_autonomy.ns3.bridge",
    "guarded_autonomy.ns3.runner", "guarded_autonomy.ns3.adapters", "guarded_autonomy.experiments.component_check",
    "guarded_autonomy.experiments.tables", "guarded_autonomy.experiments.plots", "guarded_autonomy.experiments.system_eval",
    "guarded_autonomy.experiments.demo", "guarded_autonomy.data.synthetic", "guarded_autonomy.utils.provenance",
]


def test_all_modules_import():
    for m in MODULES:
        importlib.import_module(m)


def test_version():
    import guarded_autonomy
    assert guarded_autonomy.__version__ == "0.1.0"
