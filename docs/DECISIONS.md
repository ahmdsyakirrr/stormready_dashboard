# StormReady development decisions

## Confirmed context

- Project: StormReady, for the Sime Darby Property University Hackathon 2026.
- Theme: Planet. Track: Climate resilience.
- Priority: Detect → Maintain → Verify.
- Available time: seven days or less; exact demonstration date not supplied.
- Available budget: below RM200; exact spending ceiling not supplied.
- Components purchased: none at the start of this development session.
- Development and demonstration operating system: macOS.
- Maintenance completion must remain separate from verified recovery and operator closure.
- The operator, ownership and existing workflow of a real asset remain to be validated.

## Recommendations for this sprint

- One bench drainage setup with upstream and downstream level measurement.
- ESP32 + two HC-SR04P sensors, with a small low-voltage refill pump.
- Arduino C++ firmware; HTTP/Wi-Fi; local Flask + SQLite + HTML/CSS/JavaScript.
- Controlled drain-down comparison for the initial maintenance-verification demonstration.
- Software development can start with clearly labelled simulation while parts are sourced.

These are proposed engineering choices. Hardware dimensions, calibration,
thresholds, wiring and physical performance have not been confirmed by a bench test.

## Proposed maintenance-verification test

1. Mount the sensors and establish their water-level reference points with a ruler.
2. Choose starting and finishing upstream level bands that are well separated
   relative to measured sensor noise. Choose a normal drain duration long enough
   to measure consistently.
3. Record at least three clear-drain trials to establish a provisional normal band.
4. During each timed trial, physically isolate the refill inlet, establishing zero
   incoming flow. The pump setting alone does not establish zero inflow.
5. Keep the outlet geometry and position fixed. Establish comparable downstream
   conditions and monitor the downstream level throughout the trial. The receiving
   basin must not rise enough to submerge or restrict the outlet during a valid
   free-discharge comparison.
6. Add a removable restriction and retain its trial readings as fault evidence.
7. Record inspection and maintenance before running the post-maintenance trial.
8. Compare drain time between the same level bands and evaluate reading quality.

Comparable conditions and a return within the measured normal range can provide
recovery evidence for operator review. Continuing abnormal performance keeps the
incident open. Mismatched conditions, an unfinished trial or unreliable readings
keep verification pending. Finishing maintenance never closes the incident by itself.

Three repeated trials are an initial bench check, not an established statistical
validation sample. No threshold or performance result has yet been established.

## Next milestones

| Milestone | Deliverable |
| --- | --- |
| 1 — this package | Telemetry, persistent storage, quality handling and simulator |
| 2 | Final physical layout, exact purchased board/sensor identification, wiring and sensor calibration |
| 3 | ESP32 firmware and Wi-Fi transmission to the Mac |
| 4 | Incidents, acknowledgement, assignment, inspections and maintenance history |
| 5 | Drain-down baseline, comparable-condition checks and three verification outcomes |
| 6 | Operator review/closure, repeated integration tests and demonstration rehearsal |

Parts should be available within the first one to two days to protect the hardware
integration window. A maximum seven-day plan was proposed; the final schedule
depends on the actual demonstration date and team availability.
