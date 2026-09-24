---
name: lean-turns
description: Opus 5.5 cost/latency switches from Anthropic's guide. Use on "settled", "unsettle", "time matters", "finish in N min", "checklist mode", "audit my prompts".
---

# Lean turns

On-demand modes from Anthropic's Opus 5.5 prompting guide. Apply only the ones invoked; they stack.

**`settled`** — Once something has been answered, treat that answer as done. On later turns, focus thinking on what is being asked now, and don't go back over an earlier answer unless Brandon asks about it or points out a problem with it. Cuts follow-up thinking. Not for long analyses or agentic runs where a later step can expose an earlier mistake. `unsettle` ends it.

**`time matters`** — Adopt: "Time matters here: do not spend time that can be avoided, and the earlier a correct result is obtained, the better."
**`finish in N min`** — Pace to land inside N min. For helpers or a harness, append `elapsed <s>s / <budget>s` to messages. Both are advisory (keep a real timeout if it matters) and mean slightly less searching and verifying, so don't use them for high-stakes checks.

**`checklist mode`** — Checklist every part of the task (task tool or file) before starting; tick items as they finish; before ending a turn, continue on any open item or name its blocker. A progress update isn't done. Nudge when a run stops early: "Your task list still has open items: <items>. Continue with them. If one is blocked, say what is blocking it." Max 2–3 nudges per task.

**`audit my prompts`** — Opus 5.5 declines prompts that push it to write its internal reasoning into the reply (`reasoning_extraction`; server fallback won't retry them). Search CLAUDE.md/AGENTS.md, skills, agent files and system prompts for "show/explain your reasoning/thinking" instructions → list file:line + result-only rewrite. Change nothing until Brandon says yes. API visibility: `thinking.display: "summarized"`.

**Always (silent):** don't change top-level effort between API requests because it wipes the cache (use per-message effort; see `jev-router`). Opus 5.5 default effort is medium; step up one level only on a real shortfall. Keep stable prompt content first and volatile content last.
