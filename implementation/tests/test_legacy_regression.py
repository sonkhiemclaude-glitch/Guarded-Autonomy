"""The package must reproduce the result rows that produced the manuscript's Sec. 6 numbers.

Legacy files live in paper_evidence_v1/results (hash-checked by paper_evidence_v1/results/code_sha256.txt).
A deterministic sample is checked here; scripts/verify_legacy_results.py --sample 0 checks all 780 runs.
"""
import csv

import pytest

from guarded_autonomy.simulation.suites import paper_matrix, run_spec

SKIP = {"lat_median_us", "lat_p99_us"}
SAMPLE = {"cc1": [0, 1, 4, 9, 61, 299, 360, 539], "cc2": [0, 1, 3, 42, 159], "cc3": [0, 1, 7, 44, 79]}


@pytest.mark.parametrize("suite", ["cc1", "cc2", "cc3"])
def test_reproduces_legacy_rows(repo_root, suite):
    path = repo_root / "paper_evidence_v1" / "results" / f"raw_{suite}.csv"
    if not path.exists():
        pytest.skip("legacy evidence not present")
    legacy = list(csv.DictReader(path.open(newline="")))
    specs = paper_matrix(suite)
    assert len(specs) == len(legacy)
    for k in SAMPLE[suite]:
        row = run_spec(specs[k])
        diffs = {c: (row.get(c), legacy[k][c]) for c in legacy[k] if c not in SKIP and str(row.get(c)) != legacy[k][c]}
        assert not diffs, f"{suite}[{k}] differs: {diffs}"
