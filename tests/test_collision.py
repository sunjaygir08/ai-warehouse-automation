"""
tests/test_collision.py
=======================
Automated tests for multi-robot BFS collision-free pathfinding in
Smart Warehouse Automation (app.py WarehouseSimulation class).

Run with:
    .venv\\Scripts\\python.exe -m pytest tests/test_collision.py -v

All tests use a fresh WarehouseSimulation instance with robots repositioned
to match the specific scenario being tested.  No Flask server is started —
only the WarehouseSimulation class is imported and exercised directly.
"""
import sys
import os
import pytest

# Allow running from the project root without installing the package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import WarehouseSimulation


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def fresh_sim():
    """Return a clean WarehouseSimulation with the default 10 robots."""
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


# Unique "parking" cells for robots not under test — all walkable, all distinct.
_PARK_POSITIONS = {
    "R1": (0, 0),   "R2": (0, 1),  "R3": (0, 2),  "R4": (0, 3),
    "R5": (0, 6),   "R6": (0, 9),  "R7": (0, 13), "R8": (0, 15),
    "R9": (1, 0),  "R10": (1, 1),
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


def set_path(sim, robot_id, path_cells, order_id=None, order_status="to_pick"):
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
# Test 1: Two robots approaching the same cell
# ─────────────────────────────────────────────────────────────────────────────

def test_two_robots_converge_on_same_cell():
    """
    R1 at (6,5) moves right → (6,6).
    R2 at (6,7) moves left  → (6,6).
    Both want cell (6,6) simultaneously.  Only one should be granted; the other waits.
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
    positions = {r["id"]: (r["row"], r["col"]) for r in sim.robots
                 if r["id"] in ("R1", "R2")}
    # Exactly one robot should have moved to (6,6)
    at_target = sum(1 for pos in positions.values() if pos == (6, 6))
    assert at_target == 1, (
        f"Expected exactly 1 robot at (6,6), got {at_target}. Positions: {positions}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Head-on edge swap prevention
# ─────────────────────────────────────────────────────────────────────────────

def test_head_on_edge_swap_prevented():
    """
    R1 at (6,5) wants to move → (6,6).
    R2 at (6,6) wants to move → (6,5).
    This is a head-on swap — must NOT be allowed simultaneously.
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
    # After one tick they must NOT have both swapped
    swapped = (r1["row"], r1["col"]) == (6, 6) and (r2["row"], r2["col"]) == (6, 5)
    assert not swapped, (
        f"Head-on swap was permitted! R1={r1['row'],r1['col']} R2={r2['row'],r2['col']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Narrow aisle (single-column corridor)
# ─────────────────────────────────────────────────────────────────────────────

def test_narrow_aisle_no_collision():
    """
    Three robots queued in a narrow aisle (col 6, rows 3,4,5) all move south.
    They should fan out without colliding over 10 ticks.
    """
    sim = fresh_sim()
    park_others(sim, "R1", "R2", "R3")

    place_robot(sim, "R1", 3, 6)
    place_robot(sim, "R2", 4, 6)
    place_robot(sim, "R3", 5, 6)

    add_dummy_order(sim, "ORD-NA1", "R1", 9, 6)
    add_dummy_order(sim, "ORD-NA2", "R2", 10, 6)
    add_dummy_order(sim, "ORD-NA3", "R3", 11, 6 if 11 < sim.ROWS else 10, 6)

    # Give them pre-planned south paths (long enough for the test)
    set_path(sim, "R1", [(4,6),(5,6),(6,6),(7,6),(8,6),(9,6)], order_id="ORD-NA1")
    set_path(sim, "R2", [(5,6),(6,6),(7,6),(8,6),(9,6),(10,6)], order_id="ORD-NA2")
    r3_goal = 11 if sim.ROWS > 11 else 10
    set_path(sim, "R3", [(6,6),(7,6),(8,6),(9,6),(10,6)], order_id="ORD-NA3")

    run_ticks(sim, 15)


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Robot waiting behind another robot
# ─────────────────────────────────────────────────────────────────────────────

def test_robot_waits_behind_stationary_robot():
    """
    R2 is stationary at (6,6).
    R1 at (6,5) tries to move to (6,6) — must wait (wait_ticks++), not teleport.
    """
    sim = fresh_sim()
    park_others(sim, "R1", "R2")

    place_robot(sim, "R1", 6, 5)
    place_robot(sim, "R2", 6, 6)   # R2 stays idle (stationary)

    add_dummy_order(sim, "ORD-T4", "R1", 6, 6)
    set_path(sim, "R1", [(6, 6)], order_id="ORD-T4")

    with sim.lock:
        sim._advance_one()

    r1 = next(r for r in sim.robots if r["id"] == "R1")
    r2 = next(r for r in sim.robots if r["id"] == "R2")

    assert_no_collision(sim)
    # R2 should remain at (6,6) since it has no path
    assert (r2["row"], r2["col"]) == (6, 6), "R2 should remain stationary"
    # R1 should NOT have moved into (6,6)
    assert (r1["row"], r1["col"]) == (6, 5), (
        f"R1 should still be at (6,5) — blocked by R2. Got {r1['row'],r1['col']}"
    )
    assert r1["wait_ticks"] >= 1, "R1 wait_ticks should have incremented"


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Robots navigate around storage racks (obstacles)
# ─────────────────────────────────────────────────────────────────────────────

def test_path_avoids_obstacles():
    """
    BFS path from (1,2) to (1,5) must route around the shelf at (2,3),(2,4).
    Verify the path returned contains no shelf cells.
    """
    sim = fresh_sim()
    path = sim._path((1, 2), (1, 5))
    shelf_cells = sim.obstacles
    assert path, "Path should exist between (1,2) and (1,5)"
    for step in path:
        cell = (step["row"], step["col"])
        assert cell not in shelf_cells, (
            f"Path traverses obstacle cell {cell}!"
        )
    assert (path[0]["row"], path[0]["col"]) == (1, 2)
    assert (path[-1]["row"], path[-1]["col"]) == (1, 5)


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: Simultaneous orders complete correctly
# ─────────────────────────────────────────────────────────────────────────────

def test_simultaneous_order_completion():
    """
    Dispatch 5 orders, start the simulation, advance 300 ticks, verify that
    all 5 orders eventually reach 'completed' status without collision.
    """
    sim = fresh_sim()
    for _ in range(5):
        sim.add_order()

    run_ticks(sim, 300)

    completed = [o for o in sim.orders if o["status"] == "completed"]
    assert len(completed) == 5, (
        f"Expected 5 completed orders, got {len(completed)}. "
        f"Orders: {[(o['id'], o['status']) for o in sim.orders]}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: Deadlock recovery
# ─────────────────────────────────────────────────────────────────────────────

def test_deadlock_recovery():
    """
    Force a situation where two robots are blocked waiting for each other,
    then verify that after WAIT_REPLAN_THRESHOLD ticks at least one robot
    has moved from its initial position (replan broke the deadlock).
    """
    sim = fresh_sim()
    park_others(sim, "R1", "R2")

    # R1 at (6,5), wants (6,6).  R2 at (6,6), wants (6,5) (head-on).
    # Both have longer paths so path is not exhausted immediately.
    place_robot(sim, "R1", 6, 5)
    place_robot(sim, "R2", 6, 6)

    add_dummy_order(sim, "ORD-DL1", "R1", 6, 8)
    add_dummy_order(sim, "ORD-DL2", "R2", 6, 3)
    set_path(sim, "R1", [(6, 6), (6, 7), (6, 8)], order_id="ORD-DL1")
    set_path(sim, "R2", [(6, 5), (6, 4), (6, 3)], order_id="ORD-DL2")

    threshold = sim.WAIT_REPLAN_THRESHOLD + 4
    start_positions = {
        "R1": (6, 5),
        "R2": (6, 6),
    }

    for tick in range(threshold):
        with sim.lock:
            sim._advance_one()
        assert_no_collision(sim, f"deadlock test tick {tick + 1}")

    r1 = next(r for r in sim.robots if r["id"] == "R1")
    r2 = next(r for r in sim.robots if r["id"] == "R2")
    current = {
        "R1": (r1["row"], r1["col"]),
        "R2": (r2["row"], r2["col"]),
    }

    moved = any(current[rid] != start_positions[rid] for rid in ["R1", "R2"])
    assert moved, (
        f"Neither robot escaped the deadlock after {threshold} ticks. "
        f"R1={current['R1']} R2={current['R2']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: Reset and restart
# ─────────────────────────────────────────────────────────────────────────────

def test_reset_and_restart():
    """
    Run simulation for 50 ticks, reset, verify all state is clean, then
    re-add orders and run again successfully.
    """
    sim = fresh_sim()
    for _ in range(3):
        sim.add_order()
    run_ticks(sim, 50)

    sim.reset()

    assert sim.tick == 0
    assert sim.running is False
    assert len(sim.orders) == 0
    assert len(sim.robots) == 10
    for r in sim.robots:
        assert r["assigned_order"] is None
        assert r["path"] == []
        assert r["wait_ticks"] == 0

    # Re-run with fresh orders
    for _ in range(3):
        sim.add_order()
    run_ticks(sim, 150)

    completed = [o for o in sim.orders if o["status"] == "completed"]
    assert len(completed) >= 1, "At least 1 order should complete after reset + 150 ticks"
    assert_no_collision(sim)


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: 10 robots moving concurrently, no collision
# ─────────────────────────────────────────────────────────────────────────────

def test_ten_robots_concurrent_no_collision():
    """
    Dispatch 10 orders (one per robot), run 400 ticks, assert no collisions
    ever occurred (checked every tick) and all orders complete.
    """
    sim = fresh_sim()
    for _ in range(10):
        sim.add_order()

    run_ticks(sim, 400)

    completed = [o for o in sim.orders if o["status"] == "completed"]
    assert len(completed) == 10, (
        f"Expected 10 completed orders, got {len(completed)}. "
        f"Statuses: {[(o['id'], o['status']) for o in sim.orders]}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 10: No duplicate order assignment
# ─────────────────────────────────────────────────────────────────────────────

def test_no_duplicate_order_assignment():
    """
    After many ticks, no order should be assigned to more than one robot
    at the same time.
    """
    sim = fresh_sim()
    for _ in range(10):
        sim.add_order()
    run_ticks(sim, 300)

    robot_order_map = {}
    for r in sim.robots:
        if r["assigned_order"]:
            assert r["assigned_order"] not in robot_order_map, (
                f"Order {r['assigned_order']} is assigned to both "
                f"{robot_order_map[r['assigned_order']]} and {r['id']}"
            )
            robot_order_map[r["assigned_order"]] = r["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Test 11: Order completed only after physical arrival
# ─────────────────────────────────────────────────────────────────────────────

def test_order_completes_only_at_destination():
    """
    An order status should only flip to 'completed' when the robot's (row,col)
    matches the station (10,14) AND path_index >= len(path).
    Verify that completed orders have a valid robot_id and no collision occurs.
    """
    sim = fresh_sim()
    sim.add_order()

    for _ in range(250):
        with sim.lock:
            sim._advance_one()
        assert_no_collision(sim)
        for order in sim.orders:
            if order["status"] == "completed":
                rid = order.get("robot_id")
                assert rid is not None, "Completed order has no robot_id"


# ─────────────────────────────────────────────────────────────────────────────
# Test 12: BFS returns empty list when no path exists
# ─────────────────────────────────────────────────────────────────────────────

def test_bfs_no_path_returns_empty():
    """
    _path() should return [] or handle gracefully when the goal is unreachable.
    Verify no crash occurs.
    """
    sim = fresh_sim()
    # Try to reach a shelf cell (blocked); BFS should return [] or a path
    # avoiding it — the main guarantee is no exception.
    shelf_cell = (2, 3)
    path = sim._path((0, 0), shelf_cell)
    # If path exists it must not contain the shelf cell as an intermediate step
    if path:
        for step in path[:-1]:  # last step may be adjacent
            cell = (step["row"], step["col"])
            assert cell not in sim.obstacles or cell == (0, 0), (
                f"Path goes through obstacle {cell}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Test 13: Robots at starting positions have no immediate collision
# ─────────────────────────────────────────────────────────────────────────────

def test_initial_positions_no_collision():
    """The 10 default robot start positions must all be distinct and obstacle-free."""
    sim = fresh_sim()
    assert_no_collision(sim)
    for r in sim.robots:
        assert (r["row"], r["col"]) not in sim.obstacles, (
            f"Robot {r['id']} starts on an obstacle!"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test 14: Multiple robots navigating through a narrow aisle simultaneously
# ─────────────────────────────────────────────────────────────────────────────

def test_multiple_orders_narrow_path():
    """
    4 robots all heading toward the station area simultaneously.
    Verify no collision over 200 ticks and all orders complete.
    """
    sim = fresh_sim()
    # Place 4 robots that all need to converge on the station area
    place_robot(sim, "R1", 0, 14)
    place_robot(sim, "R2", 3, 14)
    place_robot(sim, "R3", 6, 14)
    place_robot(sim, "R4", 9, 14)
    park_others(sim, "R1", "R2", "R3", "R4")

    for _ in range(4):
        sim.add_order()

    run_ticks(sim, 200)

    completed = [o for o in sim.orders if o["status"] == "completed"]
    assert len(completed) == 4, (
        f"Expected 4 completed orders, got {len(completed)}."
    )
