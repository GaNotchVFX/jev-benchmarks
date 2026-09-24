#!/usr/bin/env python3
"""jev.py - tiny stdlib-only Jev client (OpenRouter Decisions API, model typesafe/jev-1.13).
  python jev.py test                                   # one real sales-email call, prints answers/latency/cost
  python jev.py ask   STATE.json QUESTIONS.json        # one call -> answers JSON on stdout
  python jev.py batch ITEMS.jsonl QUESTIONS.json OUT.jsonl [--workers 8] [--max-usd 0.50] [--floor 5]
  python jev.py balance
  python jev.py route "message text"                    # model tier + effort + inline flag, logged
  python jev.py pick-skill SKILLS.json "request text"   # SKILLS.json = {"name": "first line of description"}
  python jev.py status                                  # routed counts per target + Jev cost so far
ITEMS.jsonl: one object per line with an "id"; every other field becomes the state.
OUT.jsonl is checkpointed: rerunning skips ids already answered (no double-paying).
Key: $OPENROUTER_API_KEY, else ~/.config/jev/openrouter_key, else Windows user env. Never printed.
"""
import json, os, sys, time, random, threading, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

URL = os.environ.get("JEV_URL", "https://openrouter.ai/api/alpha/decisions")
MODEL = os.environ.get("JEV_MODEL", "typesafe/jev-1.13")
KEYFILE = Path.home() / ".config" / "jev" / "openrouter_key"
RETRY = {408, 409, 425, 429, 500, 502, 503, 504, 529}
STOP = threading.Event()


def key():
    k = os.environ.get("OPENROUTER_API_KEY")
    if not k and KEYFILE.exists():
        k = KEYFILE.read_text().strip()
    if not k and sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
                k = winreg.QueryValueEx(h, "OPENROUTER_API_KEY")[0]
        except OSError:
            pass
    if not k:
        sys.exit("NO_KEY: set OPENROUTER_API_KEY or write it to ~/.config/jev/openrouter_key (chmod 600)")
    return k


def _req(url, body=None):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                               headers={"Authorization": f"Bearer {key()}", "Content-Type": "application/json",
                                        "X-Title": "jev-skill"})
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read())


def call(state, questions, tries=5):
    last = None
    for i in range(tries):
        t = time.perf_counter()
        try:
            out = _req(URL, {"model": MODEL, "state": state, "questions": questions})
            u = out.get("usage", {})
            return {"answers": out["answers"], "ms": round((time.perf_counter() - t) * 1000),
                    "cost": float(u.get("cost") or 0), "in_tok": u.get("input_tokens", 0)}
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}"
            if e.code == 402:
                STOP.set(); raise RuntimeError("OUT_OF_CREDIT " + last)
            if e.code not in RETRY:
                raise RuntimeError(last)
        except (urllib.error.URLError, TimeoutError) as e:
            last = repr(e)
        time.sleep(min(20, 0.5 * 2 ** i) + random.random() * 0.3)
    raise RuntimeError(f"gave up after {tries} tries: {last}")


def balance():
    d = _req("https://openrouter.ai/api/v1/credits")["data"]
    return float(d["total_credits"]) - float(d["total_usage"])


def batch(items_p, q_p, out_p, workers=8, max_usd=0.50, floor=5.0):
    q = json.loads(Path(q_p).read_text(encoding="utf-8"))
    items = [json.loads(l) for l in Path(items_p).read_text(encoding="utf-8").splitlines() if l.strip()]
    out = Path(out_p); done = set()
    if out.exists():
        done = {json.loads(l)["id"] for l in out.read_text(encoding="utf-8").splitlines()
                if l.strip() and "error" not in json.loads(l)}
    todo = [it for it in items if it["id"] not in done]
    if todo and floor > 0:
        b = balance()
        if b < floor:
            sys.exit(f"LOW_BALANCE: ${b:.2f} < floor ${floor:.2f}; not starting")
    spent = [0.0]; lock = threading.Lock(); t0 = time.perf_counter()

    def one(it):
        if STOP.is_set():
            return {"id": it["id"], "error": "skipped: stop"}
        try:
            r = call({k: v for k, v in it.items() if k != "id"}, q); r["id"] = it["id"]
            with lock:
                spent[0] += r["cost"]
                if spent[0] >= max_usd:
                    STOP.set()
            return r
        except Exception as e:
            return {"id": it["id"], "error": str(e)[:300]}

    ok = err = 0
    with out.open("a", encoding="utf-8") as f, ThreadPoolExecutor(workers) as ex:
        for fut in as_completed([ex.submit(one, it) for it in todo]):
            r = fut.result(); f.write(json.dumps(r) + "\n"); f.flush()
            ok, err = (ok + 1, err) if "error" not in r else (ok, err + 1)
    print(json.dumps({"cached": len(done), "ran_ok": ok, "errors": err, "spent_usd": round(spent[0], 6),
                      "wall_s": round(time.perf_counter() - t0, 2), "cap_hit": STOP.is_set()}))


