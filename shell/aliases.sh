# Two Brains shell shortcuts. Works in bash and zsh.
# ./install.sh adds a line like this to ~/.bash_profile and ~/.zshrc:
#   source "/path/to/two-brains/shell/aliases.sh"

# Find the repo folder so claude-local can load the bridge from it (bash and zsh).
if [ -n "${BASH_VERSION:-}" ]; then _TB_SELF="${BASH_SOURCE[0]}"
elif [ -n "${ZSH_VERSION:-}" ]; then eval '_TB_SELF=${(%):-%x}'; fi
TWO_BRAINS_HOME="$(cd "$(dirname "$_TB_SELF")/.." && pwd)"

LOCAL_AI_MODEL="qwen3.5:9b-64k"
LOCAL_AI_CONTEXT=65536   # must match num_ctx in ollama/Modelfile.qwen3.5-9b-64k

_ollama_up() {
  if ! ollama list >/dev/null 2>&1; then
    echo "Ollama is not running. Starting it..."
    open -a Ollama
    sleep 5
  fi
}

# Plain Claude without the claude.ai connectors (Gmail, Notion, Drive and so on). Every connector adds
# tool definitions to the start of each session. In our test that cost about 11K input tokens
# per session (24.7K to 13.4K for a one word prompt). Use it for coding sessions that need no connectors.
claude-lean() { TWO_BRAINS_MODE=lean ENABLE_CLAUDEAI_MCP_SERVERS=false claude "$@"; }

# Claude plus local models. Claude Code on your normal plan, with the local helper loaded:
# the bridge tools (--mcp-config) and the delegation rules (--append-system-prompt-file).
# Bulk chores go to the local model; any failure falls back to Claude. Plain `claude` is untouched.
claude-local() {
  _ollama_up
  local py="$TWO_BRAINS_HOME/bridge/.venv/bin/python" srv="$TWO_BRAINS_HOME/bridge/local_llm_mcp.py"
  if [ ! -x "$py" ]; then echo "Bridge not installed. Run ./install.sh in $TWO_BRAINS_HOME"; return 1; fi
  # A run id shared by the bridge and the status line, so the status line can show this run's local work
  local run="$(date +%s)-$$"
  TWO_BRAINS_MODE=local TWO_BRAINS_RUN="$run" claude \
    --mcp-config "{\"mcpServers\":{\"local-llm\":{\"command\":\"$py\",\"args\":[\"$srv\"],\"env\":{\"TWO_BRAINS_RUN\":\"$run\"}}}}" \
    --append-system-prompt-file "$TWO_BRAINS_HOME/claude/delegation-rules.md" "$@"
}

# Claude Code running on the local model only. Nothing leaves the Mac.
# Runs in a subshell so these settings never leak into your normal `claude`.
claude-private() {
  _ollama_up
  (
    # Label for the status line
    export TWO_BRAINS_MODE=private
    # Send every model request to local Ollama, not Anthropic
    export ANTHROPIC_BASE_URL="http://localhost:11434"
    export ANTHROPIC_AUTH_TOKEN="ollama"
    unset ANTHROPIC_API_KEY
    # Background and subagent work also stays on the local model
    export ANTHROPIC_DEFAULT_HAIKU_MODEL="$LOCAL_AI_MODEL"
    export ANTHROPIC_DEFAULT_SONNET_MODEL="$LOCAL_AI_MODEL"
    export ANTHROPIC_DEFAULT_OPUS_MODEL="$LOCAL_AI_MODEL"
    export CLAUDE_CODE_SUBAGENT_MODEL="$LOCAL_AI_MODEL"
    # Tell Claude Code the real context size so it compacts in time
    export CLAUDE_CODE_MAX_CONTEXT_TOKENS="$LOCAL_AI_CONTEXT"
    # No auto updates, telemetry, error reports, or feature flag fetching
    export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
    export DISABLE_TELEMETRY=1
    # Do not load claude.ai connectors (Gmail, Notion, Drive...), which reach the internet
    export ENABLE_CLAUDEAI_MCP_SERVERS=false
    # Ask Claude Code not to request thinking (the model may still think a little)
    export MAX_THINKING_TOKENS=0
    # Ask before running commands or editing files
    # --strict-mcp-config with no --mcp-config: load no MCP servers at all
    claude --model "$LOCAL_AI_MODEL" --permission-mode default --strict-mcp-config "$@"
  )
}

# Unload every loaded model to free memory.
ai-stop() {
  ollama ps | awk 'NR>1 {print $1}' | while read -r m; do
    [ -n "$m" ] && ollama stop "$m" && echo "Unloaded $m"
  done
  ollama ps
}

# Delegation stats from the bridge log: calls, success and fallback rate, tokens handled locally.
# Usage: ai-stats [DAYS]
ai-stats() { python3 "$TWO_BRAINS_HOME/bridge/ai_stats.py" "$@"; }

# Show what is installed and what is loaded in memory.
ai-status() {
  echo "Installed:"; ollama list
  echo; echo "Loaded in memory:"; ollama ps
  echo; echo "Max models loaded at once: $(launchctl getenv OLLAMA_MAX_LOADED_MODELS || echo 'not set')"
}
