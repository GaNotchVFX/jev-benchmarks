# Jev benchmarks: where a decision model beats an LLM, and where it does not

Three measured demos of TypeSafe's Jev 1.13 (a "System One" decision model: typed questions in, typed answers with probabilities and confidence out, no text generation) against the LLMs people actually use for the same jobs. All runs Sep 21 2026, from one Windows laptop, through OpenRouter, public datasets, billed cost as reported by the API.

| Lane | Job | Headline | Verdict |
|---|---|---|---|
| [01-cost-cut-migration](01-cost-cut-migration/README.md) | 77-way support ticket triage | Jev + small-LLM fallback: 84.0% accurate at $0.08 per 1,000 vs a frontier model's 86.7% at $5.70 | Jev alone is not accurate enough. Its confidence score makes the hybrid work. The biggest saving is getting off the frontier model at all. |
| [02-voice-decision-layer](02-voice-decision-layer/README.md) | 4 decisions per caller turn in a voice agent | Jev about 150 ms; fastest LLM 1,086 ms; 0 of 1,000 LLM turns under 300 ms | Only Jev fits a voice latency budget. It gives up 3 to 6 points of intent accuracy. A Zig client was no faster than Python. |
| [03-bulk-tagging](03-bulk-tagging/README.md) | 9 questions per review across 5,000 reviews | $29 per 1M rows vs $189 to $6,174; quality within a few points | Clean win for Jev. |

## Layout

- `common/jevlib.py`: the client. Jev via OpenRouter's Decisions API, LLM baselines via chat completions, latency and billed cost recorded per call, JSONL checkpoints so reruns never pay twice, and a balance guard that refuses to run under a $5 floor and stops on HTTP 402.
- `common/charts.py`: builds every PNG from the `results/summary.json` files. `common/facts.py` prints every headline number from the same files; if a post disagrees with it, the post is wrong.
- Each lane: `bench.py`, `results/` (raw per-call rows + summary), charts, `README.md`, `linkedin_post.md`.

## Run

```
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install "httpx[http2]" pandas pyarrow matplotlib
.\.venv\Scripts\python common\fetch_data.py
# then each lane's bench.py (see its README), then:
.\.venv\Scripts\python common\charts.py
```

Needs `OPENROUTER_API_KEY` in the environment. The key is never written to disk or logs. Full rerun of all three lanes as configured cost me roughly $7, almost all of it the frontier baselines; the Jev calls total well under $1.
