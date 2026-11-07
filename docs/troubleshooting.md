# Troubleshooting

## `./install.sh: Permission denied`
The file lost its executable bit. Run `chmod +x install.sh`, or run it with `bash install.sh`.

## "timed out waiting for server to start" or Ollama commands hang
The Ollama app is not running. Start it with `open -a Ollama`. To check without starting it, use
`curl -s localhost:11434` (it prints "Ollama is running"). Note that the `ollama` command itself
starts the app if it is closed, so `ollama list` is not a safe status check.

## `bad interpreter` from `pip` after moving or renaming the folder
A Python virtual environment stores its absolute path. Rebuild it:

```
rm -rf bridge/.venv
./install.sh
```

## Registration points at the old folder after a move
```
claude mcp remove local-llm -s user
./install.sh
```
Also update any `two-brains` paths in `~/.bash_profile`, `~/.zshrc` and `~/.claude/CLAUDE.md`.

## `ai-status` shows "Max models loaded at once: not set"
The setting is lost on reboot unless the login item is installed. Rerun `./install.sh`, then quit Ollama
from the menu bar and reopen it with `open -a Ollama`.

## Two big models downloaded by accident
The Ollama app model picker can download a second copy (for example `qwen3.8:27b` next to `qwen3.8:27b-mlx`).
In the picker, choose only models with no icon (already local). A download arrow means it is not on disk yet;
a cloud icon means it runs on Ollama's servers, not on your Mac. Remove extras with `ollama rm <name>`.

## "Insufficient Memory" / Metal crash, HTTP 500
The input was too large for the model. The bridge caps the 27B at about 3K tokens for this reason. Use the 9B
for long text, or split the input. Ollama recovers on its own; no restart needed.

## Auto mode fails in `claude-local`
Auto mode needs a network classifier, so it cannot work offline. Use default permission mode, or press
Shift+Tab to accept edits.

## `claude-local` is slow to answer
Thinking is limited but small models may still think a little. Keep prompts focused, and give the model
specific files rather than the whole repo.

## A stopped download left large files behind
Leftovers sit in `~/.ollama/models/blobs`, sometimes ending in `.tmp`, sometimes with no suffix. Identify them
by modification time (`find ~/.ollama/models/blobs -type f -mmin -N`), compare sizes against `ollama list`,
and delete only files that do not belong to an installed model.
