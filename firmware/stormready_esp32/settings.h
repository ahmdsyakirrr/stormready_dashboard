#pragma once

// Standard HC-SR04: 5 V power and ONE VOLTAGE DIVIDER ON EACH ECHO.
// Echo -> 1 kohm -> 1 kohm -> junction -> ESP32 input.
// Junction -> 1 kohm -> 1 kohm -> 1 kohm -> GND (all in SERIES).
// Five 1 kohm resistors per sensor; ten for both sensors.
// NEVER connect the raw Echo to the ESP32.

constexpr int UPSTREAM_TRIG = 25;
constexpr int UPSTREAM_ECHO = 26;
constexpr int DOWNSTREAM_TRIG = 27;
constexpr int DOWNSTREAM_ECHO = 33;

// Start with sensor A only. Change to 2 after sensor A passes the dry test.
constexpr int SENSOR_COUNT = 2;

// Leave these at zero for the dry distance test. Calibrate each mounted sensor
// separately before trying to display water depth. See START_HERE_MACOS.md.
constexpr float UPSTREAM_SENSOR_TO_FLOOR_MM = 300.8f;
constexpr float DOWNSTREAM_SENSOR_TO_FLOOR_MM = 301.2f;
// Maximum safe water depth measured from the same floor (leave freeboard).
constexpr float UPSTREAM_USABLE_DEPTH_MM = 75.0f;
constexpr float DOWNSTREAM_USABLE_DEPTH_MM = 80.0f;

// Wi-Fi is optional and OFF during the hardware/calibration tests.
constexpr bool WIFI_ENABLED = true;
const char WIFI_SSID[] = "YOUR_WIFI_NAME";
const char WIFI_PASSWORD[] = "YOUR_WIFI_PASSWORD";
// Use your Mac's LOCAL NETWORK IPv4 address, never 127.0.0.1 or 0.0.0.0 here.
const char SERVER_BASE_URL[] = "http://YOUR_COMPUTER_IP:5050";
const char DEVICE_ID[] = "stormready-esp32-01";

static_assert(SENSOR_COUNT == 1 || SENSOR_COUNT == 2,
              "SENSOR_COUNT must be 1 or 2");
