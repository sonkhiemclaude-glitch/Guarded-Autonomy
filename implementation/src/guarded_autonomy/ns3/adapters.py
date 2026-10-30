"""Readers for system-level run outputs (format in docs/data_format.md) and the aggregation into
the shape of the paper's Table 7. A run directory contains:

  run_config.json   written by ns3.runner.plan (params, run_id, synthetic flag, status)
  packets.csv       flow_id,packet_id,sent_s,received_s,size_bytes   (received_s empty if lost)
  control.csv       time_s,node,kind,bytes                            (one row per control packet sent)
  failures.csv      time_s,affected_flows                             (flows separated by ';')
  decisions.jsonl   written by the bridge (tier, proposal, is_proposal, harm, latencies)
"""
from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..metrics.harm import LabelledDecision, harm_breakdown, shield_metrics
from ..metrics.network import FailureEvent, PacketRecord, delay_stats, normalised_routing_overhead, pdr, recovery_times
from ..schemas import Tier

REQUIRED = ("run_config.json", "packets.csv", "control.csv", "decisions.jsonl")


class RunDataError(ValueError):
    pass


def _need(run_dir: Path, name: str) -> Path:
    p = run_dir / name
    if not p.exists() and p.with_name(p.name + ".gz").exists():
        p = p.with_name(p.name + ".gz")
    if not p.exists():
        raise RunDataError(f"{run_dir}: missing required file {name}")
    return p


def _open_text(path: Path, newline: Optional[str] = None):
    return gzip.open(path, "rt", encoding="utf-8", newline=newline) if path.suffix == ".gz" else path.open(
        "r", encoding="utf-8", newline=newline)


def _present(directory: Path, name: str) -> bool:
    return (directory / name).exists() or (directory / (name + ".gz")).exists()


