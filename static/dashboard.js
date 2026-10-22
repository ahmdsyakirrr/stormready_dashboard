"use strict";

const Model = window.StormReadyModel;
const el = id => document.getElementById(id);
const colors = {upstream: "#0c7660", downstream: "#3974b6"};
const timeFormat = new Intl.DateTimeFormat("en-MY", {timeZone: "Asia/Kuala_Lumpur", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false});
const dateFormat = new Intl.DateTimeFormat("en-MY", {timeZone: "Asia/Kuala_Lumpur", day: "2-digit", month: "short", year: "numeric"});
const formatTime = seconds => timeFormat.format(new Date(seconds * 1000));
const levelText = value => value == null ? "—" : Number(value).toFixed(1);
const text = (id, value) => {const node = el(id); if (node.textContent !== String(value)) node.textContent = String(value);};
const qualityLabels = {good: "Valid reading", invalid: "Reading unavailable", out_of_range: "Outside depth range", stale_sample: "Sample too old", offline: "No recent data", waiting: "Waiting for a reading"};
const sessionKey = `stormready.console.v3:${document.body.dataset.mode}:${document.body.dataset.asset}`;
let session = Model.initialSession();
try {
  const saved = JSON.parse(sessionStorage.getItem(sessionKey));
  if (saved && Array.isArray(saved.events) && Number.isFinite(saved.counter) && (!saved.episode || (typeof saved.episode.id === "string" && Number.isFinite(saved.episode.startedAt) && typeof saved.episode.acknowledged === "boolean"))) {
    session = saved;
    session.events = saved.events.filter(event => Number.isFinite(event.at) && typeof event.title === "string" && typeof event.detail === "string").slice(0, 30);
  }
} catch (_error) { /* Monitoring remains usable if browser storage is restricted. */ }

