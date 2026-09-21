"""Print every headline number used in the READMEs / LinkedIn posts straight from the summary files.
If a post and this output disagree, the post is wrong.   usage: python common/facts.py"""
import json
from pathlib import Path
R = Path(__file__).parent.parent
A, L, F, S = "openai/gpt-6-astra", "openai/gpt-5.6-luna", "google/gemini-3.8-flash", "anthropic/claude-sonnet-5"

s = json.loads((R / "01-cost-cut-migration/results/summary.json").read_text()); m = s["models"]
print("== LANE 1  (Banking77, 77 intents)")
for k, v in m.items():
    print(f"  {k:28s} n={v['n']:4d} acc={100*v['accuracy']:.1f}% p50={v['p50_ms']:.0f}ms p95={v['p95_ms']:.0f}ms $/1k={v['cost_per_1k']:.4f} invalid={v['invalid_label']}")
f = s["jev_full_test_set"]; print(f"  jev full test set n={f['n']} acc={100*f['accuracy']:.1f}% p50={f['p50_ms']:.0f}ms")
print(f"  astra/jev cost x{m[A]['cost_per_1k']/m['jev']['cost_per_1k']:.0f}  astra/luna cost x{m[A]['cost_per_1k']/m[L]['cost_per_1k']:.0f}  luna/jev cost x{m[L]['cost_per_1k']/m['jev']['cost_per_1k']:.1f}")
print(f"  astra/jev p50 x{m[A]['p50_ms']/m['jev']['p50_ms']:.1f}  luna/jev p50 x{m[L]['p50_ms']/m['jev']['p50_ms']:.1f}")
for fb, c in s["cascades"].items():
    al = c["fallback_alone"]; print(f"  cascade -> {fb} (n={c['n']}): alone acc={100*al['accuracy']:.1f}% mean={al['mean_ms']:.0f}ms $/1k={al['cost_per_1k']:.3f}")
    for r in c["curve"]:
        if r["tau"] in (0.8, 0.95):
            print(f"     tau={r['tau']}: jev handles {r['jev_handles_pct']:.0f}% acc={100*r['accuracy']:.1f}% mean={r['mean_ms']:.0f}ms $/1k={r['cost_per_1k']:.3f}"
                  f" | vs astra alone: x{m[A]['cost_per_1k']/r['cost_per_1k']:.0f} cheaper, x{m[A]['mean_ms']/r['mean_ms']:.1f} faster, {100*(m[A]['accuracy']-r['accuracy']):.1f} pts lower"
                  f" | vs fallback alone: {100*(1-r['cost_per_1k']/al['cost_per_1k']):.0f}% cheaper, {100*(1-r['mean_ms']/al['mean_ms']):.0f}% less latency")

s = json.loads((R / "02-voice-decision-layer/results/summary.json").read_text()); m = s["models"]
print("== LANE 2  (voice decision layer)", s["turns"], "turns,", s["decisions_per_turn"], "decisions per turn")
for k, v in m.items():
    print(f"  {k:28s} n={v['n']:3d} p50={v['p50_ms']:.0f} p95={v['p95_ms']:.0f} p99={v['p99_ms']:.0f}ms under300={v['pct_turns_under_300ms']:.1f}% intent={100*v['intent_accuracy_on_complete_turns']:.1f}% eot={100*v['end_of_turn_accuracy']:.1f}% $/1k={v['cost_per_1k_turns']:.4f}")
print(f"  fastest LLM p50 / jev p50 = x{min(v['p50_ms'] for k, v in m.items() if not k.startswith('jev'))/m['jev']['p50_ms']:.1f}")
z = json.loads((R / "02-voice-decision-layer/zig/latency_compare.json").read_text())
for k in ("zig", "python"):
    print(f"  {k:7s} n={z[k]['n_warm']} p50={z[k]['p50']:.1f} p95={z[k]['p95']:.1f} p99={z[k]['p99']:.1f} max={z[k]['max']:.1f} cold={z[k]['cold_ms']}")

s = json.loads((R / "03-bulk-tagging/results/summary.json").read_text()); m = s["models"]
print("== LANE 3  (bulk tagging)", s["questions_per_row"], "questions per row")
for k, v in m.items():
    print(f"  {k:28s} n={v['n']:4d} exact={100*v['stars_exact']:.1f}% within1={100*v['stars_within_1']:.1f}% mae={v['stars_mae']:.2f} sent={100*v['sentiment_accuracy']:.1f}% $/1M={v['cost_per_1M_rows']:,.0f} unparseable={v['unparseable']}")
j = m["jev (all rows)"]["cost_per_1M_rows"]
print("  cost multiples vs jev:", {k: round(v["cost_per_1M_rows"] / j, 1) for k, v in m.items() if not k.startswith("jev")})
t = s["jev_throughput"]; print(f"  throughput: {t['rows_per_sec']:.1f} rows/s, {t['decisions_per_sec']:.0f} decisions/s, {t['hours_for_1M_rows']:.1f} h per 1M rows, workers={t['workers']}")
for k, v in s["tag_agreement_with_" + A].items():
    print(f"  tag agreement with astra, {k}: min={100*min(v.values()):.0f}% mean={100*sum(v.values())/len(v):.1f}%  {v}")
