"""Build the LinkedIn-ready PNG charts for all three lanes from each lane's results/summary.json.
Every number drawn comes from a summary file; nothing is typed in by hand.   usage: python common/charts.py
"""
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).parent.parent
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE, ORANGE, NEUTRAL = "#2a78d6", "#eb6834", "#b4b2a9"
NAMES = {"jev": "Jev 1.13", "jev_described": "Jev + option descriptions", "openai/gpt-6-astra": "GPT-6 Astra", "anthropic/claude-sonnet-5": "Claude Sonnet 5",
         "google/gemini-3.8-flash": "Gemini 3.8 Flash", "openai/gpt-5.6-luna": "GPT-5.6 Luna"}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "text.color": INK, "axes.edgecolor": AXIS,
                     "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": INK2, "figure.facecolor": SURFACE,
                     "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE})


def panel(ax, keys, vals, title, fmt, hi="jev", whisk=None, whisk_label=None, ref=None, ref_label=None):
    """Horizontal bars, one highlighted. Value at the tip of every bar. Optional thin p95 tick and reference line."""
    y = list(range(len(keys)))[::-1]
    ax.barh(y, vals, height=0.46, color=[BLUE if k.startswith(hi) else NEUTRAL for k in keys], zorder=3)
    top = max(list(vals) + (list(whisk) if whisk else []) + ([ref] if ref else []))
    if whisk:
        ax.scatter(whisk, y, marker="|", s=170, color=INK2, zorder=4, linewidths=1.6)
    for yi, v, w in zip(y, vals, whisk or [None] * len(vals)):
        ax.text(max(v, w or 0) + top * 0.03, yi, fmt(v), va="center", ha="left", fontsize=10.5, color=INK)
    if ref:
        ax.axvline(ref, color=INK2, lw=1, zorder=2)
        ax.text(ref, len(keys) - 0.42, " " + ref_label, fontsize=8.5, color=INK2, va="bottom", ha="left")
    ax.set_yticks(y); ax.set_yticklabels([NAMES.get(k, k) for k in keys])
    ax.set_xlim(0, top * 1.45); ax.set_ylim(-0.6, len(keys) - 0.15)
    ax.set_title(title, loc="left", fontsize=11.5, color=INK2, pad=10)
    ax.xaxis.grid(True, color=GRID, lw=1, zorder=0); ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    if whisk_label:
        ax.text(1.0, -0.13, whisk_label, transform=ax.transAxes, fontsize=8.5, color=MUTED, ha="right", va="top")


def frame(title, subtitle, n=3, footer=""):
    fig, axes = plt.subplots(1, n, figsize=(12, 6.27), dpi=200)
    fig.subplots_adjust(left=0.115, right=0.975, top=0.70, bottom=0.17, wspace=0.62)
    fig.text(0.03, 0.93, title, fontsize=19, fontweight="bold", color=INK, va="top")
    import textwrap as _tw
    fig.text(0.03, 0.855, "\n".join(_tw.wrap(subtitle, 132)), fontsize=11.5, color=INK2, va="top", linespacing=1.45)
    import textwrap
    fig.text(0.03, 0.025, "\n".join(textwrap.wrap(footer, 165)), fontsize=8.5, color=MUTED, va="bottom", linespacing=1.5)
    return fig, (axes if n > 1 else [axes])


def strip_labels(axes):
    for ax in axes[1:]:
        ax.set_yticklabels([])


