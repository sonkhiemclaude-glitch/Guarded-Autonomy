#!/usr/bin/env python3
"""Run one experiment stage.

Stages:
  component  abstract-model component check (Sec. 6) for kind: component_check configs
  plan       write ns-3 run directories for E1-E5 (kind: ns3_system); executes nothing
  execute    execute one planned run directory (needs --run-dir and --allow-execute; Mac Studio)
  aggregate  aggregate finished run directories into system tables (needs --runs)
"""
import argparse

import _bootstrap  # noqa: F401
from guarded_autonomy.cli import main

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--stage", required=True, choices=["component", "plan", "execute", "aggregate"])
    ap.add_argument("--output")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--run-dir")
    ap.add_argument("--runs")
    ap.add_argument("--allow-execute", action="store_true")
    a = ap.parse_args()
    out = ["--output", a.output] if a.output else []
    if a.stage == "component":
        argv = ["component-check", "--config", a.config, "--workers", str(a.workers), *out]
    elif a.stage == "plan":
        argv = ["ns3-plan", "--config", a.config, *out]
    elif a.stage == "execute":
        if not a.run_dir:
            ap.error("--run-dir is required for --stage execute")
        argv = ["ns3-execute", "--config", a.config, "--run-dir", a.run_dir] + (["--allow-execute"] if a.allow_execute else [])
    else:
        if not a.runs or not a.output:
            ap.error("--runs and --output are required for --stage aggregate")
        argv = ["aggregate", "--runs", a.runs, "--output", a.output]
    raise SystemExit(main(argv))
