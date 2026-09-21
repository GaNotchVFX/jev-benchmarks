"""Shared client for the Jev benchmark demos.

- Jev is called through OpenRouter's Decisions API (same schema as api.typesafe.ai/v1/systemone).
- Baseline LLMs are called through OpenRouter chat completions with JSON output.
- Every call records wall-clock latency and the cost OpenRouter reports. Nothing is estimated.
- The API key is read from OPENROUTER_API_KEY (process env, then Windows user env). It is never printed or written.
"""
from __future__ import annotations
import json, os, sys, time, random, threading
import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
JEV = "typesafe/jev-1.13"
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
STOP = threading.Event()  # set on HTTP 402 (out of credits) or when the spend cap is hit: nothing more is submitted


class OutOfBudget(RuntimeError):
    pass


def balance() -> float:
    """Remaining prepaid OpenRouter credit in USD."""
    d = httpx.get("https://openrouter.ai/api/v1/credits", headers={"Authorization": f"Bearer {get_key()}"}, timeout=20).json()["data"]
    return float(d["total_credits"]) - float(d["total_usage"])


def guard(floor_usd: float = 5.0) -> float:
    """Call before every model run. Refuses to start if the key would drop below floor_usd."""
    b = balance()
    print(f"[budget] OpenRouter balance ${b:.2f} (floor ${floor_usd:.2f})", flush=True)
    if b < floor_usd:
        STOP.set(); raise OutOfBudget(f"balance ${b:.2f} is under the ${floor_usd:.2f} floor - not starting")
    return b


def get_key() -> str:
    k = os.environ.get("OPENROUTER_API_KEY")
    if not k and sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
            k = winreg.QueryValueEx(h, "OPENROUTER_API_KEY")[0]
    if not k:
        raise SystemExit("OPENROUTER_API_KEY not set")
    return k


_local = threading.local()


def client() -> httpx.Client:
    """One keep-alive HTTP/2 client per thread so latency numbers exclude TLS handshakes after the first call."""
    c = getattr(_local, "c", None)
    if c is None:
        c = httpx.Client(http2=True, timeout=httpx.Timeout(120, connect=15),
                         headers={"Authorization": f"Bearer {get_key()}",
                                  "X-Title": "jev-benchmarks"})
        _local.c = c
    return c


def _post(url: str, body: dict, tries: int = 6) -> tuple[dict, float]:
    """POST with backoff. Returned latency is for the successful attempt only."""
    last = None
    for i in range(tries):
        t = time.perf_counter()
        try:
            r = client().post(url, json=body)
            ms = (time.perf_counter() - t) * 1000
            if r.status_code == 200:
                return r.json(), ms
            last = f"HTTP {r.status_code}: {r.text[:300]}"
            if r.status_code == 402:
                STOP.set(); raise OutOfBudget(last)
            if r.status_code not in RETRY_STATUS:
                raise RuntimeError(last)
        except (httpx.TransportError, httpx.TimeoutException) as e:
            last = repr(e)
        time.sleep(min(30, (2 ** i) * 0.5) + random.random() * 0.3)
    raise RuntimeError(f"gave up after {tries} tries: {last}")


def jev(state, questions: dict) -> dict:
    """-> {answers, ms, cost, in_tok}"""
    out, ms = _post(DECISIONS_URL, {"model": JEV, "state": state, "questions": questions})
    u = out.get("usage", {})
    return {"answers": out["answers"], "ms": ms, "cost": float(u.get("cost") or 0.0),
            "in_tok": u.get("input_tokens", 0)}


def llm_json(model: str, system: str, user: str, max_tokens: int = 400, reasoning: str | None = "low") -> dict:
    """Ask a chat LLM for a JSON object. -> {json, raw, ms, cost, in_tok, out_tok}

    Latency is time to the COMPLETE response, because code cannot act on half a JSON object.
    """
    body = {"model": model, "max_tokens": max_tokens, "temperature": 0,
            "response_format": {"type": "json_object"},
            "usage": {"include": True},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if reasoning:
        body["reasoning"] = {"effort": reasoning}
    out, ms = _post(CHAT_URL, body)
    raw = (out["choices"][0]["message"].get("content") or "").strip()
    parsed = None
    try:
        s = raw[raw.index("{"): raw.rindex("}") + 1]
        parsed = json.loads(s)
    except Exception:
        pass
    u = out.get("usage", {})
    return {"json": parsed, "raw": raw[:500], "ms": ms, "cost": float(u.get("cost") or 0.0),
            "in_tok": u.get("prompt_tokens", 0), "out_tok": u.get("completion_tokens", 0)}


def run_checkpointed(items: list[dict], fn, out_path: Path, workers: int = 8, key: str = "id") -> list[dict]:
    """Run fn(item)->dict over items in a thread pool, appending to JSONL so reruns resume instead of re-paying."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = {}
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if "error" not in r:
                    done[r[key]] = r
    todo = [it for it in items if it[key] not in done]
    if todo:
        guard(float(os.environ.get("JEV_BENCH_FLOOR_USD", "5")))
    print(f"[{out_path.name}] {len(done)} cached, {len(todo)} to run, workers={workers}", flush=True)
    lock = threading.Lock()
    t0 = time.perf_counter()
    with out_path.open("a", encoding="utf-8") as f, ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(_safe, fn, it, key): it for it in todo}
        for n, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            with lock:
                f.write(json.dumps(r) + "\n"); f.flush()
            if "error" not in r:
                done[r[key]] = r
            if n % 100 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)}  {(time.perf_counter()-t0):.0f}s", flush=True)
    wall = time.perf_counter() - t0
    res = [done[it[key]] for it in items if it[key] in done]
    if todo:
        Path(str(out_path) + ".wall.json").write_text(json.dumps(
            {"rows_run": len(todo), "wall_s": wall, "workers": workers}))
    return res


def _safe(fn, it, key):
    if STOP.is_set():
        return {key: it[key], "error": "skipped: budget stop"}
    try:
        r = fn(it); r[key] = it[key]; return r
    except Exception as e:
        return {key: it[key], "error": str(e)[:300]}


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    i = (len(xs) - 1) * p / 100
    lo, hi = int(i), min(int(i) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)
