"""Run:  python -m unittest discover tests   (from the project folder)"""
import os, sys, unittest
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E
import gcal


def build(today=None):
    p = dict(E.DEFAULT_PROFILE)
    today = today or date.today()
    ws, _ = E.generate_plan(p, [], today)
    return p, ws, E.build_events(p, ws, 75.0, None, today)


def parse_ics(text):
    lines = text.replace("\r\n ", "").split("\r\n")      # unfold
    events, cur = [], None
    for ln in lines:
        if ln == "BEGIN:VEVENT":
            cur = {}
        elif ln == "END:VEVENT":
            events.append(cur); cur = None
        elif cur is not None and ":" in ln:
            k, v = ln.split(":", 1)
            cur.setdefault(k.split(";")[0], v)
    return events


class CalendarTests(unittest.TestCase):
    def test_ics_is_valid(self):
        p, ws, ev = build()
        text = gcal.to_ics(ev, p["timezone"])
        parsed = parse_ics(text)
        self.assertEqual(len(parsed), len(ev))
        self.assertEqual(len({e["UID"] for e in parsed}), len(ev), "UIDs must be unique")
        for e in parsed:
            self.assertGreater(e["DTEND"], e["DTSTART"])
        sums = {e["SUMMARY"].replace("\\,", ",").replace("\\;", ";") for e in parsed}
        self.assertEqual(sums, {x["summary"] for x in ev}, "emoji/text must survive line folding")
        for ln in text.split("\r\n"):
            self.assertLessEqual(len(ln.encode()), 75)

    def test_meals_fit_around_sleep(self):
        p, ws, ev = build()
        sleeps = [e for e in ev if e["kind"] == "sleep"]
        for m in (e for e in ev if e["kind"] == "meals"):
            for s in sleeps:
                if m["summary"].startswith("🍽 During"):
                    continue      # fuel taken while running
                self.assertFalse(s["start"] <= m["start"] < s["end"], f"{m['summary']} at {m['start']} is during sleep {s['start']}–{s['end']}")
            same_night = [s for s in sleeps if s["start"].date() == m["start"].date()]
            for s in same_night:
                if m["start"].hour >= 12:
                    self.assertLessEqual(m["start"], s["start"] - timedelta(minutes=60))

    def test_saturday_is_never_hard(self):
        _, ws, _ = build()
        for w in ws:
            if date.fromisoformat(w["date"]).weekday() == 5:
                self.assertIn(w["kind"], ("easy", "rest"))

    def test_taper_and_race(self):
        _, ws, _ = build()
        self.assertEqual(ws[-1]["kind"], "race")
        longs = [w["distance_km"] for w in ws if w["kind"] == "long"]
        self.assertLess(longs[-1], max(longs))


if __name__ == "__main__":
    unittest.main()
