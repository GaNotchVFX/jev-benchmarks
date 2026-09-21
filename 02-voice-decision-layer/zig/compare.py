"""Pool the ABBA runs (python, zig, zig, python) and compute both clients' percentiles with the SAME method."""
import json, sys
from pathlib import Path
H = Path(__file__).parent
sys.path.insert(0, str(H.parent.parent / "common"))
from jevlib import pct


def load(prefix):
    warm, cold, bad = [], [], 0
    for run in (1, 2):
        rows = [json.loads(l) for l in (H / f"{prefix}_latency_run{run}.jsonl").read_text().splitlines() if l.strip()]
        cold.append(rows[0]["ms"]); warm += [r["ms"] for r in rows[1:]]; bad += sum(r["status"] != 200 for r in rows)
    return {"n_warm": len(warm), "non_200": bad, "cold_ms": cold, "min": min(warm), "p50": pct(warm, 50), "p90": pct(warm, 90),
            "p95": pct(warm, 95), "p99": pct(warm, 99), "max": max(warm), "mean": sum(warm) / len(warm)}


z, p = load("zig"), load("py")
z["label"] = "Zig 0.16, std.http, ReleaseFast"; p["label"] = "Python 3.13, httpx (HTTP/2)"
out = {"zig": z, "python": p,
       "subtitle": f"Same request bodies, same endpoint, one keep-alive connection each, sequential. Runs interleaved (Python, Zig, Zig, Python). n = {z['n_warm']} warm requests per client.",
       "footer": "Request latency = send to last body byte, measured inside each client with a monotonic clock. First request of each run (TLS handshake) excluded. "
                 "The network + model round trip dominates both; the client only controls what is left over."}
(H / "latency_compare.json").write_text(json.dumps(out, indent=2))
for k in ("zig", "python"):
    print(k, {a: (round(b, 1) if isinstance(b, float) else b) for a, b in out[k].items()})
