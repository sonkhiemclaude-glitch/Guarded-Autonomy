from guarded_autonomy.config import LOOP_ONLY
from guarded_autonomy.simulation.model import AbstractNetwork, ModelParams
from guarded_autonomy.utils.provenance import SYNTHETIC_LABEL, config_hash, run_metadata

VOLATILE = {"lat_median_us", "lat_p99_us"}


def _run(seed):
    r = AbstractNetwork(ModelParams(n=20, seed=seed, mode="shielded", proposer="rand", steps=50), LOOP_ONLY).run()
    return {k: v for k, v in r.items() if k not in VOLATILE}


def test_same_seed_same_result():
    assert _run(3) == _run(3)


def test_different_seed_different_result():
    assert _run(3) != _run(4)


def test_pairing_mobility_independent_of_mode():
    a = AbstractNetwork(ModelParams(n=20, seed=5, mode="base", proposer="none", steps=1))
    b = AbstractNetwork(ModelParams(n=20, seed=5, mode="unshielded", proposer="adv", steps=1))
    for _ in range(30):
        a.step()
        b.step()
    assert a.pos == b.pos and a.adv == b.adv


def test_metadata():
    md = run_metadata({"x": 1}, synthetic=True)
    assert md["synthetic"] and md["label"] == SYNTHETIC_LABEL and md["config_sha256"] == config_hash({"x": 1})
    assert len(md["code_files"]) > 20
