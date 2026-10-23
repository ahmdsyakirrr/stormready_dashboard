# StormReady incident and maintenance upgrade

## Start on your Mac

1. Stop the running dashboard with **Control+C**. Back up your project folder before upgrading. Keep your local `data/` folder private; it now also contains accounts and maintenance evidence.
2. From the project folder run:

   ```bash
   .venv/bin/python -m pip install -r requirements.txt
   .venv/bin/python app.py --mode hardware --host 0.0.0.0 --port 5050
   ```

3. Open **http://127.0.0.1:5050/incidents** on the same Mac. First setup is restricted to localhost. Create separate supervisor and operator accounts with different passwords, at least eight characters. Save those passwords securely. Setup is required separately for simulation and hardware databases.
4. Sign in as supervisor. Return to the live dashboard using **View live dashboard**. Your existing ESP32 sketch, server URL, calibration, labels and water alerts continue to work.

## What is complete

The new workspace provides automatic high-water incident creation, assignment, inspection records, controlled before/after observations, supervisor decisions, persistent activity history, CSV queue export and full JSON evidence export. Accounts use hashed passwords and role checks. Alert acknowledgement and water returning below the threshold do not close maintenance cases.

## Demonstrate one upstream maintenance case

Use the physical model under continuous supervision. The software does not control or stop the pump. Keep electronics and wire joints dry. Never run a submersible pump without sufficient water.

1. A fresh upstream level above the configured high-water threshold (currently 50 mm) for the configured confirmation period (currently five seconds) creates a case. Pond high water creates a separate case, independently of upstream sensor health. Existing historical readings are not imported as new cases when upgrading.
2. As supervisor, select the case and assign the operator. Sign out and sign in as that operator.
3. **Before performing maintenance**, prepare the upstream observation: pump OFF, gravity drain open, no added inflow. Use a safe repeatable starting depth, such as upstream 60 mm and pond 30 mm. Record the physical fault as it actually exists; do not invent a fault or record a simulated result as hardware evidence.
4. Enter a repeatable setup label, such as `Bench setup A`. Confirm the displayed conditions and press **Capture before work**. Observe the model for 15 seconds. Check the model when the completion dialog appears.
5. Inspect the affected location and perform the actual maintenance. Enter findings and work completed, then select **Save inspection & work**. If work was already done before the first capture, a valid before-maintenance baseline cannot be reconstructed retrospectively.
6. Restore both starting depths to within 5 mm of the baseline and restore the same declared setup. Use exactly the same setup label. Press **Capture after work**, supervise the next 15 seconds, and check the model when prompted.
7. Review the comparison and submit for supervisor review. Missing or mismatched evidence is inconclusive; insufficient improvement does not establish recovery.
8. Sign in as supervisor. Read the findings, work, measurements and capture history. Confirm that the affected location has stayed below its clearing threshold for five seconds with fresh valid readings. Check the evidence review box and enter a specific review note.
9. **Approve & close case** is allowed only with comparable improved evidence and current safe readings. Otherwise choose **Keep open · request more work**. This starts a new review cycle while retaining every earlier record; capture a new before/after pair around further maintenance.
10. Export the full case JSON and queue CSV for submission evidence. CSV contains case summaries; JSON includes capture samples and the activity history.

## Pond observations and measurement limits

For a pond case, the declared comparison setup is manual transfer pump ON, gravity return CLOSED, and no added inflow. Restore matched starting levels between captures. Use only a safely submerged pump and an appropriate model configuration. Do not deliberately stall a pump to manufacture a baseline. A pond alert indicates abnormal water accumulation; it does not prove the pump has failed. This prototype has no electrical, pump-current or flow sensor.

Captures measure water-depth drawdown in mm and mm/min, not volumetric flow or proven pump health. The demonstration screening criterion is at least **5 mm greater drawdown per 15 seconds** after work, using the rate derived from the endpoint sample groups. It is a bench demonstration criterion, not a validated engineering performance standard.

Invalid readings, sensor gaps, device restarts, changed calibration and safety guard levels stop or invalidate evidence. Only one capture can run on the rig at a time. Captures stop near a chamber maximum (within 5 mm), and pond captures stop at or below 20 mm. These are software evidence guards, not automatic physical protections. Stay with the model and switch the pump manually.

## Publishing and backup

Never commit `.venv/`, `data/`, SQLite files, real Wi-Fi passwords, account passwords or backup folders. Firmware templates must keep placeholder credentials. Existing firmware needs no change for this milestone.

Run the checks from the project folder:

```bash
.venv/bin/python -m unittest discover -s tests -v
node tests/test_dashboard.js
```

After checking `git diff` and `git status`, commit the source and push normally:

```bash
git add app.py simulator.py incident_workflow.py templates/index.html templates/incidents.html static/incidents.css static/incidents.js static/workflow-link.js tests WORKFLOW_GUIDE.md README.md
git commit -m "Add incident maintenance workflow and recovery evidence"
git push origin main
```

Alternatively use GitHub Desktop: review changed files, enter the same commit summary, click **Commit to main**, then **Push origin**. If Git reports a different branch, use that branch rather than forcing main. Never force-push to solve an update conflict.

Stop the server before copying the private `data/` directory as a backup. Accounts, sessions, incidents and telemetry live in the same mode-specific SQLite database. Keep backups private. There is no account recovery screen in this version; preserve passwords and database backups. This remains a local bench prototype: telemetry ingestion has no device authentication, so do not expose port 5050 directly to the public internet.

## Verification for this release

42 Python integration tests and 13 dashboard behavior checks passed. A browser test completed account creation, assignment, both captures, inspection, supervisor closure and 1440/390/320-pixel layouts against the Flask API. The tested incident screen had zero WCAG A/AA violations reported by axe. These are software checks; perform the physical model demonstration yourself before submission.
