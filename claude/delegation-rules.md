# Local model delegation rules

These rules are loaded by the `claude-local` command. They apply when the `local-llm` MCP tools (`local_summarize`, `local_classify`,
`local_extract`, `local_run`, `local_status`) are available. If they are not available
(for example in a `claude-private` session), ignore this whole section.

## When to delegate

Hand these to the local model, then review the result yourself:
- Summarizing long text: logs, docs, notes, transcripts, long outputs.
- Classifying or tagging many items with clear categories.
- Extracting fields into JSON: emails, invoices, job posts, receipts.
- First drafts of boilerplate: docstrings, README sections, test stubs, config, simple CRUD.
- Mechanical rewrites and format conversions.

Rule of thumb: delegate when the job has about 10 or more similar items (files, emails, log
sections, records) or about 3,000 or more tokens of text to digest, and the output is a
summary, a list, a table, or JSON. When a job meets this threshold you MUST delegate the
writing to the local model, unless the user said "claude only". Reading files to gather the
text is fine, but do not write the summary, list or table yourself instead of sending the
text to the local tool. Do the work yourself only when the job is smaller than this.

## Save your own tokens: let the local model read the files

Reading is the expensive part. For jobs over many files or big files (describe each file, tag
each file, find where something is mentioned, summarize every log), do NOT read the files
yourself. Call `local_digest_files` with paths or globs and an instruction, and read only the
short result. It reads at most 30 files per call, so call again for more. It only reads inside
the project folder and refuses secrets and binaries.
- Write a specific instruction, for example: "One sentence on what this file does. Do not just
  list class names."
- Spot check 2 or 3 entries against the source. If most entries are wrong, say so and do the
  job yourself. If only a few are wrong, fix just those lines. Never rewrite everything when
  most of it is fine.
- Use the tools that take text (`local_summarize` and the others) only when the text is
  already in front of you.

Do NOT delegate:
- Design, architecture, or any decision with tradeoffs.
- Finding the root cause of a bug, security work, or tricky logic.
- Anything where a wrong answer is costly and hard to spot.
- Short tasks you can do in one step. Delegating has overhead.

## How to delegate

- Send the full text. Do not shorten or pre-summarize it first; that wastes the point.
- If the text is over the tool's limit, split it into chunks under about 20K tokens,
  delegate each chunk, then combine the results yourself.
- Use `model="small"` by default. Use `model="big"` only for short inputs (under about 3K
  tokens) that need better reasoning.
- Always review the output. Fix errors before using it. Never present local output as
  checked when you have not checked it.
- After delegating, add one short line to your reply, e.g. "(local 9B: summarize, 7s)".

## Report the outcome

After you review a delegated result, call `local_report` once with the tool name and a verdict:
accepted (used as is), edited (needed fixes), or rejected (you redid it). Keep it to that one
call and do not mention it in your reply. It feeds the savings stats.

## Fallback

If a local tool returns an error (timeout, out of memory, empty answer, Ollama down,
input too large):
- Retry at most once, and only if the error looks temporary.
- Otherwise do the task yourself and say so in one line, e.g.
  "Local model failed (timeout), so I did it myself."
- Never stop the user's task just because the local model failed.

## User overrides

- "claude only" in a request: do not use any local tool for that request.
- "local only" in a request: use local tools for the content work. If they fail, stop and
  tell the user instead of doing it yourself. Remind them that this is still not private,
  because you see the text; for private work they should use `claude-private`.
- A project CLAUDE.md line "Delegation: off" disables these tools for that project.
  "Delegation: prefer" means delegate whenever a task fits the list above.

## Privacy

- Delegation does not make data private, because you see everything you send.
- Never paste, read, or delegate anything covered by the private rules (see
  `claude/private-rules.md`, which is local to this machine and not part of the repo) in a
  normal Claude session.
- If a file, folder, or request looks sensitive (client or employer data, credentials,
  personal documents), stop and ask before reading it, and suggest `claude-private` instead.
