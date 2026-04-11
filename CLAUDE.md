# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Kepware OPC UA device monitoring system. Connects to one or more Kepware KEPServerEX V6 servers via OPC UA (asyncua library), reads device tags on a configurable interval, evaluates thresholds, runs network diagnostics on failures, sends HTML email alerts, and records everything to SQLite.

The primary user is a Mandarin Chinese speaker; all UI text, log messages, email content, and code comments are in Traditional Chinese (繁體中文).

## Running

```bash
python kepware_monitor.py
```

Requires `Config/settings.ini` (copy from `Config/settings.example.ini`) and `Config/tags.csv` (copy from `Config/tags.example.csv`). These files are gitignored since they contain site-specific credentials and IPs.

**Python version: 3.12 or 3.13 only.** The asyncua library is incompatible with Python 3.14 (`issubclass()` error in `ua_binary.py`). Windows Store Python has limitations; use the official python.org installer.

No requirements.txt exists yet. The key dependency is `asyncua` (`pip install asyncua`).

## Architecture

```
kepware_monitor.py          Entry point: config loading, logging setup, asyncio.run(main)
  └─ MonitorManager         Core orchestrator (monitor_manager.py)
       ├─ OPCConnection     Thin asyncua Client wrapper (opc_connection.py)
       ├─ DiagnosticService  3-layer network diagnostics (diagnostic_service.py)
       ├─ DatabaseService    SQLite persistence (db_service.py)
       └─ EmailService       SMTP HTML email alerts (ase_email_service.py)
```

**Data flow:** MonitorManager reads tags CSV → connects to OPC servers → enters polling loop → reads tag values → evaluates thresholds → runs diagnostics on failures → writes history to SQLite → sends email alerts.

### OPC Connection Pattern (Critical)

The OPC connection code intentionally mirrors the original working code exactly. This was arrived at after extensive debugging — any "improvements" (retry wrappers, heartbeats, reconnect-with-diagnosis) caused asyncua to hang during `activate_session`. The pattern is:

- `opc_connection.py`: Direct `Client(url)` construction, bare `await client.connect()`, simple reconnect (disconnect → sleep 5 → connect)
- `monitor_manager.py` loop: read fails → reconnect → success: continue / fail: sleep 30 → retry

**Do not add connection retry logic, heartbeat checks, or wrap connect() in try-except.** Changes to the connection flow require testing on real Kepware hardware.

### Three-Layer Diagnostics

- **Layer 1:** Ping Kepware host
- **Layer 2:** TCP check OPC UA port (default 49320)
- **Layer 3:** Ping iFIX/IGS device + TCP check IGS port (default 49310)

Diagnostics run only when a value alert triggers (not on every read), to identify root cause: host_down vs opc_service_down vs device_down vs igs_service_down vs value_abnormal.

### Alert Routing

- **Connection alerts** (host_down, opc_service_down) → global mail recipients (IT staff)
- **Device/value alerts** (device_down, igs_service_down, value_abnormal) → per-device mail recipients from CSV

### Configuration

- `Config/settings.ini`: Multi-server format `Servers = name|opc.tcp://IP:Port` with backward compatibility for legacy single `ServerUrl`
- `Config/tags.csv`: Hot-reloaded via mtime check. Columns include DeviceIP/DevicePort for Layer 3 diagnostics and per-device MailTo/MailCc
- All `config.get()` calls must include `fallback=` for backward compatibility with older ini files

### Database

SQLite with WAL journal mode (for concurrent access by other projects). Three tables:
- `monitor_history`: every tag read
- `alert_log`: every email sent
- `kepware_event_log`: Kepware server events (shared with other projects)

The `kepware_event_log` table is designed for cross-project use — other services write events here and query them.

## Key Constraints

- This runs on Windows servers alongside Kepware. Ping commands are platform-aware (Windows `-n`/`-w` vs Linux `-c`/`-W`).
- The CSV is edited on an office PC and copied to the server. Hot-reload detects file changes via mtime.
- `ase_email_service.py` uses unauthenticated SMTP (port 25), typical for internal corporate mail relays.
