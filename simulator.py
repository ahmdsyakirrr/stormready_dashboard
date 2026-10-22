"""Send clearly labelled simulated sensor packets to StormReady."""

import argparse
import json
import math
import random
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

SCENARIOS = ("normal", "high-water", "sensor-fault", "out-of-range", "stale-sample", "cycle")


def make_packet(sequence, boot_id, uptime_ms, scenario="normal", device_id="stormready-esp32-01"):
    # Reproducible tiny fluctuations; these are synthetic values, not sensor accuracy claims.
    noise = random.Random(sequence + 42)
    if scenario == "cycle":
        step = sequence % 80
        scenario = "normal" if step < 20 or step >= 60 else (
            "high-water" if step < 40 else ("sensor-fault" if step < 50 else "out-of-range")
        )
    upstream = round((112 if scenario == "high-water" else 45) + noise.uniform(-0.5, 0.5), 1)
    downstream = round(16 + noise.uniform(-0.3, 0.3), 1)
    return {
        "schema_version": 1, "device_id": device_id, "boot_id": boot_id,
        "sequence": sequence, "uptime_ms": uptime_ms,
        "sample_age_ms": 20000 if scenario == "stale-sample" else 0,
        "source": "simulator",
        "upstream_mm": None if scenario == "sensor-fault" else (300 if scenario == "out-of-range" else upstream),
        "downstream_mm": downstream,
        "upstream_valid": scenario != "sensor-fault", "downstream_valid": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--url", default="http://127.0.0.1:5050", help="Server base URL")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between samples; default 1")
    parser.add_argument("--samples", type=int, default=0, help="0 means continue until Control+C")
    parser.add_argument("--dry-run", action="store_true", help="Print packets without sending; requires --samples")
    args = parser.parse_args()
    if not math.isfinite(args.interval) or args.interval < 0.05:
        parser.error("--interval must be at least 0.05 seconds")
    if args.samples < 0 or (args.dry_run and args.samples == 0):
        parser.error("Use a positive --samples value with --dry-run")
    settings = json.loads((Path(__file__).resolve().parent / "config.json").read_text(encoding="utf-8"))
    boot_id = "sim-" + uuid.uuid4().hex[:16]
    started = time.monotonic()
    sequence = 0
    if not args.dry_run:
        print(f"SIMULATED DATA | scenario: {args.scenario} | target: {args.url}")
        print("No hardware is connected by this script. Press Control+C to stop.")
    try:
        while args.samples == 0 or sequence < args.samples:
            packet = make_packet(sequence, boot_id, int((time.monotonic() - started) * 1000), args.scenario, settings["device_id"])
            if args.dry_run:
                print(json.dumps(packet, allow_nan=False))
            else:
                request = urllib.request.Request(
                    args.url.rstrip("/") + "/api/readings",
                    data=json.dumps(packet, allow_nan=False).encode(),
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                try:
                    with urllib.request.urlopen(request, timeout=4) as response:
                        result = json.load(response)
                    print(f"#{sequence:04d} | upstream={packet['upstream_mm']} mm | downstream={packet['downstream_mm']} mm | {result['status']}")
                except urllib.error.HTTPError as error:
                    print(f"Server rejected the packet ({error.code}): {error.read().decode()}")
                    print("Check simulation mode and config.json. Simulator stopped.")
                    return 1
                except (urllib.error.URLError, TimeoutError, OSError) as error:
                    print(f"Server unavailable: {error}. Start app.py in the other terminal.")
            sequence += 1
            if args.samples and sequence >= args.samples:
                break
            if not args.dry_run:
                # Aim for the configured interval without accumulating HTTP latency.
                time.sleep(max(0, started + sequence * args.interval - time.monotonic()))
    except KeyboardInterrupt:
        print("\nSimulator stopped. The dashboard will show stale data after 10 seconds with the default settings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
