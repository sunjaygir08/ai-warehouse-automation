# ⬡ Smart Warehouse Automation System

**Design, Modelling, and Simulation of an AI-Based Smart Warehouse Automation System for Performance Evaluation and Optimization**

> Dawood University of Engineering & Technology  
> Department of Computer Systems Engineering  
> Course: Modelling & Simulation (4th Semester)  
> Team: Muhammad Ahmed (CSE-007) · Sanjay Gir (CSE-008) · Sanaullah Chauhan (CSE-016)

---

## 📁 Project Structure

```
smart-warehouse/
│
├── .gitattributes          ← Git attribute and line-ending configurations
├── .gitignore              ← Ignores virtual environments, pycache & temporary files
├── app.py                  ← Flask backend (routes + simulation engine + data)
├── requirements.txt        ← Python dependencies
├── README.md               ← Project documentation
│
├── static/
│   ├── css/
│   │   └── style.css       ← All styling (futuristic warehouse theme)
│   ├── js/
│   │   ├── script.js       ← Shared navigation and dashboard logic
│   │   └── simulation3d.js ← Three.js renderer for the backend simulation
│   └── images/
│       └── .gitkeep        ← Project screenshot & media directory
│
└── templates/
    ├── index.html          ← Home page
    ├── dashboard.html      ← Live KPIs + charts
    ├── simulation.html     ← Backend-connected 3D warehouse simulation
    ├── about.html          ← Project info + team
    └── contact.html        ← Contact form (Flask POST)
```

---

## ⚙️ Setup Instructions

### 1. Install Python
Make sure Python 3.9 or higher is installed:
```bash
python --version
```
Download from: https://python.org

---

### 2. Create a Virtual Environment (Recommended)
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

---

### 3. Install Flask
```bash
pip install -r requirements.txt
```
Or manually:
```bash
pip install flask
```

---

### 4. Run the Project
```bash
python app.py
```

You should see:
```
 * Running on http://127.0.0.1:5000
 * Debug mode: on
```

---

### 5. Open in Browser
Visit: **http://127.0.0.1:5000**

---

## 🌐 Pages

| URL             | Page        | Description                            |
|-----------------|-------------|----------------------------------------|
| `/`             | Home        | Hero, features, how it works           |
| `/dashboard`    | Dashboard   | KPI cards, charts, robot fleet table   |
| `/simulation`   | Simulation  | Live canvas animation of robots        |
| `/about`        | About       | Project details, tech stack, team      |
| `/contact`      | Contact     | Form with Flask POST handling          |

---

## 🔧 Tech Stack

| Layer      | Technology         |
|------------|--------------------|
| Backend    | Python 3 + Flask   |
| Frontend   | HTML5, CSS3, JS    |
| Charts     | Chart.js (CDN)     |
| Visualization | Three.js (WebGL) |
| Fonts      | Orbitron + Exo 2   |
| Algorithm  | BFS Pathfinding    |

---

## 📊 Key Features

- **5 KPI Cards** — active robots, orders, efficiency, inventory
- **3 Charts** — hourly throughput (line), order status (doughnut), robot utilisation (bar)
- **Live Simulation** — interactive Three.js warehouse with shelves, picking station,
  charging docks, robot selection, paths, reservations, and camera controls
- **Backend simulation** — Flask owns deterministic BFS paths, orders, ticks, speed,
  robot state, and calculated performance metrics
- **AJAX Refresh** — dashboard refreshes data without page reload
- **Contact Form** — Flask POST with validation and flash messages
- **Responsive** — works on mobile and desktop

---

## 🚀 Commands Summary

```bash
# Clone / enter directory
cd smart-warehouse

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Mac/Linux)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run server
python app.py

# Open browser
# http://127.0.0.1:5000
```

---

## 📌 Notes

- The dashboard still uses the original demo data generators; the simulation page
  uses a separate deterministic state engine.
- Click **"↻ Refresh Data"** on the dashboard to fetch new live stats via AJAX.
- The simulation is controlled by Flask through `/api/simulation/*`; the browser only
  renders state and interpolates robot movement. Three.js is loaded from jsDelivr,
  so an internet connection is needed for the 3D module unless it is vendored.
- Contact form messages are validated server-side but **not emailed** (extend with Flask-Mail if needed).

---

*Built for the Modelling & Simulation CEP — DUET 2024/25*