TIERS = {"tiny": "a lookup, a rename, a one-line answer, a format tweak",
         "everyday": "a normal email, post, short document or small code edit",
         "large": "a multi-step build, research, a full report, a multi-file code change",
         "hardest": "strategy, architecture, or anything where a wrong call is expensive"}
MODEL_FOR = {"tiny": "haiku", "everyday": "sonnet", "large": "opus", "hardest": "fable"}
EFFORTS = {"low": "simple work where speed and cost matter most, like subagent chores",
           "medium": "normal agentic work balancing speed, cost and quality",
           "high": "complex reasoning, hard debugging, difficult coding",
           "xhigh": "long-running agentic or coding work expected to take over 30 minutes"}
LOG = Path.home() / ".jev" / "router_log.jsonl"


def route(msg, gate=0.6):
    qs = {"tier": {"type": "choice", "instructions": "What is the smallest AI model size that can do the job in `message` well?",
                   "criteria": TIERS},
          "effort": {"type": "choice", "instructions": "How hard should the model think before answering `message`?",
                     "criteria": EFFORTS},
          "followup": {"type": "noul", "instructions": "Is `message` a short reply that only makes sense inside an "
                       "ongoing conversation, like 'yes do that but make it shorter'?"}}
    r = call({"message": msg[:2000]}, qs); x = r["answers"]
    t, e = x["tier"], x["effort"]
    inline = x["followup"]["noul"] >= 0.5 or t["confidence"] < gate
    out = {"tier": t["choice"], "tier_conf": round(t["confidence"], 2), "model": MODEL_FOR[t["choice"]],
           "effort": e["choice"], "effort_conf": round(e["confidence"], 2),
           "followup": round(x["followup"]["noul"], 2), "handle_inline": inline, "ms": r["ms"], "cost": r["cost"]}
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": int(time.time()), **out}) + "\n")
    return out


def pick_skill(msg, skills, gate=0.6):
    """skills: {name: first line of description}. Returns best skill or None (Claude picks) under the gate."""
    crit = {**{k: v[:200] for k, v in skills.items()}, "none": "no listed skill fits this request"}
    r = call({"request": msg[:2000]}, {"skill": {"type": "choice", "instructions":
             "Which skill should be loaded to handle `request`?", "criteria": crit}})
    s = r["answers"]["skill"]
    return {"skill": s["choice"] if s["confidence"] >= gate and s["choice"] != "none" else None,
            "jev_pick": s["choice"], "conf": round(s["confidence"], 2), "ms": r["ms"], "cost": r["cost"]}


def status():
    rows = [json.loads(l) for l in LOG.read_text().splitlines()] if LOG.exists() else []
    c = {}
    for r in rows:
        k = "inline" if r["handle_inline"] else r["model"]; c[k] = c.get(k, 0) + 1
    print(json.dumps({"routed": len(rows), "by_target": c,
                      "jev_cost_usd": round(sum(r["cost"] for r in rows), 6)}))


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__); sys.exit(0)
    opt = lambda n, d: type(d)(a[a.index(n) + 1]) if n in a else d
    if a[0] == "test":
        email = ("Hi, we run an online skincare store and want an AI agent to answer our order emails. "
                 "Budget is signed off and we want to start next month. Can we book a call this week?")
        qs = {"lead": {"type": "score", "instructions": "How strong a sales lead is `email`?",
                       "criteria": ["not a lead", "cold: vague interest", "warm: real need, no budget or timeline",
                                    "hot: clear need plus budget or timeline or decision maker"]},
              "kind": {"type": "choice", "instructions": "What kind of email is `email`?",
                       "criteria": {"new lead": None, "existing client": None, "vendor pitch": None,
                                    "spam": None, "job seeker": None, "support": None}},
              "reply": {"type": "noul", "instructions": "Does `email` need a personal reply from the team today?"}}
        print(json.dumps(call({"email": email}, qs), indent=2))
    elif a[0] == "ask":
        s, q = (json.loads(Path(p).read_text(encoding="utf-8")) for p in a[1:3])
        print(json.dumps(call(s, q), indent=2))
    elif a[0] == "batch":
        batch(a[1], a[2], a[3], opt("--workers", 8), opt("--max-usd", 0.50), opt("--floor", 5.0))
    elif a[0] == "route":
        print(json.dumps(route(" ".join(a[1:]) if a[1:] else sys.stdin.read())))
    elif a[0] == "pick-skill":
        print(json.dumps(pick_skill(" ".join(a[2:]), json.loads(Path(a[1]).read_text(encoding="utf-8")))))
    elif a[0] == "status":
        status()
    elif a[0] == "balance":
        print(f"${balance():.2f}")
    else:
        sys.exit(__doc__)
