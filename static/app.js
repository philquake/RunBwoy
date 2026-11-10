"use strict";
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtPace = s => s ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}` : "–";
const fmtDur = s => { if (!s) return "–"; s = Math.round(s); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return h ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}` : `${m}:${String(x).padStart(2, "0")}`; };
const dayName = d => new Date(d + "T12:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
const localDate = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
const LB = 2.20462;   // weight is stored in kg internally; shown and entered in lb
const lb = kg => kg == null ? "–" : (kg * LB).toFixed(1);
const store = { get: k => { try { return localStorage.getItem(k) } catch { return null } }, set: (k, v) => { try { localStorage.setItem(k, v) } catch { } } };

async function api(path, opts = {}) {
  const o = { ...opts };
  if (o.json !== undefined) { o.method = o.method || "POST"; o.headers = { "Content-Type": "application/json" }; o.body = JSON.stringify(o.json); delete o.json; }
  const r = await fetch("/api/" + path, o);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data.message || data.error || r.statusText), { status: r.status, data });
  return data;
}
let tt;
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.style.display = "block"; clearTimeout(tt); tt = setTimeout(() => t.style.display = "none", 4500); }
const form = f => Object.fromEntries([...new FormData(f)].map(([k, v]) => [k, v]));
const field = (label, name, val = "", type = "text", extra = "") => `<div><label>${label}</label><input name="${name}" type="${type}" value="${esc(val)}" ${extra}></div>`;
const sel = (label, name, opts, val) => `<div><label>${label}</label><select name="${name}">${opts.map(o => `<option value="${o[0]}" ${String(o[0]) === String(val) ? "selected" : ""}>${o[1]}</option>`).join("")}</select></div>`;
const scale = (label, name, val) => sel(label, name, [["", "–"], [1, 1], [2, 2], [3, 3], [4, 4], [5, 5]], val);
const basis = b => `<span class="pill est">${esc(b)}</span>`;

