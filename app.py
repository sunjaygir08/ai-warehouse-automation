from flask import Flask, render_template, request, jsonify, flash, redirect, url_for
import threading
import random
import time
from datetime import datetime
from collections import deque

app = Flask(__name__)
app.secret_key = "smart_warehouse_secret_2024"

# The simulation is deliberately kept in the Flask process so the browser is
# only a renderer. Coordinates are [row, column] throughout the API.


class WarehouseSimulation:
    ROWS = 12
    COLS = 16
    STATION = {"row": 10, "col": 14}
    CHARGING = [{"row": 10, "col": 1}, {"row": 10, "col": 2}]
    SHELVES = [
        {"row": row, "col": col, "levels": 3}
        for row in (2, 5, 8)
        for col in (3, 4, 7, 8, 11, 12)
    ]
    STARTS = [
        (10, 4), (10, 5), (10, 7), (10, 8), (10, 10), (10, 11),
        (0, 4), (0, 5), (0, 8), (0, 10)
    ]

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

    def reset(self):
        with getattr(self, "lock", threading.RLock()):
            self.running = False
            self.speed = 1
            self.tick = 0
            self.next_order = 1
            self.orders = []
            self.events = deque(maxlen=30)
            self.last_advance = time.monotonic()
            self.robots = [
                self._robot(i + 1, row, col)
                for i, (row, col) in enumerate(self.STARTS)
            ]
            self._log("Simulation reset")

    def _robot(self, robot_id, row, col):
        return {
            "id": f"R{robot_id}", "row": row, "col": col,
            "home": (row, col),
            "orientation": "north", "status": "idle", "carrying": False,
            "assigned_order": None, "path": [], "path_index": 0,
            "active_ticks": 0, "wait_ticks": 0,
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

    def _nearest_pick_cell(self, index):
        shelf = self.SHELVES[index % len(self.SHELVES)]
        candidates = [
            (shelf["row"], shelf["col"] - 1),
            (shelf["row"], shelf["col"] + 1),
            (shelf["row"] - 1, shelf["col"]),
            (shelf["row"] + 1, shelf["col"]),
        ]
        return next(cell for cell in candidates
                    if cell not in self.obstacles
                    and 0 <= cell[0] < self.ROWS and 0 <= cell[1] < self.COLS)

    def _occupied_cells(self, exclude_id=None):
        """Return set of (row, col) for every robot except the excluded one."""
        return {
            (r["row"], r["col"])
            for r in self.robots
            if r["id"] != exclude_id
        }

    # ─────────────────────────────────────────────
    # Order Assignment
    # ─────────────────────────────────────────────

    def add_order(self):
        with self.lock:
            order_id = f"ORD-{self.next_order:03d}"
            self.next_order += 1
            pick = self._nearest_pick_cell(len(self.orders))
            order = {
                "id": order_id, "status": "pending", "created_tick": self.tick,
                "completed_tick": None, "pick": {"row": pick[0], "col": pick[1]},
                "robot_id": None,
            }
            self.orders.append(order)
            self._assign_orders()
            self._log(f"{order_id} created")
            return order_id

    def _assign_orders(self):
        """Assign pending orders to idle robots, planning collision-aware paths."""
        for order in self.orders:
            if order["status"] != "pending":
                continue
            available = [r for r in self.robots if r["assigned_order"] is None]
            if not available:
                break
            robot = min(
                available,
                key=lambda r: abs(r["row"] - order["pick"]["row"])
                              + abs(r["col"] - order["pick"]["col"])
            )
            # Avoid current positions of other robots when planning
            others = self._occupied_cells(exclude_id=robot["id"])
            path = self._path(
                (robot["row"], robot["col"]),
                (order["pick"]["row"], order["pick"]["col"]),
                extra_blocked=others
            )
            if not path:
                # Fallback: plan without extra blocked (might still work later)
                path = self._path(
                    (robot["row"], robot["col"]),
                    (order["pick"]["row"], order["pick"]["col"])
                )
            if not path:
                continue
            robot["assigned_order"] = order["id"]
            robot["path"] = path[1:]
            robot["path_index"] = 0
            robot["status"] = "moving"
            robot["wait_ticks"] = 0
            order["status"] = "to_pick"
            order["robot_id"] = robot["id"]
            self._log(f"{order['id']} assigned to {robot['id']}")

    # ─────────────────────────────────────────────
    # Coordinated Multi-Robot Tick (Collision-Free)
    # ─────────────────────────────────────────────

    def _advance_one(self):
        """
        Centralized movement coordinator.  All robot move proposals are built
        simultaneously, conflict-checked, and applied atomically so that:
          • No two robots ever share the same cell on the same tick.
          • No head-on edge-swap (A: X→Y while B: Y→X) is allowed.
          • Waiting robots increment wait_ticks and replan when stuck too long.
          • Deadlocks are detected and broken by priority.
        """
        self.tick += 1
        self._assign_orders()

        # ── 1. Build current occupation map  ──────────────────────────────────
        # occupied: (row,col) → robot_id  (snapshot before any movement)
        occupied = {(r["row"], r["col"]): r["id"] for r in self.robots}

        # ── 2. Build move proposals  ──────────────────────────────────────────
        # proposals: robot_id → (from_cell, to_cell) | None (stationary/waiting)
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
        #
        # Algorithm: "iterative elimination"
        # 1. Start: every robot with a path proposes its next cell as intended move.
        # 2. Mark all stationary robots as BLOCKED (they don't move).
        # 3. Iteratively cancel moves that conflict until no changes occur:
        #    a. If two robots propose the SAME to_cell: lower priority one waits.
        #    b. If robot A proposes X→Y and robot B proposes Y→X (edge swap): lower priority waits.
        #    c. If a robot's to_cell is currently occupied by a robot that is
        #       NOT approved to leave (i.e., still staying): block the mover.
        # 4. Apply approved moves atomically.
        #
        # This converges because each iteration only removes moves, never adds them.

        # moving_ids: robots that currently intend to move
        moving_ids = {rid for rid, p in proposals.items() if p is not None}

        # Priority lookup: lower tuple = higher priority
        # Longest-waiting robot goes first (-wait_ticks); tie-break by robot ID number
        priority = {r["id"]: (-r.get("wait_ticks", 0), int(r["id"][1:]))
                    for r in self.robots}

        # Iterative elimination loop
        changed = True
        while changed:
            changed = False

            # Collect intended moves for all currently-moving robots
            intending = {rid: proposals[rid] for rid in moving_ids}

            # (a) Cell-claim conflicts: two movers targeting same to_cell
            target_to_movers: dict = {}
            for rid, (fc, tc) in intending.items():
                target_to_movers.setdefault(tc, []).append(rid)

            for tc, rids in target_to_movers.items():
                if len(rids) > 1:
                    # Keep highest-priority mover, cancel others
                    rids_sorted = sorted(rids, key=lambda r: priority[r])
                    for loser in rids_sorted[1:]:
                        moving_ids.discard(loser)
                        changed = True

            # (b) Edge swap conflicts
            intending = {rid: proposals[rid] for rid in moving_ids}
            edge_set = {(fc, tc): rid for rid, (fc, tc) in intending.items()}
            for rid, (fc, tc) in list(intending.items()):
                reverse = (tc, fc)
                if reverse in edge_set:
                    other = edge_set[reverse]
                    # Both robots want to swap — lower priority one waits
                    if priority[rid] > priority[other]:
                        moving_ids.discard(rid)
                        changed = True

            # (c) Target cell occupied by a robot NOT moving away
            intending = {rid: proposals[rid] for rid in moving_ids}
            for rid, (fc, tc) in list(intending.items()):
                if rid not in moving_ids:
                    continue
                if tc in occupied:
                    occupant_id = occupied[tc]
                    if occupant_id not in moving_ids:
                        # Occupant is staying → cannot move in
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
                    # Robot wanted to move but was blocked
                    robot["wait_ticks"] = robot.get("wait_ticks", 0) + 1

        # ── 5. Apply approved moves & order state transitions  ────────────────
        for robot in self.robots:
            rid = robot["id"]
            to_cell = approved.get(rid)

            if to_cell is not None:
                old = (robot["row"], robot["col"])
                robot["row"], robot["col"] = to_cell
                robot["path_index"] += 1
                # Update orientation facing
                if to_cell[0] != old[0]:
                    robot["orientation"] = "south" if to_cell[0] > old[0] else "north"
                elif to_cell[1] != old[1]:
                    robot["orientation"] = "east" if to_cell[1] > old[1] else "west"

            # If returning or unassigned robot
            if robot["assigned_order"] is None:
                if robot["path_index"] >= len(robot["path"]):
                    robot["status"] = "idle"
                    robot["path"] = []
                    robot["path_index"] = 0
                continue

            robot["active_ticks"] += 1
            order = next(
                (o for o in self.orders if o["id"] == robot["assigned_order"]),
                None
            )
            if order is None:
                robot["assigned_order"] = None
                continue

            # Check if path fully traversed → handle order state machine
            if robot["path_index"] >= len(robot["path"]):
                if order["status"] == "to_pick":
                    order["status"] = "to_station"
                    robot["carrying"] = True
                    robot["status"] = "carrying"
                    # Plan path to station, avoiding other robots
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
                    self._log(f"{robot['id']} picked {order['id']}")

                elif order["status"] == "to_station":
                    order["status"] = "completed"
                    order["completed_tick"] = self.tick
                    robot["assigned_order"] = None
                    robot["carrying"] = False
                    self._log(f"{order['id']} delivered by {robot['id']}")

                    # Return to home to vacate the station cell
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
                continue  # no active path, nothing to replan

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
                # Hard deadlock: try planning without any extra blocked
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
                "shelves": self.SHELVES, "station": self.STATION,
                "charging": self.CHARGING, "robots": self.robots,
                "orders": self.orders, "tick": self.tick,
                "running": self.running, "speed": self.speed,
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

        # In a real app you would send an email / save to DB here.
        flash("Message sent successfully! We'll get back to you soon.", "success")
        return redirect(url_for("contact"))

    return render_template("contact.html", errors=[], form_data={})


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True)
