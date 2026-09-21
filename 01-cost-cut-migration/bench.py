"""Lane 1 - Cost-cut migration.

Question a CTO asks: "We pay a big LLM to triage support tickets. What happens if the decision moves to Jev?"

Task     : Banking77 - 77-way support-ticket intent classification, public test set with gold labels.
Same info: every model gets the identical list of 77 label names. No descriptions, no few-shot, no tuning.
Measured : accuracy vs gold, latency per ticket (warm keep-alive connection), billed cost (as reported by OpenRouter).
Cascade  : Jev answers when its confidence >= tau, otherwise the ticket falls back to the big LLM.

usage: python bench.py [--n-per-intent 10] [--jev-all]
"""
import argparse, json, sys
from pathlib import Path
import pandas as pd
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "common"))
from jevlib import jev, llm_json, run_checkpointed, pct

BASELINES = ["openai/gpt-6-astra", "anthropic/claude-sonnet-5", "google/gemini-3.8-flash", "openai/gpt-5.6-luna"]
ap = argparse.ArgumentParser(); ap.add_argument("--n-per-intent", type=int, default=10)
ap.add_argument("--no-new-expensive", action="store_true", help="frontier models: reuse rows already paid for, buy no new ones")
ap.add_argument("--jev-all", action="store_true"); ap.add_argument("--workers", type=int, default=8)
a = ap.parse_args()

df = pd.read_parquet(HERE.parent / "common/data/banking77_test.parquet")
df["id"] = df.index.astype(str)
LABELS = sorted(df.label_text.unique())
sub = df.groupby("label_text", group_keys=False).sample(n=a.n_per_intent, random_state=7)
items_sub = sub[["id", "text", "label_text"]].to_dict("records")
items_all = df[["id", "text", "label_text"]].to_dict("records")

Q = {"intent": {"type": "choice",
                "instructions": "Which support intent best matches the customer's message in `ticket`?",
                "criteria": {l: None for l in LABELS}}}
SYS = ("You triage bank support tickets. Pick the single best intent for the customer's message from this list:\n"
       + "\n".join(LABELS) + '\n\nReply with JSON only: {"intent": "<one label exactly as written>"}')


def f_jev(it):
    r = jev({"ticket": it["text"]}, Q); x = r["answers"]["intent"]
    return {"pred": x["choice"], "conf": x["confidence"], "ms": r["ms"], "cost": r["cost"], "in_tok": r["in_tok"]}


def f_llm(model):
    def f(it):
        r = llm_json(model, SYS, it["text"], max_tokens=200)
        return {"pred": (r["json"] or {}).get("intent"), "ms": r["ms"], "cost": r["cost"],
                "in_tok": r["in_tok"], "out_tok": r["out_tok"]}
    return f


R = HERE / "results"; gold = {it["id"]: it["label_text"] for it in items_all}
runs = {"jev": run_checkpointed(items_all if a.jev_all else items_sub, f_jev, R / "jev.jsonl", a.workers)}
EXPENSIVE = {"openai/gpt-6-astra", "anthropic/claude-sonnet-5"}
for m in BASELINES:
    path = R / (m.replace("/", "__") + ".jsonl"); its = items_sub
    if a.no_new_expensive and m in EXPENSIVE and path.exists():
        have = {json.loads(l)["id"] for l in path.read_text(encoding="utf-8").splitlines() if l.strip() and '"error"' not in l}
        its = [it for it in items_sub if it["id"] in have]
    runs[m] = run_checkpointed(its, f_llm(m), path, a.workers)


def stats(rows):
    ok = [r["pred"] == gold[r["id"]] for r in rows]; ms = [r["ms"] for r in rows]; c = [r["cost"] for r in rows]
    return {"n": len(rows), "accuracy": sum(ok) / len(ok), "p50_ms": pct(ms, 50), "p95_ms": pct(ms, 95),
            "mean_ms": sum(ms) / len(ms), "cost_per_1k": 1000 * sum(c) / len(c),
            "invalid_label": sum(r["pred"] not in LABELS for r in rows)}


subids = {it["id"] for it in items_sub}
summary = {"task": "banking77 77-way intent", "subset_n": len(items_sub), "models": {}}
for name, rows in runs.items():
    summary["models"][name] = stats([r for r in rows if r["id"] in subids])
    if name != "jev":  # Jev on exactly the rows this model was scored on, so every comparison is like-for-like
        ids_m = {r["id"] for r in rows}
        summary["models"][name]["jev_on_same_rows"] = stats([r for r in runs["jev"] if r["id"] in ids_m])
if a.jev_all:
    summary["jev_full_test_set"] = stats(runs["jev"])

# cascade: Jev answers when conf >= tau, else the ticket falls back to an LLM.
# Blended latency/cost = Jev on every ticket + the fallback call only when Jev is under the cutoff.
J = {r["id"]: r for r in runs["jev"] if r["id"] in subids}
summary["cascades"] = {}
for fb in ["openai/gpt-6-astra", "openai/gpt-5.6-luna"]:
    F = {r["id"]: r for r in runs[fb]}; ids = [i for i in J if i in F]; casc = []
    for tau in [0, .3, .5, .6, .7, .8, .9, .95, .99, 1.01]:
        acc = ms = cost = kept = 0
        for i in ids:
            j, f = J[i], F[i]
            if j["conf"] >= tau:
                kept += 1; acc += j["pred"] == gold[i]; ms += j["ms"]; cost += j["cost"]
            else:
                acc += f["pred"] == gold[i]; ms += j["ms"] + f["ms"]; cost += j["cost"] + f["cost"]
        n = len(ids)
        casc.append({"tau": tau, "jev_handles_pct": 100 * kept / n, "accuracy": acc / n,
                     "mean_ms": ms / n, "cost_per_1k": 1000 * cost / n})
    summary["cascades"][fb] = {"n": len(ids), "fallback_alone": stats([F[i] for i in ids]), "curve": casc}
(HERE / "results/summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
