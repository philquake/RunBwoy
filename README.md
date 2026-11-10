# Run Coach

A private, single-user race-training coach that runs entirely on your own computer: a four-day-a-week running plan, nutrition and sleep targets, race readiness, Google Calendar export, and an optional local AI coach (Ollama). No account, no login, no cloud.

> Not medical advice. Targets are estimates. Stop and see a doctor for pain, chest symptoms or dizziness.

## What it does

- **Plan**: four running days (Tue, Thu, Sat, Sun) leading up to your race, with distance, pace, speed, duration and effort (RPE) for each run. Saturday stays short and easy before the Sunday long run. Long runs rebuild from your last three weeks of real running, then taper. Plan changes are proposed and only saved when you confirm.
- **Fitness**: projects your half-marathon time from your longest recent efforts (Riegel formula) and derives training paces. Historical benchmarks are used until you import real runs.
- **Nutrition**: daily calorie, protein, carb, fat, fibre and water targets (Mifflin-St Jeor plus activity and run cost), a modest deficit that pauses when recovery is poor, timed meals around each run, and race-day fuelling.
- **Sleep and recovery**: sleep targets that move towards your race start time, a recovery score from what you log, and race readiness with a confidence level and what is missing.
- **Activities**: import Strava screenshots (optional OCR) or GPX files, or type runs in. Originals are kept, duplicates are flagged, nothing is invented (no heart-rate data).
- **Google Calendar**: training, meals and sleep targets as an `.ics` file, or direct sync to a "Run Coach" calendar.
- **Local AI coach** (optional): a small Ollama model that answers from your numbers and a library of notes, and can only *propose* plan changes.

## Quick start

Requires Python 3.10+.

```bash
pip install -r requirements.txt
python app.py --open
```

Open http://127.0.0.1:5000 (`--open` does it for you). On Windows, `run.cmd` starts the app and opens the page, and you can pin a shortcut to it on the taskbar.

First run: open **Settings** and enter your age, weight (lb), height, race date, goal time, timezone and run times. The defaults are placeholders.

## Local AI coach (optional)

1. Install [Ollama](https://ollama.com) and pull a model: `ollama pull qwen3:4b` and `ollama pull nomic-embed-text`.
2. Build the coach: `ollama create runcoach -f coach/Modelfile`.
3. Open the **Coach** tab.

The model never does arithmetic: every number comes from the app's own code (`engine.py`), attached to each question as a snapshot, and general advice comes from the notes in `knowledge/`. Red-flag symptoms and finish-time guarantees get fixed wording in code (`coach.py`). The notes are summaries of general sports-science guidance, written in my own words and not checked against the original papers: review them before relying on them. Set `RUNCOACH_MODEL`, `RUNCOACH_EMBED` or `OLLAMA_HOST` to change defaults.

## Google Calendar

- **No setup**: Calendar tab, download the `.ics`, import it in Google Calendar. It cannot delete old events: after a plan change, delete that calendar and import again.
- **Direct sync**: enable the Calendar API in Google Cloud, create an OAuth *Desktop app* client, save the JSON as `data/google_credentials.json`, then press Sync. Re-syncing updates events in place and removes events that left the plan.

## Screenshot OCR (optional)

Install the Tesseract program plus `pytesseract` and `pillow`. Without them, uploads are saved and you type the values in.

## Privacy

Everything is stored locally in `data/` (SQLite database, uploaded screenshots, Google token), which is git-ignored along with any credentials and test logs. Do not commit `data/`.

## Tests

```bash
python -m unittest discover tests      # calendar and plan rules, fast
python tests/coach_evals.py            # asks the AI coach ~40 questions, slow, needs Ollama
```

`coach_evals.py` checks safety, honesty and grounding behaviour against *your* local data, so some expected answers depend on what you have imported. It writes `tests/eval_results.md` (git-ignored because it contains your numbers).

## Layout

`engine.py` all calculations · `app.py` Flask API and SQLite · `coach.py` Ollama chat and safety net · `knowledge.py` note search · `gcal.py` `.ics` and Google sync · `static/` UI · `knowledge/` notes · `coach/Modelfile` coach rules.
