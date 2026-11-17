"""
tests/test_features.py
======================
Unit tests for new warehouse features:
- Battery drain during movement
- Low battery routing to charging station
- Rack reservation and status lifecycle
- Nearest robot assignment via BFS distance
- Full simulation reset verification
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import WarehouseSimulation, BATTERY_CONFIG


def test_battery_drain_during_movement():
    """Verify that a robot's battery decreases as it moves."""
    sim = WarehouseSimulation()
    r1 = sim.robots[0]
    initial_battery = r1["battery"]
    assert initial_battery == 100

    order_id = sim.add_order()
    assert r1["assigned_order"] == order_id

    # Advance a few ticks so the robot moves
    moved = False
    for _ in range(10):
        with sim.lock:
            sim._advance_one()
        if r1["battery"] < initial_battery:
            moved = True
            break

    assert moved, f"Robot battery did not decrease: {r1['battery']}"
    assert r1["battery"] < 100


def test_low_battery_blocks_new_task_and_routes_to_charger():
    """Verify that a low-battery robot does not get assigned orders and goes to charger."""
    sim = WarehouseSimulation()
    r1 = sim.robots[0]
    # Set r1 battery below low threshold
    r1["battery"] = BATTERY_CONFIG["low_threshold"] - 5  # 15%

    # Add order: should be assigned to an available robot with good battery (not r1)
    order_id = sim.add_order()
    assigned = [r for r in sim.robots if r["assigned_order"] == order_id]
    assert len(assigned) == 1
    assert assigned[0]["id"] != r1["id"], "Low-battery robot was assigned a task!"

    # Since r1 is idle and low-battery, it should be sent to charging
    with sim.lock:
        sim._advance_one()

    assert r1["status"] in ("charging_transit", "charging"), f"Expected charging status, got {r1['status']}"


def test_rack_status_lifecycle():
    """Verify rack transitions AVAILABLE -> RESERVED -> OCCUPIED -> AVAILABLE."""
    sim = WarehouseSimulation()
    rack_01 = next(s for s in sim.SHELVES if s["id"] == "RACK-01")
    assert rack_01["status"] == "AVAILABLE"

    # Add an order
    order_id = sim.add_order()
    order = next(o for o in sim.orders if o["id"] == order_id)
    assigned_rack = next(s for s in sim.SHELVES if s["id"] == order["rack_id"])

    # Rack is now reserved
    assert assigned_rack["status"] == "RESERVED"

    # Advance simulation until pick completes
    picked = False
    for _ in range(100):
        with sim.lock:
            sim._advance_one()
        if order["status"] == "to_station":
            picked = True
            break

    assert picked, "Order never reached to_station status"
    assert assigned_rack["status"] == "OCCUPIED"

    # Advance simulation until delivery completes
    delivered = False
    for _ in range(100):
        with sim.lock:
            sim._advance_one()
        if order["status"] == "completed":
            delivered = True
            break

    assert delivered, "Order never completed delivery"
    assert assigned_rack["status"] == "AVAILABLE"


def test_nearest_robot_assigned_via_bfs_distance():
    """Verify that the nearest available robot by BFS path distance is selected."""
    sim = WarehouseSimulation()
    # Place R1 far away at (11, 0)
    sim.robots[0]["row"] = 11
    sim.robots[0]["col"] = 0
    sim.robots[0]["home"] = (11, 0)

    # Place R2 right next to RACK-01 (pick cell at (1, 2))
    sim.robots[1]["row"] = 1
    sim.robots[1]["col"] = 2
    sim.robots[1]["home"] = (1, 2)

    # Add order (will target RACK-01)
    order_id = sim.add_order()
    order = next(o for o in sim.orders if o["id"] == order_id)
    assert order["robot_id"] == "R2", f"Expected nearest robot R2, got {order['robot_id']}"


def test_reset_functionality_full_cleanup():
    """Verify that simulation reset cleanly restores all 5 robots to IDLE at home."""
    sim = WarehouseSimulation()
    for _ in range(3):
        sim.add_order()

    # Run for 20 ticks
    for _ in range(20):
        with sim.lock:
            sim._advance_one()

    # Reset
    sim.reset()

    assert sim.tick == 0
    assert not sim.running
    assert len(sim.orders) == 0
    assert len(sim.robots) == 5

    for i, r in enumerate(sim.robots):
        assert r["status"] == "idle", f"Robot {r['id']} status is {r['status']}, expected 'idle'"
        assert r["assigned_order"] is None
        assert r["destination_rack"] is None
        assert r["carrying"] is False
        assert r["battery"] == 100
        assert r["path"] == []
        assert r["path_index"] == 0
        assert (r["row"], r["col"]) == sim.STARTS[i]

    for s in sim.SHELVES:
        assert s["status"] == "AVAILABLE"
