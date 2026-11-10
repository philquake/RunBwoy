"""Local knowledge library: notes in knowledge/*.md -> embeddings (Ollama) -> cosine search. No cloud."""
import glob
import hashlib
import json
import math
import os
import re
import sqlite3

import coach

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "runcoach.db")
EMBED_MODEL = os.environ.get("RUNCOACH_EMBED", "nomic-embed-text")


def load_notes():
    """Each '## Title' section of each file is one note."""
    notes = []
    for path in sorted(glob.glob(os.path.join(BASE, "knowledge", "*.md"))):
        text = open(path, encoding="utf-8").read()
        m = re.match(r"source:\s*(.+)", text)
        src = m.group(1).strip() if m else os.path.basename(path)
        for part in re.split(r"\n## ", "\n" + text)[1:]:
            title, _, body = part.partition("\n")
            notes.append({"file": os.path.basename(path), "title": title.strip(), "text": body.strip(), "source": src})
    return notes


def _embed(texts):
    return coach._post("/api/embed", {"model": EMBED_MODEL, "input": texts}, timeout=120)["embeddings"]


def _cos(a, b):
    d = sum(x * y for x, y in zip(a, b))
    return d / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)


def _tokens(s):
    return set(re.findall(r"[a-z0-9]{3,}", s.lower()))


def index():
    """(Re)build embeddings for new/changed notes. Returns number of notes indexed."""
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS kb(id TEXT PRIMARY KEY, file TEXT, title TEXT, text TEXT, source TEXT, emb TEXT)")
    notes = load_notes()
    have = {r[0] for r in con.execute("SELECT id FROM kb")}
    ids = {}
    for n in notes:
        n["id"] = hashlib.sha1((n["title"] + n["text"] + EMBED_MODEL).encode()).hexdigest()
        ids[n["id"]] = n
    new = [n for n in notes if n["id"] not in have]
    for i in range(0, len(new), 16):
        chunk = new[i:i + 16]
        embs = _embed([f"{n['title']}. {n['text']}" for n in chunk])
        for n, e in zip(chunk, embs):
            con.execute("INSERT OR REPLACE INTO kb VALUES(?,?,?,?,?,?)", (n["id"], n["file"], n["title"], n["text"], n["source"], json.dumps(e)))
    for gone in have - set(ids):
        con.execute("DELETE FROM kb WHERE id=?", (gone,))
    con.commit(); con.close()
    return len(notes)


def search(query, k=3):
    """Top-k notes. Falls back to keyword overlap if the embedding model is unavailable."""
    try:
        index()
        con = sqlite3.connect(DB)
        rows = con.execute("SELECT file,title,text,source,emb FROM kb").fetchall(); con.close()
        q = _embed([query])[0]
        scored = sorted(((_cos(q, json.loads(r[4])), r) for r in rows), key=lambda x: -x[0])[:k]
        return [{"title": r[1], "note": r[2], "source": r[3], "score": round(s, 3)} for s, r in scored]
    except Exception:
        qt = _tokens(query)
        scored = sorted(((len(qt & _tokens(n["title"] + " " + n["text"])), n) for n in load_notes()), key=lambda x: -x[0])[:k]
        return [{"title": n["title"], "note": n["text"], "source": n["source"], "score": s} for s, n in scored if s]