/* ---------- charts (inline SVG, no libraries) ---------- */
function bars(vals, labels, unit = "") {
  const w = 300, h = 120, max = Math.max(...vals, 1), bw = w / vals.length;
  return `<svg viewBox="0 0 ${w} ${h + 18}" width="100%" role="img" aria-label="Weekly distance">${vals.map((v, i) => {
    const bh = v / max * (h - 16); return `<rect x="${i * bw + 8}" y="${h - bh}" width="${bw - 16}" height="${bh}" rx="3" fill="${i === vals.length - 1 ? "var(--accent)" : "var(--accent2)"}"/><text x="${i * bw + bw / 2}" y="${h - bh - 3}" text-anchor="middle">${v}${unit}</text><text x="${i * bw + bw / 2}" y="${h + 12}" text-anchor="middle">${labels[i]}</text>`;
  }).join("")}</svg>`;
}
function line(pts, fmt = v => v, flip = false) {
  if (pts.length < 2) return `<p class="muted small">Not enough data yet.</p>`;
  const w = 300, h = 110, ys = pts.map(p => p.y), lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1;
  const X = i => 8 + i / (pts.length - 1) * (w - 16), Y = v => flip ? 10 + (v - lo) / span * (h - 20) : h - 10 - (v - lo) / span * (h - 20);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(p.y).toFixed(1)}`).join("");
  return `<svg viewBox="0 0 ${w} ${h + 14}" width="100%"><path d="${d}" fill="none" stroke="var(--accent2)" stroke-width="2"/>${pts.map((p, i) => `<circle cx="${X(i)}" cy="${Y(p.y)}" r="3" fill="var(--accent)"/>`).join("")}<text x="8" y="${h + 11}">${esc(pts[0].x)} · ${fmt(pts[0].y)}</text><text x="${w - 8}" y="${h + 11}" text-anchor="end">${esc(pts.at(-1).x)} · ${fmt(pts.at(-1).y)}</text></svg>`;
}
const meter = (label, actual, target, unit = "") => {
  const pct = target ? Math.min(100, (actual || 0) / target * 100) : 0;
  return `<div class="macro"><div class="row between"><span>${label}</span><span class="muted">${actual == null ? "–" : Math.round(actual)} / ${Math.round(target)}${unit}</span></div><div class="bar ${(actual || 0) > target * 1.1 ? "over" : ""}"><i style="width:${pct}%"></i></div></div>`;
};

/* ---------- views ---------- */
const views = {};
let S = null;

views.dashboard = async el => {
  S = await api("state");
  const r = S.race, t = S.today_workout, nl = S.next_long, nt = S.nutrition_target, rd = S.readiness, rec = S.recovery, wt = S.weight, lg = S.nutrition_log, ls = S.last_sleep;
  const warn = [];
  if (!S.profile.sat_time_confirmed) warn.push(`Set your preferred <b>Saturday run time</b> in <a href="#profile">Profile</a> (07:00 is a placeholder).`);
  if (S.needs_review) warn.push(`${S.needs_review} imported activit${S.needs_review > 1 ? "ies need" : "y needs"} checking in <a href="#activities">Activities</a>.`);
  el.innerHTML = `
  <h1>Good ${new Date().getHours() < 12 ? "morning" : "day"}</h1>
  <p class="sub">${dayName(S.today)} · everything is stored on this computer</p>
  ${warn.map(w => `<div class="banner">${w}</div>`).join("")}
  <div class="grid">
    <div class="card c4"><h2>Race countdown</h2><div class="big">${r.days_left} <span class="mid muted">days</span></div>
      <p class="small muted">${esc(r.name)} · ${dayName(r.date)}, ${r.start}<br>Goal ${r.goal_time} → ${r.goal_pace}/km (${r.goal_speed_kmh} km/h)</p></div>
    <div class="card c4"><h2>Today's workout</h2>${workoutCard(t, "Rest day. Fuel, hydrate, sleep.")}</div>
    <div class="card c4"><h2>Next long run</h2>${nl ? `<div class="mid">${nl.distance_km} km · ${dayName(nl.date)}</div><p class="small muted">${nl.pace} · ~${nl.duration_min} min · RPE ${nl.rpe}</p>` : `<p class="muted">None scheduled.</p>`}</div>

    <div class="card c4"><h2>Weekly mileage</h2>${bars(S.weekly.map(w => w.km), S.weekly.map(w => w.week.slice(5)), "")}<p class="small muted">km per week (Mon–Sun). This week: ${S.weekly.at(-1).km} km</p></div>
    <div class="card c4"><h2>Recent pace trend</h2>${line(S.pace_trend.map(p => ({ x: p.date.slice(5), y: p.pace_s })), fmtPace, true)}<p class="small muted">min/km, lower is faster. Runs ≥ 3 km only.</p></div>
    <div class="card c4"><h2>Weight trend</h2>${line(wt.points.map(p => ({ x: p.date.slice(5), y: p.trend * LB })), v => v.toFixed(1))}
      <p class="small muted">Trend ${lb(wt.trend_kg)} lb${wt.rate_kg_wk != null ? ` · ${wt.rate_kg_wk > 0 ? "+" : ""}${(wt.rate_kg_wk * LB).toFixed(1)} lb/week` : " · need 3+ weigh-ins over a week for a rate"}</p>
      <form class="row" data-act="weight"><input name="lbs" type="number" step="0.1" placeholder="lb today" style="width:110px" required><button>Log</button></form></div>

    <div class="card c4"><h2>Nutrition today <span class="pill">${esc(nt.label)}</span> ${basis("estimate")}</h2>
      <div class="mid">${nt.kcal} kcal <span class="small muted">target${lg && lg.kcal ? ` · ${Math.round(lg.kcal)} eaten` : ""}</span></div>
      ${meter("Protein", lg?.protein, nt.protein, " g")}${meter("Carbs", lg?.carbs, nt.carbs, " g")}${meter("Fat", lg?.fat, nt.fat, " g")}
      <p class="small"><a href="#nutrition">Meals, fibre, water and electrolytes →</a></p></div>
    <div class="card c4"><h2>Sleep &amp; recovery</h2>
      <div class="row"><div class="score" style="border-color:${statusColor(rec.status)}">${rec.score ?? "–"}</div><div><b>${rec.status}</b><div class="small muted">${rec.basis === "none" ? esc(rec.missing) : "self-reported"}</div></div></div>
      <p class="small">Last night: ${ls?.hours ? ls.hours + " h" : "not logged"} · Tonight's target: bed ${S.sleep_target.bed}, wake ${S.sleep_target.wake}</p>
      <a href="#sleep" class="small">Log sleep →</a></div>
    <div class="card c4"><h2>Race readiness</h2>
      <div class="row"><div class="score" style="border-color:var(--warn)">${rd.score ?? "–"}</div><div><b>Confidence: ${rd.confidence}</b><div class="small muted">Projected half ${rd.projection.half_time} (${rd.projection.source})</div></div></div>
      <p class="small">${esc(rd.verdict)}</p><a href="#race" class="small">Details →</a></div>

    <div class="card c12"><h2>Coach recommendations</h2>${S.coach.map(c => `<div class="rec"><b>${esc(c.text)}</b><span class="small muted">${esc(c.why)} ${basis(c.basis)}</span></div>`).join("")}
      <p class="small muted">The coach runs locally with rules and Python maths. It explains each suggestion and never saves plan changes without your confirmation.</p></div>
  </div>`;
};
const statusColor = s => ({ Good: "var(--good)", Moderate: "var(--warn)", Reduced: "var(--bad)" }[s] || "var(--line)");
function workoutCard(w, empty) {
  if (!w || w.kind === "rest") return `<p class="muted">${empty}</p>${w ? `<p class="small">${esc(w.structure)}</p>` : ""}`;
  return `<div class="mid">${esc(w.title)}</div><p class="small">${w.distance_km} km · ${w.pace} (${w.speed})<br>~${w.duration_min} min · RPE ${w.rpe}/10 <span class="pill ${w.status}">${w.status}</span></p><p class="small muted">${esc(w.structure)}</p>`;
}

views.plan = async el => {
  const { workouts, paces } = await api("plan");
  const weeks = {};
  workouts.forEach(w => { const d = new Date(w.date + "T12:00"); const k = new Date(d - ((d.getDay() + 6) % 7) * 864e5).toISOString().slice(0, 10); (weeks[k] ||= []).push(w); });
  el.innerHTML = `<h1>Training plan</h1><p class="sub">Four runs per week is a maximum, not a requirement. Saturday stays short and easy before the Sunday long run.</p>
  <div class="card"><div class="row between"><div><h2>Training paces</h2><span class="small muted">Easy ${paces.easy} · Long ${paces.long} · Steady ${paces.steady} · Goal ${paces.goal}</span></div>
  <button id="replan">Ask coach to review the plan</button></div><div id="proposal"></div></div><br>
  ${Object.entries(weeks).map(([k, ws]) => `<div class="card" style="margin-bottom:12px"><h2>Week of ${dayName(k)} · ${ws.reduce((a, w) => a + w.distance_km, 0).toFixed(1)} km</h2><table><tr><th>Day</th><th>Session</th><th>Distance</th><th>Pace / speed</th><th>Time</th><th>RPE</th><th></th></tr>
  ${ws.map(w => `<tr class="${w.date === S?.today || w.status === "today" ? "today" : ""} kind-${w.kind}"><td>${dayName(w.date)}</td><td><b>${esc(w.title)}</b><div class="small muted">${esc(w.structure)}${w.notes ? "<br>" + esc(w.notes) : ""}</div></td>
  <td>${w.kind === "rest" ? "–" : w.distance_km + " km"}</td><td>${w.kind === "rest" ? "–" : w.pace + "<br><span class='small muted'>" + w.speed + "</span>"}</td><td>${w.kind === "rest" ? "–" : "~" + w.duration_min + " min"}</td><td>${w.kind === "rest" ? "–" : w.rpe}</td><td><span class="pill ${w.status}">${w.status}</span></td></tr>`).join("")}</table></div>`).join("")}`;
  $("#replan").onclick = async () => {
    const p = await api("plan/propose", { method: "POST", json: {} });
    $("#proposal").innerHTML = `<h3>Proposed changes</h3>${p.reasons.map(r => `<p class="small">• ${esc(r)}</p>`).join("")}${p.changes.length ? `<table>${p.changes.map(c => `<tr><td>${dayName(c.date)}</td><td class="muted">${esc(c.old || "–")}</td><td>→ ${esc(c.new)}</td></tr>`).join("")}</table><div class="row" style="margin-top:10px"><button id="ok">Confirm &amp; save</button><button class="ghost" id="no">Discard</button></div>` : `<p class="small">No changes needed right now. Your plan already matches the latest data.</p>`}`;
    if (p.changes.length) { $("#ok").onclick = async () => { await api("plan/apply", { json: { workouts: p.workouts } }); toast("Plan updated."); route(); }; $("#no").onclick = () => $("#proposal").innerHTML = ""; }
  };
};

views.nutrition = async (el, date = "") => {
  const n = await api("nutrition" + (date ? "?date=" + date : ""));
  const t = n.target, lg = n.log || {};
  const shift = k => { const d = new Date(n.date + "T12:00"); d.setDate(d.getDate() + k); return d.toISOString().slice(0, 10); };
  el.innerHTML = `<h1>Nutrition</h1><p class="sub">Gradual fat loss without compromising training. All targets are estimates; weight is judged by trend, not single days.</p>
  <div class="row" style="margin-bottom:12px"><button class="ghost" id="prev">←</button><b>${dayName(n.date)}</b><button class="ghost" id="next">→</button><span class="pill">${esc(t.label)}</span>${n.workout && n.workout.kind !== "rest" ? `<span class="small muted">${esc(n.workout.title)} · ${n.workout.distance_km} km</span>` : ""}</div>
  <div class="grid"><div class="card c5"><h2>Targets ${basis("estimate")}</h2>
    <div class="big">${t.kcal} <span class="mid muted">kcal</span></div>
    <p class="small muted">BMR ${t.bmr} (Mifflin–St Jeor) → non-exercise ${t.nonexercise} (×${S?.profile.activity_factor ?? 1.3}) + run ${t.run_kcal} = ~${t.tdee} − deficit ${t.deficit}</p>
    ${meter("Calories", lg.kcal, t.kcal, " kcal")}${meter("Protein", lg.protein, t.protein, " g")}${meter("Carbohydrate", lg.carbs, t.carbs, " g")}${meter("Fat", lg.fat, t.fat, " g")}${meter("Fibre", lg.fibre, t.fibre, " g")}${meter("Water", lg.water_ml, t.water_ml, " ml")}
    <p class="small">${esc(t.electrolytes)}</p>${t.notes.map(x => `<p class="small" style="color:var(--warn)">⚠ ${esc(x)}</p>`).join("")}</div>
  <div class="card c7"><h2>Meals &amp; timing</h2><table><tr><th>Time</th><th>Meal</th><th>kcal</th><th>P / C / F (g)</th></tr>
    ${n.meals.map(m => `<tr><td>${m.time}</td><td><b>${esc(m.name)}</b><div class="small muted">${esc(m.tip)}</div></td><td>${m.kcal}</td><td>${m.protein} / ${m.carbs} / ${m.fat}</td></tr>`).join("")}</table></div>
  <div class="card c12"><h2>Log what you ate</h2><form class="form" data-act="nlog"><input type="hidden" name="date" value="${n.date}">
    ${field("Calories", "kcal", lg.kcal ?? "", "number", 'step="1"')}${field("Protein g", "protein", lg.protein ?? "", "number")}${field("Carbs g", "carbs", lg.carbs ?? "", "number")}${field("Fat g", "fat", lg.fat ?? "", "number")}${field("Fibre g", "fibre", lg.fibre ?? "", "number")}${field("Water ml", "water_ml", lg.water_ml ?? "", "number")}${field("Electrolytes mg sodium", "electrolytes_mg", lg.electrolytes_mg ?? "", "number")}<button>Save</button></form></div>
  <div class="card c12"><h2>Fuelling guide</h2><div class="grid">
   <div class="c4 small"><b>Rest days</b><br>Highest protein share, steady carbs, a ${t.deficit ? "modest deficit" : "maintenance"} when recovery allows.</div>
   <div class="c4 small"><b>Easy and quality runs</b><br>Light carb snack 60–90 min before, protein + carbs within 45–60 min after.</div>
   <div class="c4 small"><b>Long runs and race</b><br>Low-fibre carbs 75–135 min before. After 45 min take 30–60 g carbs/hour with fluid and electrolytes. Practise exactly what you will use on race day. Nothing new on December 6.</div></div></div></div>`;
  $("#prev").onclick = () => views.nutrition(el, shift(-1)); $("#next").onclick = () => views.nutrition(el, shift(1));
};

views.sleep = async el => {
  const s = await api("sleep"), r = s.recovery, t = localDate();
  el.innerHTML = `<h1>Sleep &amp; recovery</h1><p class="sub">Heart-rate data isn't available, so recovery is based on what you report. Resting HR and HRV are optional if you get a device later.</p>
  <div class="grid"><div class="card c5"><h2>Recovery ${basis(r.basis)}</h2><div class="row"><div class="score" style="border-color:${statusColor(r.status)}">${r.score ?? "–"}</div><div><b>${r.status}</b><div class="small muted">${r.hours ? "Avg sleep " + r.hours + " h" : esc(r.missing || "")}</div></div></div>
    ${r.factors.length ? `<table style="margin-top:10px">${r.factors.map(f => `<tr><td>${f.name}</td><td class="small muted">${esc(f.detail || "")}</td><td>${f.points ?? "–"}/${f.weight}</td></tr>`).join("")}</table><p class="small muted">Score = weighted sum of the factors above, averaged over your last two logs. Low sleep, soreness and fatigue pull it down.</p>` : ""}</div>
   <div class="card c7"><h2>Log this morning</h2><form class="form" data-act="slog">${field("Morning of", "date", t, "date")}${field("Bedtime", "bed", "22:30", "time")}${field("Wake-up", "wake", "06:30", "time")}${scale("Sleep quality (5 best)", "quality")}${scale("Soreness (5 severe)", "soreness")}${scale("Fatigue (5 exhausted)", "fatigue")}${scale("Motivation (5 high)", "motivation")}${scale("Hydration (5 good)", "hydration")}${field("Resting HR (optional)", "rhr", "", "number")}${field("HRV (optional)", "hrv", "", "number")}<button>Save</button></form></div>
   <div class="card c6"><h2>Sleep targets (building towards the 5 AM start)</h2><table><tr><th>Night of</th><th>Bed</th><th>Wake</th><th>Note</th></tr>${s.targets.map(x => `<tr><td>${dayName(x.date)}</td><td>${x.bed}</td><td>${x.wake}</td><td class="small muted">${esc(x.note)}</td></tr>`).join("")}</table></div>
   <div class="card c6"><h2>Recent logs</h2>${s.logs.length ? `<table><tr><th>Date</th><th>Sleep</th><th>Q</th><th>Sore</th><th>Fat</th></tr>${s.logs.map(l => `<tr><td>${dayName(l.date)}</td><td>${l.hours ?? "–"} h</td><td>${l.quality ?? "–"}</td><td>${l.soreness ?? "–"}</td><td>${l.fatigue ?? "–"}</td></tr>`).join("")}</table>` : `<p class="muted">No logs yet.</p>`}</div></div>`;
};

views.activities = async el => {
  const A = await api("activities");
  el.innerHTML = `<h1>Activities</h1><p class="sub">Import Strava screenshots (several at once) or GPX files. Originals are kept. Missing values are never invented; heart rate is not collected.</p>
  <div class="grid"><div class="card c6"><h2>Import</h2><div class="drop" id="drop">Drop screenshots / .gpx here or <label style="display:inline;color:var(--accent);cursor:pointer">browse<input id="files" type="file" multiple accept="image/*,.gpx" hidden></label></div><div id="imp" class="small"></div></div>
  <div class="card c6"><h2>Add manually</h2><form class="form" data-act="alog">${field("Date", "date", localDate(), "date", "required")}${field("Distance km", "distance_km", "", "number", 'step="0.01" required')}${field("Time (h:mm:ss)", "duration", "", "text", 'placeholder="46:30" required')}${scale("RPE 1–10", "rpe")}<button>Add</button></form></div>
  <div class="card c12"><h2>History (${A.length})</h2>${A.length ? `<table><tr><th>Date</th><th>Distance</th><th>Time</th><th>Pace</th><th>RPE</th><th>Source</th><th></th></tr>${A.map(a => `<tr><td>${dayName(a.date)}</td><td>${a.distance_km ?? "?"} km</td><td>${a.duration ?? "?"}</td><td>${a.pace}/km</td><td>${a.rpe ?? "–"}</td><td>${a.file ? `<a href="/api/uploads/${a.file}" target="_blank">${a.source}</a>` : a.source}${a.needs_review ? ` <span class="pill warn">check</span>` : ""}</td><td><button class="ghost" data-edit="${a.id}">Edit</button> <button class="ghost" data-del="${a.id}">✕</button></td></tr>`).join("")}</table>` : `<p class="muted">No activities yet. Import some to verify your current fitness.</p>`}</div></div>`;
  // RPE field: full 1-10 select
  const rpe = $("[data-act=alog] select[name=rpe]"); rpe.innerHTML = `<option value="">–</option>` + [...Array(10)].map((_, i) => `<option>${i + 1}</option>`).join("");
  const send = async fl => {
    const fd = new FormData(); [...fl].forEach(f => fd.append("files", f));
    const res = await fetch("/api/activities/upload", { method: "POST", body: fd }).then(r => r.json());
    $("#imp").innerHTML = res.map(r => `<p>• ${esc(r.file)}: <b>${r.status}</b> ${esc(r.message)}</p>`).join(""); setTimeout(route, 2500);
  };
  $("#files").onchange = e => send(e.target.files);
  const d = $("#drop"); d.ondragover = e => { e.preventDefault(); d.classList.add("over") }; d.ondragleave = () => d.classList.remove("over"); d.ondrop = e => { e.preventDefault(); send(e.dataTransfer.files) };
  el.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => { if (confirm("Delete this activity?")) { await api("activities/" + b.dataset.del, { method: "DELETE" }); route(); } });
  el.querySelectorAll("[data-edit]").forEach(b => b.onclick = () => editAct(A.find(a => a.id == b.dataset.edit)));
};
function editAct(a) {
  const dlg = $("#dlg");
  dlg.innerHTML = `<h2>Edit activity #${a.id}</h2>${a.file ? `<img src="/api/uploads/${a.file}" style="max-width:100%;max-height:260px;border-radius:8px">` : ""}<form class="form" id="ef">${field("Date", "date", a.date, "date")}${field("Distance km", "distance_km", a.distance_km ?? "", "number", 'step="0.01"')}${field("Time", "duration", a.duration ?? "")}${field("RPE", "rpe", a.rpe ?? "", "number", 'min="1" max="10"')}<div style="grid-column:1/-1">${field("Notes", "notes", a.notes ?? "")}</div><button>Save</button><button type="button" class="ghost" id="cx">Cancel</button></form>`;
  dlg.showModal(); $("#cx").onclick = () => dlg.close();
  $("#ef").onsubmit = async e => { e.preventDefault(); await api("activities/" + a.id, { method: "PUT", json: form(e.target) }); dlg.close(); route(); };
}

