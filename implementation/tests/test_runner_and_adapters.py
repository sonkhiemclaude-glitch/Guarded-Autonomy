import json

import pytest

from guarded_autonomy.data.synthetic import write_synthetic_run, write_synthetic_suite
from guarded_autonomy.experiments.system_eval import aggregate
from guarded_autonomy.experiments.tables import system_table
from guarded_autonomy.ns3.adapters import RunDataError, collect, find_missing, summarise_run
from guarded_autonomy.ns3.runner import build_runs, execute, ns3_command, plan

BLOCK = {"ns3": {"root": "/nonexistent/ns-3", "scenario": "guarded-autonomy-manet"},
         "experiments": {"E1": {"n_seeds": 2, "fixed": {"n": 50}, "axes": {"configuration": ["unshielded", "shielded"],
                                                                         "adv_frac": [0.0, 0.2]}}}}


def test_build_runs_and_plan(tmp_path):
    runs = build_runs(BLOCK)
    assert len(runs) == 2 * 2 * 2 and len({r.run_id for r in runs}) == len(runs)
    dirs = plan(BLOCK, tmp_path)
    cfg = json.loads((dirs[0] / "run_config.json").read_text())
    assert cfg["status"] == "planned" and cfg["synthetic"] is False
    cmd = ns3_command(BLOCK, runs[0], dirs[0])
    assert cmd[1] == "run" and "guarded-autonomy-manet" in cmd[2]
    with pytest.raises(FileNotFoundError):
        execute(BLOCK, dirs[0])                                   # no ns-3: refuses
    with pytest.raises(ValueError):
        build_runs({"experiments": {"E": {"axes": {"configuration": ["bogus"]}}}})


def test_planned_runs_are_not_collected(tmp_path):
    plan(BLOCK, tmp_path)
    assert collect(tmp_path) == []


def test_synthetic_pipeline(tmp_path):
    write_synthetic_suite(tmp_path / "runs", seeds=2)
    paths = aggregate(tmp_path / "runs", tmp_path / "tables")
    assert paths["table7"].exists()
    d = write_synthetic_run(tmp_path / "one", "shielded", 0)
    row = summarise_run(d)
    assert row["synthetic"] is True and 0 <= row["pdr"] <= 1
    tab = system_table([row])
    assert tab[0]["synthetic"] is True


def test_missing_files_and_mixing(tmp_path):
    d = write_synthetic_run(tmp_path / "runs", "aodv", 0)
    (d / "packets.csv").unlink()
    assert find_missing(d) == ["packets.csv"]
    with pytest.raises(RunDataError):
        summarise_run(d)
    real = write_synthetic_run(tmp_path / "mix", "aodv", 1)
    cfg = json.loads((real / "run_config.json").read_text())
    cfg.update(synthetic=False, status="finished")
    (real / "run_config.json").write_text(json.dumps(cfg))
    write_synthetic_run(tmp_path / "mix", "shielded", 1)
    with pytest.raises(ValueError):
        aggregate(tmp_path / "mix", tmp_path / "t")
