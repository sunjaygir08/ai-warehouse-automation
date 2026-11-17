from flask import Flask, render_template, request, jsonify, flash, redirect, url_for
import threading
import random
import time
from datetime import datetime
from collections import deque

app = Flask(__name__)
app.secret_key = "smart_warehouse_secret_2024"

# ─────────────────────────────────────────────
# Warehouse Configuration (Single Source of Truth)
# ─────────────────────────────────────────────

WAREHOUSE_CONFIG = {
    "grid": {"rows": 12, "cols": 16},
    # Charging station: upper-left, 2 positions at row=0, col=0 and col=1
    "charging": [{"row": 0, "col": 0}, {"row": 0, "col": 1}],
    # Delivery station: bottom-right
    "station": {"row": 11, "col": 15},
    # 24 racks in 12 pairs (3 pairs per row x 4 rows), starting at col=3
    # Rows 1, 4, 7, 10
    # Cols (3,4), (7,8), (11,12)
    # 2 empty cells between pairs horizontally (cols 5-6, 9-10)
    # 2 empty cells between pair rows vertically (rows 2-3, 5-6, 8-9)
    "shelves": [
        # Row 1
        {"id": "RACK-01", "row": 1, "col": 3, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-02", "row": 1, "col": 4, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-03", "row": 1, "col": 7, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-04", "row": 1, "col": 8, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-05", "row": 1, "col": 11, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-06", "row": 1, "col": 12, "levels": 3, "status": "AVAILABLE"},
        # Row 4
        {"id": "RACK-07", "row": 4, "col": 3, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-08", "row": 4, "col": 4, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-09", "row": 4, "col": 7, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-10", "row": 4, "col": 8, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-11", "row": 4, "col": 11, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-12", "row": 4, "col": 12, "levels": 3, "status": "AVAILABLE"},
        # Row 7
        {"id": "RACK-13", "row": 7, "col": 3, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-14", "row": 7, "col": 4, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-15", "row": 7, "col": 7, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-16", "row": 7, "col": 8, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-17", "row": 7, "col": 11, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-18", "row": 7, "col": 12, "levels": 3, "status": "AVAILABLE"},
        # Row 10
        {"id": "RACK-19", "row": 10, "col": 3, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-20", "row": 10, "col": 4, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-21", "row": 10, "col": 7, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-22", "row": 10, "col": 8, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-23", "row": 10, "col": 11, "levels": 3, "status": "AVAILABLE"},
        {"id": "RACK-24", "row": 10, "col": 12, "levels": 3, "status": "AVAILABLE"},
    ],
    # Robot start positions: beside charging station (row 0, cols 2-6)
    "robot_starts": [
        (0, 2), (0, 3), (0, 4), (0, 5), (0, 6)
    ],
}

# Battery configuration
BATTERY_CONFIG = {
    "full": 100,
    "drain_per_move": 1.5,       # % per movement step
    "low_threshold": 20,          # % - warn, prevent new assignments
    "critical_threshold": 10,     # % - force return to charge
    "charge_rate": 3.0,           # % per tick while charging
    "min_to_resume": 80,          # % to return to AVAILABLE from charging
}


class WarehouseSimulation:
    ROWS = WAREHOUSE_CONFIG["grid"]["rows"]
    COLS = WAREHOUSE_CONFIG["grid"]["cols"]
    STATION = WAREHOUSE_CONFIG["station"]
    CHARGING = WAREHOUSE_CONFIG["charging"]
    SHELVES = WAREHOUSE_CONFIG["shelves"]
    STARTS = WAREHOUSE_CONFIG["robot_starts"]

    # Maximum ticks a robot waits before forcing a replan
    WAIT_REPLAN_THRESHOLD = 6
    # Maximum ticks in a deadlock cycle before breaking by priority sacrifice
    DEADLOCK_BREAK_THRESHOLD = 14

    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    @property
    def obstacles(self):
        return {(s["row"], s["col"]) for s in self.SHELVES}

    @property
    def shelf_map(self):
        """Returns dict keyed by (row,col) -> shelf dict."""
        return {(s["row"], s["col"]): s for s in self.SHELVES}

    def reset(self):
        with getattr(self, "lock", threading.RLock()):
            self.running = False
            self.speed = 1
            self.tick = 0
            self.next_order = 1
            self.orders = []
            self.events = deque(maxlen=30)
            self.last_advance = time.monotonic()
            # Reset shelves to AVAILABLE
            for shelf in self.SHELVES:
                shelf["status"] = "AVAILABLE"
            self.robots = [
                self._robot(i + 1, row, col)
                for i, (row, col) in enumerate(self.STARTS)
            ]
            self._log("Simulation reset")

    def _robot(self, robot_id, row, col):
        return {
            "id": f"R{robot_id}", "row": row, "col": col,
            "home": (row, col),
            "orientation": "south", "status": "idle", "carrying": False,
            "assigned_order": None, "path": [], "path_index": 0,
            "active_ticks": 0, "wait_ticks": 0,
            # Battery system
            "battery": BATTERY_CONFIG["full"],
            "charging": False,
            "charge_target": None,   # charging station cell robot is heading to
            "destination_rack": None,  # RACK-xx id of current destination
        }

    def _log(self, message):
        self.events.appendleft({"tick": self.tick, "message": message})

    # ─────────────────────────────────────────────
    # BFS Pathfinding
    # ─────────────────────────────────────────────

    def _path(self, start, goal, extra_blocked=None):
        """BFS from start→goal avoiding shelf obstacles + optional extra_blocked cells."""
        blocked = self.obstacles
        if extra_blocked:
            blocked = blocked | set(extra_blocked)

        # If start is in blocked (shouldn't happen), remove it so the robot can escape
        blocked.discard(start)

        queue = deque([start])
        previous = {start: None}
        while queue:
            current = queue.popleft()
            if current == goal:
                path = []
                while current is not None:
                    path.append({"row": current[0], "col": current[1]})
                    current = previous[current]
                return list(reversed(path))
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nxt = (current[0] + dr, current[1] + dc)
                if (0 <= nxt[0] < self.ROWS and 0 <= nxt[1] < self.COLS
                        and nxt not in blocked and nxt not in previous):
                    previous[nxt] = current
                    queue.append(nxt)
        return []

    def _path_distance(self, start, goal):
        """Returns BFS distance (number of steps), or infinity if unreachable."""
        if start == goal:
            return 0
        path = self._path(start, goal)
        return len(path) - 1 if path else float('inf')

    def _nearest_pick_cell(self, shelf_row, shelf_col):
        """Return nearest walkable adjacent cell for a rack."""
        candidates = [
            (shelf_row, shelf_col - 1),
            (shelf_row, shelf_col + 1),
            (shelf_row - 1, shelf_col),
            (shelf_row + 1, shelf_col),
        ]
        for cell in candidates:
            if (cell not in self.obstacles
                    and 0 <= cell[0] < self.ROWS and 0 <= cell[1] < self.COLS):
                return cell
        return None

    def _occupied_cells(self, exclude_id=None):
        """Return set of (row, col) for every robot except the excluded one."""
        return {
            (r["row"], r["col"])
            for r in self.robots
            if r["id"] != exclude_id
        }

    def _available_charging_slot(self, exclude_robot_id=None):
        """Find an available charging position not already claimed by another robot."""
        claimed = set()
        for r in self.robots:
            if r["id"] != exclude_robot_id and r.get("charge_target"):
                claimed.add(tuple(r["charge_target"]) if isinstance(r["charge_target"], (list, tuple)) else
                           (r["charge_target"]["row"], r["charge_target"]["col"]))
        for dock in self.CHARGING:
            cell = (dock["row"], dock["col"])
            if cell not in claimed:
                return cell
        return None

    # ─────────────────────────────────────────────
    # Order Assignment (Improved BFS-Distance Based)
    # ─────────────────────────────────────────────

    def add_order(self):
        with self.lock:
            order_id = f"ORD-{self.next_order:03d}"
            self.next_order += 1

            # Find an available rack
            available_rack = None
            for shelf in self.SHELVES:
                if shelf["status"] == "AVAILABLE":
                    available_rack = shelf
                    break

            if not available_rack:
                self._log(f"{order_id} rejected - no available racks")
                # Still create the order but mark pending
                order = {
                    "id": order_id, "status": "no_rack", "created_tick": self.tick,
                    "completed_tick": None,
                    "pick": {"row": 0, "col": 0},
                    "robot_id": None, "rack_id": None,
                }
                self.orders.append(order)
                return order_id

            pick_cell = self._nearest_pick_cell(available_rack["row"], available_rack["col"])
            if not pick_cell:
                self._log(f"{order_id} rejected - rack {available_rack['id']} has no accessible cell")
                return order_id

            order = {
                "id": order_id, "status": "pending", "created_tick": self.tick,
                "completed_tick": None,
                "pick": {"row": pick_cell[0], "col": pick_cell[1]},
                "robot_id": None,
                "rack_id": available_rack["id"],
            }
            self.orders.append(order)
            self._assign_orders()
            self._log(f"{order_id} created → {available_rack['id']}")
            return order_id

    def _assign_orders(self):
        """Assign pending orders to idle robots, using BFS route distance for nearest selection."""
        for order in self.orders:
            if order["status"] != "pending":
                continue

            # Find rack for this order
            rack_id = order.get("rack_id")
            rack = None
            if rack_id:
                rack = next((s for s in self.SHELVES if s["id"] == rack_id), None)
            if rack is None or rack["status"] not in ("AVAILABLE",):
                continue

            # Find available robots (not assigned, not charging critically, battery > low threshold)
            available = [
                r for r in self.robots
                if r["assigned_order"] is None
                and not r["charging"]
                and r["battery"] > BATTERY_CONFIG["low_threshold"]
                and r["status"] != "charging"
            ]
            if not available:
                break

            pick_goal = (order["pick"]["row"], order["pick"]["col"])

            # Select nearest robot by actual BFS distance
            robot = min(
                available,
                key=lambda r: self._path_distance((r["row"], r["col"]), pick_goal)
            )

            # Avoid current positions of other robots when planning
            others = self._occupied_cells(exclude_id=robot["id"])
            path = self._path(
                (robot["row"], robot["col"]),
                pick_goal,
                extra_blocked=others
            )
            if not path:
                # Fallback: plan without extra blocked (might still work later)
                path = self._path(
                    (robot["row"], robot["col"]),
                    pick_goal
                )
            if not path:
                continue

            robot["assigned_order"] = order["id"]
            robot["path"] = path[1:]
            robot["path_index"] = 0
            robot["status"] = "moving"
            robot["wait_ticks"] = 0
            robot["destination_rack"] = rack_id
            order["status"] = "to_pick"
            order["robot_id"] = robot["id"]

            # Reserve the rack
            rack["status"] = "RESERVED"

            self._log(f"{order['id']} assigned to {robot['id']} → {rack_id}")

    # ─────────────────────────────────────────────
    # Battery Management
    # ─────────────────────────────────────────────

    def _send_robot_to_charge(self, robot):
        """Send a low-battery robot to an available charging station."""
        charge_cell = self._available_charging_slot(exclude_robot_id=robot["id"])
        if not charge_cell:
            # All docks occupied, wait
            return False

        others = self._occupied_cells(exclude_id=robot["id"])
        path = self._path(
            (robot["row"], robot["col"]),
            charge_cell,
            extra_blocked=others
        )
        if not path:
            path = self._path((robot["row"], robot["col"]), charge_cell)
        if not path:
            return False

        robot["charge_target"] = {"row": charge_cell[0], "col": charge_cell[1]}
        robot["path"] = path[1:]
        robot["path_index"] = 0
        robot["status"] = "charging_transit"
        robot["wait_ticks"] = 0
        self._log(f"{robot['id']} low battery ({robot['battery']:.0f}%) → charging")
        return True

    # ─────────────────────────────────────────────
    # Coordinated Multi-Robot Tick (Collision-Free)
    # ─────────────────────────────────────────────

    def _advance_one(self):
        """
        Centralized movement coordinator. All robot move proposals are built
        simultaneously, conflict-checked, and applied atomically so that:
          • No two robots ever share the same cell on the same tick.
          • No head-on edge-swap (A: X→Y while B: Y→X) is allowed.
          • Waiting robots increment wait_ticks and replan when stuck too long.
          • Deadlocks are detected and broken by priority.
        """
        self.tick += 1
        self._assign_orders()

        # ── 1. Build current occupation map  ──────────────────────────────────
        occupied = {(r["row"], r["col"]): r["id"] for r in self.robots}

        # ── 2. Build move proposals  ──────────────────────────────────────────
        proposals = {}
        for robot in self.robots:
            if robot["path_index"] >= len(robot["path"]):
                proposals[robot["id"]] = None
                continue
            target = robot["path"][robot["path_index"]]
            proposals[robot["id"]] = (
                (robot["row"], robot["col"]),
                (target["row"], target["col"])
            )

        # ── 3. Iterative conflict resolution  ────────────────────────────────────
        moving_ids = {rid for rid, p in proposals.items() if p is not None}

        priority = {r["id"]: (-r.get("wait_ticks", 0), int(r["id"][1:]))
                    for r in self.robots}

        changed = True
        while changed:
            changed = False

            intending = {rid: proposals[rid] for rid in moving_ids}

            target_to_movers: dict = {}
            for rid, (fc, tc) in intending.items():
                target_to_movers.setdefault(tc, []).append(rid)

            for tc, rids in target_to_movers.items():
                if len(rids) > 1:
                    rids_sorted = sorted(rids, key=lambda r: priority[r])
                    for loser in rids_sorted[1:]:
                        moving_ids.discard(loser)
                        changed = True

            intending = {rid: proposals[rid] for rid in moving_ids}
            edge_set = {(fc, tc): rid for rid, (fc, tc) in intending.items()}
            for rid, (fc, tc) in list(intending.items()):
                reverse = (tc, fc)
                if reverse in edge_set:
                    other = edge_set[reverse]
                    if priority[rid] > priority[other]:
                        moving_ids.discard(rid)
                        changed = True

            intending = {rid: proposals[rid] for rid in moving_ids}
            for rid, (fc, tc) in list(intending.items()):
                if rid not in moving_ids:
                    continue
                if tc in occupied:
                    occupant_id = occupied[tc]
                    if occupant_id not in moving_ids:
                        moving_ids.discard(rid)
                        changed = True

        # Build final approved/claimed maps
        approved = {}
        for robot in self.robots:
            rid = robot["id"]
            if rid in moving_ids and proposals[rid] is not None:
                approved[rid] = proposals[rid][1]  # to_cell
                robot["wait_ticks"] = 0
            else:
                approved[rid] = None
                if proposals[rid] is not None:
                    robot["wait_ticks"] = robot.get("wait_ticks", 0) + 1

        # ── 5. Apply approved moves & state transitions  ────────────────
        for robot in self.robots:
            rid = robot["id"]
            to_cell = approved.get(rid)

            if to_cell is not None:
                old = (robot["row"], robot["col"])
                robot["row"], robot["col"] = to_cell
                robot["path_index"] += 1
                # Update orientation
                if to_cell[0] != old[0]:
                    robot["orientation"] = "south" if to_cell[0] > old[0] else "north"
                elif to_cell[1] != old[1]:
                    robot["orientation"] = "east" if to_cell[1] > old[1] else "west"

                # Drain battery on movement (not while at charger)
                if not robot["charging"]:
                    robot["battery"] = max(0, robot["battery"] - BATTERY_CONFIG["drain_per_move"])

            # ── Battery charging logic ──
            if robot["status"] == "charging":
                robot["battery"] = min(BATTERY_CONFIG["full"],
                                       robot["battery"] + BATTERY_CONFIG["charge_rate"])
                if robot["battery"] >= BATTERY_CONFIG["min_to_resume"]:
                    robot["charging"] = False
                    robot["charge_target"] = None
                    robot["status"] = "idle"
                    robot["path"] = []
                    robot["path_index"] = 0
                    self._log(f"{robot['id']} fully charged ({robot['battery']:.0f}%) → idle")
                continue

            # ── Charging transit: robot heading to charger ──
            if robot["status"] == "charging_transit":
                if robot["path_index"] >= len(robot["path"]):
                    # Arrived at charger
                    robot["charging"] = True
                    robot["status"] = "charging"
                    robot["path"] = []
                    robot["path_index"] = 0
                    robot["wait_ticks"] = 0
                    self._log(f"{robot['id']} started charging")
                continue

            # ── Critical battery: force return to charge ──
            if (robot["battery"] <= BATTERY_CONFIG["critical_threshold"]
                    and not robot["charging"]
                    and robot["status"] not in ("charging", "charging_transit")):
                # Release any current order
                if robot["assigned_order"]:
                    order = next((o for o in self.orders if o["id"] == robot["assigned_order"]), None)
                    if order and order["status"] in ("to_pick", "to_station"):
                        order["status"] = "pending"
                        order["robot_id"] = None
                    robot["assigned_order"] = None
                    if robot.get("destination_rack"):
                        rack = next((s for s in self.SHELVES if s["id"] == robot["destination_rack"]), None)
                        if rack:
                            rack["status"] = "AVAILABLE"
                    robot["destination_rack"] = None
                self._send_robot_to_charge(robot)
                continue

            # ── Normal unassigned / returning robot ──
            if robot["assigned_order"] is None:
                if robot["path_index"] >= len(robot["path"]):
                    if robot["status"] not in ("charging", "charging_transit"):
                        robot["status"] = "idle"
                    robot["path"] = []
                    robot["path_index"] = 0
                # Check if low battery and idle → go charge
                if (robot["status"] == "idle"
                        and robot["battery"] <= BATTERY_CONFIG["low_threshold"]
                        and not robot["charging"]):
                    self._send_robot_to_charge(robot)
                continue

            robot["active_ticks"] += 1
            order = next(
                (o for o in self.orders if o["id"] == robot["assigned_order"]),
                None
            )
            if order is None:
                robot["assigned_order"] = None
                robot["destination_rack"] = None
                continue

            # Check if path fully traversed → handle order state machine
            if robot["path_index"] >= len(robot["path"]):
                if order["status"] == "to_pick":
                    order["status"] = "to_station"
                    robot["carrying"] = True
                    robot["status"] = "carrying"
                    # Update rack status to OCCUPIED
                    rack_id = order.get("rack_id")
                    if rack_id:
                        rack = next((s for s in self.SHELVES if s["id"] == rack_id), None)
                        if rack:
                            rack["status"] = "OCCUPIED"
                    # Plan path to delivery station
                    others = self._occupied_cells(exclude_id=rid)
                    path = self._path(
                        (robot["row"], robot["col"]),
                        (self.STATION["row"], self.STATION["col"]),
                        extra_blocked=others
                    )
                    if not path:
                        path = self._path(
                            (robot["row"], robot["col"]),
                            (self.STATION["row"], self.STATION["col"])
                        )
                    robot["path"] = path[1:] if path else []
                    robot["path_index"] = 0
                    robot["wait_ticks"] = 0
                    self._log(f"{robot['id']} picked from {rack_id or 'rack'}")

                elif order["status"] == "to_station":
                    order["status"] = "completed"
                    order["completed_tick"] = self.tick
                    robot["assigned_order"] = None
                    robot["carrying"] = False
                    # Release rack
                    rack_id = order.get("rack_id")
                    if rack_id:
                        rack = next((s for s in self.SHELVES if s["id"] == rack_id), None)
                        if rack:
                            rack["status"] = "AVAILABLE"
                    robot["destination_rack"] = None
                    self._log(f"{order['id']} delivered by {robot['id']}")

                    # Return to home
                    home = robot.get("home", (robot["row"], robot["col"]))
                    if home != (robot["row"], robot["col"]):
                        others = self._occupied_cells(exclude_id=rid)
                        path = self._path(
                            (robot["row"], robot["col"]),
                            home,
                            extra_blocked=others
                        )
                        if not path:
                            path = self._path((robot["row"], robot["col"]), home)
                        if path and len(path) > 1:
                            robot["path"] = path[1:]
                            robot["path_index"] = 0
                            robot["status"] = "returning"
                            robot["wait_ticks"] = 0
                        else:
                            robot["status"] = "idle"
                            robot["path"] = []
                            robot["path_index"] = 0
                    else:
                        robot["status"] = "idle"
                        robot["path"] = []
                        robot["path_index"] = 0

        # ── 6. Deadlock / prolonged-wait replan  ─────────────────────────────
        for robot in self.robots:
            wt = robot.get("wait_ticks", 0)
            if wt < self.WAIT_REPLAN_THRESHOLD:
                continue
            if robot["path_index"] >= len(robot["path"]):
                continue

            goal_step = robot["path"][-1]
            goal = (goal_step["row"], goal_step["col"])
            others = self._occupied_cells(exclude_id=robot["id"])

            new_path = self._path(
                (robot["row"], robot["col"]), goal, extra_blocked=others
            )
            if new_path and len(new_path) > 1:
                robot["path"] = new_path[1:]
                robot["path_index"] = 0
                robot["wait_ticks"] = 0
                self._log(f"{robot['id']} replanned (waited {wt} ticks)")
            elif wt >= self.DEADLOCK_BREAK_THRESHOLD:
                new_path = self._path(
                    (robot["row"], robot["col"]), goal
                )
                if new_path and len(new_path) > 1:
                    robot["path"] = new_path[1:]
                    robot["path_index"] = 0
                    robot["wait_ticks"] = 0
                    self._log(f"{robot['id']} deadlock-break replan")

        self._assign_orders()

    def advance(self):
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_advance
            self.last_advance = now
            if self.running:
                for _ in range(min(10, int(elapsed * 4 * self.speed))):
                    self._advance_one()

    def set_running(self, running):
        with self.lock:
            self.running = running
            self.last_advance = time.monotonic()
            self._log("Simulation started" if running else "Simulation paused")

    def state(self):
        self.advance()
        with self.lock:
            completed = [o for o in self.orders if o["status"] == "completed"]
            total = len(self.orders)
            available_ticks = max(1, self.tick * len(self.robots))
            return {
                "grid": {"rows": self.ROWS, "cols": self.COLS},
                "obstacles": list(self.obstacles),
                "shelves": self.SHELVES,
                "station": self.STATION,
                "charging": self.CHARGING,
                "robots": self.robots,
                "orders": self.orders,
                "tick": self.tick,
                "running": self.running,
                "speed": self.speed,
                "battery_config": BATTERY_CONFIG,
                "reservations": [
                    {"row": p["row"], "col": p["col"], "robot_id": r["id"]}
                    for r in self.robots for p in r["path"][r["path_index"]:]
                ],
                "metrics": {
                    "completed": len(completed), "total": total,
                    "pending": total - len(completed),
                    "efficiency": round(len(completed) / total * 100, 1) if total else 0,
                    "utilization": round(sum(r["active_ticks"] for r in self.robots)
                                        / available_ticks * 100, 1),
                    "average_cycle": round(sum(o["completed_tick"] - o["created_tick"]
                                               for o in completed) / len(completed), 1)
                    if completed else 0,
                },
                "events": list(self.events),
            }


simulation_state = WarehouseSimulation()

# ─────────────────────────────────────────────
#  Dummy data generators
# ─────────────────────────────────────────────

def get_dashboard_data():
    return {
        "total_robots"      : 5,
        "active_robots"     : random.randint(2, 5),
        "idle_robots"       : random.randint(0, 2),
        "total_orders"      : random.randint(80, 120),
        "completed_orders"  : random.randint(60, 100),
        "pending_orders"    : random.randint(5, 20),
        "system_efficiency" : round(random.uniform(82, 98), 1),
        "avg_completion"    : round(random.uniform(4.2, 9.8), 1),
        "avg_utilization"   : round(random.uniform(70, 95), 1),
        "warehouse_capacity": 500,
        "current_inventory" : random.randint(300, 480),
        "items_delivered"   : random.randint(200, 400),
        "last_updated"      : datetime.now().strftime("%H:%M:%S"),
        "hourly_throughput" : [random.randint(10, 40) for _ in range(12)],
        "robot_utilization" : [round(random.uniform(60, 98), 1) for _ in range(5)],
        "order_status"      : {
            "completed" : random.randint(60, 90),
            "pending"   : random.randint(5, 15),
            "failed"    : random.randint(0, 5),
        },
    }

# ─────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard():
    data = get_dashboard_data()
    return render_template("dashboard.html", data=data)


@app.route("/api/dashboard-refresh")
def dashboard_refresh():
    """AJAX endpoint – returns fresh dummy stats as JSON."""
    return jsonify(get_dashboard_data())


@app.route("/simulation")
def simulation():
    return render_template("simulation.html")


@app.route("/api/simulation/state")
def simulation_state_api():
    return jsonify(simulation_state.state())


@app.route("/api/simulation/start", methods=["POST"])
def simulation_start():
    simulation_state.set_running(True)
    return jsonify(simulation_state.state())


@app.route("/api/simulation/pause", methods=["POST"])
def simulation_pause():
    simulation_state.set_running(False)
    return jsonify(simulation_state.state())


@app.route("/api/simulation/reset", methods=["POST"])
def simulation_reset():
    simulation_state.reset()
    return jsonify(simulation_state.state())


@app.route("/api/simulation/step", methods=["POST"])
def simulation_step():
    with simulation_state.lock:
        simulation_state._advance_one()
    return jsonify(simulation_state.state())


@app.route("/api/simulation/speed", methods=["POST"])
def simulation_speed():
    payload = request.get_json(silent=True) or {}
    try:
        speed = int(payload.get("speed", 1))
    except (TypeError, ValueError):
        return jsonify({"error": "speed must be an integer"}), 400
    if speed not in (1, 2, 3, 5):
        return jsonify({"error": "speed must be one of 1, 2, 3 or 5"}), 400
    simulation_state.speed = speed
    return jsonify(simulation_state.state())


@app.route("/api/simulation/order", methods=["POST"])
def simulation_order():
    order_id = simulation_state.add_order()
    return jsonify(simulation_state.state() | {"order_id": order_id})


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name    = request.form.get("name", "").strip()
        email   = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()

        errors = []
        if not name:
            errors.append("Name is required.")
        if not email or "@" not in email:
            errors.append("A valid email is required.")
        if not message:
            errors.append("Message cannot be empty.")

        if errors:
            return render_template("contact.html", errors=errors,
                                   form_data={"name": name, "email": email, "message": message})

        flash("Message sent successfully! We'll get back to you soon.", "success")
        return redirect(url_for("contact"))

    return render_template("contact.html", errors=[], form_data={})


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True)
