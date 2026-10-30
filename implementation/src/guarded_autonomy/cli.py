"""Command-line interface: ``python -m guarded_autonomy.cli --help``.

No subcommand downloads anything. ``ns3-execute`` and ``bridge-serve`` act only when explicitly
invoked with a configuration that points to locally provisioned ns-3 / model endpoints.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .config import RunConfig, ShieldConfig
from .utils.logging import setup_logging

log = logging.getLogger("guarded_autonomy")

WARNING = ("No paper-level experimental results are claimed by this repository unless real benchmark outputs "
           "are generated and their provenance is recorded.")


def _out(cfg: RunConfig, override: Optional[str]) -> Path:
    return Path(override or cfg.output_dir)


def cmd_info(_: argparse.Namespace) -> int:
    print(json.dumps({"package": "guarded_autonomy", "version": __version__, "warning": WARNING}, indent=1))
    return 0


def cmd_demo(a: argparse.Namespace) -> int:
    from .experiments.demo import run_demo
    cfg = RunConfig.load(a.config)
    if cfg.kind != "synthetic_demo":
        raise SystemExit("demo needs a config with kind: synthetic_demo")
    paths = run_demo(cfg.section, _out(cfg, a.output), cfg.to_dict())
    print(json.dumps({k: str(v) for k, v in paths.items()}, indent=1))
    return 0


def cmd_component(a: argparse.Namespace) -> int:
    from .experiments.component_check import run_component_check
    from .experiments.tables import write_component_tables
    from .utils.io import read_csv
    cfg = RunConfig.load(a.config)
    if cfg.kind != "component_check":
        raise SystemExit("component-check needs a config with kind: component_check")
    out = _out(cfg, a.output) / cfg.name
    paths = run_component_check(cfg.section, out, synthetic=cfg.synthetic, cfg_for_md=cfg.to_dict(), workers=a.workers)
    rows = [r for k, p in paths.items() if k.startswith("raw_") for r in read_csv(p)]
    paths.update(write_component_tables(rows, out / "tables"))
    print(json.dumps({k: str(v) for k, v in paths.items()}, indent=1))
    return 0


def cmd_tables(a: argparse.Namespace) -> int:
    from .experiments.tables import write_component_tables
    from .utils.io import read_csv
    rows = [r for p in sorted(Path(a.input).glob("raw_cc*.csv")) for r in read_csv(p)]
    if not rows:
        raise SystemExit(f"no raw_cc*.csv files in {a.input}")
    print(json.dumps({k: str(v) for k, v in write_component_tables(rows, Path(a.output)).items()}, indent=1))
    return 0


def cmd_plot(a: argparse.Namespace) -> int:
    from .experiments.plots import plot_cc1, plot_system
    from .utils.io import read_csv, read_json
    inp, out = Path(a.input), Path(a.output)
    synthetic = a.synthetic
    md = inp / "run_metadata.json"
    if md.exists():
        synthetic = synthetic or bool(read_json(md).get("synthetic"))
    made = []
    if (inp / "raw_cc1.csv").exists():
        rows = read_csv(inp / "raw_cc1.csv")
        ns = sorted({int(r["n"]) for r in rows})
        for vmax in sorted({float(r["vmax"]) for r in rows}):
            made.append(plot_cc1(rows, out / f"cc1_v{vmax:g}.png", vmax, ns, synthetic))
    if (inp / "system_table.csv").exists():
        tab = read_csv(inp / "system_table.csv")
        synthetic = synthetic or any(r.get("synthetic") == "True" for r in tab)
        made.append(plot_system(tab, out / "system_pdr.png", "pdr", "PDR", synthetic))
    if not made:
        raise SystemExit(f"nothing to plot in {inp} (expected raw_cc1.csv or system_table.csv)")
    print("\n".join(str(p) for p in made))
    return 0


def cmd_ns3_plan(a: argparse.Namespace) -> int:
    from .ns3.runner import plan
    cfg = RunConfig.load(a.config)
    if cfg.kind != "ns3_system":
        raise SystemExit("ns3-plan needs a config with kind: ns3_system")
    dirs = plan(cfg.section, _out(cfg, a.output) / cfg.name / "runs")
    print(f"planned {len(dirs)} runs (nothing executed)")
    return 0


def cmd_ns3_execute(a: argparse.Namespace) -> int:
    from .ns3.runner import execute
    if not a.allow_execute:
        raise SystemExit("refusing to execute without --allow-execute (intended for the Mac Studio)")
    cfg = RunConfig.load(a.config)
    return execute(cfg.section, Path(a.run_dir))


def cmd_aggregate(a: argparse.Namespace) -> int:
    from .experiments.system_eval import aggregate
    paths = aggregate(Path(a.runs), Path(a.output), require_finished=not a.include_unfinished)
    print(json.dumps({k: str(v) for k, v in paths.items()}, indent=1))
    return 0


def cmd_bridge(a: argparse.Namespace) -> int:
    from .agents.policies import make_proposer
    from .ns3.bridge import BridgeState, serve
    cfg = RunConfig.load(a.config)
    blk = cfg.section.get("bridge", {})
    if a.run_dir:
        from .ns3.settings import resolve_bridge
        run = json.loads((Path(a.run_dir) / "run_config.json").read_text())
        blk = run.get("effective_bridge") or resolve_bridge(cfg.section, run["params"])
    shield = ShieldConfig.from_mapping(blk.get("shield", {}))
    agent = make_proposer(blk)
    state = BridgeState(shield_cfg=shield, agent=agent, agent_kind=blk.get("proposer_kind", "llm"),
                        shielded=bool(blk.get("shielded", True)),
                        sanitise_inputs=bool(blk.get("sanitise_inputs", False)))
    serve(state, host=blk.get("host", "127.0.0.1"), port=int(a.port or blk.get("port", 5577)),
          run_dir=Path(a.run_dir) if a.run_dir else None)
    return 0


def cmd_verify_log(a: argparse.Namespace) -> int:
    from .decision_log import HashChainLog
    ok = HashChainLog.load_jsonl(a.log).verify(a.head)
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="guarded_autonomy", description=f"Guarded Autonomy reference implementation. {WARNING}")
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("info", help="print version and warnings")
    s.set_defaults(fn=cmd_info)
    s = sub.add_parser("demo", help="synthetic smoke-test demo (not a paper result)")
    s.add_argument("--config", required=True)
    s.add_argument("--output")
    s.set_defaults(fn=cmd_demo)
    s = sub.add_parser("component-check", help="abstract-model component check (Sec. 6)")
    s.add_argument("--config", required=True)
    s.add_argument("--output")
    s.add_argument("--workers", type=int, default=1)
    s.set_defaults(fn=cmd_component)
    s = sub.add_parser("tables", help="tables from raw_cc*.csv files")
    s.add_argument("--input", required=True)
    s.add_argument("--output", required=True)
    s.set_defaults(fn=cmd_tables)
    s = sub.add_parser("plot", help="figures from result files")
    s.add_argument("--input", required=True)
    s.add_argument("--output", required=True)
    s.add_argument("--synthetic", action="store_true", help="force the synthetic banner")
    s.set_defaults(fn=cmd_plot)
    s = sub.add_parser("ns3-plan", help="write ns-3 run directories for E1-E5 (executes nothing)")
    s.add_argument("--config", required=True)
    s.add_argument("--output")
    s.set_defaults(fn=cmd_ns3_plan)
    s = sub.add_parser("ns3-execute", help="execute one planned run (Mac Studio; needs local ns-3)")
    s.add_argument("--config", required=True)
    s.add_argument("--run-dir", required=True)
    s.add_argument("--allow-execute", action="store_true")
    s.set_defaults(fn=cmd_ns3_execute)
    s = sub.add_parser("aggregate", help="aggregate run directories into system tables")
    s.add_argument("--runs", required=True)
    s.add_argument("--output", required=True)
    s.add_argument("--include-unfinished", action="store_true")
    s.set_defaults(fn=cmd_aggregate)
    s = sub.add_parser("bridge-serve", help="start the ns-3 <-> shield bridge on localhost")
    s.add_argument("--config", required=True)
    s.add_argument("--port", type=int)
    s.add_argument("--run-dir")
    s.set_defaults(fn=cmd_bridge)
    s = sub.add_parser("verify-log", help="verify a hash-chained decision log against an anchored head")
    s.add_argument("--log", required=True)
    s.add_argument("--head")
    s.set_defaults(fn=cmd_verify_log)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.log_level)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
