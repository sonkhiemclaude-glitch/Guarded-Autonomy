"""Run-matrix builder and launcher for the system-level evaluation E1-E5 (Sec. 7).

Mac Studio-ready. By default nothing is executed: ``plan`` writes one directory per run with a
``run_config.json`` and the exact ns-3 command line. ``execute`` runs a planned directory only if
``ns3.root`` points to an ns-3 tree that contains the scenario program; it never downloads
anything. The ns-3 scenario program itself (C++, AODV routing-table hook for A4, HELLO status TLV,
attacks T1-T4, exporters) is NOT part of this repository yet: TODO_IMPLEMENTATION.md NS3-1..NS3-6.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import logging
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping

log = logging.getLogger(__name__)

CONFIGURATIONS = ("aodv", "olsr", "trust_aware_aodv", "unshielded", "shielded",
                  "shielded_no_I3", "shielded_no_I4c", "shielded_no_tier2", "sanitised_unshielded")


@dataclass(frozen=True)
class SystemRun:
    run_id: str
    experiment: str
    params: Dict[str, Any]


def _rid(params: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:12]


def build_runs(block: Mapping[str, Any]) -> List[SystemRun]:
    """Cartesian product of the axes in an ``ns3_system`` config block, per experiment."""
    exps = block.get("experiments", {})
    if not isinstance(exps, dict) or not exps:
        raise ValueError("ns3_system.experiments must be a non-empty mapping")
    runs: List[SystemRun] = []
    for name, ex in exps.items():
        axes = {k: list(v) for k, v in ex.get("axes", {}).items()}
        for c in axes.get("configuration", []):
            if c not in CONFIGURATIONS:
                raise ValueError(f"{name}: unknown configuration '{c}'")
        keys = sorted(axes)
        seeds = list(range(int(ex.get("n_seeds", 10))))
        fixed = dict(ex.get("fixed", {}))
        for combo in itertools.product(*(axes[k] for k in keys)):
            for s in seeds:
                p = {**fixed, **dict(zip(keys, combo)), "seed": s, "experiment": name}
                runs.append(SystemRun(run_id=f"{name}-{_rid(p)}", experiment=name, params=p))
    return runs


def ns3_command(block: Mapping[str, Any], run: SystemRun, run_dir: Path) -> List[str]:
    """The ns-3 invocation: ``<root>/ns3 run "<scenario> --k=v ..."`` (ns-3 >= 3.36 front end)."""
    ns3 = block.get("ns3", {})
    root = Path(str(ns3.get("root", ""))).expanduser().resolve()
    scenario = str(ns3.get("scenario", "guarded-autonomy-manet"))
    args = [f"--{k}=" + ("true" if v is True else "false" if v is False else str(v))
            for k, v in sorted(run.params.items())]
    args += [f"--outDir={run_dir.resolve()}", f"--bridgePort={ns3.get('bridge_port', 5577)}"]
    return [str(root / "ns3"), "run", shlex.join([scenario, *args])]


def plan(block: Mapping[str, Any], out_root: Path) -> List[Path]:
    """Write run directories with run_config.json and command.txt; execute nothing."""
    dirs: List[Path] = []
    for run in build_runs(block):
        d = out_root / run.experiment / run.run_id
        if (d / "run_config.json").exists():
            raise FileExistsError(f"refusing to overwrite planned or completed run {d}")
        d.mkdir(parents=True, exist_ok=True)
        (d / "run_config.json").write_text(json.dumps({"run_id": run.run_id, "experiment": run.experiment,
                                                       "params": run.params, "synthetic": False,
                                                       "status": "planned"}, indent=1, sort_keys=True))
        (d / "command.txt").write_text(shlex.join(ns3_command(block, run, d)) + "\n")
        dirs.append(d)
    log.info("planned %d runs under %s", len(dirs), out_root)
    return dirs


def execute(block: Mapping[str, Any], run_dir: Path, timeout_s: float = 7200.0) -> int:
    """Execute one planned run. Refuses unless ns-3 and the scenario are present."""
    ns3 = block.get("ns3", {})
    root = Path(str(ns3.get("root", ""))).expanduser().resolve()
    if not (root / "ns3").exists():
        raise FileNotFoundError(f"ns-3 front end not found at {root / 'ns3'}; set ns3_system.ns3.root")
    scen_src = root / "scratch" / f"{ns3.get('scenario', 'guarded-autonomy-manet')}.cc"
    if not scen_src.exists():
        raise FileNotFoundError(f"scenario {scen_src} not found (TODO NS3-1)")
    cfg = json.loads((run_dir / "run_config.json").read_text())
    cmd = ns3_command(block, SystemRun(cfg["run_id"], cfg["experiment"], cfg["params"]), run_dir)
    log.info("executing %s", cmd)
    if cfg.get("status") == "finished":
        raise FileExistsError(f"refusing to re-execute completed run {run_dir}")
    cfg["status"] = "running"
    config_path = run_dir / "run_config.json"
    config_path.write_text(json.dumps(cfg, indent=1, sort_keys=True))
    try:
        with (run_dir / "ns3.log").open("w") as output:
            res = subprocess.run(cmd, cwd=root, timeout=timeout_s, check=False, stdout=output, stderr=subprocess.STDOUT)
        cfg["status"] = "finished" if res.returncode == 0 else f"failed:{res.returncode}"
        code = res.returncode
    except subprocess.TimeoutExpired:
        cfg["status"] = "timeout"
        code = 124
    except OSError as error:
        cfg["status"] = "failed:launch"
        cfg["error"] = f"{type(error).__name__}: {error}"
        code = 127
    config_path.write_text(json.dumps(cfg, indent=1, sort_keys=True))
    return code
