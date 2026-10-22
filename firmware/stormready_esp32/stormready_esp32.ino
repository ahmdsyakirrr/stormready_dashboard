// StormReady milestone 2. Open THIS FILE in Arduino IDE, retaining its two .h files.
// Hardware: classic ESP32-WROOM dev board + two standard 5 V HC-SR04 sensors.
// Wiring and divider placement: see START_HERE_MACOS.md and HC_SR04_Wiring.png.
#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <esp_system.h>
#include <esp_timer.h>
#include "settings.h"
#include "measurement.h"

using stormready::Distance;
using stormready::Level;

char bootId[40];
uint64_t sequenceNumber = 0;
uint64_t lastWifiAttemptMs = 0;

uint64_t monotonicMs() {
  return static_cast<uint64_t>(esp_timer_get_time()) / 1000ULL;
}

float readOneDistance(int trigPin, int echoPin) {
  // A clone whose Echo is stuck high must not become a plausible distance.
  if (digitalRead(echoPin) == HIGH) {
    delay(70);
    return NAN;
  }
  digitalWrite(trigPin, LOW);
  delayMicroseconds(3);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(12);
  digitalWrite(trigPin, LOW);
  const unsigned long duration = pulseIn(echoPin, HIGH, 25000UL);
  // Only one transducer is triggered at a time; at least 70 ms of quiet follows.
  delay(70);
  return duration == 0 ? NAN : static_cast<float>(duration) * 0.343f / 2.0f;
}

void printSensor(const char* label, const Distance& distance, const Level& level) {
  Serial.print(label);
  Serial.print(" distance=");
  if (distance.valid) Serial.print(distance.mm, 1);
  else Serial.print("INVALID");
  Serial.print(" mm ["); Serial.print(distance.reason); Serial.print("]  level=");
  if (level.valid) Serial.print(level.mm, 1);
  else Serial.print("UNKNOWN");
  Serial.print(" mm ["); Serial.print(level.reason); Serial.println("]");
}

String jsonLevel(const Level& level) {
  return level.valid ? String(level.mm, 1) : String("null");
}

String makePacket(const Level& upstream, const Level& downstream,
                  uint64_t sampleStartMs) {
  const uint64_t now = monotonicMs();
  char counters[240];
  snprintf(counters, sizeof(counters),
      "\",\"sequence\":%llu,\"uptime_ms\":%llu,\"sample_age_ms\":%llu,",
      static_cast<unsigned long long>(sequenceNumber),
      static_cast<unsigned long long>(now),
      static_cast<unsigned long long>(now - sampleStartMs));
  String body;
  body.reserve(550);
  body = "{\"schema_version\":1,\"device_id\":\"";
  body += DEVICE_ID;
  body += "\",\"boot_id\":\"";
  body += bootId;
  body += counters;
  body += "\"source\":\"esp32\",\"upstream_mm\":";
  body += jsonLevel(upstream);
  body += ",\"downstream_mm\":";
  body += jsonLevel(downstream);
  body += ",\"upstream_valid\":";
  body += upstream.valid ? "true" : "false";
  body += ",\"downstream_valid\":";
  body += downstream.valid ? "true" : "false";
  body += "}";
  return body;
}

void sendCurrentReading(const Level& upstream, const Level& downstream,
                        uint64_t sampleStartMs) {
  if (!WIFI_ENABLED) return;
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi offline: current sample discarded; no old readings queued.");
    const uint64_t now = monotonicMs();
    if (now - lastWifiAttemptMs >= 10000ULL) {
      lastWifiAttemptMs = now;
      WiFi.reconnect();
    }
    return;
  }
  WiFiClient client;
  HTTPClient http;
  http.setConnectTimeout(1000);
  http.setTimeout(1000);
  const String url = String(SERVER_BASE_URL) + "/api/readings";
  if (!http.begin(client, url)) {
    Serial.println("HTTP setup failed: check SERVER_BASE_URL.");
    return;
  }
  http.addHeader("Content-Type", "application/json");
  // Measure age immediately before transmission. Never retry an old packet.
  const String packet = makePacket(upstream, downstream, sampleStartMs);
  const int status = http.POST(packet);
  Serial.print("HTTP "); Serial.println(status);
  if (status > 0 && status != 200 && status != 201) Serial.println(http.getString());
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  pinMode(UPSTREAM_TRIG, OUTPUT);
  pinMode(UPSTREAM_ECHO, INPUT);
  digitalWrite(UPSTREAM_TRIG, LOW);
  if (SENSOR_COUNT == 2) {
    pinMode(DOWNSTREAM_TRIG, OUTPUT);
    pinMode(DOWNSTREAM_ECHO, INPUT);
    digitalWrite(DOWNSTREAM_TRIG, LOW);
  }
  snprintf(bootId, sizeof(bootId), "esp32-%08lx-%08lx-%08lx",
      static_cast<unsigned long>(esp_random()),
      static_cast<unsigned long>(esp_random()),
      static_cast<unsigned long>(esp_random()));
  Serial.println("StormReady: real sensor test. Units: millimetres.");
  Serial.println("HC-SR04 ECHO divider: 2x1k upper, 3x1k lower in series to GND.");
  if (WIFI_ENABLED) {
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    lastWifiAttemptMs = monotonicMs();
    Serial.println("Connecting to Wi-Fi; serial measurement continues meanwhile.");
  } else {
    Serial.println("Wi-Fi OFF: Serial Monitor test only.");
  }
}

void loop() {
  const uint64_t started = monotonicMs();
  float a[stormready::BURST_SIZE];
  float b[stormready::BURST_SIZE];
  for (std::size_t i = 0; i < stormready::BURST_SIZE; ++i) {
    a[i] = readOneDistance(UPSTREAM_TRIG, UPSTREAM_ECHO);
    b[i] = SENSOR_COUNT == 2
        ? readOneDistance(DOWNSTREAM_TRIG, DOWNSTREAM_ECHO) : NAN;
  }
  const Distance distanceA = stormready::filterBurst(a, stormready::BURST_SIZE);
  const Distance distanceB = stormready::filterBurst(b, stormready::BURST_SIZE);
  const Level levelA = stormready::waterLevel(distanceA,
      UPSTREAM_SENSOR_TO_FLOOR_MM, UPSTREAM_USABLE_DEPTH_MM);
  const Level levelB = stormready::waterLevel(distanceB,
      DOWNSTREAM_SENSOR_TO_FLOOR_MM, DOWNSTREAM_USABLE_DEPTH_MM);
  printSensor("UP", distanceA, levelA);
  if (SENSOR_COUNT == 2) printSensor("DOWN", distanceB, levelB);
  sendCurrentReading(levelA, levelB, started);
  ++sequenceNumber;
  const uint64_t elapsed = monotonicMs() - started;
  if (elapsed < 1000ULL) delay(static_cast<unsigned long>(1000ULL - elapsed));
}
