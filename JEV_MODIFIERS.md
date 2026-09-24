# Jev Modifiers Archive

Every knob that changes what Jev (TypeSafe System One, `jev-latest` → jev-1.13.0) does or how well it does it.
Sources: docs.typesafe.ai (primitives, advanced structure, state, confidence, patterns, cookbooks, jaggedness page), community tools (jcm-router, limpet), and live runs on Brandon's machine, 24 Sept 2026.

---

## 1. Request-level modifiers

| Modifier | Values | Effect / rule |
|---|---|---|
| `model` | `jev-latest` (TypeSafe direct) · `typesafe/jev-1.13` (OpenRouter) | Direct API: `jev-latest` (currently `jev-1.13.0`) or pin `jev-1.13.0` for reproducible benchmarks; bare `jev-1.13` is rejected. |
| `state` | string · object · array | Object with named fields for anything with more than one part. Text only; English is most accurate. |
| `questions` | map of `id → question` | IDs are for your code only and never reach the model, so put the full question in `instructions`. |
| Batching | many questions, one state | State is billed once per request. 13 questions in one call was **12.2× cheaper** and 10× faster than 13 calls, with identical answers. |
| Speculative fan-out | ask "if X, then…" questions up front | Answers can't see each other. Ask branch questions in parallel and let code ignore the ones that don't apply. It saves a round trip. |
| Size | ≤ 64K tokens per request, ≤ 32K of state | Filter in code first. Big irrelevant state is a documented weak spot. |

## 2. `instructions` modifiers (all question types)

A plain string works for simple questions. Switch to an object when the judgment needs more precision:

```json
"instructions": {
  "question": "Does `extracted_value` match the field?",
  "field": {"name": "invoice_number", "type": "string", "description": "Supplier's invoice id", "unit": null},
  "inspect": "invoice.header",
  "compare": ["invoice.header", "extraction.invoice_number"],
  "focus": "Exact matches only; ignore PO numbers",
  "note": "Invoice numbers may contain dashes",
  "extracted_value": "INV-2291"
}
```

| Key | Use it to… |
|---|---|
| `question` | State the core judgment. |
| `focus` | Say what to prioritize or ignore. |
| `note` | Add caveats and edge-case context. |
| `inspect` | Point at the exact state field to examine. |
| `compare` | List the fields to judge against each other. |
| `field` | Describe the value being checked (name, type, description, unit). |
| `extracted_value` | Supply a candidate value to verify. |

**Backtick paths** reference state directly: `` `ticket.messages[0].text` ``. Jaggedness page: indirection hurts, so name the field.

## 3. Choice modifiers

```json
"criteria": {
  "billing":   {"what": "Charges, refunds, invoices", "not_for": "Plan upgrades (that's sales)", "examples": ["I was charged twice"]},
  "technical": "Bugs, outages, errors",
  "none":      "Nothing here fits"
}
```

| Modifier | Rule |
|---|---|
| Option count | Up to **255** options. `find` uses 250-line windows because of this cap. |
| One-line descriptions | Start here. |
| `what` / `not_for` / `examples` | Upgrade to these when two options get confused. Examples only help when they look like your real data. |
| `none` / `other` option | Add one whenever nothing may fit. Without it, Jev *must* pick something. |
| Nested taxonomy | `{"parent": {"child": ["leaf1","leaf2"]}}` for hierarchies (hierarchical-classification cookbook: beam search over probabilities). |
| `probabilities` | Returned for every option. Use it to rank (top-k), not just to read the winner. |
| `confidence` | How concentrated the distribution is. It is **not** "is the answer correct". Two acceptable answers can split it harmlessly. |

## 4. Score modifiers

```json
"criteria": [
  {"summary": "Cosmetic", "signals": ["typo", "misaligned icon"]},
  {"summary": "Degraded, workaround exists", "signals": ["slow", "retry works"]},
  {"summary": "Broken, no workaround", "signals": ["crash", "data loss"]}
]
```

| Modifier | Rule |
|---|---|
| Level count | **2–10**. Use as many as you can describe *distinctly*. Three is fine. |
| Describe situations, not degrees | Write "Broken feature, workaround exists", not "moderately severe". |
| One dimension per Score | Split "smart and experienced and punctual" into three Scores and combine them in code. |
| `summary` / `signals` or `what` / `examples` | Use when results sit ambiguously between levels. |
| Reading it | `score` is a probability-weighted mean (0-indexed, can be fractional). Different distributions can give the same score, so check `probabilities` and `confidence` too. |
| Math on scores | Don't treat a score as an exact magnitude. Use thresholds only. |

## 5. Noul modifiers

```json
{"type": "noul",
 "instructions": "Has the customer contacted support about this before?",
 "criteria": {"true":  {"what": "Mentions a prior attempt, ticket, or asking before"},
              "false": {"what": "No sign of any previous contact"}}}
```

