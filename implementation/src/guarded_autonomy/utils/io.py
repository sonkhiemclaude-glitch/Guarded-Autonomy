"""Small, dependency-free I/O helpers."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str] | None = None) -> Path:
    if not rows:
        raise ValueError(f"refusing to write empty CSV {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(fieldnames) if fieldnames else list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    return path


def read_csv(path: Path) -> List[Dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_json(path: Path, obj: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True, default=str))
    return path


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text())


def ensure_within(base: Path, target: Path) -> Path:
    """Resolve ``target`` and refuse paths outside ``base`` (no writes outside the output root)."""
    b, t = base.resolve(), target.resolve()
    if b != t and b not in t.parents:
        raise ValueError(f"{t} is outside {b}")
    return t


def iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)
