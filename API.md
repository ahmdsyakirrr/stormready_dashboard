# StormReady telemetry API — schema 1

This contract supports the simulator now and ESP32 firmware in a later milestone.
It accepts calibrated **water level in millimetres**, not ultrasonic distance.
Hardware conversion and range calibration must happen before a reading is sent.

## Send a reading

`POST /api/readings` with `Content-Type: application/json`.

```json
{
  "schema_version": 1,
  "device_id": "stormready-esp32-01",
  "boot_id": "sim-example-01",
  "sequence": 0,
  "uptime_ms": 1000,
  "sample_age_ms": 0,
  "source": "simulator",
  "upstream_mm": 45.2,
  "downstream_mm": 16.1,
  "upstream_valid": true,
  "downstream_valid": true
}
```

All fields are required. Additional fields are rejected to catch firmware mistakes.

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer `1` |
| `device_id` | Must match `config.json` |
| `boot_id` | New unique identifier every sender restart; 1–64 letters, digits, `_`, `-`, `.` or `:` |
| `sequence` | Increasing non-negative integer, at most 2^53−1, within the boot |
| `uptime_ms` | Non-decreasing milliseconds since sender start, at most 2^53−1 |
| `sample_age_ms` | Age since measurement, reported at transmission; integer 0–3,600,000 |
| `source` | `simulator` for simulation mode; `esp32` for hardware mode |
| `upstream_mm`, `downstream_mm` | Finite numeric level or `null`; never a numeric string |
| `upstream_valid`, `downstream_valid` | JSON booleans, not strings or integers |

When a measurement fails, send `null` and `false`. A valid zero-millimetre level
is different from a missing value and is preserved as zero.

At the default settings, an age over 3,000 ms is stored with `stale_sample`
quality. Do not label a queued old sample as freshly measured. The source field
is a provenance label, not device authentication.

### Responses

- **201:** a new packet was stored.
- **200:** an identical normalized packet with the same device/boot/sequence was
  already stored. This does not refresh its receipt time or high-water timer.
- **400:** wrong schema, source, device ID, field types or unsupported values.
- **409:** a sequence number conflicts, packets arrive out of order, or an old
  boot resumes after a newer boot has started.
- **415:** the request is not JSON.
- **413:** payload exceeds 8 KiB.

Implausible numeric levels are retained for inspection, with `out_of_range`
quality. They are not usable current measurements. A `null` value, even if the
sender incorrectly marks it valid, is stored as invalid.

## Read status

`GET /api/status` returns the configured asset, mode, latest stored packet,
current quality, recent history and summary. Raw values are historical evidence;
current presentation must use `upstream_current_quality` and
`downstream_current_quality`. Do not display a raw latest value as current when
its current quality is not `good`.

Connection states are `waiting`, `online`, and `offline`. An online connection
does not imply valid sensor data. Water states are `unknown`, `below_threshold`,
`confirming`, and `high_water`. None of these is a maintenance-verification result.

High-water confirmation uses elapsed sample time, a maximum gap, a boot boundary,
and upstream quality. Confirmed high water remains indicated in the hysteresis
band until a valid level is below the clear threshold. Missing upstream data,
an excessive gap or a new boot interrupts confirmation; data loss produces
unknown current conditions rather than a safe condition. This is a current
indication only; incident retention is a later milestone.

## Other endpoints

| Endpoint | Result |
| --- | --- |
| `GET /api/health` | Server/database availability, mode and schema version |
| `GET /api/export.csv` | All stored readings, source, quality and UTC timestamps |
| `GET /` | Dashboard |

The app listens on `127.0.0.1:5050` by default. Network exposure and device access
controls will be configured with the physical ESP32 integration milestone.