views.race = async el => {
  const { race: r, plan, readiness: rd } = await api("race");
  el.innerHTML = `<h1>Race readiness &amp; race day</h1><p class="sub">${dayName(r.date)} · ${r.start} start · goal ${r.goal_time} (${r.goal_pace}/km)</p>
  <div class="grid"><div class="card c5"><div class="row"><div class="score" style="border-color:var(--warn)">${rd.score ?? "–"}</div><div><b>Confidence: ${rd.confidence}</b><div class="small muted">Projected half ${rd.projection.half_time} (range ${rd.projection.spread.join(" – ")})</div></div></div>
   <p>${esc(rd.verdict)}</p><p class="small muted">${esc(rd.disclaimer)}</p>
   <h3>What would raise confidence</h3>${rd.missing.length ? `<ul>${rd.missing.map(m => `<li>${esc(m)}</li>`).join("")}</ul>` : "<p class='small'>Nothing major missing.</p>"}
   <p class="small"><b>Do not</b> add last-minute volume to chase the goal. Arriving healthy beats a heroic final week.</p></div>
   <div class="card c7"><h2>Evidence</h2><table>${rd.components.map(c => `<tr><td>${c.name}</td><td class="small muted">${esc(c.detail)}</td><td>${c.score ?? "–"}</td><td>${basis(c.basis)}</td></tr>`).join("")}</table></div>
   <div class="card c12"><h2>Race-day plan</h2><table>${plan.map(p => `<tr><td style="white-space:nowrap"><b>${esc(p.time)}</b></td><td>${esc(p.what)}</td></tr>`).join("")}</table></div></div>`;
};

