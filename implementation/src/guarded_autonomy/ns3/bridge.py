"""Bridge server: runs Algorithm 1 for ns-3 nodes (Sec. 7.1).

The daemon state of record lives in ns-3; each request carries the node's VIEW. The bridge keeps
per-node shield state that ns-3 does not hold (isolation budget, M1 obligations, decision log) and
returns the committed action for ns-3 to apply. Oracle snapshots are used only to write harm labels
to ``decisions.jsonl`` and never reach the agent or the guards.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import socket
import socketserver
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TextIO

from ..agents.observation import build_observation
from ..baselines.sanitisation import sanitise_observation
from ..config import ShieldConfig
from ..decision_log import HashChainLog
from ..schemas import Action, Tier, action_to_dict, parse_action
from ..shield import Shield
from ..simulation.harm import GlobalSnapshot, HarmOracle
from .protocol import PROTOCOL_VERSION, view_from_json

log = logging.getLogger(__name__)

AgentFn = Callable[[Dict[str, Any]], Any]
"""Agent callable: observation dict -> raw output (str/dict/None) or an AgentReply-like object."""


@dataclass
class BridgeState:
    shield_cfg: ShieldConfig
    agent: Optional[AgentFn] = None          # None: defer always (base protocol through the shield)
    agent_kind: str = "llm"
    shielded: bool = True                    # False: unshielded agent (commit parsed proposals)
    sanitise_inputs: bool = False            # input-sanitisation contrast baseline
    harm_oracle: HarmOracle = field(default_factory=HarmOracle)
    decisions_out: Optional[TextIO] = None
    shields: Dict[int, Shield] = field(default_factory=dict)
    run_dir: Optional[Path] = None
    oracle_out: Optional[TextIO] = None
    agent_calls_out: Optional[TextIO] = None
    observations_out: Optional[TextIO] = None
    daemon_audit_out: Optional[TextIO] = None
    capture_full_oracle: bool = False
    lock: Any = field(default_factory=threading.RLock, repr=False)
    persisted: Dict[int, int] = field(default_factory=dict)
    chain_streams: Dict[int, TextIO] = field(default_factory=dict, repr=False)
    anchor_written_at: Dict[int, float] = field(default_factory=dict)

    def persist_node(self, node: int, bundle: bool = False, force: bool = False) -> None:
        if self.run_dir is None:
            return
        log = self.shield_for(node).log
        if log is None:
            raise RuntimeError("decision chain is missing")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        stream = self.chain_streams.get(node)
        if stream is None or stream.closed:
            stream = (self.run_dir / f"chain-node-{node}.jsonl").open("a", encoding="utf-8")
            self.chain_streams[node] = stream
        for entry in log.entries[self.persisted.get(node, 0):]:
            stream.write(json.dumps(entry, sort_keys=True) + "\n")
        stream.flush()
        self.persisted[node] = len(log.entries)
        now = time.monotonic()
        if force or bundle or now - self.anchor_written_at.get(node, -float("inf")) >= 1:
            target = self.run_dir / f"anchor-node-{node}.json"
            temp = target.with_suffix(".tmp")
            temp.write_text(json.dumps(log.anchor(), indent=2, sort_keys=True) + "\n")
            temp.replace(target)
            self.anchor_written_at[node] = now
        if bundle:
            anchors = {str(n): sh.log.anchor() for n, sh in self.shields.items() if sh.log is not None}
            target = self.run_dir / "chain_anchors.json"
            temp = target.with_suffix(".tmp")
            temp.write_text(json.dumps(anchors, indent=2, sort_keys=True) + "\n")
            temp.replace(target)

    def close_logs(self) -> None:
        for stream in self.chain_streams.values():
            stream.close()

    def shield_for(self, node: int) -> Shield:
        if node not in self.shields:
            from ..schemas import LocalView
            self.shields[node] = Shield(LocalView(node_id=node), self.shield_cfg, log=HashChainLog())
        return self.shields[node]


def _snapshot_from_json(o: Dict[str, Any]) -> GlobalSnapshot:
    return GlobalSnapshot(
        dest=int(o["dest"]),
        next_hop={int(k): (None if v is None else int(v)) for k, v in o.get("next_hop", {}).items()},
        adversaries=frozenset(int(x) for x in o.get("adversaries", [])),
        required_power_dbm={int(k): {int(a): float(b) for a, b in d.items()} for k, d in o.get("required_power_dbm", {}).items()},
        tx_power_dbm={int(k): float(v) for k, v in o.get("tx_power_dbm", {}).items()},
        residual_energy_j={int(k): float(v) for k, v in o.get("residual_energy_j", {}).items()},
        energy_floor_j=float(o.get("energy_floor_j", 10.0)))


def handle_message(state: BridgeState, msg: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize decisions and monitor state, including concurrent TCP clients."""
    with state.lock:
        return _handle_message(state, msg)


