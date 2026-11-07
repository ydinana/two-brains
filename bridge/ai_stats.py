#!/usr/bin/env python3
"""Summarize bridge/bridge.log: how often Claude delegated to a local model and how it went.

Usage: ai-stats [DAYS]     (no argument means all time)
Standard library only. The log holds metadata, never prompt content.
"""
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

LOG = Path(__file__).with_name("bridge.log")


def load(days):
    rows, skipped, tests = [], 0, 0
    if not LOG.exists():
        return rows, skipped, tests
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
        if not str(r.get("tool", "")).startswith("local_"):
            tests += 1  # manual test entries, not real delegation
            continue
        r["_ts"] = ts
        rows.append(r)
    return rows, skipped, tests


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "n/a"


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 0
    rows, skipped, tests = load(days)
    scope = f"last {days} days" if days else "all time"
    print(f"Two Brains stats ({scope})")
    if not rows:
        print("  No delegated calls logged yet.")
        return
    ok = [r for r in rows if r.get("ok")]
    bad = [r for r in rows if not r.get("ok")]
    first, last = min(r["_ts"] for r in rows), max(r["_ts"] for r in rows)
    print(f"  Period              {first:%Y-%m-%d} to {last:%Y-%m-%d}")
    print(f"  Delegated calls     {len(rows)}")
    print(f"  Succeeded           {len(ok)}  ({pct(len(ok), len(rows))})")
    print(f"  Failed, Claude took over  {len(bad)}  ({pct(len(bad), len(rows))})")
    tok = sum(r.get("in_tokens_est", 0) for r in ok)
    print(f"  Tokens handled locally   {tok:,} (estimated input tokens, successful calls)")
    if ok:
        secs = [r.get("seconds", 0) for r in ok]
        print(f"  Time per successful call  avg {sum(secs) / len(secs):.1f}s, max {max(secs):.1f}s")
    print("\n  By model")
    for m, n in Counter(r.get("model", "?") for r in rows).most_common():
        good = sum(1 for r in rows if r.get("model") == m and r.get("ok"))
        print(f"    {m:<20} {n} calls, {good} ok")
    print("\n  By tool")
    for t, n in Counter(r.get("tool", "?") for r in rows).most_common():
        print(f"    {t:<20} {n}")
    if bad:
        print("\n  Failure reasons")
        for note, n in Counter(r.get("note") or "unknown" for r in bad).most_common():
            print(f"    {note:<20} {n}")
    print("\n  Notes")
    print("  - Counts bridge calls only. If Claude rejects or rewrites a draft after review,")
    print("    that is not logged, so a successful call is not proof the draft was good.")
    if tests:
        print(f"  - Ignored {tests} manual test entries.")
    if skipped:
        print(f"  - Skipped {skipped} unreadable log lines.")


if __name__ == "__main__":
    main()
