"""Hash-chained decision log (Sec. 4.5, p12-13).

e_t = SHA-256(e_{t-1} || record_t). Tamper evidence holds only against an authentic copy of a
later head held outside the node (anchoring); a node that controls the whole log can rewrite it
consistently (Remark in the paper; Schneier and Kelsey 1999; Crosby and Wallach 2009).
"""
from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

GENESIS = "0" * 64


def _digest(prev: str, body: str) -> str:
    return hashlib.sha256((prev + body).encode("utf-8")).hexdigest()


@dataclass
class HashChainLog:
    entries: List[Dict[str, str]] = field(default_factory=list)
    head: str = GENESIS

    def append(self, record: Dict[str, Any]) -> str:
        body = json.dumps(record, sort_keys=True, default=str)
        h = _digest(self.head, body)
        self.entries.append({"prev": self.head, "body": body, "hash": h})
        self.head = h
        return h

    def verify(self, anchored_head: Optional[str] = None) -> bool:
        """Check internal consistency and, if given, agreement with an anchored head."""
        prev = GENESIS
        for e in self.entries:
            if e.get("prev") != prev or _digest(prev, e.get("body", "")) != e.get("hash"):
                return False
            prev = e["hash"]
        return anchored_head is None or prev == anchored_head

    def anchor(self) -> Dict[str, Any]:
        """Head commitment to be stored outside the node (e.g. broadcast or exported)."""
        return {"head": self.head, "length": len(self.entries)}

    def save_jsonl(self, path: str | Path) -> None:
        with Path(path).open("w", encoding="utf-8") as fh:
            for e in self.entries:
                fh.write(json.dumps(e, sort_keys=True) + "\n")

    @classmethod
    def load_jsonl(cls, path: str | Path) -> HashChainLog:
        log = cls()
        actual = Path(path)
        if not actual.exists() and actual.with_name(actual.name + ".gz").exists():
            actual = actual.with_name(actual.name + ".gz")
        opener = gzip.open(actual, "rt", encoding="utf-8") if actual.suffix == ".gz" else actual.open("r", encoding="utf-8")
        with opener as fh:
            for line in fh:
                if line.strip():
                    log.entries.append(json.loads(line))
        log.head = log.entries[-1]["hash"] if log.entries else GENESIS
        return log
