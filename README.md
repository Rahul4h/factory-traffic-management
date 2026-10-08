# 🚦 Factory Traffic Management System

An **event-driven traffic-control system** for internal roads inside a garment manufacturing facility. The system receives vehicle-detection events, maintains traffic queues, controls signals through a safe state machine, handles emergency preemption, supports manual override, tolerates device failures, persists state across restarts, and exposes a live dashboard.

> **Design principle:** This is not CRUD. It is a small **safety-critical control system**. Traffic decisions are made by a pure domain engine, isolated from HTTP, database, and any specific IoT transport.

---

## 📋 Table of Contents

- [Features](#-features)
- [Architecture](#-architecture)
- [Quick Start](#-quick-start)
- [API Reference](#-api-reference)
- [Traffic-Control Algorithm](#-traffic-control-algorithm)
- [State Transitions](#-state-transitions)
- [Failure Handling](#-failure-handling)
- [Persistence & Recovery](#-persistence--recovery)
- [Demonstration Scenarios](#-demonstration-scenarios)
- [Project Structure](#-project-structure)
- [Assumptions / Questions / Requirement Issues](#-assumptions--questions--requirement-issues)
- [Architectural Decisions](#-architectural-decisions)
- [Incomplete Features & Roadmap](#-incomplete-features--roadmap)
- [AI / Tool Usage](#-ai--tool-usage)

---

## ✨ Features

| Category | Feature |
|---|---|
| **Safety** | GREEN → YELLOW → ALL_RED → GREEN state machine; conflicting phases never both GREEN |
| **Scheduling** | Priority scoring: queue length + vehicle priority + waiting time |
| **Priority** | EMERGENCY > TRUCK > FORKLIFT > EMPLOYEE_VEHICLE |
| **Anti-starvation** | Waiting time grows unbounded; hysteresis (1.2×) prevents flapping |
| **Emergency** | Immediate preemption via safe transition sequence (capped 5s green) |
| **Manual override** | Command-oriented API, 60s TTL, never bypasses safety |
| **Idempotency** | Duplicate `event_id` → rejected, queue unchanged |
| **Persistence** | SQLite; all important state survives restart |
| **Safe restart** | Forces ALL_RED on boot — never assumes prior GREEN |
| **Desired vs Actual** | Separate engine-desired and controller-confirmed signal state |
| **Controller simulation** | REST-based ACK / OFFLINE / NACK events |
| **Audit log** | Full event history per junction |
| **Dashboard** | Live polling UI with simulation form |



## 🏗️ Architecture

The system follows a **layered architecture**. The core domain logic has **zero dependencies** on Django, HTTP, or the database — it can be unit-tested in isolation.

```
┌─────────────────────────────────────────────┐
│  Presentation Layer                         │
│  templates/dashboard.html (HTML + JS)       │
│  → Polls /status every 1.5s                 │
└──────────────────────┬──────────────────────┘
                       │ HTTP/JSON
┌──────────────────────▼──────────────────────┐
│  API Layer                                  │
│  traffic/views.py + serializers.py          │
│  → DRF endpoints, validation, HTTP codes    │
└──────────────────────┬──────────────────────┘
                       │ function calls
┌──────────────────────▼──────────────────────┐
│  Registry (Persistence Bridge)              │
│  traffic/registry.py                        │
│  → Engine ⇄ DB, threading.RLock per junction│
└──────────────────────┬──────────────────────┘
                       │ Python objects
┌──────────────────────▼──────────────────────┐
│  Domain Layer (PURE)                        │
│  traffic/engine.py                          │
│  → State machine, scoring, safety invariants│
│  → NO Django, NO HTTP, NO DB                │
└─────────────────────────────────────────────┘

Background: traffic/scheduler.py
  → Daemon thread, ticks every 500ms
  → Calls engine.tick(), persists on transition
```

**Key insight:** Because `engine.py` doesn't import Django, you can test the entire traffic-control logic without spinning up HTTP, DB, or frontend. This satisfies the spec's requirement: *"The domain engine should not contain MQTT-specific or HTTP-specific traffic-control rules."*




---

## 🚀 Quick Start

### Prerequisites
- Python **3.10+**
- pip

### Installation

```bash
# 1. Clone
git clone https://github.com/Rahul4h/factory-traffic-management.git
cd factory-traffic-management

# 2. Virtual environment
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Database schema
python manage.py makemigrations traffic
python manage.py migrate

# 5. Bootstrap Junction A
python manage.py shell -c "from traffic.registry import ensure_junction; ensure_junction('A')"

# 6. Run
python manage.py runserver
Access: http://localhost:8000/

The scheduler thread starts automatically with runserver. On boot it forces the junction to ALL_RED for safety and re-evaluates from live queues.

📡 API Reference
Junctions
Method	Endpoint	Description
GET	/api/junctions	List all junctions
GET	/api/junctions/:id	Junction config
POST	/api/junctions/create	Create junction
Status
Method	Endpoint	Description
GET	/api/junctions/:id/status	Live state (mode, phase, stage, signals, queues)
Sensor Events (idempotent)
Method	Endpoint	Description
POST	/api/sensor-events	Vehicle arrival or clear
Arrival request:

json
{
  "event_id": "evt-10001",
  "junction_id": "A",
  "direction": "NORTH",
  "event_type": "VEHICLE_ARRIVED",
  "vehicle_id": "VH-501",
  "vehicle_type": "TRUCK",
  "sequence_no": 1501,
  "timestamp": "2026-10-05T10:15:20Z"
}
Responses:

202 Accepted → {"accepted": true}

200 OK → {"duplicate": true} (same event_id)

400 → validation errors

404 → unknown junction

Manual Control
Method	Endpoint	Description
POST	/api/junctions/:id/commands	Manual override / return to auto
json
{ "command": "MANUAL_GREEN_REQUEST", "direction": "WEST" }
or

json
{ "command": "RETURN_TO_AUTOMATIC" }
Controller Events
Method	Endpoint	Description
POST	/api/controller-events	Simulate ACK / OFFLINE / NACK
json
{
  "command_id": "cmd-8001",
  "junction_id": "A",
  "status": "ACK",
  "actual_state": "GREEN",
  "direction": "EAST"
}
History
Method	Endpoint	Description
GET	/api/junctions/:id/history	Last 200 audit events
🧠 Traffic-Control Algorithm
The engine runs a 3-stage safety state machine per junction. Phase selection happens only during the ALL_RED window.

Phase Selection Priority
text
1. EMERGENCY            → serve the direction of the emergency vehicle
2. MANUAL               → serve the manually requested direction
3. AUTOMATIC SCORING    → highest-scoring phase wins
Automatic Scoring Formula
text
score(phase) = Σ over green directions in phase:
                 queue_length × 10
               + Σ vehicle_priority
               + max_wait_seconds × 0.5
Vehicle priority weights:

Type	Weight
EMERGENCY	100
TRUCK	40
FORKLIFT	20
EMPLOYEE_VEHICLE	5
Anti-Starvation & Anti-Flapping
python
# Idle fairness: both phases empty → alternate
if cur_score == 0 and other_score == 0:
    return other_phase

# Current phase empty, other has traffic
if cur_score == 0 and other_score > 0:
    return other_phase

# Hysteresis: only switch if other is 20% busier
if other_score > cur_score * 1.2:
    return other_phase

return self.phase
Waiting time term grows unbounded → low-priority direction eventually overcomes queue-length disadvantage (prevents starvation).

Hysteresis (1.2×) prevents unnecessary switching and preserves throughput.

🔄 State Transitions
Junction Modes
Mode	Meaning
AUTOMATIC	Engine decides phase from scores
MANUAL	Target phase chosen by operator (60s TTL)
EMERGENCY	Emergency vehicle has priority
DEGRADED	Controller offline or refused commands
Stage Diagram
text
        ┌──────────────────────────────────────────────────┐
        │                                                  │
        ▼                                                  │
  ┌──────────┐  30s   ┌──────────┐  5s   ┌──────────┐  2s │
  │  GREEN   │───────►│  YELLOW  │──────►│ ALL_RED  │─────┘
  │ phase A  │        │ phase A  │       │ (all RED)│
  └──────────┘        └──────────┘       └─────┬────┘
                                                 │
                                                 ▼
                                         choose next phase
Safety Invariants (enforced in code, not by convention)
Conflicting phases never both GREEN. PHASES[phase].green sets are disjoint; GREEN only entered after ALL_RED.

No direct GREEN → conflicting GREEN. Only path: GREEN → YELLOW → ALL_RED → GREEN.

Manual/emergency cannot bypass transitions. They only set the target phase; state machine drives YELLOW → ALL_RED.

Invalid commands → HTTP 400, no state change.

Restart never resumes GREEN. On boot, stage forced to ALL_RED.

🛡️ Failure Handling
The system explicitly separates desired (engine intent) from actual (controller-confirmed) signal state.

Failure	Behavior
ACK received	controller_status = ONLINE, actual_signals updated
ACK delayed	pending_command retained; no assumption of execution
ACK never received	Logged; no auto-retry by default
Controller OFFLINE	mode = DEGRADED; state machine continues internally
Controller reconnects	mode restored to AUTOMATIC/MANUAL/EMERGENCY
Desired ≠ Actual	Both shown separately
Duplicate ACK	Idempotent
NACK	Logged; not assumed executed
Why no auto-retry for GREEN commands? Retrying after a timeout can create a conflicting GREEN if the first command was delivered but ACK was lost. Safety over convenience.

💾 Persistence & Recovery
Stored Entities
Table	Purpose
Junction	ID and per-junction config
ProcessedEvent	Processed event_ids (idempotency)
QueueEntry	Waiting vehicles (survives restart)
JunctionState	Mode, phase, stage, signals, emergency, manual
PendingCommand	Commands sent but not ACKed
History	Audit trail
Restart Safety
On boot, the engine:

Loads persisted queue

Loads persisted state

Forces stage = ALL_RED — never assumes GREEN survived

Scheduler ticks and re-evaluates from live queues

Why? Backend cannot know if a previously-issued GREEN was executed. Assuming it was risks a conflicting GREEN. ALL_RED guarantees clean re-evaluation.

🎬 Demonstration Scenarios
Open the dashboard at http://localhost:8000/

1. Normal Traffic
Send arrivals from NORTH, SOUTH, EAST, WEST. Engine scores phases and serves the busier one.

2. Priority Traffic
Send EMPLOYEE_VEHICLE in EAST and TRUCK in NORTH. Wait one cycle → NORTH_SOUTH serves first.

3. Emergency Preemption
While NORTH/SOUTH is GREEN, send an EMERGENCY from EAST. Observe: current GREEN capped to 5s → YELLOW → ALL_RED → EAST_WEST GREEN.

4. Manual Override
Click MANUAL GREEN for WEST. Observe safe transition. Wait 60s or click AUTO to return.

5. Duplicate Event
bash
curl -X POST http://localhost:8000/api/sensor-events \
  -H "Content-Type: application/json" \
  -d '{"event_id":"evt-dup-1","junction_id":"A","direction":"NORTH","event_type":"VEHICLE_ARRIVED","vehicle_id":"VH-X","vehicle_type":"TRUCK"}'
Repeat same event_id → {"duplicate": true}, queue unchanged.

6. Vehicle Clearance
Send arrival, then VEHICLE_CLEARED for same vehicle. Queue size decreases.

7. Controller Failure
Click OFFLINE → mode = DEGRADED. Click ACK to recover.

8. Restart
Stop server, restart. History and queues remain. Engine boots into ALL_RED.

9. Concurrent Events
Send arrival + emergency + manual command in quick succession. RLock guarantees consistency. Conflicting GREENs never occur.

📂 Project Structure
text
factory-traffic-management/
├── manage.py
├── requirements.txt
├── .gitignore
├── README.md
├── config/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── traffic/
│   ├── apps.py              # Auto-start scheduler
│   ├── engine.py            # ⭐ Pure domain logic
│   ├── registry.py          # Engine ⇄ DB bridge
│   ├── scheduler.py         # Background tick thread
│   ├── models.py            # Persistence
│   ├── serializers.py       # DRF serializers
│   ├── views.py             # API endpoints
│   ├── urls.py
│   ├── admin.py
│   └── migrations/
└── templates/
    └── dashboard.html       # Live UI
⚠️ Assumptions / Questions / Requirement Issues
Unclear Requirements
Issue	Decision
"Conflicting movements"	Assumed N+S vs E+W only (per spec's 2-phase model)
Authoritative timestamp	Server time for scheduling; sensor timestamp stored for audit only
Manual override duration	60 seconds auto-expiry (configurable)
VEHICLE_CLEARED without arrival	Accepted; no-op on queue (prevents negative)
Unknown vehicle type	Coerced to EMPLOYEE_VEHICLE (lowest priority)
Unknown junction	HTTP 404, no state change
Contradictory / Unsafe Requirements
Issue	Decision
Emergency "immediately begin preemption" could imply skipping YELLOW	Interpreted as "begin safe transition immediately," not "skip YELLOW." Safety overrides speed.
Manual override "override" could imply bypassing safety	Manual only changes intent; engine still drives safe transition
Missing Requirements
Issue	Decision
Emergency timeout	Not implemented; would add 5-min safety net
Controller ACK timeout policy	No auto-retry (safety risk)
Duplicate ACK handling	Idempotent
Reconnect policy	On ACK after OFFLINE, mode auto-restores
Technically Problematic
Issue	Decision
sequence_no reliability across sensors	Not authoritative; stored for audit
Out-of-order events	Processed by server-received order
Restart during transition	Force ALL_RED, re-evaluate
Business Decisions
Emergency triggers 5s cap on current GREEN (safety-first).

Manual override expires after 60s.

Conflicting emergencies: first-seen wins; second queues.

🏛️ Architectural Decisions
1. Pure Domain Engine
traffic/engine.py has no Django, HTTP, or DB imports. It's a plain Python class with explicit state. This satisfies the spec's requirement that the domain not depend on transport/database. Unit-testable in isolation.

2. Five-Layer Separation
Frontend → API → Registry → Engine → State — each layer has one responsibility. Handlers never contain traffic rules; rules never touch HTTP.

3. Persistence via Registry (Not in Engine)
The engine is persistence-agnostic. registry.py bridges engine ↔ DB. Swapping SQLite for PostgreSQL only touches the registry, not the engine.

4. Background Tick Thread (Not sleep in handlers)
scheduler.py runs a daemon thread ticking every 500ms. Request handlers never block. The spec explicitly prohibits sleep() in handlers.

5. Per-Junction Serialization (RLock)
Python GIL + threading.RLock around each junction's state = natural serialization. No DB locking overhead. Satisfies the spec's "serialized per-junction processing" option.

6. Idempotency via event_id
Unique event_id in ProcessedEvent table. Duplicate → 200 OK, no queue change. Matches spec explicitly.

7. Safe Restart (Force ALL_RED)
On boot, stage = 'ALL_RED' is forced regardless of persisted state. The engine never assumes a GREEN survived. Satisfies spec: "A restart must not cause the application to blindly assume that previously requested physical signal states are still correct."

8. Desired vs Actual Separation
Engine maintains desired_signals (what it wants) and actual_signals (last ACK). Never conflated. Matches spec: "Sending a command does not automatically mean the physical device successfully executed it."

9. SQLite for Portability
Zero-config, file-based. Sufficient for single-process deployment. Swap to PostgreSQL is a one-line settings.py change.

10. Polling (Not WebSocket)
Polling every 1.5s is sufficient for demo and simpler to reason about. Spec says real-time tech is not mandatory.

🚧 Incomplete Features & Roadmap
Feature	Reason	Priority
MQTT adapter	Optional per spec; REST simulator sufficient	High
Unit tests (pytest)	Time constraint	High
Emergency timeout sweeper	Time constraint	Medium
Command retry with idempotency	Safety analysis pending	Medium
Multi-junction frontend	Hardcoded to Junction A	Low
WebSocket / SSE	Polling works	Low
Auth for manual commands	Out of scope	Low
Next Steps (if 2 more days)
pytest suite covering JunctionEngine

MQTT adapter behind registry's controller port

Emergency timeout background sweeper

Multi-junction routing (URL structure already supports it)

Command retry with controller-side dedup by command_id

🤖 AI / Tool Usage
AI-assisted development tools were used:

Claude (Anthropic): Scaffolding Django boilerplate (models, serializers, project structure), reviewing safety invariants, drafting README sections, and identifying bugs during development.

Not used for: The core traffic-control logic (JunctionEngine state machine, scoring formula, safety invariants, priority weights, hysteresis threshold). These were designed and verified manually by the candidate.

The candidate understands, can explain, and can modify every part of the submitted solution, including the AI-assisted portions.

📜 License
Submitted for assessment purposes. No production license applied.

The system follows a **layered architecture**. The core domain logic has **zero dependencies** on Django, HTTP, or the database — it can be unit-tested in isolation.

👤 Author
Rahul — Backend Developer Intern Candidate
GitHub: @Rahul4h