const ui = {data: null, dashboardOnline: false, window: 120, visible: {upstream: true, downstream: true}, previousCondition: null, previousConnection: null, lastSaved: "", lastActivity: "", inspectedTime: null, chartRows: [], geometry: null, preview: false, audioEnabled: false, audio: null, masterGain: null, lastAlarmAt: 0};
function saveSession() {
  const serialized = JSON.stringify(session);
  if (serialized === ui.lastSaved) return;
  try {sessionStorage.setItem(sessionKey, serialized);} catch (_error) { /* Session alerts continue in memory. */ }
  ui.lastSaved = serialized;
}
function icon(name, extraClass = "") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", `icon ${extraClass}`);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`); svg.appendChild(use); return svg;
}
function announce(message) {text("announcer", message);}
function toast(message, tone = "normal") {
  const node = document.createElement("div"); node.className = `toast ${tone}`;
  node.appendChild(icon(tone === "normal" ? "check" : "alert"));
  const copy = document.createElement("span"); copy.textContent = message; node.appendChild(copy);
  const close = document.createElement("button"); close.type = "button"; close.setAttribute("aria-label", "Dismiss notification"); close.appendChild(icon("close")); close.addEventListener("click", () => node.remove()); node.appendChild(close);
  const stack = el("toast-stack"); stack.appendChild(node); if (stack.children.length > 3) stack.firstElementChild.remove();
  announce(message); setTimeout(() => node.remove(), 8500);
}
function renderActivity() {
  const key = JSON.stringify(session.events);
  if (key === ui.lastActivity) return;
  ui.lastActivity = key;
  const list = el("activity-list"); list.replaceChildren();
  if (!session.events.length) {const li = document.createElement("li"); li.className = "activity-empty"; li.textContent = "Connection changes and alerts will appear here."; list.appendChild(li); return;}
  session.events.slice(0, 6).forEach(event => {
    const li = document.createElement("li");
    const dot = document.createElement("span"); dot.className = `activity-dot ${event.kind}`; dot.setAttribute("aria-hidden", "true");
    const copy = document.createElement("div"); copy.className = "activity-text";
    const title = document.createElement("strong"); title.textContent = event.title;
    const detail = document.createElement("p"); detail.textContent = event.detail;
    copy.append(title, detail);
    const time = document.createElement("time"); time.className = "activity-time"; time.dateTime = new Date(event.at * 1000).toISOString(); time.textContent = formatTime(event.at);
    li.append(dot, copy, time); list.appendChild(li);
  });
}
function updateSensor(sensor, data) {
  const level = Model.currentLevel(data, sensor);
  const row = data && data.latest;
  const quality = !data ? "server_offline" : !row ? "waiting" : data.summary.connection === "offline" ? "offline" : row[`${sensor}_current_quality`];
  const maximum = data ? data.settings[`${sensor}_max_mm`] : Number(el(`${sensor}-progress`).getAttribute("aria-valuemax"));
  const percent = level === null ? 0 : Math.max(0, Math.min(100, level / maximum * 100));
  text(sensor, levelText(level));
  text(`${sensor}-quality`, !data ? "Dashboard unavailable" : qualityLabels[quality] || "Reading unavailable");
  el(`${sensor}-dot`).className = `quality-dot ${level !== null ? "good" : quality === "waiting" ? "" : "bad"}`;
  el(`${sensor}-fill`).style.width = `${percent}%`;
  el(`${sensor}-water`).style.height = `${percent}%`;
  el(`${sensor}-unknown`).hidden = level !== null;
  text(`${sensor}-capacity`, level === null ? "Depth unavailable" : `${Math.round(percent)}% of configured depth`);
  const progress = el(`${sensor}-progress`);
  if (level === null) {progress.removeAttribute("aria-valuenow"); progress.setAttribute("aria-valuetext", "Unavailable");}
  else {progress.setAttribute("aria-valuenow", String(level)); progress.setAttribute("aria-valuetext", `${level.toFixed(1)} of ${maximum} millimetres`);}
  const trend = data ? Model.sensorTrend(data, sensor) : {label: "Trend unavailable", direction: "unknown"};
  const trendNode = el(`${sensor}-trend`); trendNode.replaceChildren();
  if (trend.direction !== "unknown") trendNode.appendChild(icon(trend.direction === "rising" ? "up" : trend.direction === "falling" ? "down" : "minus"));
  trendNode.appendChild(document.createTextNode(trend.label));
  el(`${sensor}-card`).classList.toggle("alerting", !!session.episodes?.[sensor] && level !== null);
  if (data) el(sensor === "upstream" ? "tank-threshold" : "pond-tank-threshold").style.bottom = `${(sensor === "upstream" ? data.settings.high_water_mm : data.settings.pond_high_water_mm) / maximum * 100}%`;
}
function renderCondition(data) {
  const condition = Model.condition(data, session);
  const banner = el("condition-banner"); banner.className = `condition-banner ${condition.tone}`;
  text("condition-kicker", condition.kicker); text("condition-title", condition.title); text("condition-detail", condition.detail); text("condition-badge", condition.badge);
  banner.querySelector(".condition-symbol").replaceChildren(icon(condition.tone === "critical" || condition.tone === "warning" ? "alert" : "shield"));
  el("banner-review").hidden = !session.episode;
  text("condition-time", data && data.latest ? `Updated ${formatTime(data.latest.received_at)} MYT` : "Awaiting fresh data");
  text("water-state", condition.water);
  text("water-detail", session.episode ? "Each location clears independently. Acknowledgement does not resolve the water condition." : data ? `Upstream ${data.settings.high_water_mm} mm · Pond ${data.settings.pond_high_water_mm} mm.` : "Current readings unavailable.");
  el("water-state").closest("article").dataset.tone = condition.tone;
  const confirming = data && (data.summary.water_state === "confirming" || data.pond?.water_state === "confirming") && !session.episode;
  el("confirmation-track").hidden = !confirming;
  if (confirming) el("confirmation-fill").style.width = `${Math.min(100, Math.max(data.summary.confirmation_seconds / data.settings.high_water_hold_seconds, (data.pond?.confirmation_seconds || 0) / data.settings.pond_high_water_hold_seconds) * 100)}%`;
  const key = `${condition.tone}:${condition.kicker}`;
  if (ui.previousCondition && key !== ui.previousCondition && !session.episode && condition.tone === "warning") toast(condition.title, "warning");
  ui.previousCondition = key;
  renderAlertCenter(data, condition);
}
function renderAlertCenter(data, condition) {
  const active = !!session.episode;
  const acknowledged = active && session.episode.acknowledged;
  el("nav-alert-count").hidden = !active;
  text("alert-count", active ? `${Object.keys(session.episodes || {}).length} active` : condition.tone === "warning" ? "Check data" : "0 active");
  el("alert-count").className = `count-pill ${active ? "critical" : ""}`;
  el("alert-current").className = `alert-current ${condition.tone}`;
  el("alert-current-icon").replaceChildren(icon(active || condition.tone === "warning" ? "alert" : condition.tone === "normal" ? "shield" : "bell"));
  text("alert-current-tag", active ? Object.keys(session.episodes || {}).map(sensor=>sensor==="upstream"?"UPSTREAM":"RETENTION POND").join(" + ") : condition.tone === "warning" ? "ATTENTION REQUIRED" : "MONITORING STATUS");
  text("alert-current-title", active ? Object.keys(session.episodes || {}).some(sensor=>Model.currentLevel(data, sensor) === null) ? "Alert unresolved · some levels unknown" : "High-water alert active" : condition.tone === "normal" ? "No active high-water alert" : condition.water === "Confirming" ? "Checking high water" : condition.water === "Unknown" ? "Live state unavailable" : "Check reading quality");
  text("alert-current-detail", active ? acknowledged ? "Acknowledged in this browser. The warning remains until fresh readings meet the clearing condition." : "Inspect the affected locations, water paths and pump if relevant. Acknowledge after reviewing the visible alerts." : condition.tone === "normal" ? "Both locations are below their alert thresholds. Live monitoring continues." : condition.detail);
  el("acknowledge-button").hidden = !active || acknowledged;
  el("acknowledged-note").hidden = !acknowledged;
  if (el("alert-dialog").open && !ui.preview) updateDialogReading(data);
}
function updateDialogReading(data) {
  const sensor=session.episode?.sensor || "upstream";
  const value=Model.currentLevel(data,sensor);
  text("dialog-level",levelText(value));
  text("dialog-reading-label",`${sensor === "downstream" ? "RETENTION POND" : "UPSTREAM"} ${value===null?"DEPTH UNAVAILABLE":"WATER DEPTH"}`);
  if(data) text("dialog-threshold",sensor === "downstream" ? data.settings.pond_high_water_mm : data.settings.high_water_mm);
}
function openAlert(preview = false) {
  if (!preview && !session.episode) return;
  if (el("profile-dialog").open) el("profile-dialog").close();
  ui.preview = preview;
  const dialog = el("alert-dialog"); dialog.dataset.test = String(preview);
  text("dialog-tag", preview ? "TEST NOTIFICATION · PREVIEW ONLY" : "HIGH-WATER ALERT");
  text("dialog-title", preview ? "This is how an alert gets noticed." : `${Object.keys(session.episodes || {}).map(sensor=>sensor === "upstream"?"Upstream":"Retention pond").join(" + ")} high water`);
  text("dialog-description", preview ? "This preview does not change your sensor readings or create a real water-level alert." : "High water has been confirmed at the location(s) named above. Inspect water paths and receiving capacity. High pond water alone does not confirm a broken pump.");
  text("dialog-guidance", preview ? "Real alerts use this pop-up, a persistent red banner and an optional sound. Acknowledge a real alert to silence its reminder in this browser." : "Acknowledging records that you have seen this alert in this browser. Each warning stays visible until fresh readings confirm that location is below its own clearing limit.");
  text("dialog-acknowledge", preview ? "Close preview" : session.episode && Object.values(session.episodes || {}).every(item=>item.acknowledged) ? "Already acknowledged · close" : "Acknowledge alert");
  text("dialog-review", preview ? "Play test sound" : "View live readings");
  updateDialogReading(ui.dashboardOnline ? ui.data : null);
  if (!dialog.open) dialog.showModal();
  if (preview) {if (ui.audioEnabled) playAlarm();}
  else if (!session.episode.acknowledged) playAlarm();
}
function acknowledgeAlert() {
  if (Model.acknowledge(session, ui.data ? ui.data.server_time : Date.now() / 1000)) {
    saveSession(); renderActivity(); renderCondition(ui.dashboardOnline ? ui.data : null);
    toast("Alert acknowledged. The warning remains visible while the condition is unresolved.");
  }
  if (el("alert-dialog").open) el("alert-dialog").close();
}
function updateSoundUI() {
  text("sound-label", ui.audioEnabled ? "Mute sound" : "Enable sound");
  text("sound-status", ui.audioEnabled ? "Sound enabled" : "Sound off");
  el("sound-button").setAttribute("aria-pressed", String(ui.audioEnabled));
  el("sound-button").classList.toggle("sound-enabled", ui.audioEnabled);
  el("sound-button").querySelector("svg").replaceWith(icon(ui.audioEnabled ? "sound" : "mute"));
}
async function enableSound() {
  try {
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) throw new Error("unavailable");
    if (!ui.audio) {
      ui.audio = new Audio(); ui.masterGain = ui.audio.createGain(); ui.masterGain.connect(ui.audio.destination);
      ui.audio.addEventListener("statechange", () => {if (ui.audioEnabled && ui.audio.state !== "running") {ui.audioEnabled = false; updateSoundUI();}});
    }
    await ui.audio.resume();
    if (ui.audio.state !== "running") throw new Error("blocked");
    ui.masterGain.gain.setValueAtTime(.6, ui.audio.currentTime); ui.audioEnabled = true; updateSoundUI(); return true;
  } catch (_error) {ui.audioEnabled = false; updateSoundUI(); toast("Sound could not start. Click Enable sound again and check your browser and device audio settings.", "warning"); return false;}
}
function playAlarm() {
  if (!ui.audioEnabled || !ui.audio || ui.audio.state !== "running") return;
  const start = ui.audio.currentTime;
  [880, 660, 880].forEach((frequency, index) => {
    const oscillator = ui.audio.createOscillator(); const envelope = ui.audio.createGain();
    oscillator.type = "sine"; oscillator.frequency.value = frequency;
    const at = start + index * .24;
    envelope.gain.setValueAtTime(0, at); envelope.gain.linearRampToValueAtTime(.13, at + .015); envelope.gain.exponentialRampToValueAtTime(.001, at + .17);
    oscillator.connect(envelope); envelope.connect(ui.masterGain); oscillator.start(at); oscillator.stop(at + .19);
    oscillator.addEventListener("ended", () => {oscillator.disconnect(); envelope.disconnect();}, {once: true});
  });
  ui.lastAlarmAt = Date.now();
}

