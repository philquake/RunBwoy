"""Run Coach engine: every number in the app is computed here in plain Python.

Pure functions only (no database, no network) so they are easy to test.
Dates are ISO strings 'YYYY-MM-DD'; times are 'HH:MM'.
"""
import copy
import math
import statistics
from datetime import date, datetime, timedelta

HALF_KM = 21.0975

def _example_race_date():
    """A Sunday about 10 weeks out, so a fresh install always has a sensible plan."""
    d = date.today() + timedelta(days=70)
    return (d + timedelta(days=(6 - d.weekday()) % 7)).isoformat()


DEFAULT_PROFILE = {
    "age": 30, "sex": "male", "weight_kg": 70.0, "height_cm": 175,   # example values: set yours in Settings
    "longest_run_km": 10.0, "runs_per_week": 4,
    "device": "Smartphone with GPS", "heart_rate_monitor": False,
    "data_source": "Free Strava screenshots",
    "nutrition_objective": "Lose fat while maintaining running performance",
    "race_name": "Half marathon", "race_date": _example_race_date(), "race_start": "08:00",
    "race_km": HALF_KM, "goal_time": "2:20:00",
    "benchmarks": [                                           # example past efforts: replace in Settings or import runs
        {"label": "5K", "km": 5.0, "time_s": 1800},           # 30:00
        {"label": "10K", "km": 10.0, "time_s": 3900},         # 1:05:00
    ],
    # schedule
    "run_times": {"tue": "18:00", "thu": "18:00", "sat": "07:00", "sun": "05:00"},
    "sat_time_confirmed": False,          # onboarding must collect this
    "wake_time": "06:30", "sleep_target_h": 8.0,
    "meal_times": {"breakfast": "07:30", "lunch": "12:30", "dinner": "19:30"},
    "timezone": "UTC",                    # set your IANA timezone in Settings, e.g. Europe/London
    # nutrition
    "activity_factor": 1.30,              # non-exercise activity multiplier on BMR (editable)
    "deficit_kcal": 250,
}


# ---------- small helpers ----------
def d_(s):
    return date.fromisoformat(s) if isinstance(s, str) else s


