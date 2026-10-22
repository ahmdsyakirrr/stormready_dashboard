# Verification record

Date: 15 October 2026.

## Completed here

- Environment: Linux development container, Python 3.12.14, Flask 3.1.3.
- Backend: **21 automated tests passed** with Flask's in-process HTTP test client.
- Client JavaScript: syntax check passed.
- Client logic: checks passed for valid zero values, stale/invalid data, backend
  disconnection and chart gaps, using a minimal DOM test double in Node.js.
- Simulator command-line dry run: packet generation passed.
- Source package: complete Python, HTML, CSS, JavaScript, configuration, tests and
  macOS instructions. No real sensor readings or pre-populated database included.

The backend tests cover persistence after restart, boot and packet ordering,
duplicate retries without age refresh, high-water persistence and hysteresis,
long-running high-water state, invalid and old samples, simulation/hardware
separation, missing-data coverage, CSV evidence retention and local asset serving.

## Still to check on the team's equipment

- Native macOS installation and operation.
- Visual layout and interactions in the team's Safari or other chosen browser.
- Actual network transmission from an ESP32.
- Sensor wiring, calibration, reliability and physical drainage behaviour.
- The later incident, maintenance and comparable-condition verification workflow.

No browser rendering test was available in the development environment. The
JavaScript checks are logic checks, not a browser screenshot or visual inspection.
The local server and simulator processes were not run on a Mac here.

## First-run acceptance on macOS

Follow START_HERE_MACOS.md. The milestone passes the team's first-run check when:

1. The simulator updates both readings and the stored count.
2. Stopping the simulator makes current readings unavailable after the configured
   missing-data interval.
3. Restarting the server retains the stored readings.
4. Exported CSV contains source, quality, raw values and UTC timestamps.
