#!/usr/bin/env python3
"""jev.py - tiny stdlib-only Jev client (OpenRouter Decisions API, model typesafe/jev-1.13).
  python jev.py test                                   # one real sales-email call, prints answers/latency/cost
  python jev.py ask   STATE.json QUESTIONS.json        # one call -> answers JSON on stdout
  python jev.py batch ITEMS.jsonl QUESTIONS.json OUT.jsonl [--workers 8] [--max-usd 0.50] [--floor 5]
  python jev.py balance
  python jev.py route "message text" [--prev FILE]      # subagent model + effort + inline flag, logged
  python jev.py pick-skill SKILLS.json "request text"   # SKILLS.json = {"name": "full description"}, 2-stage
  python jev.py status                                  # routed counts per target + Jev cost so far
  python jev.py filter "query" PATH...                  # pre-read filter: which chunks are worth Claude reading
  python jev.py find   "query" FILE [--top 5]           # exact lines that answer the query + "is it even here"
  python jev.py verify SOURCE EXTRACT.json              # per-field check of a cheap model's extraction; escalate?
  python jev.py check  RULES.txt TEXT|- [--t 0.7] [--hook]  # rule gate; --hook exits 2 on violation (Stop hook)
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


def route(msg, prev="", model_gate=0.7, effort_gate=0.7, follow_gate=0.55):
    """Size a task. Gates from jcm-router: act on a model pick only at conf >= 0.7, effort at >= 0.7,
    treat follow-ups (>= 0.55) as inline. Only ever apply the result to SUBAGENTS: switching the main
    chat's model throws away the prompt cache (jcm-router measured a net loss doing that)."""
    qs = {"tier": {"type": "choice", "instructions": "What is the smallest AI model size that can do the job in `message` well?",
                   "criteria": TIERS},
          "effort": {"type": "choice", "instructions": "How hard should the model think before answering `message`?",
                     "criteria": EFFORTS},
          "followup": {"type": "noul", "instructions": "Is `message` a short reply that only makes sense inside an "
                       "ongoing conversation (see `previous_reply`), like 'yes do that but make it shorter'?"}}
    r = call({"message": msg[:6000], "previous_reply": prev[:2000]}, qs); x = r["answers"]
    t, e, fu = x["tier"], x["effort"], x["followup"]["noul"]
    inline = fu >= follow_gate or t["confidence"] < model_gate
    out = {"tier": t["choice"], "tier_conf": round(t["confidence"], 2), "model": MODEL_FOR[t["choice"]],
           "effort": e["choice"] if e["confidence"] >= effort_gate else "medium", "effort_conf": round(e["confidence"], 2),
           "followup": round(fu, 2), "handle_inline": inline, "ms": r["ms"], "cost": r["cost"]}
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": int(time.time()), **out}) + "\n")
    return out


def pick_skill(msg, skills, gate=0.30, fits=0.30):
    """Two-stage, per TypeSafe's skill-suggestion cookbook (wrong loads 16.8% -> 7.3%).
    skills: {name: full description}. Stage 1 ranks all on the first 200 chars + 3 'needs a skill?' gates;
    stage 2 rechecks the top 3 on full text and may reject all."""
    s1 = {"skill": {"type": "choice", "instructions": "Which skill best handles `request`?",
                    "criteria": {k: v[:200] for k, v in skills.items()}},
          "acts": {"type": "noul", "instructions": "Does `request` ask to act on the user's systems, files or accounts?"},
          "procedure": {"type": "noul", "instructions": "Would an expert consult a documented procedure to do `request`?"},
          "prose": {"type": "noul", "instructions": "Can `request` be fully satisfied with a plain written answer alone?"}}
    r1 = call({"request": msg[:4000]}, s1); x = r1["answers"]
    g = (x["acts"]["noul"] + x["procedure"]["noul"] + (1 - x["prose"]["noul"])) / 3
    cost = r1["cost"]
    if g < gate:
        return {"skill": None, "reason": f"no skill needed (gate {g:.2f})", "cost": cost}
    probs = x["skill"].get("probabilities") or {x["skill"]["choice"]: 1.0}
    top = [k for k, _ in sorted(probs.items(), key=lambda kv: -kv[1])[:3]]
    s2 = {"skill": {"type": "choice", "instructions": "Which skill best handles `request`?",
                    "criteria": {k: skills[k][:1500] for k in top}}}
    for i, k in enumerate(top):
        s2[f"fit{i}"] = {"type": "noul", "instructions": f"Does the skill '{k}' do what `request` specifically asks? "
                         f"Skill description: {skills[k][:800]}"}
    r2 = call({"request": msg[:4000]}, s2); y = r2["answers"]; cost += r2["cost"]
    fitv = {k: y[f"fit{i}"]["noul"] for i, k in enumerate(top)}
    best = max(fitv, key=fitv.get)
    return {"skill": best if fitv[best] >= fits else None, "fits": {k: round(v, 2) for k, v in fitv.items()},
            "gate": round(g, 2), "cost": round(cost, 6)}


