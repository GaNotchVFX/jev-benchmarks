"""Lane 3 - Bulk tagging: "tag every row" economics.

Question a business asks: "We have a pile of reviews / tickets / CRM notes. Can we afford to read ALL of it?"

Data    : Yelp review_full public test set (50k reviews, gold 1-5 stars).
Per row : ONE Jev request answers 9 questions in parallel: star rating, sentiment, and 7 yes/no business tags.
Gold    : stars (exact / within-1 / MAE) and sentiment (1-2 stars = negative, 3 = mixed, 4-5 = positive).
No gold : the 7 tags. For those we report agreement with a frontier LLM on a 300-row sample - agreement, not truth.
Scale   : measured rows/sec and measured $/row from the real run, then plain multiplication to 1M rows.

usage: python bench.py [--n 5000] [--n-llm 300] [--workers 12]
"""
import argparse, json, sys
from pathlib import Path
import pandas as pd
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "common"))
from jevlib import jev, llm_json, run_checkpointed, pct

BASELINES = ["openai/gpt-6-astra", "google/gemini-3.8-flash", "openai/gpt-5.6-luna"]
REFERENCE = "openai/gpt-6-astra"
ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=5000); ap.add_argument("--n-llm", type=int, default=300)
ap.add_argument("--workers", type=int, default=12); ap.add_argument("--n-frontier", type=int, default=100)
a = ap.parse_args()

df = pd.read_parquet(HERE.parent / "common/data/yelp_test.parquet").sample(n=a.n, random_state=7)
df["id"] = df.index.astype(str); df["stars"] = df.label + 1; df["text"] = df.text.str.slice(0, 1500)
items = df[["id", "text", "stars"]].to_dict("records"); items_llm = items[: a.n_llm]
sent = lambda s: "negative" if s <= 2 else ("mixed" if s == 3 else "positive")

TAGS = {
    "staff": "Does the review comment on staff or customer service (good or bad)?",
    "price": "Does the review comment on price or value for money?",
    "wait": "Does the review complain about waiting time or slowness?",
    "cleanliness": "Does the review comment on cleanliness or hygiene?",
    "compensation": "Does the reviewer say they asked for, or believe they are owed, a refund, discount or compensation?",
    "will_return": "Does the reviewer say or clearly imply they will come back or use this business again?",
    "health_safety": "Does the review describe a health or safety problem (illness, injury, pests, unsafe conditions)?",
}
Q = {"stars": {"type": "score", "instructions": "How many stars would the author of `review` give this business?",
               "criteria": ["1 star: terrible experience", "2 stars: mostly bad", "3 stars: mixed or just okay",
                            "4 stars: good with minor issues", "5 stars: excellent"]},
     "sentiment": {"type": "choice", "instructions": "What is the overall sentiment of `review`?",
                   "criteria": {"negative": None, "mixed": None, "positive": None}},
     **{k: {"type": "noul", "instructions": v} for k, v in TAGS.items()}}
SYS = ("You tag customer reviews. Reply with JSON only, exactly these keys:\n"
       '{"stars": integer 1-5 the author would give, "sentiment": "negative"|"mixed"|"positive", '
       + ", ".join(f'"{k}": true|false ({v})' for k, v in TAGS.items()) + "}")


def f_jev(it):
    r = jev({"review": it["text"]}, Q); x = r["answers"]
    return {"stars": x["stars"]["score"] + 1, "sentiment": x["sentiment"]["choice"],
            **{k: x[k]["noul"] for k in TAGS}, "ms": r["ms"], "cost": r["cost"], "in_tok": r["in_tok"]}


def f_llm(model):
    def f(it):
        r = llm_json(model, SYS, it["text"], max_tokens=300); j = r["json"] or {}
        return {"stars": j.get("stars"), "sentiment": j.get("sentiment"), **{k: j.get(k) for k in TAGS},
                "ms": r["ms"], "cost": r["cost"], "in_tok": r["in_tok"], "out_tok": r["out_tok"]}
    return f


R = HERE / "results"; G = {it["id"]: it["stars"] for it in items}
runs = {"jev": run_checkpointed(items, f_jev, R / "jev.jsonl", a.workers)}
for m in BASELINES:
    runs[m] = run_checkpointed(items_llm[: a.n_frontier] if m == REFERENCE else items_llm, f_llm(m), R / (m.replace("/", "__") + ".jsonl"), 8)


def stats(rows):
    ok = [r for r in rows if isinstance(r.get("stars"), (int, float))]
    err = [abs(round(r["stars"]) - G[r["id"]]) for r in ok]
    return {"n": len(rows), "unparseable": len(rows) - len(ok),
            "stars_exact": sum(e == 0 for e in err) / len(rows), "stars_within_1": sum(e <= 1 for e in err) / len(rows),
            "stars_mae": sum(err) / len(err), "sentiment_accuracy": sum(r.get("sentiment") == sent(G[r["id"]]) for r in rows) / len(rows),
            "p50_ms": pct([r["ms"] for r in rows], 50), "cost_per_row": sum(r["cost"] for r in rows) / len(rows),
            "cost_per_1M_rows": 1e6 * sum(r["cost"] for r in rows) / len(rows)}


llm_ids = {it["id"] for it in items_llm}
summary = {"rows_jev": len(items), "rows_llm": len(items_llm), "questions_per_row": len(Q), "models": {}}
summary["models"]["jev (all rows)"] = stats(runs["jev"])
summary["models"]["jev (same rows as LLMs)"] = stats([r for r in runs["jev"] if r["id"] in llm_ids])
for m in BASELINES:
    summary["models"][m] = stats(runs[m])
w = Path(str(R / "jev.jsonl") + ".wall.json")
if w.exists():
    wj = json.loads(w.read_text()); rps = wj["rows_run"] / wj["wall_s"]
    summary["jev_throughput"] = {**wj, "rows_per_sec": rps, "decisions_per_sec": rps * len(Q), "hours_for_1M_rows": 1e6 / rps / 3600}
ref = {r["id"]: r for r in runs[REFERENCE]}
summary["tag_agreement_with_" + REFERENCE] = {}
for name in ["jev"] + [m for m in BASELINES if m != REFERENCE]:
    rows = [r for r in runs[name] if r["id"] in ref]
    summary["tag_agreement_with_" + REFERENCE][name] = {
        k: sum(((r[k] >= 0.5) if name == "jev" else bool(r.get(k))) == bool(ref[r["id"]].get(k)) for r in rows) / len(rows) for k in TAGS}
(R / "summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
