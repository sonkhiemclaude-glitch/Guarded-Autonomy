"""Aggregate system-level run directories (E1-E5) into per-run and per-configuration tables."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

from ..ns3.adapters import collect
from ..utils.io import write_csv
from .tables import system_table

log = logging.getLogger(__name__)


def aggregate(runs_root: Path, out_dir: Path, require_finished: bool = True) -> Dict[str, Path]:
    rows = collect(runs_root, require_finished=require_finished)
    if not rows:
        raise FileNotFoundError(f"no complete run directories under {runs_root} "
                                f"(need run_config.json with status finished, packets.csv, control.csv, decisions.jsonl)")
    synthetic = [r["run_id"] for r in rows if r.get("synthetic")]
    if synthetic and len(synthetic) != len(rows):
        raise ValueError("refusing to mix synthetic and real runs in one table")
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"per_run": write_csv(out_dir / "system_per_run.csv", rows,
                                  fieldnames=sorted({k for r in rows for k in r}))}
    tab = system_table(rows)
    paths["table7"] = write_csv(out_dir / "system_table.csv", tab, fieldnames=sorted({k for r in tab for k in r}))
    log.info("aggregated %d runs (%s)", len(rows), "SYNTHETIC" if synthetic else "real")
    return paths
