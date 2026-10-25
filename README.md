# StormReady 🌧️

### Detect the problem. Support maintenance. Verify recovery.

**StormReady is an IoT-enabled drainage monitoring and maintenance prototype.**

It combines live water-level monitoring with a structured incident workflow, helping maintenance operators and supervisors identify high-water conditions, record maintenance work, compare observations and review recovery evidence.

## Interactive Demo

[Explore the StormReady Interactive Showcase](https://ahmdsyakirrr.github.io/stormready_dashboard/)

Explore simulated upstream and retention pond alerts, switch between demonstration supervisor and operator roles, and follow an incident from assignment through evidence capture to review. This standalone showcase uses simulated data and does not connect to the physical prototype, real accounts or maintenance database.

## Why StormReady?

A water-level alert identifies a potential problem, but maintenance teams also need to know:

- Who is responsible for investigating it?
- What did the inspection find?
- What maintenance was completed?
- Did conditions improve after the work?
- Is there enough evidence to close the incident?

StormReady connects these activities in one dashboard, supporting a clearer and more accountable maintenance process.

## How It Works

**Observe → Flag → Assign → Inspect → Compare → Review**

| Stage | What happens |
| --- | --- |
| **Observe** | Sensors measure water levels in the upstream chamber and retention pond. |
| **Flag** | Confirmed high water triggers a noticeable alert and creates an incident. |
| **Assign** | A supervisor assigns the incident to a maintenance operator. |
| **Inspect** | The assigned operator captures a baseline before maintenance, then records inspection findings and completed work. |
| **Compare** | An after-maintenance capture is compared with the baseline using matching setup labels and similar starting water depths. |
| **Review** | A supervisor reviews the evidence and closes the case or requests further work. |

**Acknowledging an alert or returning below a water-level threshold does not automatically close a maintenance incident.**

## Key Features

### Live Monitoring and Alerts

- Live upstream and retention pond water-level displays.
- Recent-history charts and sensor connection information.
- Independent high-water detection for both locations.
- Alert pop-ups, persistent colour indicators and optional sound.
- Data-quality checks for missing, invalid, stale and out-of-range readings.

### Incident and Maintenance Management

- Separate supervisor and maintenance operator accounts.
- Automatic incident creation after confirmed high water.
- Supervisor assignment of maintenance operators.
- Inspection findings and work-completed records.
- Controlled 15-second before-and-after evidence captures.
- Comparison checks for matching setup and starting water levels.
- Supervisor closure supported by comparable improvement and fresh, safe readings.
- Further-work requests that retain previous evidence and decisions.

### Records and Exports

- Persistent telemetry and maintenance records in SQLite.
- Incident activity history.
- Water-reading and incident-summary CSV exports.
- Full incident JSON exports containing supporting evidence.
- Separate databases for hardware and simulation modes.

## Prototype Architecture

Water-level sensors connect to an ESP32, which sends JSON readings over Wi-Fi using HTTP. The Flask backend validates and stores the readings in SQLite, then serves the browser dashboard and incident workspace.

| Component | Technology |
| --- | --- |
| Microcontroller | ESP32 |
| Water-level sensing | Two ultrasonic sensors |
| Communication | Wi-Fi and HTTP |
| Backend | Python and Flask |
| Database | SQLite |
| Interface | HTML, CSS and JavaScript |
| Firmware | Arduino-compatible C++ |
| Development environment | macOS and Visual Studio Code |

The physical model contains an upstream chamber, a retention pond, a gravity drainage connection and a manually operated submersible transfer pump.

## Run the Full Application Locally

### 1. Download and prepare the project

Install Python 3 and Git, then run:

```bash
git clone https://github.com/ahmdsyakirrr/stormready_dashboard.git
cd stormready_dashboard

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

### 2. Choose a mode

**Hardware mode — receive readings from the ESP32:**

```bash
python3 app.py --mode hardware --host 0.0.0.0 --port 5050
```

Configure your local copy of `firmware/stormready_esp32/settings.h` with the Wi-Fi credentials, sensor calibration and the dashboard computer’s local network IP address.

The ESP32 and dashboard computer must be able to communicate over the local network.

**Simulation mode — explore without connected hardware:**

```bash
python3 app.py --mode simulation --host 127.0.0.1 --port 5050
```

In another Terminal window, open the project folder and run:

```bash
source .venv/bin/activate
python3 simulator.py --scenario normal
```

Simulation readings are labelled and stored separately from hardware readings.

### 3. Open the application

- **Live dashboard:** http://127.0.0.1:5050
- **Incident workspace:** http://127.0.0.1:5050/incidents

For first-time incident setup, open the incident workspace on the computer running the server. Create separate supervisor and operator accounts.

See [WORKFLOW_GUIDE.md](WORKFLOW_GUIDE.md) for the complete maintenance demonstration and evidence-capture procedure.

## Repository Structure

| File or folder | Purpose |
| --- | --- |
| `app.py` | Telemetry API, validation, storage and dashboard server |
| `pond_monitor.py` | Retention pond monitoring and supporting logic |
| `incident_workflow.py` | Accounts, incidents, assignments, evidence and review |
| `simulator.py` | Simulated sensor readings |
| `config.json` | Asset information, limits and monitoring settings |
| `docs/` | Standalone interactive showcase published through GitHub Pages |
| `templates/` | Dashboard and incident workspace pages |
| `static/` | Styles, interface scripts and visual assets |
| `firmware/` | ESP32 sketch and hardware configuration |
| `tests/` | Backend and dashboard behaviour checks |
| `API.md` | Telemetry packet documentation |
| `WORKFLOW_GUIDE.md` | Setup and maintenance workflow instructions |

## Testing

Run the Python tests:

```bash
python3 -m unittest discover -s tests -v
```

If Node.js is installed, run the dashboard behaviour checks:

```bash
node tests/test_dashboard.js
```

## Prototype Scope

StormReady is a working bench prototype for demonstration and evaluation.

- It measures **water depth and water-depth drawdown**, not direct volumetric flow.
- High pond water can indicate unusual accumulation, but does not independently prove pump failure.
- Pump operation remains manual; the dashboard does not switch pump power.
- Before-and-after comparisons require controlled, matching conditions.
- Demonstration thresholds and improvement criteria require further validation before field use.

The application is intended for a trusted local network. Public deployment would require additional security and operational controls.

## Credentials and Local Data

Keep real Wi-Fi credentials, passwords, databases and backups out of GitHub. Published firmware configuration should contain placeholder credentials.

## Project Goal

**StormReady aims to help maintenance teams move from noticing a drainage problem to documenting action and reviewing evidence of improvement.**
