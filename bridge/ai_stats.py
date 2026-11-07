#!/usr/bin/env python3
"""Two Brains stats. Standard library only.

  ai-stats [DAYS]          what the local models did, from bridge/bridge.log
  ai-stats sessions [N]    real Claude token usage per recent session, from Claude Code's own logs

The bridge log holds metadata only, never prompt content. Session numbers are read from the
usage fields Claude Code stores in ~/.claude/projects, so they are exact, not estimated.
"""
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

LOG = Path(__file__).with_name("bridge.log")
PROJECTS = Path.home() / ".claude" / "projects"
CALL_TOOLS = {"local_summarize", "local_classify", "local_extract", "local_run", "local_digest_files"}


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "n/a"


# ------------------------------------------------------------------ bridge log stats

def load_log(days):
    rows, reports, skipped, tests = [], [], 0, 0
    if not LOG.exists():
        return rows, reports, skipped, tests
    cutoff = datetime.now() - timedelta(days=days) if days else None
    for line in LOG.read_text().splitlines():
        try:
            r = json.loads(line)
            ts = datetime.fromisoformat(r["ts"])
        except (ValueError, KeyError):
            skipped += 1
            continue
        if cutoff and ts < cutoff:
            continue
        r["_ts"] = ts
        tool = str(r.get("tool", ""))
        if tool == "local_report":
            reports.append(r)
        elif tool in CALL_TOOLS:
            rows.append(r)
        else:
            tests += 1  # manual test entries, not real delegation
    return rows, reports, skipped, tests


def log_stats(days):
    rows, reports, skipped, tests = load_log(days)
    scope = f"last {days} days" if days else "all time"
    print(f"Two Brains stats ({scope})")
    if not rows:
        print("  No delegated calls logged yet.")
        return
    ok = [r for r in rows if r.get("ok")]
    bad = [r for r in rows if not r.get("ok")]
    first, last = min(r["_ts"] for r in rows), max(r["_ts"] for r in rows)
    print(f"  Period                    {first:%Y-%m-%d} to {last:%Y-%m-%d}")
    print(f"  Delegated calls           {len(rows)}")
    print(f"  Succeeded                 {len(ok)}  ({pct(len(ok), len(rows))})")
    print(f"  Failed, Claude took over  {len(bad)}  ({pct(len(bad), len(rows))})")
    if ok:
        secs = [r.get("seconds", 0) for r in ok]
        print(f"  Time per successful call  avg {sum(secs) / len(secs):.1f}s, max {max(secs):.1f}s")

    file_rows = [r for r in ok if r.get("kind") == "file"]
    text_rows = [r for r in ok if r.get("kind") != "file"]
    kept = sum(max(0, r.get("in_tokens_est", 0) - r.get("out_tokens_est", 0)) for r in file_rows)
    files = sum(r.get("files", 0) for r in file_rows)
    drafted = sum(r.get("out_tokens_est", 0) for r in text_rows)
    print("\n  Token effect (estimates, about 4 characters per token)")
    print(f"    Kept out of Claude's context   {kept:,}   (local model read {files} files, Claude saw only the short result)")
    print(f"    Drafted locally (text tools)   {drafted:,}   (Claude read the text first, so only the writing is saved)")

    if reports:
        v = Counter(r.get("verdict") for r in reports)
        n = len(reports)
        print("\n  Review verdicts (what Claude decided after checking the draft)")
        print(f"    accepted {v['accepted']}  ({pct(v['accepted'], n)})   edited {v['edited']}  ({pct(v['edited'], n)})   "
              f"rejected {v['rejected']}  ({pct(v['rejected'], n)})")
    else:
        print("\n  Review verdicts: none recorded yet (Claude reports them after each delegated result).")

    print("\n  By model")
    for m, n in Counter(r.get("model", "?") for r in rows).most_common():
        good = sum(1 for r in rows if r.get("model") == m and r.get("ok"))
        print(f"    {m:<20} {n} calls, {good} ok")
    print("\n  By tool")
    for t, n in Counter(r.get("tool", "?") for r in rows).most_common():
        print(f"    {t:<22} {n}")
    if bad:
        print("\n  Failure reasons")
        for note, n in Counter(r.get("note") or "unknown" for r in bad).most_common():
            print(f"    {note:<22} {n}")
    print("\n  Notes")
    print("  - 'Kept out of context' is the honest saving. For text tools Claude had already read the input.")
    print("  - Compare real Claude usage per session with: ai-stats sessions")
    if tests:
        print(f"  - Ignored {tests} manual test entries.")
    if skipped:
        print(f"  - Skipped {skipped} unreadable log lines.")


# --------------------------------------------------------------- Claude session usage

def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                return b.get("text", "")
    return ""


def read_session(path):
    usage, local_calls, mode_model, first, started = {}, set(), "", "", ""
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not started and d.get("timestamp"):
            started = d["timestamp"]
        m = d.get("message") or {}
        if d.get("type") == "user" and not first:
            t = _text_of(m.get("content")).strip()
            if t and not t.startswith("<") and not t.startswith("Caveat"):
                first = " ".join(t.split())[:48]
        if d.get("type") == "assistant":
            u = m.get("usage")
            key = m.get("id") or d.get("requestId") or d.get("uuid")
            if u and key:
                usage[key] = u  # same request is logged once per content block; last one wins
            if m.get("model"):
                mode_model = m["model"]
            for b in m.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and str(b.get("name", "")).startswith("mcp__local-llm__"):
                    if b.get("name") not in ("mcp__local-llm__local_report", "mcp__local-llm__local_status"):
                        local_calls.add(b.get("id"))
    if not usage:
        return None
    fresh = sum(u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) for u in usage.values())
    cache = sum(u.get("cache_read_input_tokens", 0) for u in usage.values())
    out = sum(u.get("output_tokens", 0) for u in usage.values())
    if mode_model.startswith("qwen") or "9b" in mode_model:
        mode = "private"
    else:
        mode = "local+claude" if local_calls else "claude"
    return {"started": started[:16].replace("T", " "), "mode": mode, "first": first or "(no prompt text)",
            "fresh": fresh, "cache": cache, "out": out, "local": len(local_calls), "requests": len(usage)}


def sessions(n):
    files = sorted(PROJECTS.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[: max(n * 3, 10)]
    rows = [r for r in (read_session(f) for f in files) if r][:n]
    print(f"Claude token usage, last {len(rows)} sessions (exact, from Claude Code's own logs)")
    if not rows:
        print("  No sessions found in ~/.claude/projects.")
        return
    print(f"  {'started':<16} {'mode':<13} {'fresh in':>10} {'cache rd':>11} {'out':>8} {'local':>5}  first prompt")
    for r in rows:
        print(f"  {r['started']:<16} {r['mode']:<13} {r['fresh']:>10,} {r['cache']:>11,} {r['out']:>8,} {r['local']:>5}  {r['first']}")
    print("\n  Notes")
    print("  - fresh in = new input tokens (input plus cache writes). cache rd = cheap re-reads of earlier context.")
    print("  - out = tokens Claude wrote. local = delegated calls to the local model in that session.")
    print("  - A fair test: run the same task once in 'claude' and once in 'claude-local', then compare these rows.")
    print("  - Mode 'private' is claude-private (the local model only), so it uses no Claude tokens.")


def main():
    args = sys.argv[1:]
    if args and args[0] == "sessions":
        sessions(int(args[1]) if len(args) > 1 and args[1].isdigit() else 8)
    else:
        log_stats(int(args[0]) if args and args[0].isdigit() else 0)


if __name__ == "__main__":
    main()
