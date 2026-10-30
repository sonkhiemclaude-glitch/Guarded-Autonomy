"""Run provenance: config capture, code hashes, environment, synthetic labelling."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .. import __version__

SYNTHETIC_LABEL = "synthetic smoke-test output, not a paper result"
PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def package_fingerprint() -> Dict[str, str]:
    """SHA-256 of every source file of the installed package (relative paths)."""
    return {str(p.relative_to(PACKAGE_ROOT)): sha256_file(p)
            for p in sorted(PACKAGE_ROOT.rglob("*.py")) if "__pycache__" not in p.parts}


def config_hash(cfg: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()


def dependency_versions() -> Dict[str, Optional[str]]:
    """Installed versions of the runtime dependencies (None if not installed)."""
    from importlib import metadata
    out: Dict[str, Optional[str]] = {}
    for name in ("numpy", "pyyaml", "matplotlib"):
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = None
    return out


def _git_commit(start: Path) -> Optional[str]:
    """Read the current commit from .git without running git (no subprocess)."""
    for d in [start, *start.parents]:
        head = d / ".git" / "HEAD"
        if head.exists():
            ref = head.read_text().strip()
            if ref.startswith("ref: "):
                rp = d / ".git" / ref[5:]
                return rp.read_text().strip() if rp.exists() else None
            return ref
    return None


def run_metadata(cfg: Mapping[str, Any], synthetic: bool, extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    fp = package_fingerprint()
    md: Dict[str, Any] = {
        "created_utc": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "package": "guarded_autonomy", "version": __version__,
        "python": sys.version.split()[0], "platform": platform.platform(),
        "dependencies": dependency_versions(),
        "git_commit": _git_commit(PACKAGE_ROOT),
        "config": dict(cfg), "config_sha256": config_hash(cfg),
        "code_sha256": hashlib.sha256(json.dumps(fp, sort_keys=True).encode()).hexdigest(),
        "code_files": fp,
        "synthetic": synthetic,
        "label": SYNTHETIC_LABEL if synthetic else "real run output (verify provenance before reporting)",
    }
    if extra:
        md.update(extra)
    return md


def write_metadata(out_dir: Path, md: Mapping[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "run_metadata.json"
    p.write_text(json.dumps(md, indent=1, sort_keys=True, default=str))
    return p