def lane1():
    s = json.loads((ROOT / "01-cost-cut-migration/results/summary.json").read_text()); m = s["models"]
    keys = [k for k in NAMES if k in m]
    a = m["openai/gpt-6-astra"]; j = m["jev"]
    fig, ax = frame(f"Support-ticket triage: {a['cost_per_1k']/j['cost_per_1k']:.0f}x cheaper, {a['p50_ms']/j['p50_ms']:.0f}x faster, {100*(a['accuracy']-j['accuracy']):.0f} points less accurate",
                    "Banking77, 77 intents, public test set. Same label list for every model, zero tuning. Jev vs GPT-6 Astra shown in the title.",
                    footer="Measured " + DATE + " via OpenRouter from one Windows laptop, warm keep-alive connections. n per model: "
                           + ", ".join(f"{NAMES[k]} {m[k]['n']}" for k in keys) + ". Cost = billed cost reported by the API.")
    panel(ax[0], keys, [100 * m[k]["accuracy"] for k in keys], "Accuracy vs gold labels (%)", lambda v: f"{v:.1f}%")
    p95 = {round(m[k]["p50_ms"], 6): m[k]["p95_ms"] for k in keys}
    panel(ax[1], keys, [m[k]["p50_ms"] for k in keys], "Latency per ticket, p50 (p95 in brackets)", lambda v: f"{v:,.0f} ms ({p95[round(v, 6)]:,.0f})")
    panel(ax[2], keys, [m[k]["cost_per_1k"] for k in keys], "Cost per 1,000 tickets (USD)", lambda v: f"${v:,.2f}" if v >= 0.1 else f"${v:.3f}")
    strip_labels(ax); fig.savefig(ROOT / "01-cost-cut-migration/chart_models.png"); plt.close(fig)

    fig, axes = frame("Let Jev take the tickets it is sure about. Send the rest to an LLM.",
                      "Each dot is a confidence cutoff. Left: uncertain tickets fall back to a frontier model. Right: they fall back to a small LLM.", n=2,
                      footer="Same run as the model comparison. Blended cost = the Jev call on every ticket + the fallback call only when Jev is under the cutoff. Note the two cost axes are very different scales.")
    fig.subplots_adjust(left=0.07, bottom=0.2, wspace=0.22)
    for ax, (fb, c) in zip(axes, s["cascades"].items()):
        cur = c["curve"]; xs = [r["cost_per_1k"] for r in cur]; ys = [100 * r["accuracy"] for r in cur]
        ax.plot(xs, ys, color=BLUE, lw=2, zorder=3, solid_capstyle="round")
        ax.scatter(xs, ys, s=70, color=BLUE, edgecolors=SURFACE, linewidths=2, zorder=4)
        for r, x, y in zip(cur, xs, ys):
            if r["tau"] in (0, 0.8) or r["tau"] > 1:
                lab = "Jev only" if r["tau"] == 0 else (f"{NAMES[fb]} on every ticket" if r["tau"] > 1 else f"Jev handles {r['jev_handles_pct']:.0f}%")
                right = r["tau"] > 1
                ax.annotate(f"{lab}\n{y:.1f}%  ${x:.2f}  {r['mean_ms']:,.0f} ms avg", (x, y), xytext=(-2 if right else 10, 12 if right else -30),
                            textcoords="offset points", fontsize=9.5, color=INK, ha="right" if right else "left")
        ax.set_title(f"Fallback: {NAMES[fb]}  (n={c['n']})", loc="left", fontsize=11.5, color=INK2, pad=10)
        ax.set_xlabel("Cost per 1,000 tickets (USD)"); ax.set_ylabel("Accuracy (%)")
        ax.set_xlim(-max(xs) * 0.04, max(xs) * 1.08); ax.set_ylim(min(ys) - 3.2, max(ys) + 2.6)
        ax.grid(True, color=GRID, lw=1); ax.set_axisbelow(True)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.tick_params(length=0)
    fig.savefig(ROOT / "01-cost-cut-migration/chart_cascade.png"); plt.close(fig)


