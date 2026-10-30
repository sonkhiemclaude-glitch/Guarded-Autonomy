#!/usr/bin/env python3
"""Synthetic smoke-test demo. Outputs are "synthetic smoke-test output, not a paper result"."""
import argparse

import _bootstrap  # noqa: F401
from guarded_autonomy.cli import main

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="configs/synthetic_demo.yaml")
    ap.add_argument("--output")
    a = ap.parse_args()
    raise SystemExit(main(["demo", "--config", a.config] + (["--output", a.output] if a.output else [])))
