"""StormReady: live telemetry, independent pond alerts and supervised refill checks. Run with: python3 app.py"""

import argparse
import csv
import io
import json
import math
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, g, jsonify, render_template, request
import pond_monitor
from werkzeug.exceptions import HTTPException

ROOT = Path(__file__).resolve().parent
IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,64}\Z")
READING_FIELDS = (
    "device_id", "boot_id", "sequence", "uptime_ms", "sample_age_ms", "source",
    "upstream_mm", "downstream_mm", "upstream_quality", "downstream_quality",
)


def load_settings():
    settings = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    for name in (
        "upstream_max_mm", "downstream_max_mm", "high_water_mm", "high_water_clear_mm",
        "high_water_hold_seconds", "max_gap_seconds", "stale_after_seconds",
        "max_sample_age_seconds", "expected_interval_seconds", "history_seconds",
    ):
        value = settings.get(name)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"config.json: {name} must be a positive finite number")
    if not settings["high_water_clear_mm"] < settings["high_water_mm"] < settings["upstream_max_mm"]:
        raise ValueError("config.json: clear level < high-water level < upstream maximum is required")
    if settings["history_seconds"] < settings["high_water_hold_seconds"] + settings["max_gap_seconds"]:
        raise ValueError("config.json: history must be longer than the high-water holding interval")
    if not IDENTIFIER.fullmatch(settings["device_id"]):
        raise ValueError("config.json: invalid device_id")
    return pond_monitor.configure(settings)


def utc_iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="milliseconds")


