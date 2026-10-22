/* Pure monitoring rules shared by the interface and behavioural checks. */
(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.StormReadyModel = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const finite = value => typeof value === "number" && Number.isFinite(value);

  function currentLevel(data, sensor) {
    const row = data && data.latest;
    if (!row || !data.summary || data.summary.connection !== "online") return null;
    const value = row[`${sensor}_mm`];
    if (row[`${sensor}_current_quality`] !== "good" || !finite(value) || value < 0 || value > data.settings[`${sensor}_max_mm`]) return null;
    return value;
  }

  function initialSession() {
    return {episode: null, episodes: {}, events: [], counter: 0};
  }

  function record(session, kind, title, detail, at) {
    const event = {kind, title, detail, at};
    session.events = [event, ...session.events].slice(0, 30);
  }

  function advance(session, data) {
    session.episodes = session.episodes || {};
    const openedSensors = [], clearedSensors = [];
    for (const sensor of ["upstream", "downstream"]) {
      const value = currentLevel(data, sensor);
      const state = sensor === "upstream" ? data.summary.water_state : data.pond?.water_state;
      const high = sensor === "upstream" ? data.settings.high_water_mm : data.settings.pond_high_water_mm;
      const clear = sensor === "upstream" ? data.settings.high_water_clear_mm : data.settings.pond_high_water_clear_mm;
      const name = sensor === "upstream" ? "Upstream" : "Retention pond";
      if (value !== null && state === "high_water" && !session.episodes[sensor]) {
        session.counter += 1;
        session.episodes[sensor] = {id: `${sensor}:${data.server_time}:${session.counter}`, sensor, startedAt: data.server_time, acknowledged: false};
        record(session,"critical",`${name} high water confirmed`,`${name} ${value.toFixed(1)} mm · alert ${high} mm`,data.server_time);
        openedSensors.push(sensor);
      }
      if (session.episodes[sensor] && value !== null && state === "below_threshold" && value < clear) {
        record(session,"resolved",`${name} water-level alert cleared`,`Fresh ${name.toLowerCase()} reading below ${clear} mm. Pump health and maintenance recovery are not established.`,data.server_time);
        delete session.episodes[sensor]; clearedSensors.push(sensor);
      }
    }
    const active = Object.values(session.episodes);
    session.episode = openedSensors.length ? session.episodes[openedSensors[0]] : active.find(item=>!item.acknowledged) || active[0] || null;
    return {opened:openedSensors.length>0,cleared:clearedSensors.length>0,openedSensors,clearedSensors};
  }

  function acknowledge(session, at) {
    const active = Object.values(session.episodes || {});
    let changed = false;
    active.forEach(item=>{if(!item.acknowledged){item.acknowledged=true;changed=true;}});
    if (changed) record(session,"acknowledged","Visible alerts acknowledged","Seen in this browser. Each location clears only with its own fresh readings below its clearing limit.",at);
    return changed;
  }

  function condition(data, session) {
    const active = Object.values(session.episodes || {});
    if (active.length) {
      const names = active.map(item=>item.sensor === "upstream" ? "Upstream chamber" : "Retention pond").join(" + ");
      const unknown = !data || active.some(item=>currentLevel(data,item.sensor)===null);
      return {tone:"critical",title:`${names}: ${unknown ? "alert unresolved; level unknown" : "high-water alert"}`,detail:unknown ? "Missing readings cannot confirm that either alert has cleared. Restore reliable data and inspect conditions." : "Inspect the affected location. Each warning clears independently below its configured clearing threshold.",badge:active.every(item=>item.acknowledged)?"Acknowledged · still active":"Action required",water:unknown?"Unknown":active.length===2?"Both levels high":active[0].sensor==="downstream"?"Pond high water":"High water",kicker:"HIGH-WATER ALERT · "+names.toUpperCase()};
    }
    if (!data) return {tone:"warning",title:"Dashboard connection lost",detail:"Current water levels are unavailable.",badge:"Data unavailable",water:"Unknown",kicker:"CONNECTION NEEDS ATTENTION"};
    const up=currentLevel(data,"upstream"),down=currentLevel(data,"downstream");
    const pondState=data.pond?.water_state;
    if(data.summary.connection==="waiting") return {tone:"neutral",title:"Waiting for the first reading",detail:"Current conditions will appear when readings arrive.",badge:"Awaiting data",water:"Unknown",kicker:"READY TO MONITOR"};
    if(data.summary.connection!=="online") return {tone:"warning",title:"Sensor connection lost",detail:"No fresh readings. Current water levels are unknown.",badge:"No recent data",water:"Unknown",kicker:"DATA CONNECTION LOST"};
    if(data.summary.water_state==="confirming" || pondState==="confirming") {
      const names=[data.summary.water_state==="confirming"?"Upstream":null,pondState==="confirming"?"Retention pond":null].filter(Boolean).join(" + ");
      return {tone:"warning",title:`${names}: confirming high water`,detail:"Checking the configured persistence period before raising an alert.",badge:"Checking persistence",water:"Confirming",kicker:"HIGH LEVEL DETECTED"};
    }
    if(up===null||down===null) return {tone:"warning",title:`${up===null?"Upstream":"Retention pond"} reading unavailable`,detail:"Check sensor quality and mounting. Missing readings are not low water.",badge:"Check sensor",water:"Unknown",kicker:"READING QUALITY ALERT"};
    if(data.summary.water_state!=="below_threshold" || (pondState && pondState!=="below_threshold")) return {tone:"neutral",title:"Establishing water conditions",detail:"Waiting for fresh confirmation from both monitors.",badge:"Checking readings",water:"Unknown",kicker:"MONITORING CHECK"};
    return {tone:"normal",title:"Both water levels below their alert thresholds.",detail:`Upstream alert: ${data.settings.high_water_mm} mm · Pond alert: ${data.settings.pond_high_water_mm ?? "not configured"} mm.`,badge:"Monitoring both locations",water:"Below thresholds",kicker:"LIVE MONITORING ACTIVE"};
  }

  function chartSegments(rows, sensor, start, end, settings) {
    const segments = [];
    let previous = null;
    for (const row of rows) {
      const value = row[`${sensor}_mm`];
      if (row[`${sensor}_quality`] !== "good" || !finite(value) || value < 0 || value > settings[`${sensor}_max_mm`] || !finite(row.sampled_at) || row.sampled_at < start || row.sampled_at > end) {
        previous = null;
        continue;
      }
      const continuous = previous && row.boot_id === previous.boot_id && row.sampled_at >= previous.sampled_at && row.sampled_at - previous.sampled_at <= settings.max_gap_seconds;
      if (!continuous) segments.push([]);
      segments[segments.length - 1].push({time: row.sampled_at, value});
      previous = row;
    }
    return segments;
  }

  function sensorTrend(data, sensor) {
    const value = currentLevel(data, sensor);
    if (value === null) return {label: "Trend unavailable", direction: "unknown"};
    const current = data.latest;
    const prior = [...data.history].reverse().find(row => row.boot_id === current.boot_id && row[`${sensor}_quality`] === "good" && finite(row[`${sensor}_mm`]) && row.sampled_at <= current.sampled_at - 5 && row.sampled_at >= current.sampled_at - 10);
    if (!prior) return {label: "Building recent trend", direction: "unknown"};
    const relevant = data.history.filter(row => row.sampled_at >= prior.sampled_at && row.sampled_at <= current.sampled_at);
    const groups = chartSegments(relevant, sensor, prior.sampled_at, current.sampled_at, data.settings);
    if (groups.length !== 1 || groups[0].length < 2) return {label: "Recent trend unavailable", direction: "unknown"};
    const delta = value - prior[`${sensor}_mm`];
    if (Math.abs(delta) < 2) return {label: "Steady · recent readings", direction: "steady"};
    return {label: `${delta > 0 ? "Rising" : "Falling"} ${Math.abs(delta).toFixed(1)} mm · ${Math.round(current.sampled_at - prior.sampled_at)}s`, direction: delta > 0 ? "rising" : "falling"};
  }

  return {currentLevel, initialSession, record, advance, acknowledge, condition, chartSegments, sensorTrend};
});
