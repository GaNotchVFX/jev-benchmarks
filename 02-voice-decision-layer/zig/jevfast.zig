//! jevfast — a Zig hot-path client for Jev decisions.
//!
//! Reads `turns.jsonl`, POSTs each line verbatim to the Jev decisions
//! endpoint over a single keep-alive TLS connection, times each request
//! with the monotonic ("awake") clock, and writes per-request latencies to
//! `zig_latency.jsonl`. Prints a summary with percentiles at the end.
//!
//! Build: zig build-exe -O ReleaseFast jevfast.zig

const std = @import("std");
const Io = std.Io;
const http = std.http;
const Uri = std.Uri;

const endpoint_url = "https://openrouter.ai/api/alpha/decisions";

pub fn main(init: std.process.Init) !void {
    const gpa = init.gpa;
    const io = init.io;
    const arena = init.arena.allocator();
    const stdout_file = Io.File.stdout();
    var stdout_buf: [4096]u8 = undefined;
    var stdout_writer = stdout_file.writer(io, &stdout_buf);
    const out = &stdout_writer.interface;

    // 1. API key from env. Never printed or logged.
    const api_key = init.environ_map.get("OPENROUTER_API_KEY") orelse {
        std.log.err("OPENROUTER_API_KEY is not set", .{});
        std.process.exit(1);
    };
    const auth_header_value = try std.fmt.allocPrint(arena, "Bearer {s}", .{api_key});

    // 4. Optional arg 1 = max number of requests.
    const args = try init.minimal.args.toSlice(arena);
    var max_requests: ?usize = null;
    if (args.len > 1) {
        max_requests = std.fmt.parseInt(usize, args[1], 10) catch |err| {
            std.log.err("invalid max-requests argument {s}: {t}", .{ args[1], err });
            std.process.exit(1);
        };
    }

    // 2. Read turns.jsonl verbatim, one JSON body per line.
    const turns_bytes = try Io.Dir.cwd().readFileAlloc(io, "turns.jsonl", gpa, .limited(64 * 1024 * 1024));
    defer gpa.free(turns_bytes);

    var lines: std.ArrayList([]const u8) = .empty;
    defer lines.deinit(gpa);
    {
        var it = std.mem.splitScalar(u8, turns_bytes, '\n');
        while (it.next()) |raw_line| {
            const line = std.mem.trimEnd(u8, raw_line, "\r");
            if (line.len == 0) continue;
            try lines.append(gpa, line);
            if (max_requests) |m| if (lines.items.len >= m) break;
        }
    }

    // 3. One std.http.Client (keep-alive, TLS) reused for every request.
    var client: http.Client = .{ .allocator = gpa, .io = io };
    defer client.deinit();

    const uri = try Uri.parse(endpoint_url);

    // Pre-allocated buffers reused every iteration: the task requires no
    // allocations inside the timed section (this is a voice pipeline's hot
    // path sitting next to the audio thread — allocator jitter/GC pauses
    // are exactly the kind of latency spike the whole point is to avoid).
    // The response body is read into a fixed-size scratch buffer via a
    // discarding writer, so we count bytes without allocating or retaining
    // the body.
    var redirect_buffer: [8 * 1024]u8 = undefined;
    var transfer_buffer: [8 * 1024]u8 = undefined;
    var discard_sink_buffer: [8 * 1024]u8 = undefined;

    var latencies_file = try Io.Dir.cwd().createFile(io, "zig_latency.jsonl", .{});
    defer latencies_file.close(io);
    var latencies_file_buf: [8192]u8 = undefined;
    var latencies_writer = latencies_file.writer(io, &latencies_file_buf);
    const lw = &latencies_writer.interface;

    var ms_samples: std.ArrayList(f64) = .empty;
    defer ms_samples.deinit(gpa);
    try ms_samples.ensureTotalCapacity(gpa, lines.items.len);

    var non_200_count: usize = 0;
    var cold_ms: f64 = 0;

    for (lines.items, 0..) |body, i| {
        const start = Io.Clock.Timestamp.now(io, .awake);

        var req = try client.request(.POST, uri, .{
            .keep_alive = true,
            .extra_headers = &.{
                .{ .name = "Authorization", .value = auth_header_value },
            },
            .headers = .{
                .content_type = .{ .override = "application/json" },
            },
        });
        defer req.deinit();

        req.transfer_encoding = .{ .content_length = body.len };
        var body_writer = try req.sendBodyUnflushed(&.{});
        try body_writer.writer.writeAll(body);
        try body_writer.end();
        try req.connection.?.flush();

        var response = try req.receiveHead(&redirect_buffer);

        var discard_sink: std.Io.Writer.Discarding = .init(&discard_sink_buffer);
        const body_reader = response.reader(&transfer_buffer);
        const bytes_read = body_reader.streamRemaining(&discard_sink.writer) catch |err| switch (err) {
            error.ReadFailed => return response.bodyErr().?,
            else => |e| return e,
        };

        const end = Io.Clock.Timestamp.now(io, .awake);
        const elapsed_ns = start.durationTo(end).raw.toNanoseconds();
        const ms: f64 = @as(f64, @floatFromInt(elapsed_ns)) / 1_000_000.0;

        const status_code: u16 = @intFromEnum(response.head.status);
        if (status_code != 200) non_200_count += 1;

        // 5. Write one line per request to zig_latency.jsonl.
        try lw.print(
            "{{\"i\":{d},\"status\":{d},\"ms\":{d:.1},\"bytes\":{d}}}\n",
            .{ i, status_code, ms, bytes_read },
        );

        // 6. First request includes TLS handshake: report separately, excluded from percentiles.
        if (i == 0) {
            cold_ms = ms;
        } else {
            ms_samples.appendAssumeCapacity(ms);
        }
    }
    try lw.flush();

    std.mem.sort(f64, ms_samples.items, {}, std.sort.asc(f64));

    try out.print("count: {d}\n", .{lines.items.len});
    try out.print("non_200: {d}\n", .{non_200_count});
    try out.print("cold_ms: {d:.1}\n", .{cold_ms});
    if (ms_samples.items.len > 0) {
        try out.print("min: {d:.1}\n", .{percentile(ms_samples.items, 0.0)});
        try out.print("p50: {d:.1}\n", .{percentile(ms_samples.items, 0.50)});
        try out.print("p90: {d:.1}\n", .{percentile(ms_samples.items, 0.90)});
        try out.print("p95: {d:.1}\n", .{percentile(ms_samples.items, 0.95)});
        try out.print("p99: {d:.1}\n", .{percentile(ms_samples.items, 0.99)});
        try out.print("max: {d:.1}\n", .{percentile(ms_samples.items, 1.0)});
    } else {
        try out.print("min: n/a\np50: n/a\np90: n/a\np95: n/a\np99: n/a\nmax: n/a\n", .{});
    }
    try out.flush();
}

/// Nearest-rank percentile over an ascending-sorted slice. `p` in [0, 1].
fn percentile(sorted_ascending: []const f64, p: f64) f64 {
    if (sorted_ascending.len == 1) return sorted_ascending[0];
    const last_index: f64 = @floatFromInt(sorted_ascending.len - 1);
    const rank = p * last_index;
    const idx: usize = @intFromFloat(@round(rank));
    return sorted_ascending[idx];
}
