import json
import subprocess
import sys

import yaml

from guarded_autonomy.cli import main

TINY = {"name": "tiny", "kind": "component_check", "seed": 0, "synthetic": True,
        "component_check": {"suites": ["cc1", "cc3"], "n_seeds": 2, "steps": 15,
                            "cc1": {"ns": [20], "vmaxs": [20.0], "proposers": ["rand", "stable"]},
                            "cc3": {"n": 20, "taus": [0.5], "watchdogs": [[0.05, 0.0]]}}}


def test_help_runs(repo_root):
    r = subprocess.run([sys.executable, "-m", "guarded_autonomy.cli", "--help"], cwd=repo_root, capture_output=True,
                       text=True, env={"PYTHONPATH": str(repo_root / "src"), "PATH": ""})
    assert r.returncode == 0 and "No paper-level experimental results" in r.stdout


def test_component_check_tables_plot(tmp_path, capsys):
    cfgp = tmp_path / "c.yaml"
    cfgp.write_text(yaml.safe_dump(TINY))
    assert main(["component-check", "--config", str(cfgp), "--output", str(tmp_path / "out")]) == 0
    out = tmp_path / "out" / "tiny"
    md = json.loads((out / "run_metadata.json").read_text())
    assert md["synthetic"] is True and md["label"].startswith("synthetic smoke-test output")
    assert (out / "tables" / "cc1_table.csv").exists() and (out / "tables" / "cc1_main.tex").exists()
    assert main(["plot", "--input", str(out), "--output", str(tmp_path / "fig")]) == 0
    assert (tmp_path / "fig" / "cc1_v20.png").exists()
    assert main(["tables", "--input", str(out), "--output", str(tmp_path / "t2")]) == 0


def test_demo_and_plan(tmp_path, repo_root):
    assert main(["demo", "--config", str(repo_root / "configs" / "synthetic_demo.yaml"), "--output", str(tmp_path)]) == 0
    demo = tmp_path / "synthetic_demo"
    assert (demo / "README_SYNTHETIC.txt").exists() and (demo / "figures" / "cc1_synthetic.png").exists()
    rt = json.loads((demo / "bridge" / "roundtrip.json").read_text())
    assert rt["log_verifies_against_anchor"] is True
    assert main(["ns3-plan", "--config", str(repo_root / "configs" / "experiment_template.yaml"),
                 "--output", str(tmp_path / "plan")]) == 0
    assert any((tmp_path / "plan").rglob("command.txt"))


def test_execute_requires_flag(tmp_path, repo_root):
    import pytest
    with pytest.raises(SystemExit):
        main(["ns3-execute", "--config", str(repo_root / "configs" / "experiment_template.yaml"), "--run-dir", str(tmp_path)])


def test_verify_log(tmp_path):
    from guarded_autonomy.decision_log import HashChainLog
    log = HashChainLog()
    log.append({"a": 1})
    p = tmp_path / "l.jsonl"
    log.save_jsonl(p)
    assert main(["verify-log", "--log", str(p), "--head", log.head]) == 0
    assert main(["verify-log", "--log", str(p), "--head", "0" * 64]) == 1
