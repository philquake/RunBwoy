"""Run Coach: local Flask app. Run:  python app.py   then open http://127.0.0.1:5000"""
import hashlib
import json
import math
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

from flask import Flask, Response, jsonify, request, send_from_directory

import coach
import engine as E
import gcal
import knowledge

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
UPLOADS = os.path.join(DATA, "uploads")
DB = os.path.join(DATA, "runcoach.db")
os.makedirs(UPLOADS, exist_ok=True)

app = Flask(__name__, static_folder="static", static_url_path="")

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS weights(date TEXT PRIMARY KEY, kg REAL);
CREATE TABLE IF NOT EXISTS activities(id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, distance_km REAL, duration_s REAL,
  rpe INTEGER, notes TEXT, source TEXT, file TEXT, hash TEXT, splits TEXT, needs_review INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS workouts(date TEXT PRIMARY KEY, j TEXT);
CREATE TABLE IF NOT EXISTS nutrition(date TEXT PRIMARY KEY, kcal REAL, protein REAL, carbs REAL, fat REAL, fibre REAL, water_ml REAL, electrolytes_mg REAL);
CREATE TABLE IF NOT EXISTS sleep(date TEXT PRIMARY KEY, bed TEXT, wake TEXT, quality INTEGER, soreness INTEGER, fatigue INTEGER,
  motivation INTEGER, hydration INTEGER, rhr REAL, hrv REAL);
"""


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def q(sql, args=()):
    with db() as c:
        return [dict(r) for r in c.execute(sql, args)]


def run(sql, args=()):
    with db() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid


def init():
    with db() as c:
        c.executescript(SCHEMA)
    if not q("SELECT 1 FROM kv WHERE k='profile'"):
        save_profile(E.DEFAULT_PROFILE)
        run("INSERT OR REPLACE INTO weights VALUES(?,?)", (date.today().isoformat(), E.DEFAULT_PROFILE["weight_kg"]))
    if not q("SELECT 1 FROM workouts LIMIT 1"):
        save_plan(E.generate_plan(profile(), [], date.today())[0])


def profile():
    r = q("SELECT v FROM kv WHERE k='profile'")
    p = json.loads(r[0]["v"]) if r else {}
    return {**E.DEFAULT_PROFILE, **p}


def save_profile(p):
    run("INSERT OR REPLACE INTO kv VALUES('profile',?)", (json.dumps(p),))


def acts():
    out = q("SELECT * FROM activities ORDER BY date DESC, id DESC")
    for a in out:
        a["splits"] = json.loads(a["splits"]) if a["splits"] else None
        a["pace_s"] = E.act_pace(a)
        a["pace"] = E.pace_str(a["pace_s"])
        a["duration"] = E.fmt_time(a["duration_s"]) if a["duration_s"] else None
    return out


def workouts():
    return [json.loads(r["j"]) for r in q("SELECT j FROM workouts ORDER BY date")]


def save_plan(ws, from_date=None):
    with db() as c:
        if from_date:
            c.execute("DELETE FROM workouts WHERE date>=?", (from_date.isoformat(),))
        for w in ws:
            c.execute("INSERT OR REPLACE INTO workouts VALUES(?,?)", (w["date"], json.dumps(w)))


def weights():
    return q("SELECT date, kg FROM weights ORDER BY date")


def current_kg():
    w = weights()
    return w[-1]["kg"] if w else profile()["weight_kg"]


def sleep_logs():
    return q("SELECT * FROM sleep ORDER BY date DESC")


def today():
    return date.today()


def current_recovery():
    return E.recovery_score(sleep_logs(), profile(), today())


def with_status(ws, a):
    t = today()
    return [{**w, "status": E.workout_status(w, a, t)} for w in ws]


# ---------------- state ----------------
@app.get("/api/state")
def state():
    p, A, W, t = profile(), acts(), workouts(), today()
    rec = current_recovery()
    wt = E.weight_trend(weights())
    ws = with_status(W, A)
    td = next((w for w in ws if w["date"] == t.isoformat()), None)
    nxt_long = next((w for w in ws if w["kind"] == "long" and w["date"] >= t.isoformat()), None)
    ntarget = E.nutrition_target(p, current_kg(), next((w for w in W if w["date"] == t.isoformat()), None), t, rec, wt["rate_kg_wk"])
    ready = E.readiness(p, A, W, sleep_logs(), t)
    nlog = (q("SELECT * FROM nutrition WHERE date=?", (t.isoformat(),)) or [None])[0]
    last_sleep = (q("SELECT * FROM sleep ORDER BY date DESC LIMIT 1") or [None])[0]
    if last_sleep and last_sleep.get("bed") and last_sleep.get("wake"):
        last_sleep["hours"] = round(E.sleep_duration(last_sleep["bed"], last_sleep["wake"]), 1)
    fit = ready["projection"]
    return jsonify({
        "today": t.isoformat(), "profile": p, "race": E.race_info(p, t), "today_workout": td, "next_long": nxt_long,
        "weekly": E.weekly_mileage(A, t), "pace_trend": E.pace_trend(A), "nutrition_target": ntarget,
        "nutrition_log": nlog, "weight": wt, "last_sleep": last_sleep, "sleep_target": E.sleep_target(p, t),
        "recovery": rec, "readiness": ready,
        "paces": {k: f"{E.pace_str(v[0])}–{E.pace_str(v[1])}/km" for k, v in E.training_paces(fit, E.race_info(p, t)).items()},
        "coach": E.coach(p, A, W, weights(), ntarget, rec, ready, t),
        "needs_review": sum(1 for a in A if a["needs_review"]),
    })


# ---------------- profile & weight ----------------
@app.get("/api/profile")
def get_profile():
    return jsonify(profile())


@app.put("/api/profile")
def put_profile():
    p = {**profile(), **request.json}
    for k in ("age", "height_cm"):
        p[k] = int(p[k])
    for k in ("weight_kg", "longest_run_km", "activity_factor", "deficit_kcal", "sleep_target_h"):
        p[k] = float(p[k])
    p["goal_time"] = E.fmt_time(E.parse_time(p["goal_time"]))
    save_profile(p)
    return jsonify(p)


@app.post("/api/weights")
def add_weight():
    j = request.json
    run("INSERT OR REPLACE INTO weights VALUES(?,?)", (j.get("date") or today().isoformat(), float(j["kg"])))
    return jsonify(E.weight_trend(weights()))


@app.get("/api/weights")
def get_weights():
    return jsonify(E.weight_trend(weights()))


# ---------------- activities ----------------
def haversine(a, b):
    R = 6371.0088
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl, dp = math.radians(b[1] - a[1]), p2 - p1
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def parse_gpx(raw):
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    root = ET.fromstring(raw)
    pts = []
    for tp in root.iter():
        if tp.tag.endswith("trkpt"):
            tm = next((c.text for c in tp if c.tag.endswith("time")), None)
            if tm:
                pts.append((float(tp.get("lat")), float(tp.get("lon")),
                            datetime.fromisoformat(tm.replace("Z", "+00:00"))))
    if len(pts) < 2:
        raise ValueError("GPX has no timed track points")
    dist, splits, nxt, tk = 0.0, [], 1.0, pts[0][2]
    for a, b in zip(pts, pts[1:]):
        dist += haversine(a, b)
        if dist >= nxt:
            splits.append(round((b[2] - tk).total_seconds()))
            tk, nxt = b[2], nxt + 1
    return {"date": pts[0][2].date().isoformat(), "distance_km": round(dist, 2),
            "duration_s": round((pts[-1][2] - pts[0][2]).total_seconds()), "splits": splits}


MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()


def parse_ocr(text):
    r = {}
    m = re.search(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*km", text, re.I)
    if m:
        r["distance_km"] = float(m.group(1).replace(",", "."))
    m = re.search(r"\b(\d{1,2}:\d{2}:\d{2})\b", text) or re.search(r"\b(\d{1,2}:\d{2})\b(?!\s*/)", text)
    if m:
        r["duration_s"] = E.parse_time(m.group(1))
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        r["date"] = m.group(1)
    else:
        m = re.search(r"(?:(\d{1,2})\s+([A-Za-z]{3})[a-z]*|([A-Za-z]{3})[a-z]*\s+(\d{1,2})),?\s+(\d{4})", text)
        if m:
            day = int(m.group(1) or m.group(4))
            mon = (m.group(2) or m.group(3)).lower()
            if mon in MONTHS:
                r["date"] = date(int(m.group(5)), MONTHS.index(mon) + 1, day).isoformat()
    return r


def ocr_image(path):
    try:
        import pytesseract
        from PIL import Image
        return pytesseract.image_to_string(Image.open(path)), None
    except Exception as e:  # tesseract not installed: manual entry fallback
        return "", f"OCR unavailable ({type(e).__name__}). Enter the values manually."


def duplicate_of(d, km, ignore_id=None):
    if not d or not km:
        return None
    for a in acts():
        if a["id"] != ignore_id and a["date"] == d and a["distance_km"] and abs(a["distance_km"] - km) < 0.15:
            return a
    return None


def num(x):
    return float(x) if x not in (None, "") else None


@app.get("/api/activities")
def list_acts():
    return jsonify(acts())


@app.post("/api/activities")
def add_act():
    j = request.json
    dur = E.parse_time(j["duration"]) if j.get("duration") else num(j.get("duration_s"))
    km = num(j.get("distance_km"))
    dup = duplicate_of(j.get("date"), km)
    if dup and not j.get("force"):
        return jsonify({"error": "duplicate", "message": f"Looks like a duplicate of activity #{dup['id']} ({dup['date']}, {dup['distance_km']} km).", "activity": dup}), 409
    aid = run("INSERT INTO activities(date,distance_km,duration_s,rpe,notes,source) VALUES(?,?,?,?,?,?)",
              (j["date"], km, dur, j.get("rpe") or None, j.get("notes", ""), "manual"))
    return jsonify({"id": aid})


@app.put("/api/activities/<int:aid>")
def edit_act(aid):
    j = request.json
    dur = E.parse_time(j["duration"]) if j.get("duration") else num(j.get("duration_s"))
    km = num(j.get("distance_km"))
    review = 0 if (j.get("date") and km and dur) else 1
    run("UPDATE activities SET date=?,distance_km=?,duration_s=?,rpe=?,notes=?,needs_review=? WHERE id=?",
        (j.get("date"), km, dur, j.get("rpe") or None, j.get("notes", ""), review, aid))
    return jsonify({"ok": True})


@app.delete("/api/activities/<int:aid>")
def del_act(aid):
    run("DELETE FROM activities WHERE id=?", (aid,))
    return jsonify({"ok": True})


@app.post("/api/activities/upload")
def upload():
    results = []
    for f in request.files.getlist("files"):
        raw = f.read()
        h = hashlib.sha256(raw).hexdigest()
        ext = os.path.splitext(f.filename)[1].lower() or ".bin"
        if q("SELECT id FROM activities WHERE hash=?", (h,)):
            results.append({"file": f.filename, "status": "duplicate", "message": "This exact file was already imported."})
            continue
        path = os.path.join(UPLOADS, h + ext)
        with open(path, "wb") as out:
            out.write(raw)   # original is always preserved
        try:
            if ext == ".gpx":
                g = parse_gpx(raw)
                fields, note, splits = {k: g[k] for k in ("date", "distance_km", "duration_s")}, None, g["splits"]
            else:
                text, note = ocr_image(path)
                fields, splits = parse_ocr(text), None
        except Exception as e:
            fields, note, splits = {}, f"Could not read file: {e}", None
        dup = duplicate_of(fields.get("date"), fields.get("distance_km"))
        if dup:
            results.append({"file": f.filename, "status": "duplicate", "message": f"Matches activity #{dup['id']} ({dup['date']}, {dup['distance_km']} km); not imported.", **fields})
            continue
        review = 0 if all(fields.get(k) for k in ("date", "distance_km", "duration_s")) and ext == ".gpx" else 1
        aid = run("INSERT INTO activities(date,distance_km,duration_s,source,file,hash,splits,needs_review) VALUES(?,?,?,?,?,?,?,?)",
                  (fields.get("date") or today().isoformat(), fields.get("distance_km"), fields.get("duration_s"),
                   "gpx" if ext == ".gpx" else "screenshot", os.path.basename(path), h, json.dumps(splits) if splits else None, review))
        results.append({"file": f.filename, "status": "review" if review else "imported", "id": aid, "message": note or ("Check the values before relying on them." if review else "Imported."), **fields})
    return jsonify(results)


@app.get("/api/uploads/<name>")
def get_upload(name):
    return send_from_directory(UPLOADS, os.path.basename(name))


# ---------------- plan ----------------
def _plan_inputs():
    A, W, t = acts(), workouts(), today()
    return A, W, t


@app.get("/api/plan")
def get_plan():
    A, W, t = _plan_inputs()
    return jsonify({"workouts": with_status(W, A), "paces": state().json["paces"]})


@app.post("/api/plan/propose")
def propose():
    return jsonify(_propose())


def _propose():
    A, W, t = _plan_inputs()
    new, reasons = E.generate_plan(profile(), A, t, current_recovery(), E.completion_rate(W, A, t))
    cur = {w["date"]: w for w in W}
    changes = []
    for w in new:
        o = cur.get(w["date"])
        if not o or any(o.get(k) != w.get(k) for k in ("kind", "distance_km", "pace", "structure")):
            changes.append({"date": w["date"], "old": o and f"{o['title']} {o['distance_km']:g} km", "new": f"{w['title']} {w['distance_km']:g} km"})
    return {"workouts": new, "reasons": reasons, "changes": changes,
            "summary": f"{len(changes)} change(s) proposed." if changes else "No changes needed: the saved plan already matches your latest data."}


@app.post("/api/plan/apply")
def apply_plan():
    """Saves a previously proposed plan. Only runs when the user clicks Confirm."""
    ws = request.json["workouts"]
    save_plan(ws, today())
    return jsonify({"saved": len(ws)})


# ---------------- nutrition ----------------
@app.get("/api/nutrition")
def nutrition():
    return jsonify(_nutrition(request.args.get("date") or today().isoformat()))


def _nutrition(day):
    d = date.fromisoformat(day)
    p = profile()
    W = {w["date"]: w for w in workouts()}
    w = W.get(d.isoformat())
    rec = current_recovery()
    t = E.nutrition_target(p, current_kg(), w, d, rec, E.weight_trend(weights())["rate_kg_wk"])
    log = (q("SELECT * FROM nutrition WHERE date=?", (d.isoformat(),)) or [None])[0]
    hist = q("SELECT * FROM nutrition ORDER BY date DESC LIMIT 14")
    return {"date": d.isoformat(), "workout": w, "target": t, "meals": E.meal_plan(p, t, w, d), "log": log, "history": hist}


@app.post("/api/nutrition/log")
def log_nutrition():
    j = request.json
    f = lambda k: num(j.get(k))
    run("INSERT OR REPLACE INTO nutrition VALUES(?,?,?,?,?,?,?,?)",
        (j.get("date") or today().isoformat(), f("kcal"), f("protein"), f("carbs"), f("fat"), f("fibre"), f("water_ml"), f("electrolytes_mg")))
    return jsonify({"ok": True})


# ---------------- sleep & recovery ----------------
@app.get("/api/sleep")
def get_sleep():
    p, t = profile(), today()
    logs = sleep_logs()
    for l in logs:
        if l["bed"] and l["wake"]:
            l["hours"] = round(E.sleep_duration(l["bed"], l["wake"]), 1)
    upcoming = [E.sleep_target(p, t + timedelta(days=i)) for i in range(0, 10)]
    return jsonify({"logs": logs[:30], "recovery": current_recovery(), "targets": upcoming})


@app.post("/api/sleep")
def post_sleep():
    j = request.json
    f = lambda k: int(j[k]) if j.get(k) not in (None, "") else None
    run("INSERT OR REPLACE INTO sleep VALUES(?,?,?,?,?,?,?,?,?,?)",
        (j.get("date") or today().isoformat(), j["bed"], j["wake"], f("quality"), f("soreness"), f("fatigue"),
         f("motivation"), f("hydration"), num(j.get("rhr")), num(j.get("hrv"))))
    return jsonify(current_recovery())


# ---------------- race ----------------
@app.get("/api/race")
def race():
    p, t = profile(), today()
    r = E.race_info(p, t)
    rd = date.fromisoformat(p["race_date"])
    wake = E.sleep_target(p, rd - timedelta(days=1))
    plan = [
        {"time": "Two days before", "what": "Normal meals, hydrate well, easy sleep. Lay out kit, shoes, gels, bib, transport."},
        {"time": "Day before", "what": "Carb-up (~6 g/kg, low fibre, familiar foods). Walk only. Bed early: " + wake["bed"] + "."},
        {"time": wake["wake"], "what": "Wake up. Light stretch."},
        {"time": E.min_to_hm(E.hm_to_min(r["start"]) - 135), "what": "Race breakfast: white toast/bagel + honey/jam + banana, small coffee if usual. 75-120 g carbs, low fat/fibre."},
        {"time": E.min_to_hm(E.hm_to_min(r["start"]) - 90), "what": "Sip 400-500 ml fluid with electrolytes over the next hour. Toilet."},
        {"time": E.min_to_hm(E.hm_to_min(r["start"]) - 45), "what": "Travel/arrive, easy 10 min jog + mobility, 3-4 strides."},
        {"time": E.min_to_hm(E.hm_to_min(r["start"]) - 15), "what": "One gel (~25 g carbs) with a little water."},
        {"time": r["start"], "what": f"Start. First 3 km at {E.pace_str(r['goal_pace_s'] + 8)}/km, then settle to RPE 6-7. Goal pace {r['goal_pace']}/km only if it feels controlled."},
        {"time": "From ~30 min", "what": "A gel (~25 g carbs) every 35-40 min plus water at every station (30-60 g carbs/hour)."},
        {"time": "After the finish", "what": "Walk, fluids with salt, 30 g protein + carbs within 45 min."},
    ]
    return jsonify({"race": r, "plan": plan, "readiness": E.readiness(p, acts(), workouts(), sleep_logs(), t)})


# ---------------- calendar ----------------
def _events(include):
    p = profile()
    return E.build_events(p, workouts(), current_kg(), current_recovery(), today(), include)


def _include():
    inc = request.args.get("include", "training,meals,sleep").split(",")
    return tuple(i for i in inc if i in ("training", "meals", "sleep"))


@app.get("/api/calendar.ics")
def ics():
    body = gcal.to_ics(_events(_include()), profile()["timezone"])
    return Response(body, mimetype="text/calendar",
                    headers={"Content-Disposition": "attachment; filename=run-coach.ics"})


@app.get("/api/calendar/preview")
def preview():
    ev = _events(_include())
    ev.sort(key=lambda e: e["start"])
    return jsonify({"count": len(ev), "events": [
        {"uid": e["uid"], "kind": e["kind"], "summary": e["summary"], "start": e["start"].isoformat(timespec="minutes"),
         "end": e["end"].isoformat(timespec="minutes"), "description": e["description"]} for e in ev]})


@app.get("/api/gcal/status")
def gstatus():
    return jsonify(gcal.status())


@app.post("/api/gcal/sync")
def gsync():
    st = gcal.status()
    if not st["libraries"]:
        return jsonify({"error": "Install: pip install google-api-python-client google-auth-oauthlib"}), 400
    if not st["credentials_file"]:
        return jsonify({"error": f"Put your Google OAuth desktop client file at {st['credentials_path']} (see README)."}), 400
    try:
        return jsonify(gcal.sync(_events(_include()), profile()["timezone"]))
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


# ---------------- AI coach (Ollama) ----------------
def _tool_dashboard():
    s = state().get_json()
    return {"today": s["today"], "race": s["race"], "today_workout": s["today_workout"], "next_long_run": s["next_long"],
            "weekly_km_last_6_weeks": s["weekly"], "training_paces": s["paces"], "nutrition_target_today": s["nutrition_target"],
            "recovery": {k: s["recovery"].get(k) for k in ("score", "status", "basis", "missing")},
            "readiness": {k: s["readiness"][k] for k in ("score", "confidence", "verdict", "missing")},
            "projected_half": s["readiness"]["projection"], "weight_trend_lb": {"trend_lb": s["weight"]["trend_kg"] and round(s["weight"]["trend_kg"] * 2.20462, 1),
                                "rate_lb_per_week": s["weight"]["rate_kg_wk"] and round(s["weight"]["rate_kg_wk"] * 2.20462, 1)}}


def _tool_plan(days=14):
    end = (today() + timedelta(days=int(days))).isoformat()
    keep = ("date", "title", "kind", "distance_km", "pace", "speed", "duration_min", "rpe", "structure", "status")
    return [{k: w[k] for k in keep} for w in with_status(workouts(), acts()) if today().isoformat() <= w["date"] <= end]


def _tool_nutrition(date=None):
    n = _nutrition(date or today().isoformat())
    return {"date": n["date"], "target": n["target"], "meals": n["meals"], "logged": n["log"]}


def _tool_activities(limit=8):
    return [{k: a[k] for k in ("date", "distance_km", "duration", "pace", "rpe", "source", "needs_review")} for a in acts()[:int(limit)]]


def _tool_sleep():
    s = get_sleep().get_json()
    return {"recovery": s["recovery"], "recent_logs": s["logs"][:7], "upcoming_targets": s["targets"][:5]}


def _tool_readiness():
    return E.readiness(profile(), acts(), workouts(), sleep_logs(), today())


def _snapshot():
    """Compact current state, injected into every coach request."""
    d = _tool_dashboard()
    a = acts()
    last = next((x for x in a if x["distance_km"] and x["duration_s"]), None)
    tw, nl, nt = d["today_workout"], d["next_long_run"], d["nutrition_target_today"]
    snap = {
        "today": d["today"], "race": {k: d["race"][k] for k in ("date", "days_left", "start", "goal_time", "goal_pace")},
        "today_workout": tw and {k: tw[k] for k in ("title", "distance_km", "pace", "duration_min", "rpe")},
        "next_long_run": nl and {k: nl[k] for k in ("date", "distance_km", "pace", "duration_min")},
        "training_paces": d["training_paces"],
        "nutrition_today": {k: nt[k] for k in ("label", "kcal", "protein", "carbs", "fat", "water_ml")},
        "projected_half": {k: d["projected_half"][k] for k in ("half_time", "source")},
        "readiness": {"score": d["readiness"]["score"], "confidence": d["readiness"]["confidence"], "verdict": d["readiness"]["verdict"]},
        "recovery": d["recovery"]["status"],
        "km_per_week_last_6": [w["km"] for w in d["weekly_km_last_6_weeks"]],
        "last_run": last and {k: last[k] for k in ("date", "distance_km", "duration", "pace")},
        "body_weight_lb": round(current_kg() * 2.20462, 1),
        "heart_rate_monitor": "none (use RPE and the talk test)",
    }
    horizon = (today() + timedelta(days=7)).isoformat()
    snap["planned_runs_next_7_days"] = [
        f"{date.fromisoformat(w['date']):%a %b %d}: {w['title']} {w['distance_km']:g} km @ {w['pace']}"
        for w in workouts() if today().isoformat() <= w["date"] <= horizon and w["kind"] != "rest"] or ["none"]
    snap["note"] = "All other days in the next 7 days are rest/optional."
    st = E.sleep_target(profile(), today())
    snap["sleep_tonight"] = {"bed": st["bed"], "wake": st["wake"], "target_hours": st["hours"]}
    if nl:
        n = _nutrition(nl["date"])
        snap["long_run_day_nutrition"] = {"date": nl["date"], "kcal": n["target"]["kcal"], "protein": n["target"]["protein"],
                                          "carbs": n["target"]["carbs"], "fat": n["target"]["fat"],
                                          "meals": [f"{m['time']} {m['name']} ({m['kcal']} kcal)" for m in n["meals"]]}
    return json.dumps(snap, default=str)


def _tool_knowledge(query):
    return knowledge.search(query, 3)


TOOL_IMPL = {"search_knowledge": _tool_knowledge, "get_dashboard": _tool_dashboard, "get_plan": _tool_plan, "get_nutrition": _tool_nutrition,
             "get_recent_activities": _tool_activities, "get_sleep_recovery": _tool_sleep,
             "get_readiness": _tool_readiness, "propose_plan_change": _propose}


@app.get("/api/coach/status")
def coach_status():
    return jsonify(coach.status())


@app.post("/api/coach/chat")
def coach_chat():
    st = coach.status()
    if not st["running"]:
        return jsonify({"error": "Ollama isn't running. Start the Ollama app and try again."}), 503
    if not st["model_installed"]:
        return jsonify({"error": f"Model '{coach.MODEL}' not found. Run: ollama create runcoach -f coach/Modelfile"}), 503
    try:
        return jsonify(coach.chat(request.json["messages"], TOOL_IMPL, today().isoformat(), profile()["race_date"],
                                  context=_snapshot, notes_fn=lambda q: knowledge.search(q, 3)))
    except Exception as e:
        return jsonify({"error": f"Coach failed: {type(e).__name__}: {e}"}), 500


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


init()
if __name__ == "__main__":
    import socket
    import sys
    import threading
    import webbrowser
    URL = "http://127.0.0.1:5000"
    if sys.stdout is None or sys.stderr is None:   # started with pythonw (no console): log to a file
        sys.stdout = sys.stderr = open(os.path.join(DATA, "server.log"), "a", buffering=1, encoding="utf-8")
    with socket.socket() as s:
        already_running = s.connect_ex(("127.0.0.1", 5000)) == 0
    if "--open" in sys.argv:
        if already_running:        # second click on the taskbar icon: just show the page
            webbrowser.open(URL)
            sys.exit(0)
        threading.Timer(1.5, lambda: webbrowser.open(URL)).start()
    elif already_running:
        sys.exit("Run Coach is already running at " + URL)
    app.run(host="127.0.0.1", port=5000, debug=False)
