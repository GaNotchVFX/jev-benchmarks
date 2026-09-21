"""Lane 2 - The decision layer inside a voice agent.

A phone agent has roughly 800 ms from "caller stops talking" to "agent starts talking" before it feels broken.
After speech-to-text, code must decide several things before anything is spoken:
  1. what does the caller want (intent / which tool to call)
  2. have they actually finished talking, or was that a mid-sentence pause (end-of-turn)
  3. do they want a human / are they upset (escalate)
  4. how urgent is it
Jev answers all four in ONE request, in parallel. An LLM has to generate a JSON object token by token,
and code cannot act until the whole object has arrived, so LLM latency here = time to the complete response.

Data  : SNIPS voice-assistant utterances (public, 7 gold intents).
        End-of-turn gold labels are made mechanically: a complete utterance = finished; the same kind of
        utterance cut at a random point 35-70% of the way through = not finished. (Some cuts still read as a
        complete sentence, so nobody can score 100% on that label. It is the same noise for every model.)
Timing: sequential-ish (workers=2), warm keep-alive connections, measured from this machine.

usage: python bench.py [--n 200] [--export-zig]
"""
import argparse, json, random, sys
from pathlib import Path
import pandas as pd
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "common"))
from jevlib import jev, llm_json, run_checkpointed, pct, JEV

BASELINES = ["google/gemini-3.8-flash", "openai/gpt-5.6-luna", "anthropic/claude-sonnet-5", "openai/gpt-6-astra"]
ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=200, help="complete turns; same number of cut-off turns is added")
ap.add_argument("--n-frontier", type=int, default=100, help="turns sent to the expensive frontier models")
ap.add_argument("--llm-workers", type=int, default=6, help="LLM baselines are slow; a few parallel callers do not change per-request latency")
ap.add_argument("--export-zig", action="store_true"); ap.add_argument("--workers", type=int, default=2)
a = ap.parse_args()

df = pd.read_parquet(HERE.parent / "common/data/snips_test.parquet")
INTENTS = sorted(df.category.unique())
rng = random.Random(7)
df = df[df.text.str.split().str.len() >= 6].sample(frac=1, random_state=7).reset_index(drop=True)
items = []
for i, row in df.iterrows():
    if len(items) >= 2 * a.n:
        break
    words = row.text.split()
    if i % 2 == 0:
        items.append({"id": f"full-{i}", "text": row.text, "intent": row.category, "finished": True})
    else:
        k = max(2, int(len(words) * rng.uniform(0.35, 0.70)))
        items.append({"id": f"cut-{i}", "text": " ".join(words[:k]), "intent": row.category, "finished": False})

Q = {
    "intent": {"type": "choice", "instructions": "Which action is the caller asking for in `transcript`?",
               "criteria": {**{l: None for l in INTENTS}, "none_of_these": "the request does not match any listed action"}},
    "finished": {"type": "noul",
                 "instructions": "`transcript` is live speech-to-text. Has the caller finished their request (as opposed to being cut off or pausing mid-sentence)?",
                 "criteria": {"true": "the request is complete and could be acted on now",
                              "false": "the sentence is cut off or is clearly still missing the rest of the request"}},
    "escalate": {"type": "noul", "instructions": "Is the caller asking for a human or sounding upset?"},
    "urgency": {"type": "score", "instructions": "How time-sensitive is the caller's request?",
                "criteria": ["no time pressure", "wants it soon", "needs it right now"]},
}
# Variant: same question, but each option gets a one-line description - the normal way to deploy Jev.
DESCRIBED = {
    "AddToPlaylist": "add a song, album or artist to one of the caller's playlists",
    "BookRestaurant": "book a table or make a restaurant reservation",
    "GetWeather": "ask about the weather or a forecast",
    "PlayMusic": "play a song, album, artist, genre or playlist now",
    "RateBook": "give a rating or a number of stars to a book",
    "SearchCreativeWork": "find or look up a titled work such as a book, movie, TV show, song, game or painting, without asking for showtimes",
    "SearchScreeningEvent": "find movie showtimes or what is playing at cinemas or theatres",
    "none_of_these": "the request does not match any listed action",
}
QD = {**Q, "intent": {**Q["intent"], "criteria": DESCRIBED}}
SYS = ("You are the decision layer of a phone voice agent. You receive a live speech-to-text transcript. "
       "Reply with JSON only, exactly these keys:\n"
       '{"intent": one of [' + ", ".join(INTENTS) + ", none_of_these], "
       '"finished": true if the caller has finished their request, false if the sentence is cut off or still missing the rest, '
       '"escalate": true if the caller asks for a human or sounds upset, '
       '"urgency": 0 (no time pressure) | 1 (wants it soon) | 2 (needs it right now)}')

if a.export_zig:
    z = HERE / "zig"; z.mkdir(exist_ok=True)
    with (z / "turns.jsonl").open("w", encoding="utf-8") as f:
        for it in items[:200]:
            f.write(json.dumps({"model": JEV, "state": {"transcript": it["text"]}, "questions": Q}) + "\n")
    print("wrote", z / "turns.jsonl"); sys.exit()


def f_jev(it):
    r = jev({"transcript": it["text"]}, Q); x = r["answers"]
    return {"intent": x["intent"]["choice"], "intent_conf": x["intent"]["confidence"],
            "finished_p": x["finished"]["noul"], "ms": r["ms"], "cost": r["cost"]}


def f_jev_described(it):
    r = jev({"transcript": it["text"]}, QD); x = r["answers"]
    return {"intent": x["intent"]["choice"], "intent_conf": x["intent"]["confidence"],
            "finished_p": x["finished"]["noul"], "ms": r["ms"], "cost": r["cost"]}


def f_llm(model):
    def f(it):
        r = llm_json(model, SYS, it["text"], max_tokens=200); j = r["json"] or {}
        return {"intent": j.get("intent"), "finished": j.get("finished"), "ms": r["ms"], "cost": r["cost"]}
    return f


R = HERE / "results"; G = {it["id"]: it for it in items}
runs = {"jev": run_checkpointed(items, f_jev, R / "jev.jsonl", a.workers)}
EXPENSIVE = {"openai/gpt-6-astra", "anthropic/claude-sonnet-5"}
runs["jev_described"] = run_checkpointed(items, f_jev_described, R / "jev_described.jsonl", a.workers)
for m in BASELINES:
    runs[m] = run_checkpointed(items[: a.n_frontier] if m in EXPENSIVE else items, f_llm(m), R / (m.replace("/", "__") + ".jsonl"), a.llm_workers)

summary = {"turns": len(items), "decisions_per_turn": len(Q), "models": {}}
for name, rows in runs.items():
    full = [r for r in rows if G[r["id"]]["finished"]]
    fin = [(r["finished_p"] >= 0.5) if name.startswith("jev") else r.get("finished") for r in rows]
    ms = [r["ms"] for r in rows]
    summary["models"][name] = {
        "n": len(rows),
        "intent_accuracy_on_complete_turns": sum(r["intent"] == G[r["id"]]["intent"] for r in full) / len(full),
        "end_of_turn_accuracy": sum(f == G[r["id"]]["finished"] for f, r in zip(fin, rows)) / len(rows),
        "p50_ms": pct(ms, 50), "p90_ms": pct(ms, 90), "p95_ms": pct(ms, 95), "p99_ms": pct(ms, 99),
        "pct_turns_under_300ms": 100 * sum(m < 300 for m in ms) / len(ms),
        "cost_per_1k_turns": 1000 * sum(r["cost"] for r in rows) / len(rows)}
(R / "summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