| Modifier | Rule |
|---|---|
| One claim per Noul | No "angry *and* wants a refund". |
| Phrase so high = yes | Don't invert. P(yes) ≠ 1 − P(the negated question), so word each Noul the way you'll use it. |
| Absolute words | "any", "at all" remove middle ground ("any Python experience?"). |
| `true` / `false` criteria | Use when the boundary is subtle. |
| Multi-label | One Noul per label when several can apply at once. |
| Reading it | ≥ 0.8 yes, ≤ 0.2 no, in between → review. 0.5 means "can't tell", not "medium". |

## 6. State modifiers

- Use an **object with descriptive field names**, e.g. `{"ticket": …, "order": …, "refund_policy": …}`.
- Keep related records together when the judgment compares them.
- Add a one-line `business` field when context changes the answer (lead scoring).
- Keep `previous_reply` short (≤ 2K chars) for follow-up detection (jcm-router).
- Pass **computed facts** as fields (`code_checks: {amount_vs_usual: "+340%"}`) instead of asking Jev to do maths.
- Strip signatures, quoted threads and boilerplate before sending.

## 7. Threshold modifiers (the numbers)

| Where | Threshold | Source |
|---|---|---|
| Sorting piles, send to "check these" | Choice/Score conf < 0.6; Noul 0.4–0.6 | Jev + Claude guide |
| Model/effort routing | act ≥ 0.7; follow-up ≥ 0.55 → reuse/inline | jcm-router |
| Destructive or irreversible actions | ≥ 0.9, or a human in the loop | TypeSafe confidence page |
| Noul decisions | ≥ 0.8 yes, ≤ 0.2 no | Noul page |
| Pre-read filter | injection > 0.7 drop · conflict > 0.7 flag · relevance ≥ 0.45 · evidence > 0.55 | RAG-passage cookbook |
| Line find | exists ≥ 0.7 present · 0.35–0.69 partial · < 0.35 absent | Semantic-find cookbook |
| Extraction verify | any single field signal > 0.7 → escalate (max-gate, not average) | SDE cascade cookbook |
| Skill pick | need-a-skill gate ≥ 0.3 · fit ≥ 0.3 | Skill-suggestion cookbook |
| Rule gate / Stop hook | per-rule, start in shadow mode, calibrate | limpet |

Rule: a threshold is **not one number**. Scale it to the cost of being wrong, tune it on your own data, and don't reuse thresholds across question types.

## 8. Pattern modifiers (how to compose calls)

| Pattern | Shape |
|---|---|
| Confidence-gated routing | Answer = what; confidence = whether to act. |
| Intent routing | Choice picks the handler (code / specialist LLM / human). |
| Composite scoring | N atomic Scores, weights live in code, veto conditions are separate Nouls. |
| Cascade | Cheap model extracts → Jev verifies per field → escalate only flagged records. |
| Two-stage recheck | Wide Choice on short text → top-3 recheck on full text; free to reject all. |
| Select, don't generate | Regex/code finds candidates → Choice picks the right span → code normalizes it. |
| Count in code | One question per item, sum in code. Never ask "how many". |
| Self-consistency | Add an explicit "uncertain" outcome; route those to review while keeping raw values visible. |

## 9. Known blind spots → workarounds (jev-1.13)

| Weak at | Do instead |
|---|---|
| Counting | One question per item, add up in code. |
| Numbers / unit conversion | Convert in code, pass the number or a named bucket. |
| Date / time comparison | Jev extracts; code does the arithmetic. |
| Indirection | Direct wording, name the state field. |
| Large irrelevant state | Filter in code first. |
| Adversarial content | Explicit criteria, test before scale. |
| Contradictory instruction vs criteria | Treat criteria as an extension of the instruction and align them. |
| Generation | Turn it into a Choice over candidates, or give it to Claude. |
| Writing, chat, reasoning | Claude. Jev decides, Claude writes. |

## 10. Local client modifiers (`jev.py`)

| Env var / flag | Effect |
|---|---|
| `TYPESAFE_API_KEY` | Saved in Windows user env. Selects TypeSafe direct (default). |
| `OPENROUTER_API_KEY` | Fallback backend. |
| `JEV_BACKEND=typesafe\|openrouter` | Force a backend. |
| `JEV_MODEL=…` | Pin a model name. |
| `JEV_URL=…` | Point at a mock or proxy. |
| `--workers N` | Batch parallelism (default 8). |
| `--max-usd X` | Batch spend cap (default $0.50). On TypeSafe direct, spend is estimated from input tokens at $0.042/1M. |
| `--floor X` | Minimum OpenRouter balance to start (default $5). Skipped on TypeSafe direct because it has no balance endpoint; check console.typesafe.ai. |
| `--max-chunks N` | `filter` chunk cap (default 300). |
| `--top N` | `find` hits (default 5). |
| `--t X` / `--hook` | `check` threshold; exit code 2 on violation for hooks. |
| `--prev FILE` | `route` follow-up context. |

## 11. What to type (skills)

`jev test` · `use Jev to sort these` · `jev triage these tickets` · `jev check these invoices` · `jev filter <q> <folder>` · `jev find <q> <file>` · `jev verify` · `jev check` · `jev route <task>` · `jev on/off/status` · `jev pick skill <request>` · `jev test router` · `calibrate effort` · `settled` · `time matters` · `finish in N min` · `checklist mode` · `audit my prompts`
