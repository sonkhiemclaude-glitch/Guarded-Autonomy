"""System-level network metrics of Sec. 7.3: PDR, end-to-end delay (median, p95), normalised
routing overhead, recovery time. Inputs follow docs/data_format.md (packet and control records
exported by the ns-3 scenario).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class PacketRecord:
    """One data packet (packets.csv)."""

    flow_id: int
    packet_id: int
    sent_s: float
    received_s: Optional[float]   # None if never delivered
    size_bytes: int = 512


@dataclass(frozen=True)
class FailureEvent:
    """Induced failure (failures.csv): time and the flows whose path it cut."""

    time_s: float
    affected_flows: Sequence[int]


def pdr(packets: Iterable[PacketRecord]) -> float:
    """Packet delivery ratio = delivered / sent data packets (NaN if none sent)."""
    sent = delivered = 0
    for p in packets:
        sent += 1
        delivered += p.received_s is not None
    return delivered / sent if sent else float("nan")


def delays(packets: Iterable[PacketRecord]) -> List[float]:
    return [p.received_s - p.sent_s for p in packets if p.received_s is not None]


def delay_stats(packets: Iterable[PacketRecord]) -> Dict[str, float]:
    """Median and 95th-percentile end-to-end delay in seconds (NaN if no deliveries)."""
    d = delays(packets)
    if not d:
        return {"median_s": float("nan"), "p95_s": float("nan")}
    arr = np.asarray(d, dtype=float)
    return {"median_s": float(np.median(arr)), "p95_s": float(np.percentile(arr, 95))}


def normalised_routing_overhead(control_packets: int, delivered_data_packets: int,
                                control_bytes: Optional[int] = None, delivered_data_bytes: Optional[int] = None,
                                mode: str = "packets") -> float:
    """Normalised routing overhead. The paper names the metric without a formula (Sec. 7.3);
    default: control packets transmitted / data packets delivered. ``mode='bytes'`` uses bytes.
    Recorded in run metadata; author confirmation pending (TODO_IMPLEMENTATION.md)."""
    if mode == "packets":
        return control_packets / delivered_data_packets if delivered_data_packets else float("nan")
    if mode == "bytes":
        if control_bytes is None or delivered_data_bytes is None:
            raise ValueError("bytes mode needs control_bytes and delivered_data_bytes")
        return control_bytes / delivered_data_bytes if delivered_data_bytes else float("nan")
    raise ValueError("mode must be 'packets' or 'bytes'")


def recovery_times(packets: Sequence[PacketRecord], failures: Sequence[FailureEvent],
                   horizon_s: Optional[float] = None) -> Dict[str, float]:
    """Recovery time per (failure, affected flow): first delivery *sent at or after* the failure,
    measured as its receive time minus the failure time. Unrecovered flows are censored (NaN)
    and counted. Paper: "from an induced failure to the first delivered packet of each affected
    flow" (Sec. 7.3); censoring policy is a documented implementation choice."""
    by_flow: Dict[int, List[PacketRecord]] = {}
    for p in packets:
        by_flow.setdefault(p.flow_id, []).append(p)
    values: List[float] = []
    censored = 0
    restricted: List[float] = []
    for f in failures:
        if horizon_s is not None and horizon_s <= f.time_s:
            raise ValueError("recovery censoring horizon must follow the failure")
        for flow in f.affected_flows:
            cands = [p.received_s for p in by_flow.get(flow, []) if p.received_s is not None and p.sent_s >= f.time_s]
            if cands:
                value = min(cands) - f.time_s
                values.append(value)
                if horizon_s is not None:
                    restricted.append(min(value, horizon_s - f.time_s))
            else:
                censored += 1
                if horizon_s is not None:
                    restricted.append(horizon_s - f.time_s)
    finite = [v for v in values if math.isfinite(v)]
    return {"mean_s": float(np.mean(finite)) if finite else float("nan"),
            "median_s": float(np.median(finite)) if finite else float("nan"),
            "n_recovered": float(len(finite)), "n_censored": float(censored),
            "rmst_s": float(np.mean(restricted)) if restricted else float("nan"),
            "recovered_fraction": len(finite) / (len(finite) + censored) if finite or censored else float("nan")}