def create_app(mode="simulation", database_path=None, clock=None):
    if mode not in ("simulation", "hardware"):
        raise ValueError("mode must be simulation or hardware")
    settings = load_settings()
    profile_key = json.dumps(settings, sort_keys=True)
    database_path = Path(database_path) if database_path else ROOT / "data" / f"{mode}.sqlite3"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    app = Flask(__name__)
    app.config.update(
        MAX_CONTENT_LENGTH=8192, DATABASE=str(database_path), MODE=mode,
        SETTINGS=settings, CLOCK=clock or time.time,
    )

    def database():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"], timeout=10)
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_database(_error):
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    with app.app_context():
        connection = database()
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at REAL NOT NULL,
                sampled_at REAL NOT NULL,
                device_id TEXT NOT NULL,
                boot_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                uptime_ms INTEGER NOT NULL,
                sample_age_ms INTEGER NOT NULL,
                source TEXT NOT NULL,
                upstream_mm REAL,
                downstream_mm REAL,
                upstream_quality TEXT NOT NULL,
                downstream_quality TEXT NOT NULL,
                UNIQUE(device_id, boot_id, sequence)
            );
            CREATE INDEX IF NOT EXISTS readings_time ON readings(received_at);
            CREATE TABLE IF NOT EXISTS monitor_state (
                id INTEGER PRIMARY KEY CHECK(id=1),
                profile_key TEXT NOT NULL,
                boot_id TEXT NOT NULL,
                previous_sampled_at REAL NOT NULL,
                high_since REAL,
                active INTEGER NOT NULL,
                last_confirmed_at REAL
            );
        """)
        pond_monitor.setup(connection)
        # Keep streams isolated even if a custom database path is used accidentally.
        wrong_source = connection.execute(
            "SELECT 1 FROM readings WHERE source != ? LIMIT 1",
            ("simulator" if mode == "simulation" else "esp32",),
        ).fetchone()
        if wrong_source:
            raise ValueError("This database contains the other source type; use a separate database.")
        connection.commit()

    @app.after_request
    def response_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.get("/")
    def index():
        return render_template("index.html", mode=mode, settings=settings)

    @app.get("/api/health")
    def health():
        database().execute("SELECT 1")
        return jsonify(status="ok", mode=mode, schema_version=1)

    def validate_payload(payload):
        if not isinstance(payload, dict):
            raise ValueError("Send one JSON object")
        required = {
            "schema_version", "device_id", "boot_id", "sequence", "uptime_ms",
            "sample_age_ms", "source", "upstream_mm", "downstream_mm",
            "upstream_valid", "downstream_valid",
        }
        if set(payload) != required:
            raise ValueError("Packet fields do not match schema 1; see API.md")
        if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
            raise ValueError("schema_version must be 1")
        for field in ("device_id", "boot_id"):
            if not isinstance(payload[field], str) or not IDENTIFIER.fullmatch(payload[field]):
                raise ValueError(f"{field} must contain 1–64 letters, numbers, dots, dashes, underscores or colons")
        if payload["device_id"] != settings["device_id"]:
            raise ValueError("device_id does not match config.json")
        for field, maximum in (("sequence", 2**53 - 1), ("uptime_ms", 2**53 - 1), ("sample_age_ms", 3_600_000)):
            if type(payload[field]) is not int or not 0 <= payload[field] <= maximum:
                raise ValueError(f"{field} must be a non-negative integer within the documented range")
        expected_source = "simulator" if mode == "simulation" else "esp32"
        if payload["source"] != expected_source:
            raise ValueError(f"This server accepts source={expected_source!r} only")
        normalized = {key: payload[key] for key in READING_FIELDS if key in payload}
        for sensor in ("upstream", "downstream"):
            valid = payload[f"{sensor}_valid"]
            value = payload[f"{sensor}_mm"]
            if type(valid) is not bool:
                raise ValueError(f"{sensor}_valid must be true or false")
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise ValueError(f"{sensor}_mm must be a finite number or null")
            if not valid or value is None:
                quality = "invalid"
            elif not 0 <= value <= settings[f"{sensor}_max_mm"]:
                quality = "out_of_range"
            elif payload["sample_age_ms"] / 1000 > settings["max_sample_age_seconds"]:
                quality = "stale_sample"
            else:
                quality = "good"
            normalized[f"{sensor}_quality"] = quality
        return normalized

    def update_monitor_state(connection, reading, sampled_at):
        """Persist confirmation state so long-running events survive history-window changes."""
        state = connection.execute("SELECT * FROM monitor_state WHERE id=1").fetchone()
        same_profile = state is not None and state["profile_key"] == profile_key
        continuous = same_profile and state["boot_id"] == reading["boot_id"] and 0 <= sampled_at - state["previous_sampled_at"] <= settings["max_gap_seconds"]
        high_since = state["high_since"] if continuous else None
        active = bool(state["active"]) if continuous else False
        last_confirmed_at = state["last_confirmed_at"] if same_profile else None
        if reading["upstream_quality"] != "good":
            high_since, active = None, False
        elif reading["upstream_mm"] >= settings["high_water_mm"]:
            high_since = sampled_at if high_since is None else high_since
            if sampled_at - high_since >= settings["high_water_hold_seconds"]:
                active, last_confirmed_at = True, sampled_at
        elif reading["upstream_mm"] < settings["high_water_clear_mm"]:
            high_since, active = None, False
        else:
            high_since = None
        connection.execute(
            "INSERT OR REPLACE INTO monitor_state VALUES (1,?,?,?,?,?,?)",
            (profile_key, reading["boot_id"], sampled_at, high_since, int(active), last_confirmed_at),
        )

    @app.post("/api/readings")
    def receive_reading():
        if not request.is_json:
            return jsonify(error="Use Content-Type: application/json"), 415
        try:
            normalized = validate_payload(request.get_json())
        except ValueError as error:
            return jsonify(error=str(error)), 400
        connection = database()
        # A short write transaction protects deduplication and ordering together.
        connection.execute("BEGIN IMMEDIATE")
        duplicate = connection.execute(
            "SELECT * FROM readings WHERE device_id=? AND boot_id=? AND sequence=?",
            (normalized["device_id"], normalized["boot_id"], normalized["sequence"]),
        ).fetchone()
        if duplicate:
            identical = all(duplicate[field] == normalized[field] for field in READING_FIELDS)
            connection.rollback()
            if identical:
                return jsonify(status="duplicate", reading_id=duplicate["id"]), 200
            return jsonify(error="This sequence number already has a different reading"), 409
        latest = connection.execute("SELECT * FROM readings ORDER BY id DESC LIMIT 1").fetchone()
        same_boot = connection.execute(
            "SELECT MAX(sequence) AS sequence, MAX(uptime_ms) AS uptime_ms FROM readings WHERE boot_id=?",
            (normalized["boot_id"],),
        ).fetchone()
        if same_boot["sequence"] is not None:
            if latest["boot_id"] != normalized["boot_id"]:
                connection.rollback()
                return jsonify(error="A packet from an old boot was received; discard queued old packets"), 409
            if normalized["sequence"] <= same_boot["sequence"] or normalized["uptime_ms"] < same_boot["uptime_ms"]:
                connection.rollback()
                return jsonify(error="Out-of-order packet; sequence and uptime must increase within a boot"), 409
        now = app.config["CLOCK"]()
        fields = ("received_at", "sampled_at") + READING_FIELDS
        values = (now, now - normalized["sample_age_ms"] / 1000) + tuple(normalized[key] for key in READING_FIELDS)
        cursor = connection.execute(
            f"INSERT INTO readings ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", values,
        )
        update_monitor_state(connection, normalized, values[1])
        pond_monitor.update_pond(connection, normalized, values[1], settings, profile_key)
        pond_monitor.tick_refill(connection, dict(normalized, sampled_at=values[1], received_at=now), now, settings, profile_key)
        connection.commit()
        return jsonify(status="stored", reading_id=cursor.lastrowid), 201

    def snapshot():
        now = app.config["CLOCK"]()
        connection = database()
        aggregate = connection.execute("SELECT COUNT(*) AS count, MIN(received_at) AS first FROM readings").fetchone()
        last = connection.execute("SELECT * FROM readings ORDER BY id DESC LIMIT 1").fetchone()
        rows = [dict(row) for row in connection.execute(
            "SELECT * FROM readings WHERE received_at >= ? ORDER BY id",
            (now - settings["history_seconds"],),
        )]
        latest = dict(last) if last else None
        age = max(0, now - latest["received_at"]) if latest else None
        connection_state = "waiting" if latest is None else ("offline" if age > settings["stale_after_seconds"] else "online")
        if latest:
            latest["received_at_iso"] = utc_iso(latest["received_at"])
            latest["sampled_at_iso"] = utc_iso(latest["sampled_at"])
            for sensor in ("upstream", "downstream"):
                latest[f"{sensor}_current_quality"] = (
                    "offline" if connection_state == "offline" else latest[f"{sensor}_quality"]
                )

        state = connection.execute("SELECT * FROM monitor_state WHERE id=1").fetchone()
        state_matches = state is not None and state["profile_key"] == profile_key
        high_since = state["high_since"] if state_matches else None
        active = bool(state["active"]) if state_matches else False
        last_confirmed_at = state["last_confirmed_at"] if state_matches else None
        if latest is None or not state_matches or connection_state == "offline" or latest["upstream_quality"] != "good":
            water_state = "unknown"
        elif active:
            water_state = "high_water"
        elif latest["upstream_mm"] >= settings["high_water_mm"]:
            water_state = "confirming"
        else:
            water_state = "below_threshold"

        good_count = sum(row["upstream_quality"] == row["downstream_quality"] == "good" for row in rows)
        start = max(now - settings["history_seconds"], aggregate["first"]) if aggregate["first"] is not None else None
        expected = max(1, math.floor((now - start) / settings["expected_interval_seconds"]) + 1) if start is not None else 0
        slots = {
            math.floor((row["received_at"] - start) / settings["expected_interval_seconds"])
            for row in rows
            if row["upstream_quality"] == row["downstream_quality"] == "good"
        } if start is not None else set()
        return {
            "schema_version": 1, "mode": mode, "asset": {
                key: settings[key] for key in ("asset_id", "asset_name", "operator", "location", "device_id")
            },
            "settings": settings, "server_time": now, "latest": latest, "history": rows,
            "pond": pond_monitor.pond_status(connection, latest, connection_state, settings, profile_key),
            "refill": pond_monitor.refill_snapshot(connection, now, settings, profile_key),
            "summary": {
                "connection": connection_state, "age_seconds": round(age, 1) if age is not None else None,
                "total_readings": aggregate["count"], "window_received": len(rows), "window_valid_pairs": good_count,
                "expected_slots": expected, "valid_slots": len(slots),
                "coverage_percent": round(min(100, len(slots) / expected * 100), 1) if expected else None,
                "water_state": water_state, "last_confirmed_high_at": last_confirmed_at,
                "confirmation_seconds": round(max(0, latest["sampled_at"] - high_since), 1) if latest and high_since is not None else 0,
            },
        }

    @app.get("/api/status")
    def get_status():
        return jsonify(snapshot())

    @app.post("/api/refill/start")
    def start_refill():
        connection = database()
        connection.execute("BEGIN IMMEDIATE")
        try:
            run_id = pond_monitor.start_refill(connection, request.get_json(silent=True), app.config["CLOCK"](), settings, profile_key)
        except ValueError as error:
            connection.rollback()
            return jsonify(error=str(error)), 400
        connection.commit()
        return jsonify(status="running", run_id=run_id), 201

    @app.post("/api/refill/cancel")
    def cancel_refill():
        connection = database()
        connection.execute("BEGIN IMMEDIATE")
        run = connection.execute("SELECT * FROM refill_runs WHERE status='running'").fetchone()
        if run:
            pond_monitor.finish(connection, run, "cancelled", "Operator cancelled. STOP the manual pump.", app.config["CLOCK"]())
        connection.commit()
        return jsonify(status="cancelled" if run else "idle")

    @app.get("/api/refill/export.csv")
    def export_refill():
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        fields = ("id", "phase", "status", "started_at", "finished_at", "start_up", "start_pond", "end_up", "end_pond", "elapsed", "baseline_seconds", "reason")
        writer.writerow(fields)
        for row in database().execute("SELECT * FROM refill_runs ORDER BY id"):
            writer.writerow(tuple(row[key] for key in fields))
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="stormready_{mode}_refill_checks.csv"'})

    @app.get("/api/export.csv")
    def export_csv():
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(("id", "received_at_utc", "sampled_at_utc") + READING_FIELDS)
        for row in database().execute("SELECT * FROM readings ORDER BY id"):
            writer.writerow((row["id"], utc_iso(row["received_at"]), utc_iso(row["sampled_at"])) + tuple(row[key] for key in READING_FIELDS))
        return Response(
            output.getvalue(), mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="stormready_{mode}_readings.csv"'},
        )

    import incident_workflow
    incident_workflow.register(app, database, settings, profile_key)

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("simulation", "hardware"), default="simulation")
    parser.add_argument("--host", default="127.0.0.1", help="Keep the default for this milestone")
    parser.add_argument("--port", type=int, default=5050, help="5050 avoids macOS AirPlay's common port conflict")
    args = parser.parse_args()
    app = create_app(args.mode)
    print(f"StormReady | {args.mode.upper()} | http://127.0.0.1:{args.port}", flush=True)
    print(f"Readings persist in data/{args.mode}.sqlite3. Press Control+C to stop.", flush=True)
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
