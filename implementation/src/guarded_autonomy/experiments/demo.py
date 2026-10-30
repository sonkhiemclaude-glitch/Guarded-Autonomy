"""Synthetic smoke-test demo: exercises every pipeline stage quickly on toy inputs.

Writes to ``<output_dir>/synthetic_demo/``. Everything produced is labelled
"synthetic smoke-test output, not a paper result".
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Mapping

from ..agents.injection import make_payloads
from ..agents.observation import build_observation
from ..config import ShieldConfig
from ..data.synthetic import write_synthetic_suite
from ..decision_log import HashChainLog
from ..ns3.bridge import BridgeState, handle_message
from ..ns3.protocol import view_to_json
from ..schemas import LocalView, RouteEntry
from ..utils.io import read_csv, write_json
from ..utils.provenance import SYNTHETIC_LABEL, run_metadata, write_metadata
from .component_check import run_component_check
from .plots import plot_cc1, plot_system
from .system_eval import aggregate
from .tables import system_table, write_component_tables

log = logging.getLogger(__name__)


def _bridge_roundtrip(out: Path) -> Dict[str, Any]:
    """One decide/check/anchor exchange with an injected proposal, no network."""
    v = LocalView(node_id=1, neighbours={0, 2, 3}, active_dests={0})
    v.routes[0] = RouteEntry(seq=5, hops=3, next_hop=2, valid=True)
    v.adv[0] = {2: (5, 2), 3: (5, 2), 0: (6, 0)}
    payloads = make_payloads(target_node=2, own_id=3)
    status = {3: payloads[0].text}
    obs = build_observation(v, status_fields=status)
    state = BridgeState(shield_cfg=ShieldConfig(use_trust=False), agent=lambda o: payloads[2].text)  # obeys injection
    out.mkdir(parents=True, exist_ok=True)
    with (out / "decisions.jsonl").open("w") as fh:
        state.decisions_out = fh
        msgs: List[Dict[str, Any]] = [{"type": "hello", "version": 1, "run_id": "demo", "nodes": 4},
                {"type": "decide", "node": 1, "t": 1.0, "view": view_to_json(v), "observation": obs,
                 "base_candidates": [{"type": "route_change", "dest": 0, "next_hop": 0}],
                 "oracle": {"dest": 0, "next_hop": {"1": 2, "2": 0}, "adversaries": [3]}},
                {"type": "check", "node": 1, "t": 1.0, "view": view_to_json(v),
                 "action": {"type": "route_change", "dest": 0, "next_hop": 3}},
                {"type": "anchor", "node": 1}, {"type": "bye"}]
        replies = [handle_message(state, m) for m in msgs]
    log_ok = isinstance(state.shields[1].log, HashChainLog) and state.shields[1].log.verify(replies[3]["head"])
    return {"replies": replies, "log_verifies_against_anchor": log_ok, "_label": SYNTHETIC_LABEL}


def run_demo(section: Mapping[str, Any], out_root: Path, cfg_for_md: Mapping[str, Any]) -> Dict[str, Path]:
    out = out_root / "synthetic_demo"
    out.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, Path] = {}
    # 1. small component check
    cc_block = dict(section.get("component_check", {}))
    cc_paths = run_component_check(cc_block, out / "component_check", synthetic=True, cfg_for_md=cfg_for_md)
    paths.update({f"cc_{k}": v for k, v in cc_paths.items()})
    rows = []
    for k, p in cc_paths.items():
        if k.startswith("raw_"):
            rows += read_csv(p)
    paths.update(write_component_tables(rows, out / "component_check" / "tables"))
    cc1 = cc_block.get("cc1", {})
    if "cc1" in cc_block.get("suites", []):
        paths["fig_cc1"] = plot_cc1(rows, out / "figures" / "cc1_synthetic.png", vmax=float(cc1.get("vmaxs", [20.0])[0]),
                                    ns=list(cc1.get("ns", [20])), synthetic=True)
    # 2. bridge round trip with an injected proposal
    rt = _bridge_roundtrip(out / "bridge")
    paths["bridge"] = write_json(out / "bridge" / "roundtrip.json", rt)
    # 3. synthetic system-level pipeline (toy generator, NOT ns-3)
    runs = out / "system_runs"
    write_synthetic_suite(runs, seeds=int(section.get("system_seeds", 3)))
    agg = aggregate(runs, out / "system_tables", require_finished=True)
    paths.update({f"system_{k}": v for k, v in agg.items()})
    tab = system_table(read_csv(agg["per_run"]))
    paths["fig_system_pdr"] = plot_system(tab, out / "figures" / "system_pdr_synthetic.png", "pdr", "PDR", synthetic=True)
    (out / "README_SYNTHETIC.txt").write_text(SYNTHETIC_LABEL.upper() + "\n\nEvery file in this directory was "
                                              "produced by the synthetic demo. None of it is a paper result.\n")
    paths["metadata"] = write_metadata(out, run_metadata(cfg_for_md, True, {"stage": "synthetic_demo",
                                                                           "files": sorted(str(p) for p in paths.values())}))
    write_json(out / "manifest.json", {k: str(v) for k, v in paths.items()} | {"_label": SYNTHETIC_LABEL})
    log.info("synthetic demo written to %s", out)
    return paths

