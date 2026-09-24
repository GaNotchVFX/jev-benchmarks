---
name: jev-router
description: Jev picks the cheapest model + effort (or skill) for a task; delegates only when it saves money. Use on "jev route", "jev on/off/status", "jev pick skill", "jev test router", "calibrate effort".
---

# Jev router

Run `jev.py` per the `jev-sort` skill's "Where to run" section (same key, privacy and client rules). A route call costs ~$0.00002 and ~0.3 s. Routed text leaves the machine: never route private work.

## Delegation rule (the whole point: net savings)
**Only ever route to subagents, never switch the main chat's model.** jcm-router measured routing the main chat as a net *loss* ($106.73 vs an $87.19 baseline): every switch throws away the cached prefix and rewrites it at cache-write price. Subagents start cold, so picking their model is close to free.

`python jev.py route "<task>" [--prev last_reply.txt]` → `tier`, `model`, `effort`, `handle_inline`. The script already applies jcm-router's gates: it acts on a model pick only at confidence ≥ 0.7, falls back to medium effort under 0.7, and treats follow-ups ≥ 0.55 as inline. Then:
1. `handle_inline` true (conf < 0.7 or short follow-up) → do it here.
2. Mapped model is **not cheaper** than the model running now → do it here. Never upsize automatically; if Jev says `hardest` and a bigger model exists, suggest it in one line and continue.
3. Cheaper **and** token-heavy (lots to read or write, many steps, bulk/mechanical) → delegate via the Agent tool `model` param (Claude Code: pinned agent files `jev-haiku|sonnet|opus|fable.md`, built on request).
4. Cheaper but small (a few hundred tokens of work) → do it here. The brief plus the helper's own startup costs more than it saves.

Brief for a helper is self-contained (it can't see this chat): goal, exact files/paths, constraints, output format, "end with `done by <model>`". Pass the result back; don't redo it.

Tiers → model: tiny→haiku · everyday→sonnet · large→opus · hardest→fable (fewer models → collapse upward).

## Effort
Can't be set per helper; report Jev's pick, Brandon switches. Opus 5.5 default = medium (matches/beats Opus 5 at high); step up one level only when a result falls short. Never auto-pick max; xhigh only as a suggestion (Anthropic: reserve for measured gains). API: switch per message with `{"role":"system","content":[],"output_config":{"effort":"low"}}` + beta header `mid-conversation-output-config-2026-07-01`; changing top-level effort wipes the prompt cache.

## Modes
- **`jev route <task>`** — one route, apply the rule, one-line verdict (tier → model, effort, conf, delegated or inline, cost).
- **`jev on` / `off` / `status`** — OFF by default. While ON, route each substantive message; skip slash commands and replies under ~12 words. Any Jev error/slowness/missing key → carry on silently. On `jev on`, one-line privacy reminder. `status` → ON/OFF + `python jev.py status`. Claude Code only: optional `UserPromptSubmit` hook that prints the verdict as a note, exits 0 on any error or >1.5 s. It's still a note, not a model switch.
- **`jev pick skill <request>`** — write `{name: full description}` for available skills to a temp JSON, `python jev.py pick-skill skills.json "<request>"`. Two stages (TypeSafe's cookbook cut wrong skill loads from 16.8% to 7.3%): 3 "does this need a skill at all?" gates, then the top 3 rechecked on full text. `skill: null` → load nothing, or Claude picks if it clearly needs one. Live test: "Q3 numbers into an excel sheet with a chart" → xlsx at 0.95; "capital of France" → no skill.
- **`jev test router`** — 8 samples tiny→hardest + 2 follow-ups; table of tier, model, effort, conf, what the rule decided. Leave router OFF.
- **`calibrate effort`** — warn that it burns real usage, then: pick one real, frequent task Brandon can judge by eye (finishes in minutes; say which and why in 2 lines) → run it at every available effort, lowest→highest, same inputs, fresh context each, large `max_tokens` at high levels → HTML artifact, columns lowest-left, time + usage on top → pick the lowest level where quality stops improving. Can't switch effort here? Say so, show the closest working option.

Prices (21 Sept 2026, recheck before quoting): Jev $0.042/1M in, output free · Haiku 4.5 $1/$5 · Fable 5.1 $10/$50.
