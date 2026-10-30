"""Configuration objects and YAML loading.

Default threshold values follow Table A.8 (p40). Configuration files never execute code;
only plain YAML scalars, lists and mappings are accepted (``yaml.safe_load``).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping

import yaml


@dataclass(frozen=True)
class ShieldConfig:
    """Invariant parameters (Table 2; values from Table A.8)."""

    trust_min_route: float = 0.7      # I3 tau_route
    min_obs_route: int = 5            # I3 m_r
    trust_max_isolate: float = 0.5    # I4a tau_iso
    min_obs_isolate: int = 10         # I4b m_iso
    iso_window_s: float = 60.0        # I4c W
    iso_max_in_window: int = 2        # I4c k
    p_min_dbm: float = 0.0            # I5a
    p_max_dbm: float = 20.0           # I5a
    energy_floor_j: float = 10.0      # I6
    use_loop: bool = True             # I2 on/off (never off in the paper)
    use_trust: bool = True            # I3 on/off (ablation "-I3")
    use_isolation: bool = True        # I4a-I4c on/off
    use_rate_limit: bool = True       # I4c on/off (ablation "-I4c")
    use_power: bool = True            # I5/I6 on/off
    use_olsr_downhill: bool = False   # OLSR structural invariant (Sec. 4.6) instead of I2
    tier2_enabled: bool = True        # ablation "tier 2 disabled"
    review_deadline_s: float = 120.0  # M1 obligation deadline (not given in paper; config choice)

    def __post_init__(self) -> None:
        for name in ("trust_min_route", "trust_max_isolate"):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{name} must be in [0, 1], got {v}")
        if self.iso_max_in_window < 0 or self.min_obs_route < 0 or self.min_obs_isolate < 0:
            raise ValueError("counts must be non-negative")
        if self.iso_window_s <= 0:
            raise ValueError("iso_window_s must be positive")
        if self.p_min_dbm > self.p_max_dbm:
            raise ValueError("p_min_dbm must not exceed p_max_dbm")

    @classmethod
    def from_mapping(cls, m: Mapping[str, Any]) -> ShieldConfig:
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = set(m) - known
        if unknown:
            raise ValueError(f"unknown shield config keys: {sorted(unknown)}")
        return cls(**dict(m))

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


# Named configurations used in the paper's component check (Sec. 6.1)
LOOP_ONLY = ShieldConfig(use_trust=False, use_isolation=True)
FULL = ShieldConfig()


@dataclass
class RunConfig:
    """Top-level run configuration loaded from YAML."""

    name: str
    kind: str                                   # "component_check" | "ns3_system" | "synthetic_demo"
    seed: int = 0
    output_dir: str = "outputs"
    synthetic: bool = True
    section: Dict[str, Any] = field(default_factory=dict)  # kind-specific block

    @classmethod
    def load(cls, path: str | Path) -> RunConfig:
        p = Path(path)
        with p.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if not isinstance(raw, dict):
            raise ValueError(f"{p}: top level must be a mapping")
        for key in ("name", "kind"):
            if key not in raw:
                raise ValueError(f"{p}: missing required key '{key}'")
        kind = raw["kind"]
        if kind not in ("component_check", "ns3_system", "synthetic_demo"):
            raise ValueError(f"{p}: unknown kind '{kind}'")
        section = raw.get(kind, {}) or {}
        if not isinstance(section, dict):
            raise ValueError(f"{p}: '{kind}' block must be a mapping")
        return cls(name=str(raw["name"]), kind=kind, seed=int(raw.get("seed", 0)),
                   output_dir=str(raw.get("output_dir", "outputs")),
                   synthetic=bool(raw.get("synthetic", kind != "ns3_system")), section=section)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "seed": self.seed, "output_dir": self.output_dir,
                "synthetic": self.synthetic, self.kind: self.section}