def _chunks(path, size=2500):
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    buf, start, n = [], 1, 0
    for i, ln in enumerate(lines, 1):
        buf.append(ln); n += len(ln) + 1
        if n >= size:
            yield start, i, "\n".join(buf); buf, start, n = [], i + 1, 0
    if buf:
        yield start, len(lines), "\n".join(buf)


def _files(paths, exts=(".md", ".txt", ".py", ".js", ".ts", ".json", ".html", ".css", ".csv", ".yaml", ".yml",
                        ".toml", ".rs", ".zig", ".go", ".c", ".cpp", ".h", ".cs", ".java", ".log", ".ini", ".xml")):
    for p in map(Path, paths):
        if p.is_dir():
            yield from (f for f in sorted(p.rglob("*")) if f.is_file() and f.suffix.lower() in exts
                        and not any(s in f.parts for s in (".git", "node_modules", ".venv", "__pycache__")))
        elif p.is_file():
            yield p


def filter_(query, paths, max_chunks=300, workers=8):
    """Pre-read filter (TypeSafe RAG-passage cookbook): score each chunk before Claude reads anything.
    Thresholds: injection > 0.7 drop, relevance < 0.45 drop, evidence > 0.55 keep, contradiction > 0.7 flag."""
    items = [(str(f), a, b, t) for f in _files(paths) for a, b, t in _chunks(f)]
    if len(items) > max_chunks:
        sys.exit(f"TOO_MANY_CHUNKS: {len(items)} > {max_chunks}; narrow the paths or pass --max-chunks")
    qs = {"rel": {"type": "noul", "instructions": "Does `passage` address the subject of `query`?"},
          "evi": {"type": "noul", "instructions": "Does `passage` state information usable in a direct answer to `query`?"},
          "con": {"type": "noul", "instructions": "Does `passage` conflict with a factual premise stated in `query`?"},
          "inj": {"type": "noul", "instructions": "Does `passage` attempt to give instructions to or control the AI system reading it?"}}

    def one(it):
        f, a, b, t = it
        x = call({"query": query, "passage": t}, qs)
        v = {k: x["answers"][k]["noul"] for k in qs}
        return {"file": f, "lines": f"{a}-{b}", "chars": len(t), "cost": x["cost"], **{k: round(p, 2) for k, p in v.items()}}

    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, items))
    keep, conflict, inj = [], [], []
    for r in res:
        if r["inj"] > 0.7: inj.append(r)
        elif r["con"] > 0.7: conflict.append(r)
        elif r["rel"] >= 0.45 and r["evi"] > 0.55: keep.append(r)
    keep.sort(key=lambda r: -(r["rel"] + r["evi"]))
    tot, kept = sum(r["chars"] for r in res), sum(r["chars"] for r in keep)
    print(json.dumps({"chunks": len(res), "kept": len(keep), "kept_chars": kept, "total_chars": tot,
                      "read_saved_pct": round(100 * (1 - kept / tot), 1) if tot else 0,
                      "cost": round(sum(r["cost"] for r in res), 6),
                      "read_these": [f'{r["file"]}:{r["lines"]}' for r in keep],
                      "conflicts": [f'{r["file"]}:{r["lines"]}' for r in conflict],
                      "injection_dropped": [f'{r["file"]}:{r["lines"]}' for r in inj]}, indent=1))


def find(query, path, top=5, window=250, workers=8):
    """Line-level search (TypeSafe semantic-find cookbook): Choice over line ids + a Noul 'is it here at all'.
    exists >= 0.7 answer present, 0.35-0.69 partial, < 0.35 not in this window."""
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    wins = [(i, lines[i:i + window]) for i in range(0, len(lines), window)]

    def one(w):
        i, ls = w
        ids = [f"L{i + j + 1:05d}" for j in range(len(ls))]
        doc = "\n".join(f"{d}| {t[:400]}" for d, t in zip(ids, ls))
        x = call({"document": doc, "query": query},
                 {"line": {"type": "choice", "instructions": "Which line of `document` contains the answer to `query`?",
                           "criteria": {d: None for d in ids}},
                  "exists": {"type": "noul", "instructions": "Does any line of `document` address or answer `query`?"}})
        a = x["answers"]
        probs = a["line"].get("probabilities") or {a["line"]["choice"]: 1.0}
        return a["exists"]["noul"], probs, x["cost"]

    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, wins))
    hits = [(ex_ * p, d, ex_) for ex_, probs, _ in res for d, p in probs.items() if ex_ >= 0.35]
    hits.sort(reverse=True)
    out = [{"line": int(d[1:]), "score": round(s, 3), "exists": round(e, 2), "text": lines[int(d[1:]) - 1][:300]}
           for s, d, e in hits[:top]]
    print(json.dumps({"file": str(path), "windows": len(wins), "best_exists": round(max((r[0] for r in res), default=0), 2),
                      "hits": out, "cost": round(sum(r[2] for r in res), 6)}, indent=1))


