# Run StormReady on macOS

You need a Mac, a browser and two Terminal tabs. No sensors are needed for this
first milestone. Use the same project folder in both tabs.

## 1. Extract the download

Double-click `StormReady_Milestone_1_macOS.zip` in Finder. Place the extracted
`stormready_milestone_1` folder in Downloads.

If macOS has already extracted it, use that folder. Do not try to run Python files
from inside the ZIP.

## 2. Check Python

Open Terminal and enter:

```bash
python3 --version
```

Use a supported Python 3 installation. Python 3.12 or 3.13 is a practical choice
for this project; the automated checks were run on Python 3.12. If Python is
missing, use a macOS installer from https://www.python.org/downloads/macos/,
complete its installer, reopen Terminal and check again. Flask 3.1 requires
Python 3.9 or newer. No Homebrew installation is required by this guide.

## 3. Install this project's dependency

Run these lines in Terminal, one at a time:

```bash
cd ~/Downloads/stormready_milestone_1
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

You should see `(.venv)` in the Terminal prompt after activation. This keeps the
project's packages separate from other Python projects. The installation step
needs an internet connection.

If the folder is elsewhere, type `cd ` with a trailing space, drag the extracted
folder from Finder into Terminal, then press Enter. Continue with the other lines.

## 4. Start the dashboard server — Terminal 1

In that same Terminal tab:

```bash
python app.py
```

Leave it running. Open this address in your browser:

http://127.0.0.1:5050

You should see the StormReady dashboard, the **SIMULATION** banner, and blank
current readings. No data has been invented or preloaded.

## 5. Start the sensor simulator — Terminal 2

Open another Terminal tab with **Command+T**, then enter:

```bash
cd ~/Downloads/stormready_milestone_1
source .venv/bin/activate
python simulator.py --scenario cycle
```

Both programs must run at the same time: Terminal 1 receives and stores readings;
Terminal 2 sends them. Repeated numbers will appear in Terminal 2. The browser
updates automatically.

The cycle repeats every 80 samples, approximately 80 seconds at the default rate:

| Samples | Scenario | Expected dashboard behaviour |
| --- | --- | --- |
| 0–19 | Normal example values | Levels around 45 mm upstream and 16 mm downstream; below demo limit |
| 20–39 | High water | About 112 mm upstream; confirmation, then high-water indication after five seconds |
| 40–49 | Upstream sensor unavailable | Upstream is blank; water-level check becomes unknown |
| 50–59 | Upstream value outside configured range | Upstream remains blank; raw 300 mm value is retained in the table and CSV |
| 60–79 | Normal example values | Valid readings resume; below demo limit |

The word "normal" here names synthetic example values. It is not a validated
drainage-performance or flood-safety assessment.

## 6. Run the milestone checks

1. **Updates:** current values and the chart change; stored reading count grows.
2. **Missing data:** press **Control+C** in Terminal 2 only. Wait more than
   10 seconds. The dashboard must show **No recent data**, blank current levels
   and **Unknown** for the water-level check.
3. **Persistent storage:** leave the simulator stopped. Stop Terminal 1 with
   Control+C, then run `python app.py` again. Refresh the browser. The stored
   count must remain, and the old readings must remain unavailable as current data.
4. **CSV:** click **Export readings**. Check that source, raw values, quality and
   UTC timestamps are included.
5. **Resume:** restart the simulator. Current readings return without deleting
   earlier evidence.

Historical rows show the quality when each reading was accepted. A past row
labelled "Both valid" does not mean the sensors are connected now.

To test one scenario at a time, stop the current simulator and run one command:

```bash
python simulator.py --scenario normal
python simulator.py --scenario high-water
python simulator.py --scenario sensor-fault
python simulator.py --scenario out-of-range
python simulator.py --scenario stale-sample
```

These are alternatives; run only one simulator at a time. `stale-sample` sends
new packets containing samples declared to be 20 seconds old. Packet receipt can
be online while the water readings remain unusable.

## 7. Stop and restart later

Press **Control+C**, not Command+C, in each running Terminal tab to stop the
programs. In a new tab or future session, first enter the project folder and
activate `.venv` again. You do not need to reinstall Flask each time.

## Troubleshooting

| What you see | What to do |
| --- | --- |
| `python3: command not found` | Install Python using the official macOS installer and reopen Terminal. |
| `No module named flask` | Activate `.venv` in the server tab, then install `requirements.txt`. |
| `No such file or directory` | Check the extracted folder name and location; use Finder drag-and-drop with `cd `. |
| Installation reports a certificate error | For a Python.org installation, run its supplied `Install Certificates.command` from the Python folder in Applications, then retry. |
| Address or port already in use | Stop the other StormReady server, or use `python app.py --port 5051`; open port 5051 in the browser and add `--url http://127.0.0.1:5051` to the simulator command. |
| Simulator says server unavailable | Keep Terminal 1 running and ensure the simulator URL uses the same port. |
| No readings while server is in hardware mode | Stop the server and run plain `python app.py` for this simulation milestone. |
| Browser shows dashboard disconnected | Restart `app.py`. Current readings stay unknown until the backend is reachable. |

The app initially listens only on your Mac. ESP32 Wi-Fi integration and the
physical wiring are the next milestone.
