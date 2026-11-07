# Private rules (this file is local only and git ignored)

`install.sh` copies this example to `claude/private-rules.md` and loads it into Claude Code.
Edit your copy to list the data that must never go through a normal (cloud) Claude session.
For anything listed here, use `claude-private`, the Ollama chat, or a local script instead.

## Never read, paste, or delegate in a normal session

- Client or employer data (add names, projects, systems, folders)
- Credentials, API keys, tokens, `.env` files
- Personal documents (IDs, contracts, finances, medical)

If a file or request looks like it belongs here, stop, ask first, and suggest `claude-private`.
