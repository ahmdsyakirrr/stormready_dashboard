"use strict";
const assert = require("node:assert/strict");
const Model = require("../static/monitor.js");
function fixture(state = "below_threshold", up = 25, down = 35) {
  return {mode: "hardware", server_time: 1000, settings: {upstream_max_mm: 75, downstream_max_mm: 80, high_water_mm: 50, high_water_clear_mm: 40, high_water_hold_seconds: 5, stale_after_seconds: 10, max_gap_seconds: 3, history_seconds: 120}, latest: {boot_id: "a", sampled_at: 1000, received_at: 1000, upstream_mm: up, downstream_mm: down, upstream_current_quality: "good", downstream_current_quality: "good"}, summary: {connection: "online", water_state: state, confirmation_seconds: 2}, history: []};
}
let checks = 0;
function check(name, fn) {fn(); checks += 1; console.log(`PASS: ${name}`);}
check("Valid zero depths are shown; non-finite and out-of-range values are not", () => {
  const data = fixture("below_threshold", 0, 0);
  assert.equal(Model.currentLevel(data, "upstream"), 0);
  for (const value of [null, NaN, Infinity, -1, 75.1, "35"]) {data.latest.upstream_mm = value; assert.equal(Model.currentLevel(data, "upstream"), null);}
});
check("Neither held raw values nor quality failures become current readings", () => {
  const data = fixture();
  for (const quality of ["invalid", "out_of_range", "stale_sample", "offline"]) {data.latest.upstream_current_quality = quality; assert.equal(Model.currentLevel(data, "upstream"), null);}
  data.latest.upstream_current_quality = "good"; data.summary.connection = "offline";
  assert.equal(Model.currentLevel(data, "upstream"), null);
});
check("Confirmation produces no premature critical pop-up", () => {
  const session = Model.initialSession(), data = fixture("confirming", 60);
  assert.equal(Model.advance(session, data).opened, false);
  assert.equal(session.episode, null);
  assert.equal(Model.condition(data, session).tone, "warning");
});
check("A high-water episode opens once, including after session restore", () => {
  const session = Model.initialSession(), data = fixture("high_water", 60);
  assert.equal(Model.advance(session, data).opened, true);
  for (let n = 0; n < 20; n++) {data.server_time++; assert.equal(Model.advance(session, data).opened, false);}
  assert.equal(session.events.length, 1);
  assert.equal(Model.advance(JSON.parse(JSON.stringify(session)), data).opened, false);
});
check("Acknowledgement silences attention without resolving the water alert", () => {
  const session = Model.initialSession(), data = fixture("high_water", 60);
  Model.advance(session, data);
  assert.equal(Model.acknowledge(session, 1001), true);
  assert.equal(Model.acknowledge(session, 1002), false);
  assert.ok(session.episode);
  assert.equal(Model.condition(data, session).tone, "critical");
});
check("Offline, bad readings and an unconfirmed middle level cannot clear an alert", () => {
  const session = Model.initialSession(); Model.advance(session, fixture("high_water", 60));
  const offline = fixture("unknown", 0); offline.summary.connection = "offline";
  assert.equal(Model.advance(session, offline).cleared, false);
  const invalid = fixture("unknown", 0); invalid.latest.upstream_current_quality = "invalid";
  assert.equal(Model.advance(session, invalid).cleared, false);
  assert.equal(Model.advance(session, fixture("below_threshold", 45)).cleared, false);
  assert.equal(Model.advance(session, fixture("below_threshold", 40)).cleared, false);
  assert.equal(Model.condition(null, session).tone, "critical");
  assert.equal(Model.condition(null, session).water, "Unknown");
});
check("Fresh readings strictly below the clearing limit resolve and permit a later new alert", () => {
  const session = Model.initialSession(); Model.advance(session, fixture("high_water", 60));
  assert.equal(Model.advance(session, fixture("below_threshold", 39.9)).cleared, true);
  assert.equal(session.episode, null);
  assert.equal(Model.advance(session, fixture("high_water", 60)).opened, true);
});
check("A downstream fault never hides confirmed upstream high water", () => {
  const session = Model.initialSession(), data = fixture("high_water", 60, null); data.latest.downstream_current_quality = "invalid";
  Model.advance(session, data);
  assert.equal(Model.condition(data, session).tone, "critical");
});
check("An unknown backend state never turns green from a numeric reading alone", () => {
  const condition = Model.condition(fixture("unknown"), Model.initialSession());
  assert.notEqual(condition.tone, "normal"); assert.equal(condition.water, "Unknown");
});
check("Charts break across invalid data, device restarts and missing intervals", () => {
  const settings = fixture().settings;
  const rows = [{sampled_at: 990, boot_id: "a", upstream_mm: 20, upstream_quality: "good"}, {sampled_at: 991, boot_id: "a", upstream_mm: null, upstream_quality: "invalid"}, {sampled_at: 992, boot_id: "a", upstream_mm: 22, upstream_quality: "good"}, {sampled_at: 993, boot_id: "b", upstream_mm: 23, upstream_quality: "good"}, {sampled_at: 999, boot_id: "b", upstream_mm: 24, upstream_quality: "good"}];
  assert.equal(Model.chartSegments(rows, "upstream", 980, 1000, settings).length, 4);
  assert.deepEqual(Model.chartSegments([{...rows[0], upstream_mm: 999}], "upstream", 980, 1000, settings), []);
});
check("Trend labels do not bridge sensor gaps", () => {
  const data = fixture();
  data.history = Array.from({length: 6}, (_, i) => ({sampled_at: 995 + i, boot_id: "a", upstream_mm: 20 + i, upstream_quality: "good"}));
  assert.equal(Model.sensorTrend(data, "upstream").direction, "rising");
  data.history[3].upstream_quality = "invalid";
  assert.equal(Model.sensorTrend(data, "upstream").direction, "unknown");
});
check("Pond-only high water alerts even when upstream is invalid", () => {
  const data=fixture("unknown",null,65),session=Model.initialSession();
  data.latest.upstream_current_quality="invalid";
  data.settings.pond_high_water_mm=60;data.settings.pond_high_water_clear_mm=50;
  data.pond={water_state:"high_water"};
  assert.deepEqual(Model.advance(session,data).openedSensors,["downstream"]);
  assert.equal(Model.condition(data,session).water,"Pond high water");
  assert.equal(Model.condition(data,session).tone,"critical");
});
check("Simultaneous alerts clear independently and a new location reopens attention", () => {
  const data=fixture("high_water",60,65),session=Model.initialSession();
  data.settings.pond_high_water_mm=60;data.settings.pond_high_water_clear_mm=50;
  data.pond={water_state:"high_water"};
  assert.equal(Model.advance(session,data).openedSensors.length,2);
  Model.acknowledge(session,1001);
  data.summary.water_state="below_threshold";data.latest.upstream_mm=35;
  assert.deepEqual(Model.advance(session,data).clearedSensors,["upstream"]);
  assert.ok(session.episodes.downstream.acknowledged);
  data.summary.water_state="high_water";data.latest.upstream_mm=60;
  assert.deepEqual(Model.advance(session,data).openedSensors,["upstream"]);
  assert.equal(session.episodes.upstream.acknowledged,false);
  data.pond.water_state="unknown";data.latest.downstream_current_quality="invalid";
  assert.equal(Model.advance(session,data).cleared,false);
  data.pond.water_state="below_threshold";data.latest.downstream_current_quality="good";
  data.latest.downstream_mm=50;assert.equal(Model.advance(session,data).cleared,false);
  data.latest.downstream_mm=49;assert.deepEqual(Model.advance(session,data).clearedSensors,["downstream"]);
  assert.ok(session.episodes.upstream);
});
console.log(`${checks} dashboard behaviour checks passed.`);