views.calendar = async el => {
  const inc = JSON.parse(store.get("inc") || '["training","meals","sleep"]');
  const q = () => inc.join(",");
  const [g, pv] = await Promise.all([api("gcal/status"), api("calendar/preview?include=" + q())]);
  const byDay = {}; pv.events.forEach(e => (byDay[e.start.slice(0, 10)] ||= []).push(e));
  el.innerHTML = `<h1>Google Calendar</h1><p class="sub">Training days, meals and sleep targets as calendar events. Direct sync updates events in place and removes ones that left the plan. Runs and bedtime get a 15-minute reminder; meals and sleep show as "free" time.</p>
  <div class="grid"><div class="card c6"><h2>1 · Choose what to send</h2><div class="row">${[["training", "Training"], ["meals", "Meals"], ["sleep", "Sleep targets"]].map(([k, l]) => `<label style="display:flex;gap:6px;align-items:center;font-size:14px;color:var(--text)"><input type="checkbox" data-inc="${k}" style="width:auto" ${inc.includes(k) ? "checked" : ""}>${l}</label>`).join("")}</div>
    <p class="small muted">${pv.count} events from today to race day, in ${esc(S?.profile.timezone || "your timezone")}.</p>
    <h3>Option A · No setup</h3><a class="btn" href="/api/calendar.ics?include=${q()}">Download .ics</a>
    <p class="small muted">In Google Calendar: Settings → Import &amp; export → Import, pick the file and choose a calendar (create a "Run Coach" calendar first so you can delete it in one click). <b>After you change the plan, delete that calendar and import again</b>; a file import cannot remove old events by itself.</p></div>
  <div class="card c6"><h2>2 · Or sync directly</h2><p class="small">Status: libraries ${g.libraries ? "✓" : "✗"} · credentials file ${g.credentials_file ? "✓" : "✗"} · signed in ${g.authorised ? "✓" : "not yet"}</p>
    <button id="gsync" ${g.libraries && g.credentials_file ? "" : "disabled"}>Sync to Google Calendar</button><p id="gout" class="small"></p>
    <details><summary>One-time setup</summary><ol class="small"><li>Google Cloud Console → create a project → enable <b>Google Calendar API</b>.</li><li>OAuth consent screen → External → add yourself as a test user.</li><li>Credentials → Create OAuth client ID → <b>Desktop app</b> → download JSON.</li><li>Save it as <code>${esc(g.credentials_path)}</code></li><li>Click Sync. A browser tab asks you to sign in once. Events go into a new calendar called "Run Coach".</li></ol></details></div>
  <div class="card c12"><h2>Preview</h2>${Object.entries(byDay).slice(0, 14).map(([d, es]) => `<h3>${dayName(d)}</h3><table>${es.map(e => `<tr><td style="white-space:nowrap" class="small muted">${e.start.slice(11)}–${e.end.slice(11)}</td><td>${esc(e.summary)}</td></tr>`).join("")}</table>`).join("")}<p class="small muted">Showing the next 14 days.</p></div></div>`;
  el.querySelectorAll("[data-inc]").forEach(c => c.onchange = () => { const k = c.dataset.inc; const i = inc.indexOf(k); i < 0 ? inc.push(k) : inc.splice(i, 1); store.set("inc", JSON.stringify(inc)); views.calendar(el); });
  $("#gsync").onclick = async e => {
    e.target.disabled = true; $("#gout").textContent = "Syncing… a browser window may ask you to sign in.";
    try { const r = await api("gcal/sync?include=" + q(), { method: "POST", json: {} }); $("#gout").textContent = `Done: ${r.created} created, ${r.updated} updated.`; }
    catch (err) { $("#gout").textContent = err.message; } e.target.disabled = false;
  };
};

