#!/usr/bin/env python3
"""Re-run a sample (or all) of the paper's component-check runs with this package and compare them
field by field with the legacy result files that produced the manuscript's numbers.

Timing fields (lat_median_us, lat_p99_us) are machine-dependent and excluded.
"""
import argparse
import csv
import logging
import random
import sys
from pathlib import Path

import _bootstrap  # noqa: F401
from guarded_autonomy.simulation.suites import paper_matrix, run_spec
from guarded_autonomy.utils.logging import setup_logging

SKIP = {"lat_median_us", "lat_p99_us"}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--legacy", required=True, help="directory with raw_cc1.csv, raw_cc2.csv, raw_cc3.csv")
    ap.add_argument("--sample", type=int, default=30, help="runs per suite to re-check (0 = all)")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    setup_logging()
    log = logging.getLogger("verify")
    rng = random.Random(a.seed)
    bad = 0
    for suite in ("cc1", "cc2", "cc3"):
        legacy = list(csv.DictReader(open(Path(a.legacy) / f"raw_{suite}.csv", newline="")))
        specs = paper_matrix(suite)
        if len(specs) != len(legacy):
            log.error("%s: matrix has %d runs, legacy file %d", suite, len(specs), len(legacy))
            sys.exit(2)
        idx = range(len(specs)) if a.sample == 0 else sorted(rng.sample(range(len(specs)), min(a.sample, len(specs))))
        for k in idx:
            row = run_spec(specs[k])
            diffs = [c for c in legacy[k] if c not in SKIP and str(row.get(c)) != legacy[k][c]]
            if diffs:
                bad += 1
                log.error("%s run %d differs in %s", suite, k, diffs)
        log.info("%s: checked %d runs", suite, len(list(idx)))
    print("ALL MATCH" if bad == 0 else f"{bad} MISMATCHES")
    sys.exit(1 if bad else 0)
