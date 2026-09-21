"""Same 200 request bodies as jevfast.exe, same endpoint, one keep-alive connection, sequential - but Python + httpx.
Run right before/after jevfast.exe so both see the same network conditions."""
import json, sys, time
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent / "common"))
from jevlib import client, DECISIONS_URL, pct, guard
guard(5)
n = int(sys.argv[1]) if len(sys.argv) > 1 else 10**9
bodies = [l for l in (HERE / "turns.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()][:n]
c = client(); rows = []
for i, b in enumerate(bodies):
    t = time.perf_counter()
    r = c.post(DECISIONS_URL, content=b.encode(), headers={"Content-Type": "application/json"}); _ = r.content
    rows.append({"i": i, "status": r.status_code, "ms": round((time.perf_counter() - t) * 1000, 2), "bytes": len(r.content)})
(HERE / "py_latency.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
warm = [r["ms"] for r in rows[1:]]
print(f"requests={len(rows)} non_200={sum(r['status'] != 200 for r in rows)} cold_ms={rows[0]['ms']:.1f}")
print("warm: min=%.1f p50=%.1f p90=%.1f p95=%.1f p99=%.1f max=%.1f (ms)" % (min(warm), pct(warm, 50), pct(warm, 90), pct(warm, 95), pct(warm, 99), max(warm)))
