# Two Brains

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Platform: macOS Apple Silicon](https://img.shields.io/badge/platform-macOS%20Apple%20Silicon-lightgrey.svg)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)

**Claude Code as the frontier brain. A local model as the private brain. One setup, with automatic fallback.**

Two Brains connects Claude Code (on your Claude subscription) to local models running in Ollama on your Mac.
Claude does the hard thinking. A local model takes the bulk chores. If the local model fails for any reason,
Claude quietly does the job itself. When the data is sensitive, you switch to a fully offline Claude Code
that never leaves your machine. Plain `claude` stays exactly as it was.

Built and tested on a MacBook Pro (Apple Silicon, 24 GB unified memory). Not affiliated with Anthropic, Ollama or Alibaba.

## Contents

- [Why](#why)
- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Daily use](#daily-use)
- [Privacy model](#privacy-model)
- [Models and memory](#models-and-memory)
- [Configuration](#configuration)
- [Repo layout](#repo-layout)
- [FAQ](#faq)
- [Uninstall](#uninstall)
- [Known limits](#known-limits)
- [Contributing](#contributing)

## Why

Three problems show up when you mix cloud and local models:

1. **Local models fail quietly or loudly.** On a 24 GB Mac a big input can crash the model with an out of memory error.
   Here, every failure reaches Claude as an error that says "Do this task yourself", so your work never stalls.
2. **Sometimes you want cloud only, sometimes local only.** You can say "claude only" or "local only" per request,
   or set it per project.
3. **Some data must never reach a cloud model.** `claude-private` runs Claude Code against Ollama only, with telemetry
   and connectors off and no MCP servers loaded.

It deliberately has no auto router that guesses task difficulty. Fixed roles plus fallback on failure is simpler
and easier to trust.

## How it works

```
     claude                claude-local              claude-private
 (plain Claude)      (Claude + local models)       (local model only)
       |                       |                          |
 your plan only                | MCP tool call            | nothing leaves
                               v                          v
                    +------------------+          +-------------+
                    | delegation bridge|--------> |   Ollama    | <--- scripts/
                    +------------------+          +-------------+
                               |  failure (timeout, out of memory, empty)
                               v
                     "Do this task yourself"
                               |
                               v
          Claude finishes the task and says so in one line
```

1. In a `claude-local` session, Claude decides a chore is bulk work (summarize, classify, extract, boilerplate) using `claude/delegation-rules.md`.
2. It calls a bridge tool. The bridge checks input size, calls Ollama on localhost with a timeout, and treats empty answers as errors.
3. Success: Claude reviews the result and adds a one line note, for example "(local 9B: summarize, 7s)".
4. Failure: the bridge returns a clear error and Claude does the task itself.

Tested failure cases: Ollama off (instant error), and a real Metal out of memory crash on a 29K token input
(clean error after 31 seconds, Ollama recovered without a restart).

## Quick start

Requirements: macOS on Apple Silicon, [Homebrew](https://brew.sh), [Claude Code](https://claude.com/claude-code) (installed and logged in), Python 3.10+.

```
git clone https://github.com/ydinana/two-brains.git
cd two-brains
./install.sh              # full setup, about 26 GB of model downloads
./install.sh --skip-27b   # without the 18 GB large model
```

The installer is safe to rerun: every step checks first and skips what is already done. It will:

1. Check your tools
2. Install and start Ollama
3. Download the models and build the 64K context variant
4. Create the bridge's Python environment
5. Check the bridge (it loads only in `claude-local`; plain `claude` is left alone)
6. Add the shell shortcuts to `~/.bash_profile` and `~/.zshrc`
7. Load your private rules into `~/.claude/CLAUDE.md`
8. Limit Ollama to one loaded model, reapplied at every login

Then open a new Terminal window. A two page guide to every run mode is in [docs/how-to-run.pdf](docs/how-to-run.pdf).

## Daily use

| Command | What it does |
|---|---|
| `claude` | Plain Claude Code, exactly as before. No local models. |
| `claude-local` | Claude plus local models: bulk chores go to the local model, failures fall back to Claude. |
| `claude-private` | Claude Code on the local model only. Works offline. Use it for sensitive data. |
| `ollama run qwen3.5:9b-64k` | Plain chat with Qwen (or `qwen3.8:27b-mlx` for hard, short questions). No Claude. |
| `ai-status` | Shows installed models, what is loaded in memory, and the one-model limit. |
| `ai-stop` | Unloads every model to free RAM. |

Example prompts in a `claude-local` session:

```
Summarize this 3,000 line log file.                    -> delegated to the 9B, reviewed by Claude
Classify these 200 support emails by topic. claude only -> no local tools are used
Extract the invoice fields from these PDFs. local only  -> local tools only, stops if they fail
```

Per project, add one line to that project's `CLAUDE.md`: `Delegation: off` or `Delegation: prefer`.

To see which model did the work, check `tail -5 bridge/bridge.log` (model, seconds, success or failure per call).

## Privacy model

Delegation through Claude is **not** private, because Claude sees everything it sends to the local model.
Real privacy comes from `claude-private`, which:

- sends model requests to local Ollama only
- turns off telemetry, nonessential traffic and claude.ai connectors
- loads no MCP servers (`--strict-mcp-config`)
- runs in default permission mode (auto mode needs a network and does not work offline)

### Why the 9B and not the 27B

Claude Code needs a large context window (about 64K tokens) because it reads files and tool instructions. The 9B
runs that comfortably (7.7 GB loaded). The 27B takes 18 GB of a 24 GB Mac and crashed with out of memory errors on
large inputs, which is what an agent produces. Use the 27B for short questions in a plain `ollama run` chat.
`claude-private` is much less capable than Claude, so use it when privacy matters more than quality.

Your own sensitive categories go in `claude/private-rules.md`. The installer creates it from
`claude/private-rules.example.md` and loads it into Claude Code. It is git ignored, so it never leaves your machine.

## Models and memory

| Name | Base | Use |
|---|---|---|
| `qwen3.5:9b-64k` | `qwen3.5:9b` with a 64K context window | Everyday worker, `claude-private`, long inputs. About 7.7 GB loaded. |
| `qwen3.8:27b-mlx` | as downloaded, about 18 GB | Harder questions on short inputs only. The bridge caps it at about 3K tokens. |

On a 24 GB Mac, the large model leaves little headroom and crashes on big inputs, so it is capped. Ollama is limited
to one loaded model (`OLLAMA_MAX_LOADED_MODELS=1`) because its own memory estimates proved unreliable.

To use other models, edit `ollama/Modelfile.*`, `LOCAL_AI_MODEL` in `shell/aliases.sh`, and the `MODELS` table in `bridge/local_llm_mcp.py`.

## Configuration

Bridge environment variables: `LOCAL_LLM_URL`, `LOCAL_LLM_TIMEOUT` (default 180 s), `LOCAL_LLM_SMALL`, `LOCAL_LLM_BIG`.

The bridge talks to localhost only, has no file or shell access, retries nothing, and logs metadata
(never content) to `bridge/bridge.log`.

## Repo layout

| Path | What |
|---|---|
| `install.sh` | Idempotent installer |
| `shell/aliases.sh` | `claude-private`, `ai-stop`, `ai-status` |
| `bridge/` | The MCP server and its requirements |
| `claude/` | Delegation rules and the private rules example |
| `ollama/` | Modelfile and the login item that limits Ollama to one loaded model |
| `scripts/` | Space for Python automations that call Ollama directly, with no Claude involved |
| `docs/how-to-run.pdf` | Two page guide: every way to run it (cloud, local, fallback) |
| `docs/architecture.md` | Design decisions and the reasons behind them |
| `docs/troubleshooting.md` | Fixes for problems seen in real use |

## FAQ

**Does this cost extra?** No API billing. Claude Code uses your existing subscription, and the models run locally for free.

**Do I need the 27B model?** No. Use `--skip-27b`. The 9B handles almost everything.

**Does it work on 16 GB?** Untested. The 9B at 64K context needs about 8 GB, so it may work. Skip the 27B.

**Does it work on Intel Macs, Linux or Windows?** Untested. The installer is macOS only.

**Can the bridge read my files?** No. It only receives text that Claude sends it, and it talks to localhost.

**Why not LiteLLM or a router?** They target bigger machines and add moving parts. See `docs/architecture.md`.

## Uninstall

1. Remove the lines containing `two-brains` from `~/.bash_profile` and `~/.zshrc`.
2. Remove the `@.../claude/private-rules.md` line from `~/.claude/CLAUDE.md`.
3. `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.localaistack.ollama-env.plist && rm ~/Library/LaunchAgents/com.localaistack.ollama-env.plist`
4. `ollama rm qwen3.5:9b-64k qwen3.5:9b qwen3.8:27b-mlx`
5. Delete the repo folder.

## Known limits

- 24 GB is tight. Large inputs to the 27B crash, so it is capped. Use the 9B for long text.
- Small local models write working but quirky code. Review their output.
- Tested on macOS with bash and zsh only.
- The community tools mentioned in `docs/architecture.md` were reviewed at the time of writing and may have changed.

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
