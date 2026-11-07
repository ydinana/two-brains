#!/usr/bin/env python3
"""Two Brains status line for Claude Code. Standard library only.

Shows which brain you are in, the model, this session's exact token usage,
how many jobs went to the local model, context fill and plan usage:

  ● LOCAL+CLAUDE │ Opus │ in 41.2K  out 3.1K  cache 212K │ local 4 │ ctx 18% │ 5h 23%

Claude Code runs this after each message and passes session data as JSON on stdin.
The mode comes from TWO_BRAINS_MODE, which the claude-lean, claude-local and
claude-private shortcuts set. Plain `claude` has no mode set and shows CLAUDE.

Token numbers are read from the session transcript (the same source as ai-stats sessions),
deduplicated by message id. Parsing is incremental and cached, so it stays fast in long sessions.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

RESET = "\033[0m"
DIM = "\033[2m"
MODES = {  # mode: (label, color)
    "lean": ("LEAN", "\033[32m"),             # green
    "local": ("LOCAL+CLAUDE", "\033[36m"),     # cyan
    "private": ("PRIVATE offline", "\033[35m"),  # magenta
    "claude": ("CLAUDE", "\033[33m"),          # yellow
}
SKIP_LOCAL = {"mcp__local-llm__local_report", "mcp__local-llm__local_status"}
CACHE_DIR = Path(tempfile.gettempdir()) / "two-brains-statusline"


def human(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def detect_mode():
    mode = os.environ.get("TWO_BRAINS_MODE", "").strip().lower()
    base = os.environ.get("ANTHROPIC_BASE_URL", "")
    if "localhost" in base or "127.0.0.1" in base:
        return "private"  # requests go to a local server, whatever the label says
    return mode if mode in MODES else "claude"


def session_usage(transcript, session_id):
    """Exact token totals for this session, parsed incrementally from the transcript."""
    path = Path(transcript)
    if not transcript or not path.is_file():
        return None
    CACHE_DIR.mkdir(exist_ok=True)
    state_file = CACHE_DIR / f"{session_id or path.stem}.json"
    state = {"offset": 0, "usage": {}, "local": []}
    try:
        state = json.loads(state_file.read_text())
    except (OSError, ValueError):
        pass
    size = path.stat().st_size
    if size < state.get("offset", 0):  # transcript was rewritten: start over
        state = {"offset": 0, "usage": {}, "local": []}
    local = set(state["local"])
    with path.open("rb") as f:
        f.seek(state["offset"])
        chunk = f.read()
    end = chunk.rfind(b"\n") + 1  # only parse complete lines, the last one may still be written
    for line in chunk[:end].splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "assistant":
            continue
        m = d.get("message") or {}
        u, key = m.get("usage"), m.get("id") or d.get("requestId") or d.get("uuid")
        if u and key:  # the same request is logged once per content block; last one wins
            state["usage"][key] = [
                u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0),
                u.get("cache_read_input_tokens", 0),
                u.get("output_tokens", 0),
            ]
        for b in m.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                name = str(b.get("name", ""))
                if name.startswith("mcp__local-llm__") and name not in SKIP_LOCAL:
                    local.add(b.get("id"))
    state["offset"] += end
    state["local"] = sorted(x for x in local if x)
    try:
        state_file.write_text(json.dumps(state))
    except OSError:
        pass
    vals = state["usage"].values()
    return {
        "fresh": sum(v[0] for v in vals),
        "cache": sum(v[1] for v in vals),
        "out": sum(v[2] for v in vals),
        "local": len(state["local"]),
    }


def build(data):
    mode = detect_mode()
    label, color = MODES[mode]
    parts = [f"{color}● {label}{RESET}"]
    model = (data.get("model") or {}).get("display_name") or (data.get("model") or {}).get("id")
    if model:
        parts.append(model)

    try:
        u = session_usage(data.get("transcript_path"), data.get("session_id"))
    except Exception:
        u = None
    if u:
        tokens = f"in {human(u['fresh'])}  out {human(u['out'])}  {DIM}cache {human(u['cache'])}{RESET}"
        if mode == "private":
            tokens = f"{tokens}  {DIM}(all on this Mac, 0 cloud){RESET}"
        parts.append(tokens)
        if mode == "local":
            parts.append(f"local {u['local']}")

    ctx = (data.get("context_window") or {}).get("used_percentage")
    if ctx is not None:
        parts.append(f"ctx {int(ctx)}%")
    five = ((data.get("rate_limits") or {}).get("five_hour") or {}).get("used_percentage")
    if five is not None and mode != "private":
        parts.append(f"5h {int(five)}%")
    return " │ ".join(parts)


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    try:
        print(build(data))
    except Exception:  # a status line must never break the session
        label, color = MODES[detect_mode()]
        print(f"{color}● {label}{RESET}")


if __name__ == "__main__":
    main()
