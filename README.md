# 🚦 Factory Traffic Management System

[![Django](https://img.shields.io/badge/Django-5.0+-092E20?style=flat-square&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/DRF-3.15+-A30000?style=flat-square)](https://www.django-rest-framework.org/)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)

An **event-driven traffic-control system** for internal roads inside a garment manufacturing facility. The system receives vehicle-detection events, maintains traffic queues, controls signals through a safe state machine, handles emergency preemption, supports manual override, tolerates device failures, persists state across restarts, and exposes a live dashboard.

> **Design principle:** This is not CRUD. It is a small **safety-critical control system**. Traffic decisions are made by a pure domain engine, isolated from HTTP, database, and any specific IoT transport.

---

## 📑 Table of Contents

- [Features](#-features)
- [Architecture](#-architecture)
- [Quick Start](#-quick-start)
- [API Reference](#-api-reference)
- [Traffic-Control Algorithm](#-traffic-control-algorithm)
- [State Machine](#-state-machine)
- [Failure Handling](#-failure-handling)
- [Persistence & Recovery](#-persistence--recovery)
- [Demonstration Scenarios](#-demonstration-scenarios)
- [Project Structure](#-project-structure)
- [Testing](#-testing)
- [Assumptions / Questions / Requirement Issues](#-assumptions--questions--requirement-issues)
- [Incomplete Features & Roadmap](#-incomplete-features--roadmap)
- [AI / Tool Usage](#-ai--tool-usage)
- [License](#-license)

---

## ✨ Features

| Category | Feature |
|---|---|
| **Safety** | GREEN → YELLOW → ALL_RED → GREEN state machine; conflicting phases never both GREEN |
| **Scheduling** | Priority scoring: queue length + vehicle priority + waiting time |
| **Priority** | EMERGENCY > TRUCK > FORKLIFT > EMPLOYEE_VEHICLE |
| **Anti-starvation** | Waiting time grows unbounded; hysteresis (1.2×) prevents flapping |
| **Emergency** | Immediate preemption via the safe transition sequence (capped 5s green) |
| **Manual override** | Command-oriented API, 60s TTL, never bypasses safety |
| **Idempotency** | Duplicate `event_id` → rejected, queue unchanged |
| **Persistence** | SQLite; all important state survives restart |
| **Safe restart** | Forces ALL_RED on boot — never assumes prior GREEN |
| **Desired vs Actual** | Separate engine-desired and controller-confirmed signal state |
| **Controller simulation** | REST-based ACK / OFFLINE / NACK events |
| **Audit log** | Full event history per junction |
| **Dashboard** | Live polling UI with simulation form |

---

## 🏗️ Architecture

The system follows a **5-layer architecture**. The core domain logic has **zero dependencies** on Django, HTTP, or the database — it can be unit-tested in isolation.
