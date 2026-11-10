"""Local AI coach: talks to Ollama, and only ever gets numbers from the app's own tools."""
import json
import os
import re
import urllib.request

OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL = os.environ.get("RUNCOACH_MODEL", "runcoach")
MAX_STEPS = 5
PLAN_INTENT = re.compile(r"\b(review|update|change|adjust|revise|re-?plan|rework|modify)\b.*\b(plan|schedule|training)\b", re.I | re.S)

TOOLS = [
    {"type": "function", "function": {"name": n, "description": d, "parameters": {"type": "object", "properties": p, "required": []}}}
    for n, d, p in [
        ("get_dashboard", "Overview: race countdown, today's workout, next long run, weekly km, projected half-marathon time, readiness, recovery, today's nutrition target.", {}),
        ("get_plan", "Planned workouts (distance, pace, speed, duration, RPE, status) for the next N days.",
         {"days": {"type": "integer", "description": "How many days ahead, default 14"}}),
        ("get_nutrition", "Calorie/macro/water targets and timed meals for a date, plus what was logged.",
         {"date": {"type": "string", "description": "YYYY-MM-DD, default today"}}),
        ("get_recent_activities", "Recent imported/manual runs with distance, time, pace, RPE.",
         {"limit": {"type": "integer", "description": "Default 8"}}),
        ("get_sleep_recovery", "Recovery score with factors, recent sleep logs, and upcoming sleep targets.", {}),
        ("get_readiness", "Race readiness score, confidence, projection, what evidence is missing.", {}),
        ("search_knowledge", "Search the vetted library of running, nutrition, fuelling, sleep, recovery and safety notes. Use for general how/why questions (e.g. gels, tapering, protein, heat). Returns notes with their sources.",
         {"query": {"type": "string", "description": "What to look up, in plain words"}}),
        ("propose_plan_change", "Ask the planner to re-evaluate the remaining plan using latest activities, completion and recovery. Returns a PROPOSAL only; the athlete confirms in the app.", {}),
    ]
]


def _post(path, body, timeout=300):
    req = urllib.request.Request(OLLAMA + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def status():
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=3) as r:
            names = [m["name"] for m in json.load(r)["models"]]
        return {"running": True, "model": MODEL, "model_installed": any(n.split(":")[0] == MODEL for n in names)}
    except Exception as e:
        return {"running": False, "model": MODEL, "model_installed": False, "error": str(e)}


URGENT = re.compile(r"chest\s*(pain|tight|pressure)|\bfaint|passed out|blacked? out|can'?t breathe|short(ness)? of breath|palpitat|heart (racing|pounding)|dizz", re.I)
PAIN = re.compile(r"\bpain\b|injur|swell|numb|\blimp|\bpop(ped)?\b|\btear\b|sprain|strain", re.I)
URGENT_TEXT = ("**Stop exercising now.** Chest pain, dizziness, fainting or trouble breathing can be serious. Get medical help now "
               "(call emergency services if it doesn't ease straight away) instead of waiting to see how it develops. "
               "I can't assess symptoms, and I won't plan any training until you've been checked by a doctor.")


GUARANTEE = re.compile(r"guarantee|promise me|definitely|for sure|surely|100\s*%", re.I)
REFUSES = re.compile(r"(can'?t|cannot|won'?t|unable to|no one can|nobody can) (honestly )?(guarantee|promise)|no guarantee|not (a )?guarantee", re.I)


def safety(user_text, reply, projected=None):
    """Hard safety net: red-flag symptoms and finish-time guarantees never depend on the small model's wording."""
    if URGENT.search(user_text):
        return URGENT_TEXT
    if GUARANTEE.search(user_text) and re.search(r"finish|race|marathon|2:\d\d|sub|time|goal", user_text, re.I):
        reply = re.sub(r"\bto guarantee\b", "to improve your chances of", reply, flags=re.I)
        if not REFUSES.search(reply):
            reply = ("I can't guarantee a finish time, and nobody honestly can: race day depends on heat, health and pacing. "
                     + (f"Your evidence so far projects about {projected}. " if projected else "")
                     + "A faster goal is possible, but it depends on consistent training and a controlled start. "
                     "Keep your four weekly runs consistent and arrive at the start healthy.")
    if PAIN.search(user_text) and not re.search(r"doctor|physio", reply, re.I):
        reply += ("\n\nStop running if it hurts, and see a doctor or physiotherapist if it doesn't settle quickly or gets worse. "
                  "I can't diagnose injuries.")
    return reply


