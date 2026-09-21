# Task: jevfast — a Zig hot-path client for Jev decisions

Work ONLY inside this directory (`02-voice-decision-layer/zig`). Do not touch anything outside it.
Zig version installed: 0.16.0 (`zig version`). The std lib source is on disk next to zig.exe — READ IT
(`lib/std/http/Client.zig`, `lib/std/Io*.zig`, `lib/std/process*.zig`) instead of guessing APIs. 0.15/0.16 changed
std.http, std.Io readers/writers and process/env APIs a lot; code from older Zig versions will not compile.

## What to build
`jevfast.zig` -> `jevfast.exe`, built with: `zig build-exe -O ReleaseFast jevfast.zig`

Behaviour:
1. Read the API key from env var `OPENROUTER_API_KEY`. NEVER print or log it.
2. Read `turns.jsonl` (in this dir). Each line is a complete JSON request body. Do not parse or modify it.
3. Open ONE std.http.Client (keep-alive, TLS) and for each line, sequentially:
   `POST https://openrouter.ai/api/alpha/decisions`
   headers: `Authorization: Bearer <key>`, `Content-Type: application/json`
   body: the line, verbatim. Read the full response body.
   Time each request with a monotonic clock from just before sending to after the last body byte is read.
4. Optional arg 1 = max number of requests (default: all lines). Use `5` while testing to keep spend tiny.
5. Write `zig_latency.jsonl`, one line per request: `{"i":0,"status":200,"ms":142.3,"bytes":612}`
6. At the end print: count, non-200 count, min / p50 / p90 / p95 / p99 / max in ms.
   The FIRST request includes the TLS handshake - report it separately as `cold_ms` and exclude it from percentiles.
7. No third-party dependencies. No allocations inside the timed section if reasonably avoidable
   (pre-allocate the response buffer, reuse it). Add a short comment explaining that choice:
   in a voice pipeline this loop sits next to the audio thread, so no GC pauses / no allocator jitter is the point.

## Done means
- `zig build-exe -O ReleaseFast jevfast.zig` succeeds with zero errors on Zig 0.16.0 on Windows.
- `./jevfast.exe 5` runs, gets HTTP 200s, writes zig_latency.jsonl, prints the summary.
- Write `NOTES.md`: exact build command, anything surprising about the 0.16 std.http API, and the numbers from your `5`-request test.
- If TLS/cert loading fails on Windows, fix it properly (e.g. rescan system cert bundle) - do NOT disable verification.
