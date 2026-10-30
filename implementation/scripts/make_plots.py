#!/usr/bin/env python3
"""Make figures from result files (raw_cc1.csv and/or system_table.csv in --input)."""
import argparse

import _bootstrap  # noqa: F401
from guarded_autonomy.cli import main

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--synthetic", action="store_true")
    a = ap.parse_args()
    raise SystemExit(main(["plot", "--input", a.input, "--output", a.output] + (["--synthetic"] if a.synthetic else [])))