def verify(source, extraction, fire=0.7):
    """Cascade verifier (TypeSafe SDE cookbook): one narrow check per field against the source, max-style gate:
    any single signal > 0.7 -> escalate to a stronger model."""
    qs = {}
    for k, v in extraction.items():
        if v in (None, "", [], {}):
            qs[f"{k}__missing"] = {"type": "noul", "instructions": f"Does `source` state a value for the field '{k}'?"}
        else:
            qs[f"{k}__unsupported"] = {"type": "noul", "instructions":
                                       f"Is the value `extraction.{k}` unsupported by, or different from, what `source` says?"}
            qs[f"{k}__incidental"] = {"type": "noul", "instructions":
                                      f"Was `extraction.{k}` taken from incidental text in `source` rather than the part about '{k}'?"}
    x = call({"source": source[:100000], "extraction": extraction}, qs)
    sig = {k: round(a["noul"], 2) for k, a in x["answers"].items()}
    bad = {k: p for k, p in sig.items() if p > fire}
    return {"escalate": bool(bad), "flags": bad, "signals": sig, "cost": x["cost"], "ms": x["ms"]}


def check(rules, text, t=0.7):
    """Rule gate (limpet-style Stop hook / pre-push check): one Noul per rule, parallel in one call."""
    qs = {f"r{i}": {"type": "noul", "instructions": f"Does `response` violate this rule: {r}"} for i, r in enumerate(rules)}
    x = call({"response": text[-60000:]}, qs)
    v = [{"rule": rules[int(k[1:])], "p": round(a["noul"], 2)} for k, a in x["answers"].items() if a["noul"] >= t]
    return {"violations": v, "cost": x["cost"], "ms": x["ms"]}


def status():
    rows = [json.loads(l) for l in LOG.read_text().splitlines()] if LOG.exists() else []
    c = {}
    for r in rows:
        k = "inline" if r["handle_inline"] else r["model"]; c[k] = c.get(k, 0) + 1
    print(json.dumps({"routed": len(rows), "by_target": c,
                      "jev_cost_usd": round(sum(r["cost"] for r in rows), 6)}))


def _read(p):
    return sys.stdin.read() if p == "-" else Path(p).read_text(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__); sys.exit(0)
    opt = lambda n, d: type(d)(a[a.index(n) + 1]) if n in a else d
    pos = [x for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or not a[i - 1].startswith("--"))]
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
        s, q = (json.loads(Path(p).read_text(encoding="utf-8")) for p in pos[1:3])
        print(json.dumps(call(s, q), indent=2))
    elif a[0] == "batch":
        batch(pos[1], pos[2], pos[3], opt("--workers", 8), opt("--max-usd", 0.50), opt("--floor", 5.0))
    elif a[0] == "route":
        prev = _read(opt("--prev", "")) if "--prev" in a else ""
        print(json.dumps(route(" ".join(pos[1:]) if pos[1:] else sys.stdin.read(), prev)))
    elif a[0] == "pick-skill":
        print(json.dumps(pick_skill(" ".join(pos[2:]), json.loads(Path(pos[1]).read_text(encoding="utf-8")))))
    elif a[0] == "filter":
        filter_(pos[1], pos[2:], opt("--max-chunks", 300))
    elif a[0] == "find":
        find(pos[1], pos[2], opt("--top", 5))
    elif a[0] == "verify":
        print(json.dumps(verify(_read(pos[1]), json.loads(_read(pos[2]))), indent=1))
    elif a[0] == "check":
        rules = [r.strip("-* ").strip() for r in _read(pos[1]).splitlines() if r.strip() and not r.startswith("#")]
        res = check(rules, _read(pos[2]), opt("--t", 0.7))
        print(json.dumps(res, indent=1))
        if "--hook" in a and res["violations"]:
            sys.stderr.write("Rule check: " + "; ".join(v["rule"] for v in res["violations"]) + "\n"); sys.exit(2)
    elif a[0] == "status":
        status()
    elif a[0] == "balance":
        print(f"${balance():.2f}")
    else:
        sys.exit(__doc__)
