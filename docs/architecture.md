# Architecture and decisions

## Layers

| Command | Job |
|---|---|
| `claude` | Plain Claude Code. Untouched, no local models. |
| `claude-local` | Claude plus the delegation bridge. Bulk chores go local; every failure tells Claude to do it itself. |
| `claude-private` | Fully local Claude Code for private or offline work. |
| Script lane (`scripts/`) | Scheduled Python automations that call Ollama directly |

## Decisions

- **Real token savings need file reading by the local model.** If Claude reads a file first, those tokens are already spent, so delegating text saves only the writing. `local_digest_files` lets the local model read files (read only, fenced to the project folder, secrets and binaries blocked, 30 files per call) so Claude sees only a short result. Savings are not assumed: in a first A/B test on 62 small files, plain Claude was cheaper than the delegated run, so the benefit is expected only for large reads and must be measured. Savings are measured two ways: the bridge log (tokens kept out of Claude's context, plus accepted, edited or rejected verdicts) and Claude Code's own session usage (`ai-stats sessions`).
- **Plain `claude` stays untouched.** The bridge and the delegation rules load only in `claude-local`, through `--mcp-config` and `--append-system-prompt-file`. Nothing is registered globally, so there is no way for local models to leak into normal sessions.
- **Fixed roles plus fallback, no auto router.** A router that guesses task difficulty adds a failure mode of its own. Fixed roles with fallback on failure is what most people run in practice.
- **Own bridge instead of community MCP servers.** The ones reviewed had no timeouts, no input limits, treated empty answers as success, or fell back to the paid API. This bridge is about 200 lines of Python and does the opposite on each point.
- **Errors must reach the model.** In the MCP Python SDK, only `ToolError` subclasses are passed through; anything else becomes a generic message. The bridge subclasses `ToolError` so Claude sees "Do this task yourself".
- **One model loaded at a time** (`OLLAMA_MAX_LOADED_MODELS=1`, reapplied at login by a LaunchAgent). Ollama's own memory estimates proved wrong in an out of memory test.
- **No LiteLLM, llama-swap or similar proxies.** They target 48 to 64 GB machines and add moving parts. Revisit for apps that need many models.
- **`claude-private` sets its own environment in a subshell** (base URL, model aliases, context size, telemetry off, connectors off, no MCP) so nothing leaks into normal `claude`.
- **Do not use "Connect" for Claude Code in the Ollama app.** It replaces Claude with a local model instead of adding one.

## Measured on a 24 GB M5 Pro

- `qwen3.8:27b-mlx`: about 30 tokens per second, crashes on large inputs.
- `qwen3.5:9b-64k`: 7.7 GB loaded at 65536 context, 100% GPU.
- `claude-private` offline: whole small task in about 55 seconds with thinking limited.