def hm_to_min(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def min_to_hm(m):
    m %= 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def parse_time(s):
    """'2:30:00' or '25:10' -> seconds."""
    parts = [float(x) for x in str(s).strip().split(":")]
    t = 0
    for p in parts:
        t = t * 60 + p
    return t


def fmt_time(sec):
    sec = round(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def pace_str(sec_per_km):
    if not sec_per_km:
        return "–"
    m, s = divmod(round(sec_per_km), 60)
    return f"{m}:{s:02d}"


def riegel(t1, d1, d2=HALF_KM):
    return t1 * (d2 / d1) ** 1.06


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


# ---------- race ----------
def race_info(p, today):
    rd = d_(p["race_date"])
    goal = parse_time(p["goal_time"])
    km = p.get("race_km", HALF_KM)
    return {
        "date": rd.isoformat(), "days_left": (rd - today).days,
        "goal_s": goal, "goal_time": fmt_time(goal),
        "goal_pace_s": goal / km, "goal_pace": pace_str(goal / km),
        "goal_speed_kmh": round(km / (goal / 3600), 2), "km": km,
        "start": p["race_start"], "name": p["race_name"],
    }


# ---------- fitness & paces ----------
def fitness(p, acts, today):
    """Projected half-marathon time. Verified (recent imported runs) beats historical."""
    recent = [a for a in acts if a.get("distance_km") and a.get("duration_s")
              and a["distance_km"] >= 5 and 0 <= (today - d_(a["date"])).days <= 42]
    longer = [a for a in recent if a["distance_km"] >= 8]
    # Longer efforts are the most relevant evidence for a half marathon: short runs project
    # too optimistically (race-like 5Ks) or too pessimistically (easy jogs).
    use = longer if longer else recent
    if len(recent) >= 2 or longer:
        proj = [riegel(a["duration_s"], a["distance_km"]) for a in use]
        src, n = "verified", len(recent)
    else:
        proj = [riegel(b["time_s"], b["km"]) for b in p["benchmarks"]]
        src, n = "historical", len(recent)
    t = statistics.median(proj)
    return {"half_time_s": t, "half_time": fmt_time(t), "half_pace_s": t / HALF_KM,
            "source": src, "n_recent": n,
            "spread": [fmt_time(min(proj)), fmt_time(max(proj))]}


def training_paces(fit, race):
    r = fit["half_pace_s"]
    return {
        "easy": (r * 1.06, r * 1.12),
        "long": (r * 1.08, r * 1.14),
        "steady": (r * 0.95, r * 0.99),
        "goal": (race["goal_pace_s"], race["goal_pace_s"] + 4),
    }


# ---------- workouts ----------
def _mk(d, kind, title, km, pace, rpe, structure, notes="", minutes=None):
    lo, hi = pace
    avg = (lo + hi) / 2
    return {
        "date": d.isoformat(), "kind": kind, "title": title,
        "distance_km": round(km, 1), "pace_lo": round(lo), "pace_hi": round(hi),
        "pace": f"{pace_str(lo)}–{pace_str(hi)}/km",
        "speed": f"{3600 / hi:.1f}–{3600 / lo:.1f} km/h",
        "duration_min": round(minutes if minutes is not None else km * avg / 60),
        "rpe": rpe, "structure": structure, "notes": notes,
    }


def _quality(d, offset, pc):
    easy = sum(pc["easy"]) / 2
    steady = sum(pc["steady"]) / 2
    goal = sum(pc["goal"]) / 2
    if offset >= 4:
        km = 1.5 + 1.5 + 900 / steady + 0.25 * 4   # warm-up + cool-down + 5x3 min + jogs
        sp = pc["steady"]
        title, struct = "Quality: steady fartlek", (
            f"1.5 km easy warm-up, 5 x 3 min steady @ {pace_str(pc['steady'][0])}–{pace_str(pc['steady'][1])}/km "
            f"(RPE 6) with 2 min easy jog, 1.5 km easy cool-down")
        minutes = 3 + 15 + 8 + 3
        rpe = 6
    elif offset == 3:
        km, sp, rpe = 6.0, pc["steady"], 6
        title, struct = "Quality: steady tempo", (
            f"1.5 km easy, 2 x 1.5 km @ {pace_str(pc['steady'][0])}–{pace_str(pc['steady'][1])}/km (RPE 6–7) "
            f"with 3 min easy jog, 1.5 km easy cool-down")
        minutes = (3 * easy + 3 * steady) / 60 + 3 + 1
    elif offset == 2:
        km, sp, rpe = 7.0, pc["goal"], 7
        title, struct = "Quality: race-pace familiarisation", (
            f"2 km easy, 3 x 1 km @ goal pace {pace_str(pc['goal'][0])}/km (RPE 7) with 2 min easy jog, 1.5 km easy cool-down. "
            "Stop the reps early if form or breathing falls apart.")
        minutes = (3.5 * easy + 3 * goal) / 60 + 4 + 1
    else:
        km, sp, rpe = 5.0, pc["goal"], 6
        title, struct = "Quality: light sharpening", (
            f"1.5 km easy, 2 x 1 km @ goal pace {pace_str(pc['goal'][0])}/km (RPE 6–7) with 2 min jog, 1.5 km easy. "
            "Finish feeling fresh, not tired.")
        minutes = (3.0 * easy + 2 * goal) / 60 + 2 + 1
    return _mk(d, "quality", title, km, sp, rpe, struct,
               "Main-set pace shown; warm-up and cool-down are easy. Use RPE + talk test, not pace alone, if it is hot.",
               minutes)


def generate_plan(p, acts, today, recovery=None, completion=None):
    """Return (workouts, reasons). Pure proposal; caller decides whether to save."""
    race = race_info(p, today)
    fit = fitness(p, acts, today)
    pc = training_paces(fit, race)
    rd = d_(p["race_date"])
    reasons = [f"Training paces come from {'verified recent runs' if fit['source'] == 'verified' else 'historical benchmarks (not yet verified by recent imported runs)'}: "
               f"projected half marathon {fit['half_time']} (~{pace_str(fit['half_pace_s'])}/km)."]
    runs_ever = [a for a in acts if a.get("distance_km")]
    if runs_ever:
        # Long-run base comes from the last 3 weeks of real running (never below 8 km),
        # not from an old best, so a gap in training can't trigger a big jump.
        last21 = [a["distance_km"] for a in runs_ever if 0 <= (today - d_(a["date"])).days <= 21]
        cur_long = max([8.0] + last21)
        if cur_long < p["longest_run_km"]:
            reasons.append(f"Your longest run in the last 3 weeks was {max(last21 or [0]):g} km (earlier best {p['longest_run_km']:g} km), "
                           f"so long runs rebuild from {cur_long:g} km, adding at most 2 km a week.")
    else:
        cur_long = p["longest_run_km"]
    reduced = recovery is not None and recovery.get("status") == "Reduced"
    low_completion = completion is not None and completion < 0.5
    if low_completion:
        reasons.append("You completed under half of the recent sessions, so non-long runs are trimmed 15% and the long run only grows modestly.")
    out = []
    d = today
    while d <= rd:
        wd = d.weekday()
        sunday = d + timedelta(days=6 - wd)
        off = max(0, (rd - sunday).days // 7)
        near = (d - today).days <= 2
        k = 0.85 if low_completion else 1.0
        w = None
        if d == rd:
            w = _mk(d, "race", f"RACE DAY: {race['name']}", race["km"], pc["goal"], 8,
                    f"Start {race['start']}. Run the first 3 km at {pace_str(race['goal_pace_s'] + 8)}/km, settle to "
                    f"{race['goal_pace']}/km only if breathing is controlled. Fuel on plan.",
                    "Goal is a target, not a promise. Never chase it with a hard first half.", race["goal_s"] / 60)
        elif wd == 6:  # long run
            tpl = {0: None, 1: 10.0, 2: 16.0, 3: 14.0}.get(off, 13.0 if off == 4 else 12.0)
            if tpl:
                km = min(tpl, cur_long + 2)
                if off >= 2:
                    cur_long = max(cur_long, km)
                if reduced and near:
                    km = round(km * 0.85, 1)
                    reasons.append(f"{d}: recovery is reduced, long run shortened to {km} km.")
                taper = " Taper week: keep it relaxed." if off == 1 else ""
                reh = (" Race-morning rehearsal: eat the planned race breakfast, carry the same gels and shoes."
                       if off == 2 else "")
                w = _mk(d, "long", "Long run", km, pc["long"], 4,
                        "Continuous, conversational pace. Walk 1 min through water/fuel stops if needed. "
                        "Over 75 min: 30–60 g carbs per hour.", "Keep it easy; time on feet matters more than speed." + taper + reh)
        elif wd == 1:
            km = {0: 5.0, 1: 5.0, 2: 6.0, 3: 5.0}.get(off, 5.0) * k
            if off == 0:
                w = _mk(d, "easy", "Easy run + strides", km, pc["easy"], 3,
                        "Easy run, then 4 x 15 s relaxed strides with full recovery.", "Race week: stay fresh.")
            else:
                w = _mk(d, "easy", "Easy run", km, pc["easy"], 3,
                        "Easy continuous run. You should be able to speak full sentences.", "")
        elif wd == 3:
            if off == 0:
                w = _mk(d, "easy", "Easy shake-out", 4.0, pc["easy"], 3, "Very easy. Optional 3 x 15 s strides.", "Race week: stay fresh.")
            else:
                w = _quality(d, off, pc)
                if reduced and near:
                    w = _mk(d, "easy", "Easy run (swapped from quality)", 5.0, pc["easy"], 3,
                            "Easy continuous run.", "Recovery is reduced, so the quality session was swapped for easy running.")
                    reasons.append(f"{d}: quality session swapped for an easy run because recovery is reduced.")
        elif wd == 5:
            if off <= 1:
                w = _mk(d, "rest", "Rest day", 0, pc["easy"], 1,
                        "Rest. Optional 10 min mobility." if off == 1 else "Rest before the race. Optional 10-15 min shake-out jog with 2-3 strides.",
                        "Day before a long run or the race: no running needed.")
            elif reduced and near:
                w = _mk(d, "rest", "Rest day (recovery)", 0, pc["easy"], 1, "Rest or 10 min mobility.",
                        "Skipped Saturday because recovery is low; four runs is a maximum, not a requirement.")
                reasons.append(f"{d}: Saturday run recommended skipped because recovery is reduced.")
            else:
                w = _mk(d, "easy", "Short easy / recovery run", 3.0 * k, pc["easy"], 2,
                        "Very easy, shorter than your weekday runs. Never intervals or tempo the day before the long run.",
                        "Skip it if legs feel heavy.")
        else:
            w = _mk(d, "rest", "Rest / mobility / cross-training", 0, pc["easy"], 1,
                    "Rest, or 20-30 min easy cross-training or mobility.", "Optional.")
        if w:
            out.append(w)
        d += timedelta(days=1)
    return out, reasons


# ---------- activities & analytics ----------
def act_pace(a):
    if a.get("distance_km") and a.get("duration_s"):
        return a["duration_s"] / a["distance_km"]
    return None


def week_start(d):
    return d - timedelta(days=d.weekday())


def weekly_mileage(acts, today, weeks=6):
    ws = week_start(today)
    rows = []
    for i in range(weeks - 1, -1, -1):
        s = ws - timedelta(days=7 * i)
        e = s + timedelta(days=7)
        km = sum(a["distance_km"] or 0 for a in acts if s <= d_(a["date"]) < e)
        mins = sum((a["duration_s"] or 0) / 60 for a in acts if s <= d_(a["date"]) < e)
        rows.append({"week": s.isoformat(), "km": round(km, 1), "minutes": round(mins)})
    return rows


def pace_trend(acts, n=10):
    runs = [a for a in acts if act_pace(a) and a["distance_km"] >= 3]
    runs.sort(key=lambda a: a["date"])
    return [{"date": a["date"], "pace_s": round(act_pace(a)), "km": a["distance_km"], "rpe": a.get("rpe")}
            for a in runs[-n:]]


def completion_rate(workouts, acts, today, days=14):
    planned = [w for w in workouts if w["kind"] in ("easy", "quality", "long")
               and 0 < (today - d_(w["date"])).days <= days]
    if not planned:
        return None
    done = 0
    for w in planned:
        if any(a["date"] == w["date"] and (a["distance_km"] or 0) >= 0.5 * w["distance_km"] for a in acts):
            done += 1
    return done / len(planned)


def workout_status(w, acts, today):
    dd = d_(w["date"])
    if w["kind"] == "rest":
        return "rest"
    hit = [a for a in acts if a["date"] == w["date"]]
    if hit and (hit[0]["distance_km"] or 0) >= 0.5 * w["distance_km"]:
        return "done"
    return "missed" if dd < today else ("today" if dd == today else "planned")


# ---------- weight ----------
def weight_trend(weights):
    ws = sorted(weights, key=lambda x: x["date"])
    if not ws:
        return {"points": [], "trend_kg": None, "rate_kg_wk": None}
    ema, pts = None, []
    for x in ws:
        ema = x["kg"] if ema is None else ema + 0.3 * (x["kg"] - ema)
        pts.append({"date": x["date"], "kg": x["kg"], "trend": round(ema, 2)})
    last = d_(ws[-1]["date"])
    win = [x for x in ws if (last - d_(x["date"])).days <= 14]
    rate = None
    if len(win) >= 3 and (d_(win[-1]["date"]) - d_(win[0]["date"])).days >= 6:
        xs = [(d_(x["date"]) - d_(win[0]["date"])).days for x in win]
        ys = [x["kg"] for x in win]
        mx, my = statistics.mean(xs), statistics.mean(ys)
        den = sum((x - mx) ** 2 for x in xs)
        if den:
            rate = round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den * 7, 2)
    return {"points": pts, "trend_kg": pts[-1]["trend"], "rate_kg_wk": rate}


# ---------- nutrition ----------
def bmr(p, kg=None):
    kg = kg or p["weight_kg"]
    return 10 * kg + 6.25 * p["height_cm"] - 5 * p["age"] + (5 if p["sex"] == "male" else -161)


def day_type(w, d, race_date):
    if d == race_date:
        return "race"
    if d == race_date - timedelta(days=1):
        return "prerace"
    if not w:
        return "rest"
    return {"long": "long", "quality": "quality", "easy": "easy", "race": "race"}.get(w["kind"], "rest")


DAY_LABEL = {"rest": "Rest day", "easy": "Easy run day", "quality": "Quality session day",
             "long": "Long run day", "prerace": "Day before the race (carb-up)", "race": "Race day"}


def nutrition_target(p, kg, w, d, recovery=None, rate_kg_wk=None):
    race_date = d_(p["race_date"])
    dt = day_type(w, d, race_date)
    km = w["distance_km"] if w else 0
    base = bmr(p, kg)
    nonex = base * p["activity_factor"]
    run_kcal = kg * km * 1.0
    tdee = nonex + run_kcal
    deficit = {"rest": 1, "easy": 1, "quality": 0.6}.get(dt, 0) * p["deficit_kcal"]
    notes = []
    days_to_race = (race_date - d).days
    if days_to_race <= 7:
        deficit = 0
        notes.append("Race week: no calorie deficit. Arrive fuelled and fresh.")
    if recovery and recovery.get("status") == "Reduced" and deficit:
        deficit = 0
        notes.append("Deficit paused because recovery is reduced.")
    if rate_kg_wk is not None and rate_kg_wk < -0.0075 * kg and deficit:
        deficit = 0
        notes.append("Deficit paused: weight is falling faster than ~0.75% of body weight per week.")
    protein = round(1.8 * kg)
    fat_min = 0.8 * kg
    if dt == "prerace":
        carbs = 6.0 * kg
        fat = fat_min
        kcal = protein * 4 + carbs * 4 + fat * 9
        deficit = 0
        notes.append("Carb-up: about 6 g carbs/kg, low fibre, familiar foods only. Nothing new.")
    else:
        kcal = tdee - deficit
        fat = max(fat_min, 0.22 * kcal / 9)
        carbs = (kcal - protein * 4 - fat * 9) / 4
    if carbs / kg < 2.8:
        notes.append("Carbs are very low (<2.8 g/kg). Consider a smaller deficit.")
    water = 35 * kg + (w["duration_min"] / 60 * 600 if w else 0)
    elec = "Add electrolytes (about 500-700 mg sodium per litre) during and after the run." if (
        w and w["duration_min"] >= 60) else "Electrolytes optional; a pinch of salt in food is enough."
    return {
        "day_type": dt, "label": DAY_LABEL[dt], "bmr": round(base), "nonexercise": round(nonex),
        "run_kcal": round(run_kcal), "tdee": round(tdee), "deficit": round(deficit),
        "kcal": round(kcal), "protein": protein, "carbs": round(carbs), "fat": round(fat),
        "fibre": 18 if dt in ("prerace", "race") else 30, "water_ml": round(water, -1),
        "electrolytes": elec, "notes": notes, "basis": "estimate",
    }


def meal_plan(p, t, w, d):
    """Split the day target into timed meals. Returns list of meal dicts."""
    dt = t["day_type"]
    mt = p["meal_times"]
    rt = None
    if w and w["kind"] != "rest":
        key = {1: "tue", 3: "thu", 5: "sat", 6: "sun"}.get(d.weekday())
        rt = hm_to_min(p["race_start"] if dt == "race" else p["run_times"].get(key, "18:00"))
    dur = w["duration_min"] if w else 0
    meals = []
    fixed_k = fixed_p = fixed_c = fixed_f = 0

    def add(name, time_min, kcal, prot, carb, fat, tip, fixed=False):
        nonlocal fixed_k, fixed_p, fixed_c, fixed_f
        meals.append({"name": name, "time": min_to_hm(time_min), "kcal": round(kcal), "protein": round(prot),
                      "carbs": round(carb), "fat": round(fat), "tip": tip, "_t": time_min})
        if fixed:
            fixed_k += kcal; fixed_p += prot; fixed_c += carb; fixed_f += fat

    def snack(name, tm, carbs, tip):
        add(name, tm, carbs * 4 + 20 + 36, 5, carbs, 4, tip, fixed=True)

    if dt == "race":
        t0 = rt - 135
        snack("Race breakfast", t0, 90, "White toast/bagel with honey or jam, banana, small coffee if you usually have it. Low fibre, low fat, familiar. Sip 400-500 ml fluid with electrolytes until 15 min before the start.")
        snack("Pre-start gel", rt - 15, 25, "One gel with a few sips of water.")
        add("During race", rt + 35, 100, 0, 25, 0, "One gel (about 25 g carbs) every 35-40 min from ~30 min in; water at every station. Aim 30-60 g carbs/hour.", fixed=True)
        add("Post-race recovery", rt + dur + 20, 500, 30, 80, 8, "Chocolate milk or rice + eggs/chicken, fruit, salty food, lots of fluid.", fixed=True)
        rest_slots = [("Lunch", hm_to_min(mt["lunch"]), .5), ("Dinner", hm_to_min(mt["dinner"]), .5)]
    elif rt is not None and rt < 8 * 60:  # early-morning run
        pre_gap = 75 if dt == "long" else 45
        snack("Pre-run snack", rt - pre_gap, 40 if dt != "long" else 55,
              "Banana + slice of toast with honey, or small bowl of white rice cereal. Low fibre, low fat. Sip water.")
        if dur >= 75:
            add("During run (fuel)", rt + 40, 120, 0, 30, 0, "30-60 g carbs per hour after the first 45 min (gels, chews or banana pieces) with water and electrolytes.", fixed=True)
        post = rt + dur + 25
        rest_slots = [("Post-run breakfast", post, .35), ("Lunch", max(hm_to_min(mt["lunch"]), post + 150), .3),
                      ("Snack", 16 * 60, .1), ("Dinner", hm_to_min(mt["dinner"]), .25)]
    elif rt is not None:  # evening run
        snack("Pre-run snack", rt - 90, 35, "Toast with jam/honey and a banana, or rice cakes. Keep fat and fibre low.")
        post = rt + dur + 30
        rest_slots = [("Breakfast", hm_to_min(mt["breakfast"]), .28), ("Lunch", hm_to_min(mt["lunch"]), .32),
                      ("Post-run dinner", post, .40)]
    else:
        rest_slots = [("Breakfast", hm_to_min(mt["breakfast"]), .27), ("Lunch", hm_to_min(mt["lunch"]), .3),
                      ("Snack", 16 * 60, .13), ("Dinner", hm_to_min(mt["dinner"]), .30)]
    rk = max(0, t["kcal"] - fixed_k)
    rp = max(0, t["protein"] - fixed_p)
    rc = max(0, t["carbs"] - fixed_c)
    rf = max(0, t["fat"] - fixed_f)
    tips = {
        "Breakfast": "Oats or eggs on toast, fruit, yoghurt or milk.",
        "Lunch": "Rice/potato/yam with chicken, fish, beans or eggs, plus vegetables.",
        "Snack": "Fruit + yoghurt, nuts, or a sandwich.",
        "Dinner": "Lean protein, a starch and plenty of vegetables.",
        "Post-run breakfast": "Within 45 min: eggs + toast, oats with milk and fruit. 25-40 g protein, plenty of carbs.",
        "Post-run dinner": "Within 60 min: chicken/fish/beans with rice or potato and vegetables. 25-40 g protein.",
    }
    tot = sum(s for _, _, s in rest_slots)
    bed_latest = None
    if d < d_(p["race_date"]):
        bed_latest = hm_to_min(sleep_target(p, d)["bed"]) - 120   # finish eating 2 h before bed
    for name, tm, share in rest_slots:
        f = share / tot
        if bed_latest is not None and bed_latest > 12 * 60:
            tm = min(tm, bed_latest)
        add(name, tm, rk * f, rp * f, rc * f, rf * f, tips.get(name, ""))
    meals.sort(key=lambda m: m["_t"])
    for m in meals:
        m.pop("_t")
    return meals


# ---------- sleep & recovery ----------
def sleep_target(p, d):
    """Target for the night that STARTS on evening of date d (wakes d+1)."""
    race = d_(p["race_date"])
    nxt = d + timedelta(days=1)
    start = date.today() if d < date.today() else d
    key = {5: "sat", 6: "sun"}.get(nxt.weekday())
    base = hm_to_min(p["wake_time"])
    total = max(1, (race - timedelta(days=5) - date.today()).days)
    frac = clamp((d - date.today()).days / total)
    wake = base - round((base - 5 * 60) * frac / 5) * 5 if base > 5 * 60 else base
    hrs, note = p["sleep_target_h"], "Gradually moving wake-up earlier to match the 5 AM race start."
    if nxt == race:
        wake, hrs, note = hm_to_min(p["race_start"]) - 150, 7.0, "Race morning: wake 2.5 h before the start. Bank sleep on the previous two nights."
    elif key and hm_to_min(p["run_times"][key]) < 8 * 60 and nxt >= date.today():
        # morning run: wake early enough to eat the pre-run snack 45-75 min before the run
        wake = min(wake, hm_to_min(p["run_times"][key]) - (105 if key == "sun" else 90))
        hrs = 7.0
        note = ("Long-run morning wake-up. Go to bed early; nap 20-30 min in the afternoon if short." if key == "sun"
                else "Early Saturday run: wake in time for the pre-run snack, so go to bed a little earlier.")
    bed = wake - round(hrs * 60)
    return {"date": d.isoformat(), "bed": min_to_hm(bed), "wake": min_to_hm(wake), "hours": hrs, "note": note}


def sleep_duration(bed, wake):
    b, w = hm_to_min(bed), hm_to_min(wake)
    return ((w - b) % 1440) / 60


def recovery_score(logs, p, today):
    """Average of the two most recent morning logs (<=3 days old)."""
    ls = [l for l in sorted(logs, key=lambda x: x["date"], reverse=True) if 0 <= (today - d_(l["date"])).days <= 3][:2]
    if not ls:
        return {"score": None, "status": "Unknown", "factors": [], "missing": "Log last night's sleep and how you feel to get a recovery score.",
                "basis": "none"}

    def avg(f):
        v = [f(l) for l in ls if f(l) is not None]
        return statistics.mean(v) if v else None

    hrs = avg(lambda l: sleep_duration(l["bed"], l["wake"]) if l.get("bed") and l.get("wake") else None)
    comps = [
        ("Sleep duration", 30, None if hrs is None else clamp(hrs / p["sleep_target_h"]),
         None if hrs is None else f"{hrs:.1f} h vs {p['sleep_target_h']:g} h target"),
        ("Sleep quality", 10, (lambda v: None if v is None else (v - 1) / 4)(avg(lambda l: l.get("quality"))), "1 poor – 5 great"),
        ("Muscle soreness", 20, (lambda v: None if v is None else (5 - v) / 4)(avg(lambda l: l.get("soreness"))), "1 none – 5 severe"),
        ("Fatigue", 20, (lambda v: None if v is None else (5 - v) / 4)(avg(lambda l: l.get("fatigue"))), "1 fresh – 5 exhausted"),
        ("Motivation", 10, (lambda v: None if v is None else (v - 1) / 4)(avg(lambda l: l.get("motivation"))), "1 low – 5 high"),
        ("Hydration", 10, (lambda v: None if v is None else (v - 1) / 4)(avg(lambda l: l.get("hydration"))), "1 poor – 5 great"),
    ]
    known = [c for c in comps if c[2] is not None]
    wsum = sum(c[1] for c in known)
    score = round(sum(c[1] * c[2] for c in known) / wsum * 100)
    status = "Good" if score >= 75 else "Moderate" if score >= 55 else "Reduced"
    return {
        "score": score, "status": status, "basis": "self-reported",
        "factors": [{"name": n, "weight": w, "points": None if v is None else round(v * w, 1), "detail": dtl} for n, w, v, dtl in comps],
        "missing": None if len(known) == len(comps) else "Some fields not logged; score uses what is available.",
        "hours": None if hrs is None else round(hrs, 1),
    }


# ---------- race readiness ----------
def readiness(p, acts, workouts, logs, today):
    race = race_info(p, today)
    fit = fitness(p, acts, today)
    runs28 = [a for a in acts if a.get("distance_km") and 0 <= (today - d_(a["date"])).days < 28]
    comps, missing = [], []

    def add(name, weight, val, detail, basis):
        comps.append({"name": name, "weight": weight, "score": None if val is None else round(val * 100),
                      "detail": detail, "basis": basis})
    # consistency
    if runs28:
        add("Running consistency", 15, clamp(len(runs28) / 16), f"{len(runs28)} runs in last 28 days (target ~16)", "measured")
    else:
        add("Running consistency", 15, None, "No imported runs in last 28 days", "none"); missing.append("Import your recent Strava runs")
    # mileage
    if runs28:
        wk = sum(a["distance_km"] for a in runs28) / 4
        add("Weekly mileage", 15, clamp(wk / 28), f"{wk:.1f} km/week average (target ~28)", "measured")
    else:
        add("Weekly mileage", 15, None, "No data", "none")
    # longest
    lr = max([a["distance_km"] for a in acts if a.get("distance_km") and 0 <= (today - d_(a["date"])).days <= 60] or [0])
    if lr:
        add("Longest run", 15, clamp(lr / 16), f"{lr:.1f} km in the last 60 days (target 16)", "measured")
    else:
        add("Longest run", 15, clamp(p["longest_run_km"] / 16) * 0.8,
            f"{p['longest_run_km']:g} km self-reported, not yet verified", "historical"); missing.append("Verified long run (15 km+) in the next two weeks")
    # pace
    gap = fit["half_time_s"] - race["goal_s"]
    add("Ability to hold race pace", 25, clamp(1 - gap / 1800),
        f"Projected half {fit['half_time']} vs goal {race['goal_time']} ({'verified recent runs' if fit['source'] == 'verified' else 'historical benchmarks'})",
        "estimate" if fit["source"] == "verified" else "historical")
    if fit["source"] != "verified":
        missing.append("At least two recent runs of 5 km+ to verify current pace")
    # RPE
    easy_rpe = [a["rpe"] for a in runs28 if a.get("rpe")]
    if len(easy_rpe) >= 3:
        add("Effort (RPE) trend", 10, clamp(1 - (statistics.mean(easy_rpe) - 4) / 4), f"Average RPE {statistics.mean(easy_rpe):.1f} over {len(easy_rpe)} runs", "self-reported")
    else:
        add("Effort (RPE) trend", 10, None, "Fewer than 3 runs with RPE", "none"); missing.append("RPE on each run")
    # completion
    cr = completion_rate(workouts, acts, today, 14)
    if cr is None:
        add("Training completion", 10, None, "No planned sessions finished yet", "none")
    else:
        add("Training completion", 10, cr, f"{round(cr * 100)}% of planned runs done in last 14 days", "measured")
    # recovery
    rec = recovery_score(logs, p, today)
    if rec["score"] is None:
        add("Recovery", 10, None, "No recent sleep/recovery log", "none"); missing.append("Daily sleep and recovery log")
    else:
        add("Recovery", 10, rec["score"] / 100, f"Recovery {rec['score']}/100", "self-reported")
    known = [c for c in comps if c["score"] is not None]
    wk = sum(c["weight"] for c in known)
    total = round(sum(c["weight"] * c["score"] for c in known) / wk) if wk else None
    known_share = wk / sum(c["weight"] for c in comps)
    conf = "High" if known_share >= .85 and fit["source"] == "verified" and len(runs28) >= 8 else \
        "Medium" if known_share >= .6 and fit["source"] == "verified" else "Low"
    ratio = fit["half_time_s"] / race["goal_s"]
    if ratio <= 1.03:
        verdict = "On track: recorded evidence supports the goal pace."
    elif ratio <= 1.10:
        verdict = "Possible: you are close, but it needs steady progress and a controlled race."
    else:
        verdict = ("Stretch: current evidence projects a slower finish than the goal. Pick a realistic A/B plan "
                   f"(for example a safe finish near {fit['half_time']}) and use the goal pace as an upside.")
    return {
        "score": total, "confidence": conf, "verdict": verdict, "components": comps, "missing": missing,
        "projection": fit, "disclaimer": "A projection, not a guarantee. Riegel-style estimates ignore heat, hills and race-day factors.",
    }


# ---------- coach ----------
def coach(p, acts, workouts, weights, nutri_today, rec, ready, today):
    out = []

    def r(text, why, basis):
        out.append({"text": text, "why": why, "basis": basis})
    race = race_info(p, today)
    fit = ready["projection"]
    if fit["source"] == "historical":
        r("Import your last 3-4 Strava runs.", "Paces are currently based on old benchmarks. Verified runs let me recalculate honest training paces.", "missing data")
    if not p.get("sat_time_confirmed"):
        r("Confirm your Saturday run time in Profile.", "Saturday time is a placeholder (07:00) until you set it. It feeds the calendar.", "missing data")
    if rec["status"] == "Reduced":
        r("Recovery is low: take an easier day and pause the calorie deficit.", f"Recovery score {rec['score']}/100.", "self-reported")
    elif rec["status"] == "Unknown":
        r("Log last night's sleep and soreness each morning.", "Recovery can't be assessed without it.", "missing data")
    nxt = next((w for w in workouts if d_(w["date"]) >= today and w["kind"] == "long"), None)
    if nxt:
        r(f"Next long run: {nxt['distance_km']:g} km on {nxt['date']} at {nxt['pace']}.",
          "Long runs build the endurance you need; pace is easy by design.", "plan")
    if race["days_left"] <= 14:
        r("You are in taper: don't add volume now.", "Fitness cannot be gained this close to the race; fatigue can.", "plan")
    if nutri_today:
        r(f"Today's target is about {nutri_today['kcal']} kcal ({nutri_today['label']}).",
          f"Estimated from BMR {nutri_today['bmr']} kcal + activity {nutri_today['nonexercise'] - nutri_today['bmr']} + run {nutri_today['run_kcal']} - deficit {nutri_today['deficit']}.", "estimate")
    wt = weight_trend(weights)
    if wt["rate_kg_wk"] is not None:
        r(f"Weight trend is {wt['rate_kg_wk'] * 2.20462:+.1f} lb/week.", "Based on a 14-day fit, not single weigh-ins.", "measured")
    return out


# ---------- calendar events ----------
def build_events(p, workouts, weights_kg, recovery, today, include=("training", "meals", "sleep")):
    """Return list of events: uid, summary, description, start, end (datetime), kind."""
    ev = []
    rd = d_(p["race_date"])
    wmap = {w["date"]: w for w in workouts}
    last = rd
    d = today
    while d <= last:
        w = wmap.get(d.isoformat())
        key = {1: "tue", 3: "thu", 5: "sat", 6: "sun"}.get(d.weekday())
        if "training" in include and w and w["kind"] != "rest":
            t = p["race_start"] if d == rd else p["run_times"].get(key, "18:00")
            st = datetime.combine(d, datetime.min.time()) + timedelta(minutes=hm_to_min(t))
            icon = {"long": "🏃", "quality": "⚡", "easy": "🏃", "race": "🏁"}[w["kind"]]
            desc = (f"{w['title']}\nDistance: {w['distance_km']:g} km\nPace: {w['pace']}\nSpeed: {w['speed']}\n"
                    f"Duration: ~{w['duration_min']} min\nEffort: RPE {w['rpe']}/10 (talk test)\n\n{w['structure']}\n{w['notes']}")
            ev.append({"uid": f"run-{d}", "kind": "training", "start": st,
                       "end": st + timedelta(minutes=max(20, w["duration_min"])),
                       "summary": f"{icon} {w['title']} · {w['distance_km']:g} km @ {w['pace']}", "description": desc})
        if "meals" in include:
            kg = weights_kg
            t = nutrition_target(p, kg, w, d, recovery)
            for m in meal_plan(p, t, w, d):
                st = datetime.combine(d, datetime.min.time()) + timedelta(minutes=hm_to_min(m["time"]))
                if m["name"] == "During race" or m["name"].startswith("During run"):
                    dur = 15
                else:
                    dur = 30
                ev.append({"uid": f"meal-{d}-{m['name'].lower().replace(' ', '-')}", "kind": "meals", "start": st,
                           "end": st + timedelta(minutes=dur),
                           "summary": f"🍽 {m['name']} · {m['kcal']} kcal · P{m['protein']} C{m['carbs']} F{m['fat']}",
                           "description": f"{t['label']} (day target {t['kcal']} kcal, P{t['protein']}/C{t['carbs']}/F{t['fat']} g)\n"
                                          f"{m['tip']}\nWater target {t['water_ml']:.0f} ml. {t['electrolytes']}\nEstimates, not medical advice."})
        if "sleep" in include and d < rd:
            s = sleep_target(p, d)
            bed = datetime.combine(d, datetime.min.time()) + timedelta(minutes=hm_to_min(s["bed"]))
            wake = datetime.combine(d + timedelta(days=1), datetime.min.time()) + timedelta(minutes=hm_to_min(s["wake"]))
            if bed >= wake:
                bed -= timedelta(days=1)
            ev.append({"uid": f"sleep-{d}", "kind": "sleep", "start": bed, "end": wake,
                       "summary": f"😴 Sleep · bed {s['bed']} → wake {s['wake']}",
                       "description": f"{s['hours']:g} h target. {s['note']}\nWind down 30 min before bed: dim lights, no screens."})
        d += timedelta(days=1)
    return ev