function svgNode(tag, attributes = {}, copy = "") {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
  if (copy) node.textContent = copy;
  return node;
}
function renderChart(data) {
  const chart = el("chart"); chart.replaceChildren();
  const width = 820, left = 45, top = 20, plotWidth = 748, plotHeight = 210;
  const duration = Math.min(ui.window, data.settings.history_seconds);
  const end = data.server_time, start = end - duration;
  const ceiling = Math.ceil(Math.max(data.settings.upstream_max_mm, data.settings.downstream_max_mm) / 20) * 20;
  const x = time => left + (time - start) / duration * plotWidth;
  const y = value => top + plotHeight - value / ceiling * plotHeight;
  ui.geometry = {x, y, start, end, width, left, plotWidth, top, plotHeight};
  chart.appendChild(svgNode("title", {}, "Recorded water levels in millimetres. Missing and invalid readings form gaps."));
  for (let tick = 0; tick <= 4; tick += 1) {
    const value = ceiling * tick / 4;
    chart.appendChild(svgNode("line", {x1: left, x2: left + plotWidth, y1: y(value), y2: y(value), stroke: "#e6eee8", "stroke-width": 1}));
    chart.appendChild(svgNode("text", {x: left - 11, y: y(value) + 3, "text-anchor": "end", class: "chart-axis"}, String(Math.round(value))));
    const time = start + duration * tick / 4;
    chart.appendChild(svgNode("text", {x: x(time), y: top + plotHeight + 26, "text-anchor": tick === 0 ? "start" : tick === 4 ? "end" : "middle", class: "chart-axis"}, formatTime(time)));
  }
  const pondThreshold=data.settings.pond_high_water_mm;
  if(Number.isFinite(pondThreshold)){
    chart.appendChild(svgNode("line",{x1:left,x2:left+plotWidth,y1:y(pondThreshold),y2:y(pondThreshold),stroke:"#b72d39","stroke-width":1.2,"stroke-dasharray":"3 5"}));
    chart.appendChild(svgNode("text",{x:left+4,y:y(pondThreshold)-7,class:"chart-threshold-label"},`Pond alert ${pondThreshold} mm`));
  }
  const threshold = data.settings.high_water_mm;
  chart.appendChild(svgNode("line", {x1: left, x2: left + plotWidth, y1: y(threshold), y2: y(threshold), stroke: "#ae791d", "stroke-width": 1.2, "stroke-dasharray": "5 5"}));
  chart.appendChild(svgNode("text", {x: left + plotWidth - 2, y: y(threshold) - 7, "text-anchor": "end", class: "chart-threshold-label"}, `Upstream alert ${threshold} mm`));
  let plotted = 0;
  ["upstream", "downstream"].forEach(sensor => {
    if (!ui.visible[sensor]) return;
    const segments = Model.chartSegments(data.history, sensor, start, end, data.settings);
    let path = "";
    segments.forEach(points => {
      plotted += points.length;
      const segment = points.map((point, index) => `${index ? "L" : "M"}${x(point.time).toFixed(2)},${y(point.value).toFixed(2)}`).join(" ");
      path += segment + " ";
      if (points.length > 1 && sensor === "upstream") chart.appendChild(svgNode("path", {d: `${segment} L${x(points[points.length - 1].time)},${y(0)} L${x(points[0].time)},${y(0)} Z`, fill: colors[sensor], opacity: ".045", "aria-hidden": "true"}));
      if (points.length === 1) chart.appendChild(svgNode("circle", {cx: x(points[0].time), cy: y(points[0].value), r: 2.3, fill: colors[sensor]}));
    });
    if (path) chart.appendChild(svgNode("path", {d: path, fill: "none", stroke: colors[sensor], "stroke-width": 2.4, "stroke-linecap": "round", "stroke-linejoin": "round", "data-sensor": sensor}));
  });
  if (!plotted) chart.appendChild(svgNode("text", {x: left + plotWidth / 2, y: top + plotHeight / 2, "text-anchor": "middle", class: "chart-empty"}, !ui.visible.upstream && !ui.visible.downstream ? "Choose a series above to display readings" : "Waiting for valid measurements"));
  chart.appendChild(svgNode("g", {id: "chart-cursor", "pointer-events": "none"}));
  ui.chartRows = data.history.filter(row => row.sampled_at >= start && row.sampled_at <= end);
  if (ui.inspectedTime !== null) inspectChart(ui.inspectedTime);
}
function inspectChart(at, keyboard = false) {
  if (!ui.chartRows.length || !ui.geometry || (!ui.visible.upstream && !ui.visible.downstream)) {el("chart-tooltip").hidden = true; return;}
  const row = ui.chartRows.reduce((best, item) => Math.abs(item.sampled_at - at) < Math.abs(best.sampled_at - at) ? item : best);
  ui.inspectedTime = row.sampled_at;
  const {x, y, top, plotHeight, width} = ui.geometry;
  const cursor = el("chart-cursor"); cursor.replaceChildren();
  cursor.appendChild(svgNode("line", {x1: x(row.sampled_at), x2: x(row.sampled_at), y1: top, y2: top + plotHeight, stroke: "#7d9690", "stroke-width": 1, "stroke-dasharray": "3 3"}));
  const tip = el("chart-tooltip"); tip.replaceChildren();
  const title = document.createElement("strong"); title.textContent = `${formatTime(row.sampled_at)} MYT · recorded`; tip.appendChild(title);
  const values = [];
  ["upstream", "downstream"].forEach(sensor => {
    if (!ui.visible[sensor]) return;
    const value = row[`${sensor}_mm`];
    const valid = row[`${sensor}_quality`] === "good" && typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= ui.data.settings[`${sensor}_max_mm`];
    if (valid) cursor.appendChild(svgNode("circle", {cx: x(row.sampled_at), cy: y(value), r: 4, fill: colors[sensor], stroke: "white", "stroke-width": 2}));
    const line = document.createElement("div"), label = document.createElement("span"), number = document.createElement("b");
    label.textContent = sensor === "upstream" ? "Upstream" : "Retention pond"; number.textContent = valid ? `${levelText(value)} mm` : "Unavailable";
    line.append(label, number); tip.appendChild(line); values.push(`${label.textContent} ${number.textContent}`);
  });
  tip.hidden = false;
  const chartWidth = el("chart").getBoundingClientRect().width;
  tip.style.left = `${Math.max(8, Math.min(chartWidth - tip.offsetWidth - 4, x(row.sampled_at) / width * chartWidth + 12))}px`;
  if (keyboard) announce(`${title.textContent}. ${values.join(". ")}.`);
}
function renderRows() {
  if (!ui.data) return;
  const search = el("reading-search").value.trim().toLowerCase();
  const filter = el("quality-filter").value;
  const limit = Number(el("row-limit").value);
  const matches = [...ui.data.history].reverse().filter(row => {
    const good = row.upstream_quality === "good" && row.downstream_quality === "good";
    if ((filter === "valid" && !good) || (filter === "issues" && good)) return false;
    return !search || [formatTime(row.received_at), row.sequence, levelText(row.upstream_mm), levelText(row.downstream_mm), qualityLabels[row.upstream_quality], qualityLabels[row.downstream_quality]].join(" ").toLowerCase().includes(search);
  });
  const body = el("reading-rows"); body.replaceChildren();
  if (!matches.length) {const tr = document.createElement("tr"), td = document.createElement("td"); td.colSpan = 5; td.className = "empty-row"; td.textContent = ui.data.history.length ? "No readings match your filters." : "No readings in the recent window."; tr.appendChild(td); body.appendChild(tr);}
  matches.slice(0, limit).forEach(row => {
    const tr = document.createElement("tr");
    [formatTime(row.received_at), String(row.sequence), levelText(row.upstream_mm), levelText(row.downstream_mm)].forEach(value => {const td = document.createElement("td"); td.textContent = value; tr.appendChild(td);});
    const good = row.upstream_quality === "good" && row.downstream_quality === "good";
    const td = document.createElement("td"), badge = document.createElement("span"), dot = document.createElement("span");
    badge.className = `quality-badge ${good ? "" : "issue"}`; dot.className = "status-dot"; dot.setAttribute("aria-hidden", "true"); badge.appendChild(dot);
    badge.appendChild(document.createTextNode(good ? "Both valid" : [row.upstream_quality !== "good" ? `Upstream: ${qualityLabels[row.upstream_quality] || "Unavailable"}` : null, row.downstream_quality !== "good" ? `Pond: ${qualityLabels[row.downstream_quality] || "Unavailable"}` : null].filter(Boolean).join(" · ")));
    td.appendChild(badge); tr.appendChild(td); body.appendChild(tr);
  });
  text("table-count", `${ui.dashboardOnline ? "Showing" : "Last loaded:"} ${Math.min(limit, matches.length)} of ${matches.length} matching recent readings`);
}
function render(data) {
  ui.data = data; ui.dashboardOnline = true;
  const profile = JSON.stringify([data.settings.device_id, data.settings.upstream_max_mm, data.settings.downstream_max_mm, data.settings.high_water_mm, data.settings.high_water_clear_mm, data.settings.high_water_hold_seconds, data.settings.pond_high_water_mm, data.settings.pond_high_water_clear_mm, data.settings.pond_high_water_hold_seconds]);
  if (session.profile && session.profile !== profile) {session = Model.initialSession(); Model.record(session, "info", "Operating profile updated", "This browser is monitoring the current configured limits.", data.server_time);}
  session.profile = profile;
  if (ui.previousConnection !== data.summary.connection) {
    if (data.summary.connection === "online") Model.record(session, "connected", "Live readings connected", `${data.mode === "simulation" ? "Synthetic source" : "ESP32"} packets are arriving.`, data.server_time);
    else if (data.summary.connection === "offline") Model.record(session, "warning", "Sensor connection lost", "Fresh readings are unavailable. Current water conditions are unknown.", data.server_time);
    ui.previousConnection = data.summary.connection;
  }
  const transition = Model.advance(session, data);
  const connections = {online: ["Live readings", "good"], offline: ["No recent data", "bad"], waiting: ["Awaiting data", "neutral"]};
  const [label, tone] = connections[data.summary.connection] || connections.waiting;
  text("connection-text", label); el("connection").className = `chip ${tone}`;
  ["upstream", "downstream"].forEach(sensor => updateSensor(sensor, data));
  text("coverage", data.summary.coverage_percent == null ? "—" : String(data.summary.coverage_percent));
  text("coverage-detail", data.summary.expected_slots ? `${data.summary.valid_slots} / ${data.summary.expected_slots} expected intervals` : "Waiting for paired readings");
  el("coverage-ring").setAttribute("stroke-dasharray", `${data.summary.coverage_percent || 0} 100`);
  text("valid-pairs", `${data.summary.window_valid_pairs} / ${data.summary.window_received}`);
  text("total", Number(data.summary.total_readings).toLocaleString("en-MY"));
  text("last-received", data.latest ? `${formatTime(data.latest.received_at)} MYT · last packet` : "Waiting for first packet");
  text("packet-age", data.latest ? `${data.summary.age_seconds}s ago` : "—");
  renderCondition(data); renderChart(data); renderRows(); renderActivity(); saveSession();
  if (transition.opened) {announce("High water confirmed. Review the affected location."); openAlert();}
  if (transition.cleared) {if (!session.episode && el("alert-dialog").open && !ui.preview) el("alert-dialog").close(); toast("A location has fresh readings below its clearing limit. Any other active warning remains visible.");}
  window.dispatchEvent(new CustomEvent("stormready:status",{detail:data}));
}
function disconnected() {
  ui.dashboardOnline = false;
  window.dispatchEvent(new CustomEvent("stormready:offline"));
  if (ui.previousConnection !== "server_offline") {Model.record(session, "warning", "Dashboard connection lost", "Current levels are unavailable. Check the running dashboard server.", Date.now() / 1000); ui.previousConnection = "server_offline";}
  text("connection-text", "Dashboard offline"); el("connection").className = "chip bad";
  ["upstream", "downstream"].forEach(sensor => updateSensor(sensor, null));
  text("coverage", "—"); text("coverage-detail", "Current coverage unavailable"); text("valid-pairs", "— / —"); text("packet-age", "Unavailable");
  el("coverage-ring").setAttribute("stroke-dasharray", "0 100");
  renderCondition(null); renderActivity(); renderRows(); saveSession();
  text("chart-caption", "Dashboard offline. Any chart data shown is the last loaded history.");
}
async function poll() {
  const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 4000);
  try {
    const response = await fetch("/api/status", {cache: "no-store", signal: controller.signal});
    if (!response.ok) throw new Error(`Status ${response.status}`);
    const data = await response.json();
    if (!data || data.schema_version !== 1 || !data.settings || !data.summary || !Array.isArray(data.history)) throw new Error("Unsupported dashboard response");
    text("chart-caption", "Hover or use arrow keys to inspect. Gaps indicate unavailable data."); render(data);
  } catch (_error) {disconnected();}
  finally {clearTimeout(timeout); setTimeout(poll, 1000);}
}

