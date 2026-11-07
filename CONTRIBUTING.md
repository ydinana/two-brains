# Contributing

Thanks for your interest. Issues and pull requests are welcome.

## Before you open an issue
Check `docs/troubleshooting.md`. When reporting a bug, include your Mac model and memory, macOS version,
`ollama --version`, `claude --version`, the output of `ai-status`, and the last lines of `bridge/bridge.log`
(it contains no prompt content).

## Pull requests
- Keep changes small and focused, with a clear description of what and why.
- Run `bash -n install.sh shell/aliases.sh` and test `./install.sh` twice; it must stay safe to rerun.
- Bridge changes: failures must still reach Claude as a tool error that ends with "Do this task yourself".
- Never add content logging, network calls beyond localhost, or file/shell access to the bridge.
- No personal paths, names or client data anywhere in the repo.

## Ideas that would help
- Linux support in `install.sh`
- Tests for the bridge
- Support for other local models and memory sizes
- Example scripts for `scripts/`
