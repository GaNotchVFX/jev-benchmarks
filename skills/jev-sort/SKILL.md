---
name: jev-sort
description: Sort, triage, score or flag a pile of text with Jev (typesafe/jev-1.13) so Claude only writes. Use on "use Jev to sort these", "jev leads/tickets/invoices", "jev test".
---

# Jev sort — Jev decides, Claude writes

Jev answers typed questions about a state in one parallel pass (~0.3 s, $0.042/1M input, output free). 100 emails: $0.0032 vs $0.061 Haiku 4.5 vs $0.76 Fable 5.1. Never pay a chat model to read what Jev can sort. New question designs → also load `typesafe-ai` and check https://docs.typesafe.ai/llms.txt.

## Rules
1. Jev never writes. Claude writes only for items that matter.
2. Choice/Score conf < 0.6, or Noul 0.4–0.6 → "check these"; Claude judges them.
3. Data leaves the machine (to TypeSafe's API). Ask before sending private/client data; a yes covers that pile only.
4. Jev is weak at writing, reasoning, counting, maths, dates, and noisy long input. Do sums, date checks, dedupe and lookups in code; strip signatures/quoted threads.
5. 32K tokens of state per request, text only, English best. One item = one request with all its questions.
6. Batches cap at $0.50 of estimated spend. Report cost, time and "check these" count after every run.

## Where to run
Client: `C:\Users\sauce\Documents\jev-benchmarks\common\jev.py` (stdlib only; also on GitHub GaNotchVFX/jev-benchmarks). Tools for filter, find, verify and check: see `jev-tools`. Question-writing reference (criteria structures, thresholds, blind spots): `JEV_MODIFIERS.md` in the same repo, so read the relevant section before designing new questions.
**Backend: TypeSafe direct**, `https://api.typesafe.ai/v1/systemone`, model `jev-latest` (pin `JEV_MODEL=jev-1.13.0` for benchmarks). Key `TYPESAFE_API_KEY` is saved in Windows user env and picked up automatically. OpenRouter (`typesafe/jev-1.13`) is a fallback only when no TypeSafe key exists or `JEV_BACKEND=openrouter`; its balance was -$0.01 on 24 Sept 2026. The direct API reports tokens, not dollars, so cost is estimated at $0.042/1M input and there's no balance check (console.typesafe.ai). Never print, echo or copy the key into files.
- **Claude Code on the laptop:** run it directly.
- **Cowork:** run it on Windows via Desktop Commander (`python ...\jev.py ...`, PowerShell). It reads the Windows key. The Linux device shell and cloud container have no key; don't use them unless Brandon puts one in `~/.config/jev/typesafe_key` there.

```
jev.py test | balance (shows backend + model) | status
jev.py ask   state.json questions.json
jev.py batch items.jsonl questions.json out.jsonl [--workers 8 --max-usd 0.50]
```
`items.jsonl`: one object per line with `id`; other fields = state. `out.jsonl` is checkpointed, so reruns never double-bill. Answers: choice `{choice, probabilities, confidence}` · score `{score (0-indexed), probabilities, confidence}` · noul `{noul}`.

## Procedure
Parse the pile to JSONL in code and trim it → questions (recipe or custom; add a one-line `business` field when it helps) → `test` if new setup → 5-item batch, eyeball → full batch → merge in code, sort, split out "check these" → Claude writes only what the recipe names.

## Recipes
**Leads** ("sort my inbox by lead quality") → sheet, hot on top; replies for hot only.
```json
{"lead":{"type":"score","instructions":"How strong a sales lead is `email` for `business`?","criteria":["not a lead: spam, vendors, newsletters, job seekers, support, existing clients","cold: vague interest, tiny budget, poor fit","warm: real need that fits, no budget or timeline yet","hot: clear fitting need plus two of: stated budget, stated timeline, decision maker writing"]},
 "kind":{"type":"choice","instructions":"What kind of email is `email`?","criteria":{"new lead":null,"existing client":null,"vendor pitch":null,"spam":null,"job seeker":null,"newsletter or support":null}},
 "reply":{"type":"noul","instructions":"Does `email` need a personal reply from the team?"}}
```
**Tickets** ("jev triage these tickets"; add `plan`, `tenure` if known) → table by urgency then churn; first replies for "today" only.
```json
{"urgency":{"type":"choice","instructions":"How soon does `ticket` need an answer?","criteria":{"today":null,"this week":null,"no rush":null}},
 "team":{"type":"choice","instructions":"Which team should handle `ticket`?","criteria":{"technical":"bugs, outages, errors","billing":"charges, refunds, invoices","sales":"upgrades, pricing","success":"onboarding, training"}},
 "churn":{"type":"score","instructions":"How likely is the customer in `ticket` to leave?","criteria":["no sign of leaving","mild frustration","openly looking at other options","has set a deadline to leave"]}}
```
**Invoices** ("jev check these invoices") → invoices to plain text; state = invoice + `supplier_history` (usual bank details, amounts, last date) + `code_checks` (amount/date comparisons done in code). Riskiest first, one line why. Nothing paid or rejected on Jev's word.
```json
{"risk":{"type":"score","instructions":"How risky does `invoice` look given `supplier_history` and `code_checks`?","criteria":["looks normal","one small oddity","several warning signs","strong signs of fraud"]},
 "bank_pressure":{"type":"noul","instructions":"Does `invoice` combine changed bank details with pressure to pay fast?"},
 "action":{"type":"choice","instructions":"What should happen to `invoice`?","criteria":{"pay as normal":null,"hold and phone the supplier on a number we already know":null,"reject":null}}}
```
