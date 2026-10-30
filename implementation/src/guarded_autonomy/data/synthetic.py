"""Synthetic system-level run directories in the ns-3 output format (docs/data_format.md).

PURPOSE: exercise the adapters, metrics, tables and plots end-to-end without ns-3 or an LLM.
Every directory written here is marked ``"synthetic": true`` and ``"status": "synthetic"`` and the
numbers are random draws from a toy generator: they are NOT simulation results and carry no
information about the shield. Label: "synthetic smoke-test output, not a paper result".
"""
from __future__ import annotations

import csv
import json
import random
from pathlib import Path
from typing import Dict, List

from ..utils.provenance import SYNTHETIC_LABEL

CONFIGS = ("aodv", "unshielded", "shielded")


def write_synthetic_run(out_dir: Path, configuration: str, seed: int, n_flows: int = 4,
                        packets_per_flow: int = 50, n_decisions: int = 40) -> Path:
    rng = random.Random(f"{configuration}-{seed}")
    d = out_dir / f"synthetic-{configuration}-s{seed}"
    d.mkdir(parents=True, exist_ok=True)
    params = {"configuration": configuration, "seed": seed, "n": 20, "experiment": "SYNTHETIC"}
    (d / "run_config.json").write_text(json.dumps({"run_id": d.name, "experiment": "SYNTHETIC", "params": params,
                                                   "synthetic": True, "status": "synthetic",
                                                   "label": SYNTHETIC_LABEL}, indent=1, sort_keys=True))
    loss = rng.uniform(0.05, 0.4)
    with (d / "packets.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["flow_id", "packet_id", "sent_s", "received_s", "size_bytes"])
        for f in range(n_flows):
            for k in range(packets_per_flow):
                t = k * 0.25
                rx = "" if rng.random() < loss else f"{t + rng.uniform(0.002, 0.2):.6f}"
                w.writerow([f, k, f"{t:.6f}", rx, 512])
    with (d / "control.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time_s", "node", "kind", "bytes"])
        for _ in range(rng.randint(50, 200)):
            w.writerow([f"{rng.uniform(0, 12.5):.4f}", rng.randrange(20), rng.choice(["RREQ", "RREP", "RERR", "HELLO"]), 64])
    with (d / "failures.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time_s", "affected_flows"])
        w.writerow(["5.0", "0;1"])
    with (d / "decisions.jsonl").open("w") as fh:
        for k in range(n_decisions):
            is_prop = configuration != "aodv" and rng.random() < 0.7
            harm: List[str] = []
            if is_prop and rng.random() < 0.3:
                harm = [rng.choice(["H-loop", "H-iso", "H-adv"])]
            if configuration == "unshielded":
                tier = "agent" if is_prop else "base"
            elif configuration == "shielded":
                tier = rng.choice(["base", "null"]) if harm else ("agent" if is_prop and rng.random() < 0.6 else "base")
            else:
                tier = "base"
            rec: Dict[str, object] = {"t": k * 0.3, "node": rng.randrange(20), "is_proposal": is_prop, "harm": harm,
                                      "tier": tier, "agent_latency_ms": rng.uniform(5, 50) if is_prop else 0.0,
                                      "synthetic": True}
            fh.write(json.dumps(rec) + "\n")
    return d


def write_synthetic_suite(out_dir: Path, seeds: int = 3) -> List[Path]:
    return [write_synthetic_run(out_dir, c, s) for c in CONFIGS for s in range(seeds)]
