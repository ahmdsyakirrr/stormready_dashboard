# StormReady

**Detect the problem. Support maintenance. Verify recovery.**

This is the StormReady bench prototype.
It runs and accepts clearly labelled simulated readings while the
physical components are being sourced.

**Begin with [START_HERE_MACOS.md](START_HERE_MACOS.md).**

## What works in this milestone

- Receive sensor packets through an HTTP endpoint.
- Store the original numeric values, quality flags and receipt times in SQLite.
- Display upstream and downstream water levels and a recent-history chart.
- Mark missing, invalid, out-of-range and already-old measurements as unavailable.
- Require five seconds of supporting readings for the provisional high-water check.
- Preserve readings and high-water confirmation state after restarting the server.
- Export all stored readings to CSV, including their source and quality.
- Keep simulation and hardware data in separate database files.

This milestone does **not yet implement** incidents, work assignment, maintenance
records, drainage-performance detection or verification after maintenance. Those
are subsequent milestones. A return below the demo water-level threshold is
not a maintenance-verification result.

## Architecture

`simulator.py` sends JSON packets over HTTP to `app.py`.
Flask stores them in SQLite and serves the HTML/CSS/JavaScript dashboard.
The browser requests current status approximately once a second. The same packet
contract will be used by ESP32 firmware in hardware mode.

All dashboard assets are included. There are no external fonts, chart libraries,
cloud accounts, API keys or CDN requests. Internet access is required for the
initial Python dependency installation; it is not needed for the local simulation
after installation.

| File | Purpose |
| --- | --- |
| `app.py` | Backend, validation, storage and provisional high-water check |
| `simulator.py` | Simulated sensor source with five individual scenarios and a cycle |
| `config.json` | Asset information and uncalibrated demonstration settings |
| `templates/index.html` | Dashboard page |
| `static/` | Included styles, chart logic and logo |
| `API.md` | Exact packet format for future firmware |
| `tests/` | Backend and optional JavaScript behaviour checks |
| `docs/DECISIONS.md` | Current constraints, proposed physical test and next milestones |
| `VERIFICATION.md` | Checks completed in the development environment |

## Data and thresholds

The first run creates `data/simulation.sqlite3`. Restarting the application does
not delete it. `python app.py --mode hardware` instead uses
`data/hardware.sqlite3` and rejects simulator packets. Hardware mode is a future
integration entry point, not evidence of an attached or tested device.

Settings in `config.json` are demonstration values, not field thresholds:

| Setting | Default | Meaning |
| --- | --- | --- |
| `upstream_max_mm` | 75 | Provisional upper plausible upstream level |
| `downstream_max_mm` | 80 | Provisional upper plausible downstream level |
| `high_water_mm` | 50 | Provisional high-water threshold |
| `high_water_clear_mm` | 40 | Clear a confirmed high-water indication below this level |
| `high_water_hold_seconds` | 5 | Required duration of supporting high readings |
| `max_gap_seconds` | 3 | A longer gap restarts high-water confirmation |
| `stale_after_seconds` | 10 | No recent packets: mark current conditions unknown |
| `max_sample_age_seconds` | 3 | Reject an already-old sample as current evidence |
| `expected_interval_seconds` | 1 | Expected device sampling interval |
| `history_seconds` | 120 | Dashboard chart and coverage window |

Edit settings while the server is stopped, then restart it. After a settings
change, confirmation starts again with new readings. Export old data before
starting a physical calibration session and use a separate project copy for a
different rig profile. 

Valid data coverage estimates the fraction of expected sampling intervals
containing at least one valid upstream/downstream pair. Its window is up to the
last 120 seconds, or since the first packet if the run is shorter. Missing
intervals and invalid pairs reduce coverage; multiple packets in one interval do
not increase it. Packet timing jitter can affect this estimate.

Receipt and estimated sampling times are stored as UTC. Dashboard times are
shown in Malaysia time (MYT). `sample_age_ms` is reported by the sender; the backend
cannot independently establish when a device actually measured the water.

## Checks

With the virtual environment active:

```bash
python -m unittest discover -s tests -v
```

Optional, only if Node.js is already installed:

```bash
node tests/test_dashboard.js
```

## Official setup references

- Flask installation: https://flask.palletsprojects.com/en/stable/installation/
- Flask local server: https://flask.palletsprojects.com/en/stable/quickstart/
- Python virtual environments: https://docs.python.org/3/library/venv.html
- Official Python macOS installers: https://www.python.org/downloads/macos/

No hardware or field-performance results are claimed by this package.

## Maintenance workflow

Open `/incidents`. See [WORKFLOW_GUIDE.md](WORKFLOW_GUIDE.md) for setup and usage.
