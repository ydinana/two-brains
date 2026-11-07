#!/usr/bin/env bash
# Two Brains installer for macOS (Apple Silicon).
# Safe to run again: every step checks first and skips what is already done.
#
# Usage:   ./install.sh              full setup, including the 18 GB 27B model
#          ./install.sh --skip-27b   everything except the 27B model
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
SMALL_BASE="qwen3.5:9b"
SMALL="qwen3.5:9b-64k"
BIG="qwen3.8:27b-mlx"
WITH_27B=1
[[ "${1:-}" == "--skip-27b" ]] && WITH_27B=0

step() { printf "\n==> %s\n" "$1"; }
ok()   { printf "    ok: %s\n" "$1"; }
die()  { printf "    ERROR: %s\n" "$1" >&2; exit 1; }
has_model() { ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$1"; }
add_line_once() {  # add_line_once <file> <line> <marker>: skip if any line already contains <marker>
  touch "$1"
  if grep -qF "$3" "$1"; then ok "already in $1"; else printf '%s\n' "$2" >> "$1"; ok "added to $1"; fi
}

step "1/9 Checking tools"
[[ "$(uname -s)" == "Darwin" ]] || die "This script is for macOS."
command -v brew >/dev/null || die "Homebrew is missing. Install it from https://brew.sh and rerun."
command -v claude >/dev/null || die "Claude Code is missing. Install it and log in, then rerun."
PY="$(command -v python3 || true)"
[[ -n "$PY" ]] && "$PY" -c 'import sys; sys.exit(sys.version_info < (3,10))' \
  || die "Python 3.10 or newer is needed. Run: brew install python"
ok "macOS, Homebrew, Claude Code, $("$PY" --version)"

step "2/9 Ollama"
if ! command -v ollama >/dev/null; then brew install --cask ollama-app; fi
if ! curl -s localhost:11434 >/dev/null; then
  open -a Ollama
  for _ in {1..30}; do curl -s localhost:11434 >/dev/null && break; sleep 1; done
fi
curl -s localhost:11434 >/dev/null || die "Ollama did not start. Open the Ollama app and rerun."
ok "Ollama running"

step "3/9 Models"
if has_model "$SMALL_BASE"; then ok "$SMALL_BASE present"; else caffeinate -i ollama pull "$SMALL_BASE"; fi
if has_model "$SMALL"; then ok "$SMALL present"; else ollama create "$SMALL" -f "$REPO/ollama/Modelfile.qwen3.5-9b-64k"; fi
if [[ $WITH_27B -eq 1 ]]; then
  if has_model "$BIG"; then ok "$BIG present"; else caffeinate -i ollama pull "$BIG"; fi
else
  ok "skipping $BIG (--skip-27b)"
fi

step "4/9 Bridge Python environment"
if [[ ! -x "$REPO/bridge/.venv/bin/python" ]]; then "$PY" -m venv "$REPO/bridge/.venv"; fi
"$REPO/bridge/.venv/bin/pip" install -q --disable-pip-version-check -r "$REPO/bridge/requirements.txt"
(cd "$REPO/bridge" && .venv/bin/python -c "import local_llm_mcp") || die "Bridge failed to import."
ok "bridge imports"

step "5/9 Bridge wiring"
# The bridge loads only in claude-local (through --mcp-config), so plain claude stays untouched.
# Older versions registered it globally; remove that so plain claude has no local models.
if claude mcp get local-llm >/dev/null 2>&1; then
  claude mcp remove local-llm -s user >/dev/null 2>&1 || true
  ok "removed old global registration"
fi
ok "bridge loads only in claude-local"

step "6/9 Shell shortcuts (claude-local, claude-private, ai-stop, ai-status)"
SRC_LINE="source \"$REPO/shell/aliases.sh\""
add_line_once "$HOME/.bash_profile" "$SRC_LINE" "shell/aliases.sh"
add_line_once "$HOME/.zshrc" "$SRC_LINE" "shell/aliases.sh"

step "7/9 Private rules for Claude Code"
mkdir -p "$HOME/.claude"
# Older versions imported the delegation rules globally; claude-local now loads them itself.
if [[ -f "$HOME/.claude/CLAUDE.md" ]] && grep -qF "claude/delegation-rules.md" "$HOME/.claude/CLAUDE.md"; then
  sed -i.bak '/claude\/delegation-rules\.md/d' "$HOME/.claude/CLAUDE.md" && rm -f "$HOME/.claude/CLAUDE.md.bak"
  ok "removed old global delegation import"
fi
# Private rules stay on this machine (git ignored). Created from the example the first time.
if [[ ! -f "$REPO/claude/private-rules.md" ]]; then
  cp "$REPO/claude/private-rules.example.md" "$REPO/claude/private-rules.md"
  ok "created claude/private-rules.md (edit it: list your own sensitive data)"
fi
add_line_once "$HOME/.claude/CLAUDE.md" "@$REPO/claude/private-rules.md" "claude/private-rules.md"

step "8/9 Ollama memory setting (one model loaded at a time)"
PLIST="com.localaistack.ollama-env.plist"
DST="$HOME/Library/LaunchAgents/$PLIST"
mkdir -p "$HOME/Library/LaunchAgents"
if cmp -s "$REPO/ollama/$PLIST" "$DST"; then
  ok "login item already installed"
else
  cp "$REPO/ollama/$PLIST" "$DST"
  launchctl bootout "gui/$(id -u)" "$DST" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$DST"
  ok "login item installed"
fi
if [[ "$(launchctl getenv OLLAMA_MAX_LOADED_MODELS)" != "1" ]]; then
  launchctl setenv OLLAMA_MAX_LOADED_MODELS 1
  echo "    NOTE: quit Ollama from the menu bar and reopen it to apply this setting."
fi
ok "OLLAMA_MAX_LOADED_MODELS=$(launchctl getenv OLLAMA_MAX_LOADED_MODELS)"

step "9/9 Status line (shows which brain you are in, tokens and local calls)"
"$PY" - "$HOME/.claude/settings.json" "$REPO/shell/statusline.py" "$PY" <<'PYEOF'
import json, shutil, sys
from pathlib import Path
p, script, py = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
cmd = f'"{py}" "{script}"'
data = {}
if p.exists():
    try:
        data = json.loads(p.read_text() or "{}")
    except ValueError:
        print(f"    NOTE: {p} is not valid JSON, status line not added"); sys.exit(0)
cur = (data.get("statusLine") or {}).get("command", "")
if cur == cmd:
    print("    ok: status line already set"); sys.exit(0)
if cur and "statusline.py" not in cur:
    print(f"    NOTE: you already have your own status line, left it alone: {cur}"); sys.exit(0)
if p.exists():
    shutil.copy(p, str(p) + ".bak")
data["statusLine"] = {"type": "command", "command": cmd}
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(data, indent=2) + "\n")
print(f"    ok: status line added to {p}")
PYEOF

step "Done"
ollama list
echo
echo "Open a new Terminal window (or run: source ~/.bash_profile) to use claude-local and claude-private."
