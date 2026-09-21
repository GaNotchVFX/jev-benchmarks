# jevfast — notes

## Build

```
zig build-exe -O ReleaseFast jevfast.zig
```

Zero errors/warnings on Zig 0.16.0, Windows x64.

## Run

```
./jevfast.exe 5
```

```
count: 5
non_200: 0
cold_ms: 319.2
min: 156.5
p50: 167.6
p90: 809.4
p95: 809.4
p99: 809.4
max: 809.4
```

`zig_latency.jsonl`:

```
{"i":0,"status":200,"ms":319.2,"bytes":418}
{"i":1,"status":200,"ms":164.1,"bytes":425}
{"i":2,"status":200,"ms":809.4,"bytes":417}
{"i":3,"status":200,"ms":167.6,"bytes":433}
{"i":4,"status":200,"ms":156.5,"bytes":424}
```

The first request (`i:0`) is included in `zig_latency.jsonl` with its real
wall time, but it is excluded from the min/p50/p90/p95/p99/max computation
and reported separately as `cold_ms` because it pays for the TLS handshake
(`319.2ms` here vs. warm keep-alive requests, one of which (`i:2`) spiked to
`809.4ms` — likely a transient network/server hiccup rather than anything
client-side, since the surrounding requests stayed in the 150–170ms band).

## Surprises in the 0.16 `std.http` / `std.Io` API

- **No global implicit I/O.** Everything (`std.http.Client`, file ops, env,
  args) takes an explicit `Io` interface now. The entry point signature
  `pub fn main(init: std.process.Init) !void` hands you a ready-made
  `Io.Threaded` (`init.io`), a GPA (`init.gpa`), an arena (`init.arena`), a
  pre-parsed env map (`init.environ_map`), and args (`init.minimal.args`).
  No manual `std.Io.Threaded.init(...)` / `std.process.argsAlloc` /
  `std.process.getEnvMap` boilerplate is needed — just accept the richer
  `Init` struct instead of `void` and the start code builds it for you.

- **TLS cert loading is automatic and correct on Windows already.**
  `Client.request()` checks `client.now == null` and if so calls
  `Certificate.Bundle.rescan()`, which on Windows dispatches to
  `rescanWindows()` (scans the system cert store via the Windows crypto
  API). No manual cert bundle plumbing or `-lcrypt32`-style hacks needed;
  no reason to ever disable verification. First call pays the rescan cost,
  which is part of why request #0 is slower — plumbed as `cold_ms` here.

- **Sending a request body is three explicit steps**, not one call:
  `req.sendBodyUnflushed(&.{})` (returns an `http.BodyWriter`, buffer arg
  is for the writer's *own* internal buffering, `&.{}` is fine since we
  write the whole body in one `writeAll`) → `body_writer.writer.writeAll(body)`
  → `body_writer.end()` → `req.connection.?.flush()`. Setting
  `req.transfer_encoding = .{ .content_length = body.len }` beforehand is
  what makes `sendHead` emit the right `Content-Length` header.

- **Reading the response body without allocating** means routing
  `response.reader(&transfer_buffer)` through a `std.Io.Writer.Discarding`
  sink and calling `.streamRemaining()`. `Discarding.fullCount()` (or the
  return value of `streamRemaining`) gives the byte count for the
  `"bytes"` field without ever materializing the body in memory.

- **Headers API is a mix of structured overridable fields
  (`Request.Headers`, e.g. `content_type`) and a flat `extra_headers:
  []const http.Header` list** for anything not in that struct (like
  `Authorization`). Both are consulted at `sendHead` time; the struct
  fields have library-chosen defaults (e.g. auto `user-agent`,
  `accept-encoding`) that `extra_headers` doesn't get.

- **Monotonic timing** goes through `Io.Clock.Timestamp.now(io, .awake)` and
  `.durationTo()` — `std.time.Timer` from older Zig doesn't exist in this
  `Io`-based world; the clock itself is threaded through the same `Io`
  abstraction as every other syscall.

## No-allocation hot loop

Per the task, the timed section (from just before `client.request()` to
just after the last body byte is read) makes zero heap allocations:
`redirect_buffer`, `transfer_buffer`, and `discard_sink_buffer` are
fixed-size stack arrays declared once outside the loop and reused every
iteration; the response body is discarded through
`std.Io.Writer.Discarding` rather than collected into a growing buffer.
This matters because in a real voice pipeline this loop runs on a thread
adjacent to the audio callback thread — any allocator syscall (`mmap`/
`VirtualAlloc`) or GC-style pause becomes an audible glitch, so the
allocator is kept completely out of the request/response path.
