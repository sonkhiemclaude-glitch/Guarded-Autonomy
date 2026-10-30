import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from guarded_autonomy.schemas import LocalView, RouteEntry  # noqa: E402


@pytest.fixture
def repo_root() -> Path:
    return ROOT


@pytest.fixture
def view() -> LocalView:
    """Node 1 with neighbours 2, 3, 4; route to 0 via 2 with key (5, -3)."""
    v = LocalView(node_id=1, neighbours={2, 3, 4}, active_dests={0})
    v.routes[0] = RouteEntry(seq=5, hops=3, next_hop=2, valid=True)
    v.adv[0] = {2: (5, 2), 3: (5, 2), 4: (6, 9)}
    v.trust = {2: 0.9, 3: 0.9, 4: 0.9}
    return v