def clean(text):
    """Drop any leaked <think> reasoning."""
    if "</think>" in text:
        text = text.split("</think>")[-1]
    return re.sub(r"<think>.*?(</think>|$)", "", text, flags=re.S).strip()


def chat(history, impl, today_iso, race_iso, context=None, notes_fn=None):
    """history: [{role, content}], impl: {tool_name: callable(**args) -> jsonable}.
    Returns {reply, tools_used, proposal}."""
    from datetime import date, timedelta
    t0 = date.fromisoformat(today_iso)
    cal = ", ".join(f"{(t0 + timedelta(days=i)):%a %b %d}" + (" (today)" if i == 0 else "") for i in range(8))
    msgs = [{"role": "system", "content": f"/no_think\nToday is {t0:%A %Y-%m-%d}. The race is on {race_iso}. Next days: {cal}. "
             "'This Sunday' means the first Sunday in that list. Answer the athlete directly in second person (you/your). "
             "Never mention tool or function names and never show your reasoning."}]
    # Always-on grounding, so the answer never depends on the small model choosing to look things up:
    # (1) the athlete's current numbers from the app, (2) the library notes most relevant to the question.
    snapshot, projected = (context() if context else ""), None
    if snapshot:
        try:
            projected = json.loads(snapshot).get("projected_half", {}).get("half_time")
        except Exception:
            pass
        msgs.append({"role": "system", "content": "ATHLETE SNAPSHOT (from the app). For the athlete's OWN targets, times, paces and weight, quote exactly these numbers. "
                     "General ranges in the library notes are for explaining why, never a replacement for these values:\n" + snapshot})
    last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
    if notes_fn and last_user:
        try:
            notes = [n for n in notes_fn(last_user) if n.get("score", 0) >= 0.55]
        except Exception:
            notes = []
        if notes:
            msgs.append({"role": "system", "content": "RELEVANT NOTES FROM THE KNOWLEDGE LIBRARY (base general advice on these; quote their numbers, never other numbers):\n" +
                         "\n\n".join(f"[{n['title']}] {n['note']}" for n in notes)})
    msgs += history[-12:]
    used, proposal, seen = [], None, set()
    # A request to review/update the plan always runs the planner (small models skip the tool call).
    if last_user and PLAN_INTENT.search(last_user) and "propose_plan_change" in impl:
        out = impl["propose_plan_change"]()
        used.append({"name": "propose_plan_change", "args": {}})
        if out.get("workouts"):
            proposal = {"workouts": out["workouts"], "changes": out["changes"], "reasons": out["reasons"]}
        msgs.append({"role": "system", "content": "PLAN REVIEW RESULT (a proposal only; the athlete confirms in the app). "
                     "Tell the athlete this result plainly, mention the plan, and if there are changes say they can press Confirm below your message.\n" +
                     json.dumps({"summary": out["summary"], "changes": out["changes"], "reasons": out["reasons"]}, default=str)[:3000]})
    for _ in range(MAX_STEPS):
        res = _post("/api/chat", {"model": MODEL, "messages": msgs, "tools": TOOLS, "stream": False, "think": False,
                                  "options": {"num_ctx": 6144}})["message"]
        msgs.append(res)
        calls = res.get("tool_calls") or []
        if not calls:
            return {"reply": safety(last_user, clean(res.get("content") or ""), projected), "tools_used": used, "proposal": proposal}
        for c in calls:
            name, args = c["function"]["name"], c["function"].get("arguments") or {}
            key = (name, json.dumps(args, sort_keys=True))
            if key in seen:   # small models repeat themselves; don't re-run, just nudge
                msgs.append({"role": "tool", "tool_name": name, "content": "You already have this data above. Answer the athlete now in plain language."})
                continue
            try:
                out = impl[name](**args) if name in impl else {"error": f"unknown tool {name}"}
            except Exception as e:
                out = {"error": f"{type(e).__name__}: {e}"}
            seen.add(key)
            used.append({"name": name, "args": args})
            if name == "propose_plan_change" and isinstance(out, dict) and out.get("workouts"):
                proposal = {"workouts": out["workouts"], "changes": out["changes"], "reasons": out["reasons"]}
                out = {"summary": out["summary"], "changes": out["changes"], "reasons": out["reasons"],
                       "note": "Proposal only. Tell the athlete to review and press Confirm below your message."}
            msgs.append({"role": "tool", "tool_name": name, "content": json.dumps(out, default=str)[:6000]})
    return {"reply": "I couldn't finish that. Please try a simpler question.", "tools_used": used, "proposal": proposal}
