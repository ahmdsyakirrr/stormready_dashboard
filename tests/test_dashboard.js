// Optional pure client-logic checks. No browser or third-party packages required.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor() { this.textContent = ""; this.children = []; this.attributes = {}; this.hidden = false; }
  appendChild(node) { this.children.push(node); return node; }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this.attributes[name] = value; }
}
const nodes = new Map();
const context = vm.createContext({
  document: {
    getElementById(id) { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); },
    createElement: () => new Element(), createElementNS: () => new Element(),
  },
  Intl, Date, Number, String, Object, Math,
});
const script = fs.readFileSync(path.join(__dirname, "../static/dashboard.js"), "utf8").replace(/\npoll\(\);\s*$/, "\n");
vm.runInContext(script, context);
const read = (id) => nodes.get(id).textContent;
const data = {
  mode: "simulation", server_time: 1800000000,
  settings: {history_seconds: 120, upstream_max_mm: 160, downstream_max_mm: 250, high_water_mm: 100, high_water_hold_seconds: 5, max_gap_seconds: 3},
  latest: {received_at: 1800000000, upstream_mm: 0, downstream_mm: 16, upstream_current_quality: "good", downstream_current_quality: "good"},
  summary: {connection: "online", age_seconds: 0, water_state: "below_threshold", total_readings: 1, window_received: 1, window_valid_pairs: 1, coverage_percent: 100, expected_slots: 1, valid_slots: 1},
  history: [],
};
context.fixture = data;
vm.runInContext("render(fixture)", context);
assert.equal(read("upstream"), "0.0", "A valid zero level must remain visible");
assert.equal(read("downstream"), "16.0");

data.latest.upstream_current_quality = "offline";
data.latest.downstream_current_quality = "offline";
data.summary.connection = "offline";
data.summary.water_state = "unknown";
vm.runInContext("render(fixture)", context);
assert.equal(read("upstream"), "—", "Old stored values must not be shown as current");
assert.equal(read("downstream"), "—");
assert.equal(read("water-state"), "Unknown");

data.latest.upstream_current_quality = "out_of_range";
data.latest.upstream_mm = 300;
vm.runInContext("render(fixture)", context);
assert.equal(read("upstream"), "—", "An implausible raw value must not become a current reading");

vm.runInContext("disconnected()", context);
assert.equal(read("connection"), "Dashboard disconnected");
assert.equal(read("coverage"), "—");
assert.equal(read("water-state"), "Unknown");
assert.equal(nodes.get("network-warning").hidden, false);

data.history = [
  {sampled_at: 1799999996, boot_id: "a", upstream_mm: 40, downstream_mm: 10, upstream_quality: "good", downstream_quality: "good"},
  {sampled_at: 1799999997, boot_id: "a", upstream_mm: null, downstream_mm: 10, upstream_quality: "invalid", downstream_quality: "good"},
  {sampled_at: 1799999998, boot_id: "a", upstream_mm: 42, downstream_mm: 10, upstream_quality: "good", downstream_quality: "good"},
];
vm.runInContext("renderChart(fixture)", context);
const upstreamPath = nodes.get("chart").children.find((node) => node.attributes.stroke === "#0b9687" && node.attributes.d);
assert.equal((upstreamPath.attributes.d.match(/M/g) || []).length, 2, "The upstream chart must break across an invalid reading");
assert.equal((upstreamPath.attributes.d.match(/L/g) || []).length, 0);
console.log("PASS: zero values; stale/invalid data; backend disconnection; chart gaps");
