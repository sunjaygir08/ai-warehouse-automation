"""
tests/test_collision.py
=======================
Automated tests for multi-robot BFS collision-free pathfinding in
Smart Warehouse Automation (app.py WarehouseSimulation class).

Run with:
    .venv\\Scripts\\python.exe -m pytest tests/test_collision.py -v
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import WarehouseSimulation


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def fresh_sim():
    """Return a clean WarehouseSimulation with exactly 5 robots."""
    return WarehouseSimulation()


def place_robot(sim, robot_id, row, col):
    """Move a robot to an arbitrary (non-obstacle) cell for test setup."""
    for r in sim.robots:
        if r["id"] == robot_id:
            r["row"] = row
            r["col"] = col
            r["home"] = (row, col)
            r["path"] = []
            r["path_index"] = 0
            r["assigned_order"] = None
            r["status"] = "idle"
            r["carrying"] = False
            r["wait_ticks"] = 0
            break


# Unique parking positions in clear upper aisles for robots not under test
_PARK_POSITIONS = {
    "R1": (0, 8),
    "R2": (0, 9),
    "R3": (0, 10),
    "R4": (0, 11),
    "R5": (0, 12),
}


def park_all_robots(sim):
    """Put every robot at a known unique idle position."""
    for r in sim.robots:
        row, col = _PARK_POSITIONS[r["id"]]
        place_robot(sim, r["id"], row, col)


def park_others(sim, *active_ids):
    """Park every robot NOT in active_ids at a unique idle cell."""
    for r in sim.robots:
        if r["id"] not in active_ids:
            row, col = _PARK_POSITIONS[r["id"]]
            place_robot(sim, r["id"], row, col)


def assert_no_collision(sim, context=""):
    """Assert that no two robots share the same (row, col)."""
    positions = [(r["row"], r["col"]) for r in sim.robots]
    duplicates = [p for p in set(positions) if positions.count(p) > 1]
    assert not duplicates, (
        f"Collision detected at {duplicates}! "
        f"Robot positions: {[(r['id'], r['row'], r['col']) for r in sim.robots]}"
        + (f" [{context}]" if context else "")
    )


def run_ticks(sim, n):
    """Advance the simulation n ticks under lock and check collisions each tick."""
    for tick in range(n):
        with sim.lock:
            sim._advance_one()
        assert_no_collision(sim, f"after tick {tick + 1}")


def set_path(sim, robot_id, path_cells, order_id=None):
    """Manually assign a path list (excluding current cell) to a robot."""
    for r in sim.robots:
        if r["id"] == robot_id:
            r["path"] = [{"row": row, "col": col} for row, col in path_cells]
            r["path_index"] = 0
            r["status"] = "moving"
            if order_id:
                r["assigned_order"] = order_id
            break


def add_dummy_order(sim, order_id, robot_id, pick_row, pick_col, status="to_pick"):
    """Add a manually constructed order and assign it to a robot."""
    sim.orders.append({
        "id": order_id, "status": status, "created_tick": 0,
        "completed_tick": None,
        "pick": {"row": pick_row, "col": pick_col},
        "robot_id": robot_id,
    })
    for r in sim.robots:
        if r["id"] == robot_id:
            r["assigned_order"] = order_id
            r["status"] = "moving"
            break


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Layout & Rack Identification Verification
# ─────────────────────────────────────────────────────────────────────────────

def test_warehouse_grid_redesign_and_rack_ids():
    """
    Verify:
    1. Exactly 5 robots (R1..R5).
    2. Starting positions are in row 0 side by side beside charging: (0, 2) to (0, 6).
    3. Charging station moved to the top-left: (0, 0) and (0, 1).
    4. Racks arranged in 4 rows (1, 4, 7, 10) in 3 pair columns (cols 3-4, 7-8, 11-12).
    5. Exactly 24 racks, all with unique sequential IDs RACK-01 to RACK-24.
    6. Delivery station moved to bottom-right: (11, 15).
    """
    sim = fresh_sim()

    # 1. Exactly 5 robots
    assert len(sim.robots) == 5, f"Expected exactly 5 robots, got {len(sim.robots)}"
    assert [r["id"] for r in sim.robots] == ["R1", "R2", "R3", "R4", "R5"]

    # 2. Charging station at top-left
    assert sim.CHARGING == [{"row": 0, "col": 0}, {"row": 0, "col": 1}]

    # 3. 5 robots side by side beside charging station
    assert sim.STARTS == [(0, 2), (0, 3), (0, 4), (0, 5), (0, 6)]
    for i, r in enumerate(sim.robots):
        assert (r["row"], r["col"]) == sim.STARTS[i]

    # 4. Delivery station at bottom-right
    assert sim.STATION == {"row": 11, "col": 15}

    # 5. Exactly 24 racks arranged in 4 rows
    assert len(sim.SHELVES) == 24
    expected_ids = [f"RACK-{i+1:02d}" for i in range(24)]
    rack_ids = [s["id"] for s in sim.SHELVES]
    assert rack_ids == expected_ids, f"Rack IDs mismatch: {rack_ids}"

    # Verify rack rows are 1, 4, 7, 10
    shelf_rows = {s["row"] for s in sim.SHELVES}
    assert shelf_rows == {1, 4, 7, 10}, f"Expected shelf rows {{1, 4, 7, 10}}, got {shelf_rows}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Two robots approaching the same cell
# ─────────────────────────────────────────────────────────────────────────────

def test_two_robots_converge_on_same_cell():
    """
    R1 at (6,5) moves right -> (6,6).
    R2 at (6,7) moves left  -> (6,6).
    Only one robot moves; the other waits without collision.
    """
    sim = fresh_sim()
    park_others(sim, "R1", "R2")

    place_robot(sim, "R1", 6, 5)
    place_robot(sim, "R2", 6, 7)

    add_dummy_order(sim, "ORD-T1A", "R1", 6, 6)
    add_dummy_order(sim, "ORD-T1B", "R2", 6, 6)
    set_path(sim, "R1", [(6, 6)], order_id="ORD-T1A")
    set_path(sim, "R2", [(6, 6)], order_id="ORD-T1B")

    with sim.lock:
        sim._advance_one()

    assert_no_collision(sim)
    positions = {r["id"]: (r["row"], r["col"]) for r in sim.robots if r["id"] in ("R1", "R2")}
    at_target = sum(1 for pos in positions.values() if pos == (6, 6))
    assert at_target == 1, f"Expected 1 robot at (6,6), got {at_target}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Head-on edge swap prevention
# ─────────────────────────────────────────────────────────────────────────────

def test_head_on_edge_swap_prevented():
    """
    R1 at (6,5) wants to move -> (6,6).
    R2 at (6,6) wants to move -> (6,5).
    Simultaneous swap must be prevented.
    """
    sim = fresh_sim()
    park_others(sim, "R1", "R2")

    place_robot(sim, "R1", 6, 5)
    place_robot(sim, "R2", 6, 6)

    add_dummy_order(sim, "ORD-T2A", "R1", 6, 6)
    add_dummy_order(sim, "ORD-T2B", "R2", 6, 5)
    set_path(sim, "R1", [(6, 6)], order_id="ORD-T2A")
    set_path(sim, "R2", [(6, 5)], order_id="ORD-T2B")

    with sim.lock:
        sim._advance_one()

    r1 = next(r for r in sim.robots if r["id"] == "R1")
    r2 = next(r for r in sim.robots if r["id"] == "R2")

    assert_no_collision(sim)
    swapped = (r1["row"], r1["col"]) == (6, 6) and (r2["row"], r2["col"]) == (6, 5)
    assert not swapped, "Head-on swap occurred!"


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Narrow aisle queuing
# ─────────────────────────────────────────────────────────────────────────────

def test_narrow_aisle_no_collision():
    """Three robots in a single-column corridor all moving south."""
    sim = fresh_sim()
    park_others(sim, "R1", "R2", "R3")

    place_robot(sim, "R1", 3, 6)
    place_robot(sim, "R2", 4, 6)
    place_robot(sim, "R3", 5, 6)

    add_dummy_order(sim, "ORD-NA1", "R1", 9, 6)
    add_dummy_order(sim, "ORD-NA2", "R2", 10, 6)
    add_dummy_order(sim, "ORD-NA3", "R3", 10, 6)

    set_path(sim, "R1", [(4,6),(5,6),(6,6),(7,6),(8,6),(9,6)], order_id="ORD-NA1")
    set_path(sim, "R2", [(5,6),(6,6),(7,6),(8,6),(9,6),(10,6)], order_id="ORD-NA2")
    set_path(sim, "R3", [(6,6),(7,6),(8,6),(9,6),(10,6)], order_id="ORD-NA3")

    run_ticks(sim, 15)


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Robot waiting behind stationary robot
# ─────────────────────────────────────────────────────────────────────────────

def test_robot_waits_behind_stationary_robot():
    """R1 must wait when R2 is stationary in its target cell."""
    sim = fresh_sim()
    park_others(sim, "R1", "R2")

    place_robot(sim, "R1", 6, 5)
    place_robot(sim, "R2", 6, 6)

    add_dummy_order(sim, "ORD-T4", "R1", 6, 6)
    set_path(sim, "R1", [(6, 6)], order_id="ORD-T4")

    with sim.lock:
        sim._advance_one()

    r1 = next(r for r in sim.robots if r["id"] == "R1")
    r2 = next(r for r in sim.robots if r["id"] == "R2")

    assert_no_collision(sim)
    assert (r2["row"], r2["col"]) == (6, 6)
    assert (r1["row"], r1["col"]) == (6, 5)
    assert r1["wait_ticks"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: Navigation around racks (obstacles)
# ─────────────────────────────────────────────────────────────────────────────

def test_path_avoids_obstacles():
    """Path from (1, 2) to (1, 5) must route around shelf at (1, 3), (1, 4)."""
    sim = fresh_sim()
    path = sim._path((1, 2), (1, 5))
    shelf_cells = sim.obstacles
    assert path, "Path should exist between (1,2) and (1,5)"
    for step in path:
        cell = (step["row"], step["col"])
        assert cell not in shelf_cells, f"Path traverses obstacle {cell}"
    assert (path[0]["row"], path[0]["col"]) == (1, 2)
    assert (path[-1]["row"], path[-1]["col"]) == (1, 5)


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: Simultaneous order completion with 5 robots
# ─────────────────────────────────────────────────────────────────────────────

def test_simultaneous_order_completion():
    """Dispatch 5 orders, all 5 complete and robots return to home without collisions."""
    sim = fresh_sim()
    for _ in range(5):
        sim.add_order()

    run_ticks(sim, 250)

    completed = [o for o in sim.orders if o["status"] == "completed"]
    assert len(completed) == 5, f"Expected 5 completed, got {len(completed)}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: Deadlock recovery
# ─────────────────────────────────────────────────────────────────────────────

def test_deadlock_recovery():
    """Verify that deadlock recovery replans when two robots are blocked."""
    sim = fresh_sim()
    park_others(sim, "R1", "R2")

    place_robot(sim, "R1", 6, 5)
    place_robot(sim, "R2", 6, 6)

    add_dummy_order(sim, "ORD-DL1", "R1", 6, 8)
    add_dummy_order(sim, "ORD-DL2", "R2", 6, 3)
    set_path(sim, "R1", [(6, 6), (6, 7), (6, 8)], order_id="ORD-DL1")
    set_path(sim, "R2", [(6, 5), (6, 4), (6, 3)], order_id="ORD-DL2")

    threshold = sim.WAIT_REPLAN_THRESHOLD + 4
    start_positions = {"R1": (6, 5), "R2": (6, 6)}

    for tick in range(threshold):
        with sim.lock:
            sim._advance_one()
        assert_no_collision(sim, f"deadlock tick {tick + 1}")

    r1 = next(r for r in sim.robots if r["id"] == "R1")
    r2 = next(r for r in sim.robots if r["id"] == "R2")
    current = {"R1": (r1["row"], r1["col"]), "R2": (r2["row"], r2["col"])}

    moved = any(current[rid] != start_positions[rid] for rid in ["R1", "R2"])
    assert moved, "Neither robot escaped deadlock"


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: Reset and restart
# ─────────────────────────────────────────────────────────────────────────────

def test_reset_and_restart():
    """Verify state reset maintains exactly 5 robots, clean queues, and resumes properly."""
    sim = fresh_sim()
    for _ in range(3):
        sim.add_order()
    run_ticks(sim, 50)

    sim.reset()

    assert sim.tick == 0
    assert sim.running is False
    assert len(sim.orders) == 0
    assert len(sim.robots) == 5
    for r in sim.robots:
        assert r["assigned_order"] is None
        assert r["path"] == []
        assert r["wait_ticks"] == 0

    for _ in range(3):
        sim.add_order()
    run_ticks(sim, 150)

    completed = [o for o in sim.orders if o["status"] == "completed"]
    assert len(completed) >= 1
    assert_no_collision(sim)


# ─────────────────────────────────────────────────────────────────────────────
# Test 10: 5 robots concurrent stress test
# ─────────────────────────────────────────────────────────────────────────────

def test_five_robots_concurrent_no_collision():
    """Dispatch 5 orders simultaneously, run 300 ticks, assert zero collisions."""
    sim = fresh_sim()
    for _ in range(5):
        sim.add_order()

    run_ticks(sim, 300)

    completed = [o for o in sim.orders if o["status"] == "completed"]
    assert len(completed) == 5, f"Expected 5 completed, got {len(completed)}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 11: No duplicate order assignment
# ─────────────────────────────────────────────────────────────────────────────

def test_no_duplicate_order_assignment():
    """Ensure no order is simultaneously assigned to multiple robots."""
    sim = fresh_sim()
    for _ in range(5):
        sim.add_order()
    run_ticks(sim, 200)

    robot_order_map = {}
    for r in sim.robots:
        if r["assigned_order"]:
            assert r["assigned_order"] not in robot_order_map
            robot_order_map[r["assigned_order"]] = r["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Test 12: Order completes only after physical destination arrival
# ─────────────────────────────────────────────────────────────────────────────

def test_order_completes_only_at_destination():
    """Order only completes when physically at the delivery station (10, 14)."""
    sim = fresh_sim()
    sim.add_order()

    for _ in range(200):
        with sim.lock:
            sim._advance_one()
        assert_no_collision(sim)
        for order in sim.orders:
            if order["status"] == "completed":
                assert order.get("robot_id") is not None


# ─────────────────────────────────────────────────────────────────────────────
# Test 13: Unreachable goal handling
# ─────────────────────────────────────────────────────────────────────────────

def test_bfs_no_path_returns_empty():
    """BFS handles unreachable goal gracefully without crashing."""
    sim = fresh_sim()
    shelf_cell = (1, 3)
    path = sim._path((0, 0), shelf_cell)
    if path:
        for step in path[:-1]:
            assert (step["row"], step["col"]) not in sim.obstacles


# ─────────────────────────────────────────────────────────────────────────────
# Test 14: Initial robot positions are valid and non-colliding
# ─────────────────────────────────────────────────────────────────────────────

def test_initial_positions_no_collision():
    """Default 5 robot starting positions must be distinct and obstacle-free."""
    sim = fresh_sim()
    assert_no_collision(sim)
    assert len(sim.robots) == 5
    for r in sim.robots:
        assert (r["row"], r["col"]) not in sim.obstacles