def lane2():
    s = json.loads((ROOT / "02-voice-decision-layer/results/summary.json").read_text()); m = s["models"]
    keys = [k for k in NAMES if k in m]; j = m.get("jev_described", m["jev"])
    fig, ax = frame(f"Voice agent decision step: {j['p50_ms']:.0f} ms for {s['decisions_per_turn']} decisions in one call",
                    "Per caller turn: intent, end-of-turn, escalate, urgency. SNIPS utterances, half cut off mid-sentence to test end-of-turn detection.",
                    footer="Measured " + DATE + " via OpenRouter from one Windows laptop, warm connections. LLM latency = time to the complete JSON (code cannot act on half an object). n per model: "
                           + ", ".join(f"{NAMES[k]} {m[k]['n']}" for k in keys) + ".")
    fig.subplots_adjust(left=0.2, wspace=0.5)
    p95 = {round(m[k]["p50_ms"], 6): m[k]["p95_ms"] for k in keys}
    panel(ax[0], keys, [m[k]["p50_ms"] for k in keys], "Decision latency, p50 (p95 in brackets)", lambda v: f"{v:,.0f} ms ({p95[round(v, 6)]:,.0f})")
    panel(ax[1], keys, [100 * m[k]["intent_accuracy_on_complete_turns"] for k in keys], "Intent accuracy, complete turns (%)", lambda v: f"{v:.1f}%")
    panel(ax[2], keys, [100 * m[k]["end_of_turn_accuracy"] for k in keys], "End-of-turn accuracy (%)", lambda v: f"{v:.1f}%")
    strip_labels(ax); fig.savefig(ROOT / "02-voice-decision-layer/chart_models.png"); plt.close(fig)

    z = ROOT / "02-voice-decision-layer/zig/latency_compare.json"
    if z.exists():
        d = json.loads(z.read_text()); cats = ["p50", "p90", "p95", "p99"]
        diff = d["zig"]["p50"] - d["python"]["p50"]
        fig, (ax,) = frame(f"Zig vs Python client: {abs(diff):.0f} ms apart at p50. The round trip is the cost.", d["subtitle"], n=1, footer=d["footer"])
        fig.subplots_adjust(left=0.08, bottom=0.2)
        for i, (k, col) in enumerate((("zig", BLUE), ("python", ORANGE))):
            xs = [c + (i - 0.5) * 0.34 for c in range(len(cats))]
            ax.bar(xs, [d[k][c] for c in cats], width=0.30, color=col, label=d[k]["label"], zorder=3)
            for x, c in zip(xs, cats):
                ax.text(x, d[k][c] + 3, f"{d[k][c]:.0f}", ha="center", fontsize=10, color=INK)
        ax.set_xticks(range(len(cats))); ax.set_xticklabels(cats); ax.set_ylabel("Request latency (ms)")
        ax.legend(frameon=False, loc="upper left"); ax.yaxis.grid(True, color=GRID, lw=1); ax.set_axisbelow(True)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.tick_params(length=0); fig.savefig(ROOT / "02-voice-decision-layer/chart_zig_vs_python.png"); plt.close(fig)


def lane3():
    s = json.loads((ROOT / "03-bulk-tagging/results/summary.json").read_text()); m = s["models"]
    mm = {"jev": m["jev (all rows)"], **{k: v for k, v in m.items() if k in NAMES}}
    keys = [k for k in NAMES if k in mm]; t = s.get("jev_throughput", {}); j = mm["jev"]
    fig, ax = frame(f"Tag 1,000,000 reviews with {s['questions_per_row']} questions each for ${j['cost_per_1M_rows']:,.0f}",
                    f"Yelp reviews: stars, sentiment and 7 yes/no business tags per row in one call. Measured {t.get('rows_per_sec', 0):.0f} rows/sec "
                    f"({t.get('decisions_per_sec', 0):.0f} decisions/sec) with {t.get('workers', '?')} parallel connections.",
                    footer="Measured " + DATE + " via OpenRouter. $/1M rows = measured billed cost per row x 1,000,000. n per model: "
                           + ", ".join(f"{NAMES[k]} {mm[k]['n']:,}" for k in keys) + ". Reviews truncated to 1,500 characters.")
    panel(ax[0], keys, [mm[k]["cost_per_1M_rows"] for k in keys], "Cost per 1M rows (USD)", lambda v: f"${v:,.0f}")
    panel(ax[1], keys, [100 * mm[k]["stars_within_1"] for k in keys], "Star rating within 1 of the real one (%)", lambda v: f"{v:.1f}%")
    panel(ax[2], keys, [100 * mm[k]["sentiment_accuracy"] for k in keys], "Sentiment accuracy (%)", lambda v: f"{v:.1f}%")
    strip_labels(ax); fig.savefig(ROOT / "03-bulk-tagging/chart_models.png"); plt.close(fig)


if __name__ == "__main__":
    import datetime
    DATE = datetime.date.today().strftime("%b %d, %Y")
    for f in (lane1, lane2, lane3):
        try:
            f(); print("ok", f.__name__)
        except FileNotFoundError as e:
            print("skip", f.__name__, e)
