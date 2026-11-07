# Two Brains

**Claude Code as the frontier brain. Local models as the private brain. One setup, with automatic fallback.**

Two Brains wires Claude Code (on a Claude subscription) to local models running in Ollama on your Mac.
Claude does the hard thinking. A local model takes the bulk chores. If the local model fails,
Claude quietly does the job itself. When the data is sensitive, you switch to a fully offline
Claude Code that never leaves your machine.

Built and tested on a MacBook Pro (Apple Silicon, 24 GB unified memory). Not affiliated with Anthropic, Ollama or Alibaba.

## What you get

| Piece | What it does |
|---|---|
| `claude` | Your normal Claude Code. It can hand bulk chores to the local model through the bridge. |
| `claude-local` | Claude Code running entirely on a local model. Works offline. Nothing leaves the Mac. |
| Delegation bridge | A small MCP server (Python) with `local_summarize`, `local_classify`, `local_extract`, `local_run`, `local_status`. |
| Fallback | Any local failure (timeout, out of memory, Ollama down, empty answer) becomes a tool error that tells Claude to do the task itself. |
| Overrides | Say "claude only" or "local only" per request, or set "Delegation: off" in a project's `CLAUDE.md`. |
| Private rules | A local, git ignored file listing data that must never go through a normal cloud session. |
| Memory guard | Ollama is limited to one loaded model, so two models cannot fight for 24 GB. |

## Quick start

Requirements: macOS on Apple Silicon, [Homebrew](https://brew.sh), [Claude Code](https://claude.com/claude-code) (logged in), Python 3.10+.

```
git clone https://github.com/ydinana/two-brains.git
cd two-brains
./install.sh              # full setup (about 26 GB of downloads)
./install.sh --skip-27b   # without the 18 GB large model
```

The installer is safe to rerun: every step checks first and skips what is done. Then open a new Terminal and try:

```
claude-local     # private, offline Claude Code on the local model
ai-status        # what is installed, what is loaded in memory
ai-stop          # unload every model to free RAM
claude           # normal Claude Code, now with the local-llm tools available
```

## How the fallback works

1. Claude decides a chore is bulk work (summarize, classify, extract, boilerplate) using the rules in `claude/delegation-rules.md`.
2. It calls a bridge tool. The bridge checks input size, calls Ollama on localhost with a timeout, and treats empty answers as errors.
3. On any failure the bridge returns a clear error ending with "Do this task yourself". Claude does, and says so in one line.

Tested failure cases: Ollama off (instant), and a real Metal out of memory crash on a 29K token input (clean error after 31 seconds, Ollama recovered without a restart).

## Privacy model

Delegation through Claude is **not** private, because Claude sees everything it sends to the local model.
Real privacy comes from `claude-local`, which sets Claude Code to talk only to local Ollama, disables
telemetry and claude.ai connectors, and loads no MCP servers. Auto mode does not work offline, so it
runs in default permission mode. Put your own sensitive categories in `claude/private-rules.md`
(created from `claude/private-rules.example.md` by the installer, never committed).

## Models

| Name | Base | Use |
|---|---|---|
| `qwen3.5:9b-64k` | `qwen3.5:9b` with 64K context | Everyday worker, `claude-local`, long inputs. About 7.7 GB loaded. |
| `qwen3.8:27b-mlx` | as downloaded (about 18 GB) | Harder questions on short inputs only (the bridge caps it at about 3K tokens). |

Swap in other models by editing `ollama/Modelfile.*`, `shell/aliases.sh` and the `MODELS` table in `bridge/local_llm_mcp.py`.

## Layout

| Path | What |
|---|---|
| `install.sh` | Idempotent installer |
| `shell/aliases.sh` | `claude-local`, `ai-stop`, `ai-status` |
| `bridge/` | The MCP server and its requirements |
| `claude/` | Delegation rules and the private rules example |
| `ollama/` | Modelfile and a login item that limits Ollama to one loaded model |
| `scripts/` | Space for Python automations that call Ollama directly, with no Claude involved |
| `docs/architecture.md` | Design decisions and the reasons behind them |

## Bridge settings

Environment variables: `LOCAL_LLM_URL`, `LOCAL_LLM_TIMEOUT` (default 180 s), `LOCAL_LLM_SMALL`, `LOCAL_LLM_BIG`.
The bridge talks to localhost only, has no file or shell access, retries nothing, and logs metadata
(never content) to `bridge/bridge.log`.

## Known limits

- 24 GB is tight: the large model crashes on big inputs, so it is capped. Use the 9B for long text.
- Small local models write working but quirky code. Review their output.
- Tested on macOS with bash and zsh only.

## License

MIT
