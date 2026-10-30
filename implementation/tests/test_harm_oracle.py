import pytest

from guarded_autonomy.schemas import Isolate, RouteChange, SetPower
from guarded_autonomy.simulation.harm import GlobalSnapshot, HarmOracle


def snap():
    # honest chain 3 -> 2 -> 1 -> 0 (dest); adversary 9
    return GlobalSnapshot(dest=0, next_hop={1: 0, 2: 1, 3: 2, 4: None}, adversaries=frozenset({9}),
                          required_power_dbm={1: {0: 10.0}}, tx_power_dbm={1: 16.0, 2: 16.0},
                          residual_energy_j={1: 50.0, 2: 5.0})


def test_h_loop_and_adv():
    o = HarmOracle()
    assert "H-loop" in o.label(snap(), 1, RouteChange(0, 3))          # 1 -> 3 -> 2 -> 1
    assert o.label(snap(), 4, RouteChange(0, 3)) == set()            # 4 -> 3 -> ... -> 0
    assert "H-adv" in o.label(snap(), 4, RouteChange(0, 9))
    assert "H-adv" in HarmOracle("direct").label(snap(), 4, RouteChange(0, 9))


def test_h_iso_power_energy():
    o = HarmOracle()
    assert o.label(snap(), 1, Isolate(2)) == {"H-iso"}
    assert o.label(snap(), 1, Isolate(9)) == set()
    assert o.label(snap(), 1, SetPower(8.0)) == {"H-power"}
    assert o.label(snap(), 1, SetPower(12.0)) == set()
    assert o.label(snap(), 2, SetPower(18.0)) == {"H-energy"}
    with pytest.raises(ValueError):
        HarmOracle("nope")
