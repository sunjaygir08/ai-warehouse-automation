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
            "orientation": "north", "status": "idle", "carrying": False,
            "assigned_order": None, "path": [], "path_index": 0,
            "active_ticks": 0, "wait_ticks": 0,
        }

    def _log(self, message):
        self.events.appendleft({"tick": self.tick, "message": message})

    def _path(self, start, goal):
        blocked = self.obstacles
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
        for order in self.orders:
            if order["status"] != "pending":
                continue
            available = [r for r in self.robots if r["assigned_order"] is None]
            if not available:
                break
            robot = min(available, key=lambda r: abs(r["row"] - order["pick"]["row"])
                        + abs(r["col"] - order["pick"]["col"]))
            path = self._path((robot["row"], robot["col"]),
                              (order["pick"]["row"], order["pick"]["col"]))
            if not path:
                continue
            robot["assigned_order"] = order["id"]
            robot["path"] = path[1:]
            robot["path_index"] = 0
            robot["status"] = "moving"
            order["status"] = "to_pick"
            order["robot_id"] = robot["id"]
            self._log(f"{order['id']} assigned to {robot['id']}")

    def _advance_one(self):
        self.tick += 1
        self._assign_orders()
        for robot in self.robots:
            if robot["assigned_order"] is None:
                continue
            robot["active_ticks"] += 1
            order = next(o for o in self.orders
                         if o["id"] == robot["assigned_order"])
            if robot["path_index"] < len(robot["path"]):
                old = (robot["row"], robot["col"])
                target = robot["path"][robot["path_index"]]
                robot["row"], robot["col"] = target["row"], target["col"]
                robot["path_index"] += 1
                if target["row"] != old[0]:
                    robot["orientation"] = "south" if target["row"] > old[0] else "north"
                elif target["col"] != old[1]:
                    robot["orientation"] = "east" if target["col"] > old[1] else "west"
                continue
            if order["status"] == "to_pick":
                order["status"] = "to_station"
                robot["carrying"] = True
                robot["status"] = "carrying"
                robot["path"] = self._path((robot["row"], robot["col"]),
                                            (self.STATION["row"], self.STATION["col"]))[1:]
                robot["path_index"] = 0
                self._log(f"{robot['id']} picked {order['id']}")
            else:
                order["status"] = "completed"
                order["completed_tick"] = self.tick
                robot["assigned_order"] = None
                robot["carrying"] = False
                robot["status"] = "idle"
                robot["path"] = []
                robot["path_index"] = 0
                self._log(f"{order['id']} delivered by {robot['id']}")
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