const chatLog = [];   // kept for the session; cleared on page reload
const TOOL_LABEL = { get_dashboard: "overview", get_plan: "training plan", get_nutrition: "nutrition", get_recent_activities: "activities", get_sleep_recovery: "sleep & recovery", get_readiness: "race readiness", search_knowledge: "knowledge notes", propose_plan_change: "plan review" };
views.coach = async el => {
  const st = await api("coach/status");
  const msgHtml = m => m.role === "user" ? `<div class="msg me">${esc(m.content)}</div>` :
    `<div class="msg ai">${esc(m.content).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br>")}${m.tools?.length ? `<div class="small muted" style="margin-top:6px">Based on: ${[...new Set(m.tools)].map(t => TOOL_LABEL[t] || t).join(", ")} ${basis("local data")}</div>` : ""}${m.proposal ? proposalHtml(m.proposal) : ""}</div>`;
  const proposalHtml = p => `<div class="card" style="margin-top:8px"><b>Proposed plan changes</b>${p.reasons.map(r => `<p class="small">• ${esc(r)}</p>`).join("")}${p.changes.length ? `<table>${p.changes.map(c => `<tr><td>${dayName(c.date)}</td><td class="muted">${esc(c.old || "–")}</td><td>→ ${esc(c.new)}</td></tr>`).join("")}</table><button data-confirm>Confirm &amp; save</button>` : `<p class="small">No changes needed.</p>`}</div>`;
  el.innerHTML = `<h1>Coach</h1><p class="sub">Runs on your computer through Ollama (model <code>${esc(st.model)}</code>). It reads your data, but every number comes from the app's own calculations, and it can only <i>propose</i> plan changes.</p>
  ${!st.running ? `<div class="banner">Ollama isn't running. Start the Ollama app, then reload this page.</div>` : !st.model_installed ? `<div class="banner">Model not found. In the project folder run: <code>ollama create runcoach -f coach/Modelfile</code></div>` : ""}
  <div class="card"><div id="log">${chatLog.length ? chatLog.map(msgHtml).join("") : `<p class="muted">Try: "What's my plan this week?", "What should I eat before Sunday's long run?", "Is sub-2:30 realistic?", "Review my plan."</p>`}</div>
  <form id="cf" class="row" style="margin-top:12px;flex-wrap:nowrap"><input id="ci" placeholder="Ask your coach…" autocomplete="off" ${st.running && st.model_installed ? "" : "disabled"}><button id="cb" ${st.running && st.model_installed ? "" : "disabled"}>Send</button></form>
  <p class="small muted">Replies can take up to a minute on this computer. The coach is not a doctor; stop and get medical advice for pain or unusual symptoms.</p></div>`;
  const log = $("#log"), bind = () => log.querySelectorAll("[data-confirm]").forEach(b => b.onclick = async () => {
    const last = [...chatLog].reverse().find(m => m.proposal);
    await api("plan/apply", { json: { workouts: last.proposal.workouts } }); last.proposal = null; toast("Plan updated."); views.coach(el);
  });
  bind(); log.scrollTop = log.scrollHeight;
  $("#cf").onsubmit = async e => {
    e.preventDefault(); const t = $("#ci").value.trim(); if (!t) return;
    chatLog.push({ role: "user", content: t }); $("#ci").value = ""; $("#cb").disabled = true;
    log.innerHTML = chatLog.map(msgHtml).join("") + `<div class="msg ai muted">Thinking… reading your data</div>`;
    try {
      const r = await api("coach/chat", { json: { messages: chatLog.map(m => ({ role: m.role, content: m.content })) } });
      chatLog.push({ role: "assistant", content: r.reply || "(no answer)", tools: r.tools_used.map(u => u.name), proposal: r.proposal });
    } catch (err) { chatLog.push({ role: "assistant", content: "Sorry: " + err.message }); }
    log.innerHTML = chatLog.map(msgHtml).join(""); bind(); $("#cb").disabled = false; log.scrollTop = log.scrollHeight;
  };
};

views.profile = async el => {
  const p = await api("profile"), wt = await api("weights");
  const rt = p.run_times, mt = p.meal_times;
  el.innerHTML = `<h1>Settings</h1><p class="sub">Single-user app: no account or login. Editable at any time. Changing weight logs a new entry so history is kept.</p>
  <form data-act="profile"><div class="grid"><div class="card c6"><h2>Athlete</h2><div class="form">
   ${field("Age", "age", p.age, "number")}${sel("Sex", "sex", [["male", "Male"], ["female", "Female"]], p.sex)}${field("Weight lb", "weight_lbs", lb(p.weight_kg), "number", 'step="0.1"')}${field("Height cm", "height_cm", p.height_cm, "number")}${field("Longest recent run km", "longest_run_km", p.longest_run_km, "number", 'step="0.1"')}
   ${field("Activity factor (1.2 desk – 1.5 active job)", "activity_factor", p.activity_factor, "number", 'step="0.05"')}${field("Daily deficit kcal (0–300)", "deficit_kcal", p.deficit_kcal, "number")}</div></div>
  <div class="card c6"><h2>Race</h2><div class="form">${field("Race date", "race_date", p.race_date, "date")}${field("Start time", "race_start", p.race_start, "time")}${field("Goal time", "goal_time", p.goal_time)}${field("Timezone (IANA)", "timezone", p.timezone)}</div>
   <p class="small muted">Historical benchmarks (not verified current fitness): ${p.benchmarks.map(b => esc(b.label)).join(" · ")}.</p></div>
  <div class="card c12"><h2>Schedule</h2><div class="form">${field("Tuesday run", "rt_tue", rt.tue, "time")}${field("Thursday run", "rt_thu", rt.thu, "time")}${field("Saturday run (set yours!)", "rt_sat", rt.sat, "time")}${field("Sunday long run", "rt_sun", rt.sun, "time")}
   ${field("Usual wake-up", "wake_time", p.wake_time, "time")}${field("Sleep target h", "sleep_target_h", p.sleep_target_h, "number", 'step="0.25"')}${field("Breakfast", "mt_breakfast", mt.breakfast, "time")}${field("Lunch", "mt_lunch", mt.lunch, "time")}${field("Dinner", "mt_dinner", mt.dinner, "time")}</div>
   <div class="row" style="margin-top:14px"><button>Save profile</button></div></div></div></form>
  <div class="card" style="margin-top:14px"><h2>Weight history</h2>${wt.points.length ? `<table><tr><th>Date</th><th>lb</th><th>Trend (lb)</th></tr>${wt.points.slice().reverse().map(x => `<tr><td>${x.date}</td><td>${lb(x.kg)}</td><td>${lb(x.trend)}</td></tr>`).join("")}</table>` : "<p class='muted'>None.</p>"}</div>`;
};

/* ---------- forms ---------- */
const actions = {
  weight: async d => { await api("weights", { json: { kg: +(d.lbs / LB).toFixed(2) } }); toast("Weight logged."); },
  nlog: async d => { await api("nutrition/log", { json: d }); toast("Nutrition saved."); },
  slog: async d => { const r = await api("sleep", { json: d }); toast("Recovery: " + r.status + (r.score != null ? " (" + r.score + ")" : "")); },
  alog: async d => {
    try { await api("activities", { json: d }); toast("Activity added."); }
    catch (e) { if (e.status === 409 && confirm(e.message + "\nAdd it anyway?")) await api("activities", { json: { ...d, force: true } }); else if (e.status !== 409) throw e; }
  },
  profile: async d => {
    const p = { ...d, run_times: { tue: d.rt_tue, thu: d.rt_thu, sat: d.rt_sat, sun: d.rt_sun }, meal_times: { breakfast: d.mt_breakfast, lunch: d.mt_lunch, dinner: d.mt_dinner }, sat_time_confirmed: true };
    ["rt_tue", "rt_thu", "rt_sat", "rt_sun", "mt_breakfast", "mt_lunch", "mt_dinner"].forEach(k => delete p[k]);
    const old = await api("profile");
    // keep the stored kg exactly unless the lb figure was actually changed
    p.weight_kg = +p.weight_lbs === +lb(old.weight_kg) ? old.weight_kg : +(p.weight_lbs / LB).toFixed(2);
    delete p.weight_lbs;
    await api("profile", { method: "PUT", json: p });
    if (p.weight_kg !== old.weight_kg) await api("weights", { json: { kg: p.weight_kg } });
    toast("Profile saved. Review your plan if you changed your race or schedule.");
  },
};
document.addEventListener("submit", async e => {
  const act = e.target.dataset.act; if (!act) return;
  e.preventDefault();
  try { await actions[act](form(e.target)); route(); } catch (err) { toast(err.message); }
});

/* ---------- router ---------- */
const NAV = [["dashboard", "Dashboard"], ["coach", "Coach"], ["plan", "Training plan"], ["nutrition", "Nutrition"], ["sleep", "Sleep & recovery"], ["activities", "Activities"], ["race", "Race readiness"], ["calendar", "Google Calendar"], ["profile", "Settings"]];
async function route() {
  const v = (location.hash.slice(1) || "dashboard"); const view = views[v] || views.dashboard;
  $("#nav").innerHTML = NAV.map(([k, l]) => `<a href="#${k}" class="${k === v ? "on" : ""}">${l}</a>`).join("");
  if (!S) { try { S = await api("state"); } catch { } }
  try { await view($("#main")); } catch (e) { $("#main").innerHTML = `<div class="banner">Something went wrong: ${esc(e.message)}</div>`; }
  if (v !== "dashboard") S = null;
}
window.addEventListener("hashchange", route);
function setTheme(t) { document.documentElement.dataset.theme = t; store.set("theme", t); }
setTheme(store.get("theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
$("#theme").onclick = () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
route();
