"""Run matrices of the component-level check (Sec. 6.2-6.4; Table A.8).

``paper_matrix`` returns exactly the runs behind the paper's Tables 4-6, A.9 and Fig. 3, in the
same order. ``build_matrix`` reads the same structure from a configuration block so that reduced
(smoke-test) or extended grids can be run without editing code.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Mapping, Sequence

from ..config import FULL, LOOP_ONLY, ShieldConfig
from .model import AbstractNetwork, ModelParams


@dataclass(frozen=True)
class RunSpec:
    suite: str
    params: ModelParams
    shield: ShieldConfig
    shield_label: str

    def metadata(self) -> Dict[str, Any]:
        p = self.params
        return dict(suite=self.suite, n=p.n, seed=p.seed, mode=p.mode, proposer=p.proposer,
                    cfg=self.shield_label, adv_frac=p.adv_frac, iso_prob=p.iso_prob, vmax=p.vmax,
                    attack=p.attack if self.suite != "cc1" else "", trust_max_isolate=self.shield.trust_max_isolate,
                    wd_err=p.wd_err, frame=p.frame)


def _label(cfg: ShieldConfig) -> str:
    return "loop" if not cfg.use_trust else "loop+trust"


def cc1(seeds: Sequence[int], ns: Sequence[int] = (20, 50, 100), vmaxs: Sequence[float] = (5.0, 20.0),
        proposers: Sequence[str] = ("rand", "greedy", "adv", "stable"), steps: int = 300) -> Iterator[RunSpec]:
    for vmax in vmaxs:
        for n in ns:
            for s in seeds:
                yield RunSpec("cc1", ModelParams(n=n, seed=s, mode="base", proposer="none", vmax=vmax, steps=steps),
                              LOOP_ONLY, _label(LOOP_ONLY))
                for p in proposers:
                    for mode in ("unshielded", "shielded"):
                        yield RunSpec("cc1", ModelParams(n=n, seed=s, mode=mode, proposer=p, vmax=vmax, steps=steps),
                                      LOOP_ONLY, _label(LOOP_ONLY))


def cc2(seeds: Sequence[int], n: int = 50, attacks: Sequence[str] = ("inflate", "shortcut"),
        fracs: Sequence[float] = (0.1, 0.2), steps: int = 300) -> Iterator[RunSpec]:
    for attack in attacks:
        for f in fracs:
            for s in seeds:
                base = dict(n=n, seed=s, adv_frac=f, attack=attack, steps=steps)
                yield RunSpec("cc2", ModelParams(mode="base", proposer="none", **base), LOOP_ONLY, "loop")  # type: ignore[arg-type]
                yield RunSpec("cc2", ModelParams(mode="unshielded", proposer="greedy", **base), LOOP_ONLY, "loop")  # type: ignore[arg-type]
                yield RunSpec("cc2", ModelParams(mode="shielded", proposer="greedy", **base), LOOP_ONLY, "loop")  # type: ignore[arg-type]
                yield RunSpec("cc2", ModelParams(mode="shielded", proposer="greedy", **base), FULL, "loop+trust")  # type: ignore[arg-type]


def cc3(seeds: Sequence[int], n: int = 50, taus: Sequence[float] = (0.3, 0.5, 0.7),
        watchdogs: Sequence[Sequence[float]] = ((0.05, 0.0), (0.15, 0.3)), steps: int = 300) -> Iterator[RunSpec]:
    for wd_err, frame in watchdogs:
        for tiso in taus:
            cfg = ShieldConfig(trust_max_isolate=tiso)
            for s in seeds:
                base = dict(n=n, seed=s, adv_frac=0.1, iso_prob=0.3, attack="shortcut", wd_err=wd_err,
                            frame=frame, steps=steps)
                if tiso == taus[0]:
                    yield RunSpec("cc3", ModelParams(mode="unshielded", proposer="greedy", **base), cfg, _label(cfg))  # type: ignore[arg-type]
                yield RunSpec("cc3", ModelParams(mode="shielded", proposer="greedy", **base), cfg, _label(cfg))  # type: ignore[arg-type]


def paper_matrix(suite: str, n_seeds: int = 10, steps: int = 300) -> List[RunSpec]:
    """Exactly the paper's runs (Sec. 6) for 'cc1', 'cc2' or 'cc3'."""
    seeds = list(range(n_seeds))
    if suite == "cc1":
        return list(cc1(seeds, steps=steps))
    if suite == "cc2":
        return list(cc2(seeds, steps=steps))
    if suite == "cc3":
        return list(cc3(seeds, steps=steps))
    raise ValueError(f"unknown suite {suite}")


def build_matrix(block: Mapping[str, Any]) -> List[RunSpec]:
    """Build a run matrix from a config block (see configs/component_check_paper.yaml)."""
    seeds = list(range(int(block.get("seed_offset", 0)), int(block.get("seed_offset", 0)) + int(block.get("n_seeds", 10))))
    steps = int(block.get("steps", 300))
    specs: List[RunSpec] = []
    for suite in block.get("suites", ["cc1", "cc2", "cc3"]):
        sub = block.get(suite, {}) or {}
        if suite == "cc1":
            specs += list(cc1(seeds, ns=sub.get("ns", (20, 50, 100)), vmaxs=sub.get("vmaxs", (5.0, 20.0)),
                              proposers=sub.get("proposers", ("rand", "greedy", "adv", "stable")), steps=steps))
        elif suite == "cc2":
            specs += list(cc2(seeds, n=sub.get("n", 50), attacks=sub.get("attacks", ("inflate", "shortcut")),
                              fracs=sub.get("fracs", (0.1, 0.2)), steps=steps))
        elif suite == "cc3":
            specs += list(cc3(seeds, n=sub.get("n", 50), taus=sub.get("taus", (0.3, 0.5, 0.7)),
                              watchdogs=sub.get("watchdogs", ((0.05, 0.0), (0.15, 0.3))), steps=steps))
        else:
            raise ValueError(f"unknown suite '{suite}'")
    return specs


def run_spec(spec: RunSpec) -> Dict[str, Any]:
    row = AbstractNetwork(spec.params, spec.shield).run()
    row.update(spec.metadata())
    return row
