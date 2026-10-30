import pytest

from guarded_autonomy.config import FULL, LOOP_ONLY
from guarded_autonomy.simulation.model import AbstractNetwork, ModelParams
from guarded_autonomy.simulation.suites import build_matrix, paper_matrix


@pytest.mark.parametrize("proposer", ["rand", "greedy", "adv", "stable"])
def test_p2_key_order_and_no_loops(proposer):
    """Proposition 2 in the abstract model: under the shield every honest edge has kappa_i < kappa_j
    and no honest next-hop chain loops, at every step."""
    for seed in range(4):
        net = AbstractNetwork(ModelParams(n=30, seed=seed, mode="shielded", proposer=proposer, p_dec=0.3, steps=60), LOOP_ONLY)
        for _ in range(60):
            net.step()
            assert net.key_order_violations() == []
            assert net.m.looping_frac[-1] == 0.0


def test_p2_holds_with_adversaries_on_honest_subgraph():
    for attack in ("inflate", "shortcut"):
        net = AbstractNetwork(ModelParams(n=30, seed=1, mode="shielded", proposer="adv", adv_frac=0.2, attack=attack,
                                          p_dec=0.3, steps=60), FULL)
        for _ in range(60):
            net.step()
            assert net.key_order_violations() == []


def test_unshielded_adversarial_creates_loops():
    net = AbstractNetwork(ModelParams(n=30, seed=1, mode="unshielded", proposer="adv", p_dec=0.3, steps=80), LOOP_ONLY)
    row = net.run()
    assert row["loop_step_frac"] > 0 and row["loop_creating_committed"] > 0


def test_trust_aware_mode_runs_without_agent():
    row = AbstractNetwork(ModelParams(n=20, seed=0, mode="trust_aware", proposer="none", adv_frac=0.1, steps=40), FULL).run()
    assert row["proposals"] == 0 and row["loop_step_frac"] == 0.0


def test_params_validation():
    with pytest.raises(ValueError):
        ModelParams(mode="nope")
    with pytest.raises(ValueError):
        ModelParams(proposer="llm")
    with pytest.raises(ValueError):
        ModelParams(adv_frac=1.5)
    with pytest.raises(ValueError):
        ModelParams(n=2)


def test_paper_matrix_sizes_match_paper():
    assert len(paper_matrix("cc1")) == 540 and len(paper_matrix("cc2")) == 160 and len(paper_matrix("cc3")) == 80


def test_build_matrix_from_config():
    specs = build_matrix({"suites": ["cc1"], "n_seeds": 2, "steps": 10, "cc1": {"ns": [20], "vmaxs": [20.0],
                                                                               "proposers": ["rand"]}})
    assert len(specs) == 2 * (1 + 2)  # per seed: base + unshielded + shielded
    with pytest.raises(ValueError):
        build_matrix({"suites": ["cc9"]})
