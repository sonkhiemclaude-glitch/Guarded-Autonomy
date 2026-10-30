"""Component-level check runner (Sec. 6): run a matrix, write raw rows, summary and provenance."""
from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from ..metrics.component import summarise_cc
from ..simulation.suites import RunSpec, build_matrix, run_spec
from ..utils.io import write_csv, write_json
from ..utils.provenance import run_metadata, write_metadata

log = logging.getLogger(__name__)


def run_matrix(specs: Sequence[RunSpec], workers: int = 1) -> List[Dict[str, Any]]:
    if workers <= 1:
        rows = []
        for k, s in enumerate(specs):
            rows.append(run_spec(s))
            if (k + 1) % 50 == 0:
                log.info("%d/%d runs", k + 1, len(specs))
        return rows
    with ProcessPoolExecutor(max_workers=workers) as ex:      # results returned in submission order
        return list(ex.map(run_spec, specs, chunksize=4))


def run_component_check(block: Mapping[str, Any], out_dir: Path, synthetic: bool, cfg_for_md: Mapping[str, Any],
                        workers: int = 1) -> Dict[str, Path]:
    specs = build_matrix(block)
    log.info("component check: %d runs, %d worker(s)", len(specs), workers)
    rows = run_matrix(specs, workers)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, Path] = {}
    for suite in sorted({s.suite for s in specs}):
        sub = [r for r in rows if r["suite"] == suite]
        paths[f"raw_{suite}"] = write_csv(out_dir / f"raw_{suite}.csv", sub)
    summary = summarise_cc(rows)
    summary["_label"] = ("synthetic smoke-test output, not a paper result" if synthetic
                         else "component-check output (abstract model; not ns-3, not an LLM)")
    paths["summary"] = write_json(out_dir / "summary.json", summary)
    paths["metadata"] = write_metadata(out_dir, run_metadata(cfg_for_md, synthetic, {"n_runs": len(rows)}))
    return paths