def read_packets(run_dir: Path) -> List[PacketRecord]:
    out = []
    with _open_text(_need(run_dir, "packets.csv"), newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                out.append(PacketRecord(int(r["flow_id"]), int(r["packet_id"]), float(r["sent_s"]),
                                        float(r["received_s"]) if r.get("received_s") not in ("", None) else None,
                                        int(r.get("size_bytes") or 512)))
            except (KeyError, ValueError) as exc:
                raise RunDataError(f"{run_dir}/packets.csv: bad row {r}: {exc}") from exc
    return out


def read_control(run_dir: Path, start_s: float = 0.0, stop_s: Optional[float] = None) -> Dict[str, int]:
    n = b = 0
    with _open_text(_need(run_dir, "control.csv"), newline="") as fh:
        for r in csv.DictReader(fh):
            time_s = float(r.get("time_s") or 0.0)
            if time_s < start_s or (stop_s is not None and time_s >= stop_s):
                continue
            n += 1
            b += int(r.get("bytes") or 0)
    return {"packets": n, "bytes": b}


def read_failures(run_dir: Path) -> List[FailureEvent]:
    if not _present(run_dir, "failures.csv"):
        return []
    p = _need(run_dir, "failures.csv")
    out = []
    with _open_text(p, newline="") as fh:
        for r in csv.DictReader(fh):
            flows = [int(x) for x in str(r["affected_flows"]).split(";") if x.strip()]
            out.append(FailureEvent(float(r["time_s"]), flows))
    return out


def read_decisions(run_dir: Path) -> List[Dict[str, Any]]:
    out = []
    with _open_text(_need(run_dir, "decisions.jsonl")) as fh:
        for line in fh:
            if line.strip():
                out.append(json.loads(line))
    return out


def summarise_run(run_dir: Path, overhead_mode: str = "packets") -> Dict[str, Any]:
    cfg = json.loads(_need(run_dir, "run_config.json").read_text())
    start = float(cfg["params"].get("warmup_s", 0.0))
    stop = start + float(cfg["params"]["sim_time_s"]) if "sim_time_s" in cfg["params"] else None
    pk = [p for p in read_packets(run_dir) if p.sent_s >= start and (stop is None or p.sent_s < stop)]
    control_stop = stop + float(cfg["params"].get("drain_s", 61.0)) if stop is not None else None
    ctl = read_control(run_dir, start, control_stop)
    dec = [d for d in read_decisions(run_dir) if float(d.get("observation_t", d.get("proposal_t", d.get("t"))) or 0) >= start
           and (stop is None or float(d.get("observation_t", d.get("proposal_t", d.get("t"))) or 0) < stop)]
    delivered = [p for p in pk if p.received_s is not None]
    labelled = [LabelledDecision(Tier(d["tier"]), bool(d.get("is_proposal")), set(d.get("harm") or []))
                for d in dec]
    proposals = [d for d in dec if d.get("is_proposal")]
    labelled_proposals = [d for d in proposals if d.get("harm") is not None]
    complete_harm = len(labelled_proposals) == len(proposals)
    agent_calls = [d for d in dec if d.get("agent_called", bool(d.get("agent_latency_ms")))]
    lat = [float(d.get("agent_latency_ms") or 0.0) for d in agent_calls]
    row: Dict[str, Any] = {"run_id": cfg["run_id"], "experiment": cfg["experiment"],
                           "synthetic": bool(cfg.get("synthetic", False)), **cfg["params"],
                           "pdr": pdr(pk), **{f"delay_{k}": v for k, v in delay_stats(pk).items()},
                           "routing_overhead": normalised_routing_overhead(
                               ctl["packets"], len(delivered), ctl["bytes"], sum(p.size_bytes for p in delivered),
                               mode=overhead_mode),
                           "overhead_mode": overhead_mode,
                           "condition_json": json.dumps({k: v for k, v in cfg["params"].items()
                                                        if k not in {"seed", "failure_from", "failure_to", "failure_flows"}},
                                                        sort_keys=True),
                           "harm_labels_available": complete_harm,
                           "proposal_count": len(proposals),
                           "unknown_harm_proposals": len(proposals) - len(labelled_proposals),
                           "harm_label_coverage": len(labelled_proposals) / len(proposals) if proposals else None,
                           "agent_calls": len(agent_calls),
                           "agent_errors": sum(bool(d.get("agent_error")) for d in agent_calls),
                           "agent_latency_ms_mean": (sum(lat) / len(lat)) if lat else None}
    row["invalid_replies"] = sum(d.get("proposal") is None for d in agent_calls)
    row["defer_replies"] = sum((d.get("proposal") or {}).get("type") == "defer" for d in agent_calls)
    labelled_commits = [d for d in dec if d.get("event") != "base_commit" and d.get("action") is not None]
    row["query_time_harmful_commits"] = sum(bool(d.get("committed_harm")) for d in labelled_commits)
    row["query_time_fallback_harmful_commits"] = sum(
        bool(d.get("committed_harm")) and d.get("tier") == "base" for d in labelled_commits)
    row["query_time_unknown_commit_labels"] = sum(d.get("committed_harm") is None for d in labelled_commits)
    row["query_time_commit_count"] = len(labelled_commits)
    row["query_time_harmful_commit_fraction"] = (row["query_time_harmful_commits"] / len(labelled_commits)
                                                if labelled_commits else None)
    for action_type in ("route_change", "isolate", "reinstate", "set_power", "defer"):
        row[f"proposal_type_{action_type}"] = sum((d.get("proposal") or {}).get("type") == action_type
                                                 for d in agent_calls)
        row[f"query_commit_type_{action_type}"] = sum((d.get("action") or {}).get("type") == action_type
                                                     for d in labelled_commits)
    obligations_path = run_dir / "review_obligations.json"
    if obligations_path.exists():
        obligations = json.loads(obligations_path.read_text())
        for key in ("pending", "closed", "overdue"):
            row[f"review_{key}_final"] = sum(len(value.get(key, [])) for value in obligations.values())
    row["proposer_calls"] = len(agent_calls)
    row["llm_calls"] = sum(d.get("proposer_kind", "llm") == "llm" for d in agent_calls)
    row["proposer_kind"] = cfg.get("effective_bridge", {}).get("proposer_kind", "llm")
    row["agent_tier_commits"] = sum(d.get("tier") == "agent" for d in dec)
    row["base_tier_commits"] = sum(d.get("tier") == "base" for d in dec)
    row["null_decisions"] = sum(d.get("tier") == "null" for d in dec)
    shield_calls = [d for d in dec if float(d.get("latency_us") or 0.0) > 0]
    row["shield_cpu_us_mean"] = (sum(float(d.get("shield_cpu_us") or 0) for d in shield_calls) / len(shield_calls)
                                  if shield_calls else None)
    row["shield_wall_us_mean"] = (sum(float(d.get("latency_us") or 0) for d in shield_calls) / len(shield_calls)
                                   if shield_calls else None)
    for key in ("ns3_cpu_s", "bridge_cpu_s", "model_server_cpu_s", "wall_s"):
        row[key] = cfg.get(key)
    row["model_cpu_scope"] = cfg.get("model_server_cpu_scope")
    rec = recovery_times(pk, read_failures(run_dir), horizon_s=control_stop)
    row.update({f"recovery_{k}": v for k, v in rec.items()})
    if _present(run_dir, "daemon_audits.jsonl"):
        checked = cached = false_cached = physical = missing_cached = 0
        with _open_text(_need(run_dir, "daemon_audits.jsonl")) as stream:
            for line in stream:
                audit = json.loads(line)
                if float(audit["t"]) < start or (control_stop is not None and float(audit["t"]) >= control_stop):
                    continue
                truth = audit["cache_audit"]
                local = set(truth["cached_neighbours"])
                actual = set(truth["bidirectional_budget_neighbours"])
                checked += 1
                cached += len(local)
                false_cached += len(local - actual)
                physical += len(actual)
                missing_cached += len(actual - local)
        row["cache_audit_queries"] = checked
        row["cache_false_neighbor_fraction"] = false_cached / cached if cached else None
        row["cache_missing_neighbor_fraction"] = missing_cached / physical if physical else None
    row.update(shield_metrics(labelled))
    row["harmful_proposal_rate"] = row["harmful_proposals"] / len(proposals) if proposals else float("nan")
    if complete_harm:
        row.update({f"harm_{k}": v for k, v in harm_breakdown(labelled).items()})
    else:
        for key in ("harmful_proposals", "benign_proposals", "blocked_fraction", "residual_harm",
                    "residual_harm_rate", "false_positive_rate", "harmful_proposal_rate"):
            row[key] = float("nan")
    return row


def collect(root: Path, require_finished: bool = True) -> List[Dict[str, Any]]:
    """Summaries of every run directory under ``root`` that has all required files."""
    rows = []
    for cfg_path in sorted(root.rglob("run_config.json")):
        d = cfg_path.parent
        status = json.loads(cfg_path.read_text()).get("status")
        if require_finished and status not in ("finished", "synthetic"):
            continue
        if all(_present(d, f) for f in REQUIRED):
            rows.append(summarise_run(d))
    return rows


def find_missing(run_dir: Path) -> Optional[List[str]]:
    missing = [f for f in REQUIRED if not _present(run_dir, f)]
    return missing or None