document.querySelectorAll("[data-window]").forEach(button => button.addEventListener("click", () => {
  ui.window = Number(button.dataset.window); ui.inspectedTime = null; el("chart-tooltip").hidden = true;
  document.querySelectorAll("[data-window]").forEach(item => {const selected = item === button; item.classList.toggle("selected", selected); item.setAttribute("aria-pressed", String(selected));});
  if (ui.data) renderChart(ui.data);
}));
document.querySelectorAll("[data-series]").forEach(button => button.addEventListener("click", () => {const sensor = button.dataset.series; ui.visible[sensor] = !ui.visible[sensor]; button.setAttribute("aria-pressed", String(ui.visible[sensor])); if (ui.data) renderChart(ui.data);}));
el("chart").addEventListener("pointermove", event => {if (!ui.geometry) return; const rect = el("chart").getBoundingClientRect(); const {start, end, left, plotWidth, width} = ui.geometry; const fraction = Math.max(0, Math.min(1, ((event.clientX - rect.left) / rect.width * width - left) / plotWidth)); inspectChart(start + fraction * (end - start));});
function clearChartInspection() {ui.inspectedTime = null; el("chart-tooltip").hidden = true; if (el("chart-cursor")) el("chart-cursor").replaceChildren();}
el("chart").addEventListener("pointerleave", clearChartInspection); el("chart").addEventListener("blur", clearChartInspection);
el("chart").addEventListener("keydown", event => {if (!["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(event.key)) return; event.preventDefault(); if (event.key === "Escape") {clearChartInspection(); return;} if (!ui.chartRows.length) return; let index = ui.inspectedTime === null ? ui.chartRows.length - 1 : ui.chartRows.findIndex(row => row.sampled_at === ui.inspectedTime); if (index < 0) index = ui.chartRows.length - 1; if (event.key === "Home") index = 0; else if (event.key === "End") index = ui.chartRows.length - 1; else index = Math.max(0, Math.min(ui.chartRows.length - 1, index + (event.key === "ArrowLeft" ? -1 : 1))); inspectChart(ui.chartRows[index].sampled_at, true);});
["reading-search", "quality-filter", "row-limit"].forEach(id => el(id).addEventListener(id === "reading-search" ? "input" : "change", renderRows));
el("sound-button").addEventListener("click", async () => {if (ui.audioEnabled) {ui.audioEnabled = false; if (ui.audio) ui.masterGain.gain.setTargetAtTime(0, ui.audio.currentTime, .01); updateSoundUI(); toast("Alert sound muted. Visual warnings remain active.");} else if (await enableSound()) {playAlarm(); toast("Sound enabled. Unacknowledged high-water alerts repeat every 30 seconds while this page is running.");}});
el("test-alert-button").addEventListener("click", () => openAlert(true));
el("banner-review").addEventListener("click", () => openAlert(false));
el("acknowledge-button").addEventListener("click", acknowledgeAlert);
el("dialog-close").addEventListener("click", () => el("alert-dialog").close());
el("dialog-acknowledge").addEventListener("click", () => {if (ui.preview) el("alert-dialog").close(); else acknowledgeAlert();});
el("dialog-review").addEventListener("click", async () => {if (ui.preview) {if (await enableSound()) playAlarm();} else {el("alert-dialog").close(); el("alert-center").scrollIntoView({block: "center"});}});
function openProfile() {if (!el("profile-dialog").open) el("profile-dialog").showModal();}
["profile-button", "profile-detail-button"].forEach(id => el(id).addEventListener("click", openProfile));
["profile-close", "profile-done"].forEach(id => el(id).addEventListener("click", () => el("profile-dialog").close()));
document.querySelectorAll(".nav-item[href]").forEach(link => link.addEventListener("click", () => {document.querySelectorAll(".nav-item[href]").forEach(item => {item.classList.toggle("active", item === link); if (item === link) item.setAttribute("aria-current", "location"); else item.removeAttribute("aria-current");});}));
el("fullscreen-button").addEventListener("click", async () => {try {if (document.fullscreenElement) await document.exitFullscreen(); else if (document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen(); else toast("Use your browser’s fullscreen control for presentation mode.");} catch (_error) {toast("Use your browser’s fullscreen control for presentation mode.");}});
document.addEventListener("fullscreenchange", () => el("fullscreen-button").setAttribute("aria-label", document.fullscreenElement ? "Exit presentation fullscreen" : "Enter presentation fullscreen"));
text("header-date", dateFormat.format(new Date()));
setInterval(() => {if (Object.values(session.episodes || {}).some(item=>!item.acknowledged) && ui.audioEnabled && Date.now() - ui.lastAlarmAt >= 30000) playAlarm();}, 1000);
poll();