def _handle_message(state: BridgeState, msg: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.perf_counter()
    t = msg.get("type")
    if t == "hello":
        if int(msg.get("version", -1)) != PROTOCOL_VERSION:
            return {"type": "error", "message": f"protocol version mismatch: bridge={PROTOCOL_VERSION}"}
        return {"type": "hello", "version": PROTOCOL_VERSION}
    if t == "bye":
        for node in state.shields:
            state.persist_node(node, force=True)
        state.close_logs()
        if state.run_dir is not None:
            now = float(msg.get("t", max((sh.v.now for sh in state.shields.values()), default=0.0)))
            obligations = {str(node): {"pending": [asdict(o) for o in sh.m1.open.values()],
                                       "closed": [asdict(o) for o in sh.m1.closed],
                                       "overdue": [asdict(o) for o in sh.m1.overdue(now)]}
                           for node, sh in state.shields.items()}
            (state.run_dir / "review_obligations.json").write_text(json.dumps(obligations, indent=2) + "\n")
        if state.decisions_out is not None:
            state.decisions_out.flush()
        return {"type": "bye"}
    if t == "anchor":
        state.persist_node(int(msg["node"]), bundle=True)
        return {"type": "anchor", **state.shield_for(int(msg["node"])).log.anchor()}  # type: ignore[union-attr]
    if t not in ("decide", "propose", "check", "base_commit"):
        return {"type": "error", "message": f"unknown message type {t!r}"}
    node = int(msg["node"])
    view = view_from_json(msg["view"])
    if view.node_id != node:
        return {"type": "error", "message": "view.node_id does not match node"}
    sh = state.shield_for(node)
    sh.v = view                                   # daemon state of record comes from ns-3
    if t == "check":
        a = parse_action(msg.get("action"))
        return {"type": "check_result", "violated": sh.violations(a)}
    # decide
    obs = msg.get("observation") or build_observation(view)
    if state.sanitise_inputs:
        obs = sanitise_observation(obs)
    raw: Any = None
    agent_latency_ms = 0.0
    agent_error: Optional[str] = None
    agent_called = state.agent is not None and t in ("decide", "propose")
    if "raw_proposal" in msg:
        raw = msg["raw_proposal"]
        agent_latency_ms = float(msg.get("agent_latency_ms", 0.0))
        agent_error = msg.get("agent_error")
    if agent_called and state.agent is not None and "raw_proposal" not in msg:
        reply = state.agent(obs)
        if hasattr(reply, "raw_text"):
            raw, agent_latency_ms, agent_error = reply.raw_text, reply.latency_ms, reply.error
        else:
            raw = reply
    if agent_called and "raw_proposal" not in msg and state.agent_calls_out is not None:
        observation_hash = hashlib.sha256(json.dumps(obs, sort_keys=True).encode()).hexdigest()
        state.agent_calls_out.write(json.dumps({"t": msg.get("t"), "node": node, "raw": raw,
                                               "latency_ms": agent_latency_ms, "error": agent_error,
                                               "proposer_kind": state.agent_kind,
                                               "observation_sha256": observation_hash},
                                              sort_keys=True) + "\n")
        state.agent_calls_out.flush()
        if state.observations_out is not None:
            state.observations_out.write(json.dumps({"t": msg.get("t"), "node": node, "observation": obs,
                                                    "observation_sha256": observation_hash}, sort_keys=True) + "\n")
            state.observations_out.flush()
    if t == "propose":
        precheck_us = precheck_cpu = 0.0
        if state.shielded:
            preview = Shield(copy.deepcopy(view), state.shield_cfg)
            preview.budget.times = list(sh.budget.times)
            preview_candidates = [a for a in (parse_action(x) for x in msg.get("base_candidates", [])) if a is not None]
            preview_decision = preview.decide(raw, preview_candidates)
            precheck_us, precheck_cpu = preview_decision.latency_us, preview_decision.cpu_us
        return {"type": "proposal", "raw_proposal": raw, "agent_latency_ms": agent_latency_ms,
                "agent_error": agent_error, "precheck_latency_us": precheck_us, "precheck_cpu_us": precheck_cpu}
    candidates = [msg.get("action")] if t == "base_commit" else msg.get("base_candidates", [])
    cands = [c for c in (parse_action(x) for x in candidates) if c is not None]
    if t == "base_commit" and state.shielded:
        before_check = time.perf_counter()
        cpu0 = time.thread_time_ns()
        candidate = parse_action(msg.get("action"))
        violated = sh.violations(candidate)
        action = candidate if candidate is not None and not violated else None
        tier = Tier.BASE if action is not None else Tier.NULL
        proposal = None
        if action is not None:
            sh.apply(action)
        cpu_us = (time.thread_time_ns() - cpu0) / 1e3
        lat = (time.perf_counter() - before_check) * 1e6
        if sh.log is not None:
            sh.log.append({"t": view.now, "node": node, "proposal": None, "violated": violated,
                           "tier": tier.value, "committed": action_to_dict(action), "event": "base_commit"})
    elif state.shielded:
        dec = sh.decide(raw, cands)
        tier, action, violated, lat = dec.tier, dec.action, dec.violated, dec.latency_us
        proposal = dec.proposal
        cpu_us = dec.cpu_us
    else:
        # unshielded agent: commit any parsed proposal; otherwise ns-3's own AODV decides (action None)
        proposal = parse_action(raw) if raw is not None else None
        cpu_us = 0.0
        if _is_proposal(proposal):
            tier, action, violated, lat = Tier.AGENT, proposal, [], 0.0
        else:
            tier, action, violated, lat = Tier.BASE, (cands[0] if t == "base_commit" and cands else None), [], 0.0
        if sh.log is not None:
            sh.log.append({"t": view.now, "node": node, "raw": raw, "proposal": action_to_dict(proposal),
                           "violated": violated, "tier": tier.value, "committed": action_to_dict(action)})
    reply_msg = {"type": "decision", "tier": tier.value, "action": action_to_dict(action), "violated": violated,
                 "latency_us": lat, "agent_latency_ms": agent_latency_ms, "agent_error": agent_error,
                 "agent_called": agent_called, "shield_cpu_us": cpu_us, "decision_wall_ms": (time.perf_counter() - t0) * 1e3}
    if state.decisions_out is not None:
        harm = _oracle_labels(state, msg.get("oracle"), node, proposal) if _is_proposal(proposal) else None
        committed_harm = _oracle_labels(state, msg.get("oracle"), node, action) if action is not None else []
        rec = {"t": msg.get("t"), "node": node, "raw": raw if isinstance(raw, (str, type(None))) else json.dumps(raw),
               "proposal": action_to_dict(proposal), "is_proposal": _is_proposal(proposal),
               "harm": harm, "committed_harm": committed_harm, "agent_called": agent_called,
               "proposer_kind": state.agent_kind, "event": t,
               "proposal_t": msg.get("proposal_t", msg.get("t")),
               "observation_t": msg.get("observation_t", msg.get("proposal_t", msg.get("t"))),
               "precheck_latency_us": float(msg.get("precheck_latency_us", 0.0)),
               "precheck_cpu_us": float(msg.get("precheck_cpu_us", 0.0)),
               "decision_wall_ms": reply_msg["decision_wall_ms"], "shield_cpu_us": cpu_us,
               **{k: reply_msg[k] for k in ("tier", "action", "violated", "latency_us",
                                                          "agent_latency_ms", "agent_error")}}
        state.decisions_out.write(json.dumps(rec, sort_keys=True) + "\n")
        state.decisions_out.flush()
    if state.daemon_audit_out is not None and msg.get("oracle", {}).get("cache_audit"):
        audit = {"t": msg.get("t"), "node": node, "cache_audit": msg["oracle"]["cache_audit"],
                 "daemon_neighbours": sorted(view.neighbours)}
        if state.capture_full_oracle:
            audit.update(oracle=msg["oracle"], daemon_view=msg["view"],
                         base_candidates=msg.get("base_candidates", []))
        state.daemon_audit_out.write(json.dumps(audit, sort_keys=True) + "\n")
        state.daemon_audit_out.flush()
    if state.oracle_out is not None and (_is_proposal(proposal) or action is not None) and msg.get("oracle"):
        state.oracle_out.write(json.dumps({"t": msg.get("proposal_t", msg.get("t")), "node": node,
                                          "proposal": action_to_dict(proposal), "is_proposal": _is_proposal(proposal),
                                          "committed": action_to_dict(action), "oracle": msg["oracle"],
                                          "daemon_neighbours": sorted(view.neighbours)},
                                         sort_keys=True) + "\n")
        state.oracle_out.flush()
    state.persist_node(node)
    return reply_msg


def _oracle_labels(state: BridgeState, oracle: Optional[Dict[str, Any]], node: int,
                   action: Optional[Action]) -> Optional[list[str]]:
    if not oracle:
        return None
    if action is None:
        return []
    from ..schemas import RouteChange, SetPower
    if "destinations" in oracle:
        destinations = oracle["destinations"]
        if isinstance(action, RouteChange):
            selected = [destinations[str(action.dest)]] if str(action.dest) in destinations else []
        elif isinstance(action, SetPower):
            selected = list(destinations.values())
        else:
            selected = list(destinations.values())[:1]
        snapshots = [_snapshot_from_json({**oracle.get("shared", {}), **o}) for o in selected]
    else:
        snapshots = [_snapshot_from_json(oracle)]
        if isinstance(action, RouteChange):
            snapshots = [o for o in snapshots if o.dest == action.dest]
    return sorted(set().union(*(state.harm_oracle.label(o, node, action) for o in snapshots))) if snapshots else None


def _is_proposal(a: Optional[Action]) -> bool:
    return a is not None and a.type.value != "defer"


class _Handler(socketserver.StreamRequestHandler):
    def setup(self) -> None:
        super().setup()
        self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def handle(self) -> None:
        state: BridgeState = self.server.state  # type: ignore[attr-defined]
        for line in self.rfile:
            if not line.strip():
                continue
            try:
                reply = handle_message(state, json.loads(line))
            except (ValueError, KeyError, TypeError) as exc:
                reply = {"type": "error", "message": str(exc)}
            self.wfile.write((json.dumps(reply) + "\n").encode("utf-8"))
            self.wfile.flush()
            if reply.get("type") == "bye":
                break


def serve(state: BridgeState, host: str = "127.0.0.1", port: int = 5577, run_dir: Optional[Path] = None) -> None:
    """Blocking TCP server bound to localhost by default. Not started by tests."""
    if run_dir is not None:
        run_dir.mkdir(parents=True, exist_ok=True)
        if (run_dir / "decisions.jsonl").exists():
            raise FileExistsError("bridge refuses to append a fresh state to an existing decision log")
        state.run_dir = run_dir
        state.decisions_out = (run_dir / "decisions.jsonl").open("w", encoding="utf-8")
    with socketserver.ThreadingTCPServer((host, port), _Handler) as srv:
        srv.state = state  # type: ignore[attr-defined]
        log.info("bridge listening on %s:%d", host, port)
        srv.serve_forever()
