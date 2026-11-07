"""Local LLM bridge: an MCP server that lets Claude Code hand chores to Ollama.

Claude (on the Max plan) stays in charge. It calls these tools for bulk,
mechanical work and reviews what comes back. Any failure is returned as a
tool error so Claude falls back to doing the task itself.

Safety by design:
  * Talks only to Ollama on localhost. No shell, no internet, no writes.
  * The file tool is read only and fenced to the project folder (see "File access").
  * Hard timeout and no retries, so a crashed model fails fast.
  * Input size limits per model, checked before anything is sent.
  * Thinking is turned off so the reply budget goes to the answer.
  * Empty answers are errors, never silent successes.
  * Logs metadata only (tool, model, sizes, time, ok). Never the content.

File access (local_digest_files only):
  * Root is the folder Claude Code was started in (or LOCAL_LLM_ROOT). Home and / are refused.
  * Paths and globs are resolved first; anything that lands outside the root is skipped,
    which also stops symlinks and ".." from escaping.
  * Secret looking files (.env, keys, credentials) and folders like .git and .ssh are blocked.
  * Text files only, size capped, at most MAX_FILES per call.

Why the file tool exists: when Claude reads a big file itself, those tokens are already spent.
With local_digest_files the local model reads the file and Claude only sees the short result.

Run by Claude Code (see README). Config via environment variables below.
"""

from __future__ import annotations

import glob
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

try:  # MCP Python SDK 2.x renamed FastMCP to MCPServer
    from mcp.server.mcpserver import MCPServer as _Server
    from mcp.server.mcpserver.exceptions import ToolError as _ToolError
except ImportError:  # SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server
    from mcp.server.fastmcp.exceptions import ToolError as _ToolError

OLLAMA_URL = os.environ.get("LOCAL_LLM_URL", "http://localhost:11434")
TIMEOUT_S = int(os.environ.get("LOCAL_LLM_TIMEOUT", "180"))

# name -> (Ollama model, max input tokens). The 27B crashed on long inputs,
# so it only takes short ones. The 9B has a 64K window; we keep a safety margin.
MODELS: dict[str, tuple[str, int]] = {
    "small": (os.environ.get("LOCAL_LLM_SMALL", "qwen3.5:9b-64k"), 24_000),
    "big": (os.environ.get("LOCAL_LLM_BIG", "qwen3.8:27b-mlx"), 3_000),
}

MAX_FILES = 30            # files per local_digest_files call
MAX_FILE_BYTES = 400_000  # bigger files are read only up to this size
DENY_DIRS = {".git", ".ssh", ".aws", ".gnupg", ".kube", ".docker"}
DENY_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".kdbx", ".keystore")
DENY_PREFIXES = (".env", "credentials", "secrets", "id_rsa", "id_ed25519")
DENY_NAMES = {".netrc", ".npmrc", ".pypirc"}

LOG_FILE = Path(__file__).with_name("bridge.log")  # *.log is git ignored

mcp = _Server("local-llm")


class LocalLLMError(_ToolError):
    """Raised for any failure. Subclassing ToolError makes the MCP server return it
    as a tool error with this exact message, so Claude reads why and falls back."""


def _estimate_tokens(text: str) -> int:
    # Rough rule: about 4 characters per token for English and code.
    return len(text) // 4 + 1


def _write_log(row: dict) -> None:
    run = os.environ.get("TWO_BRAINS_RUN")  # set by claude-local, lets the status line show this run only
    if run:
        row["run"] = run
    try:
        with LOG_FILE.open("a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass  # logging must never break a tool call


def _log(tool: str, model: str, in_tokens: int, seconds: float, ok: bool, note: str = "",
         out_tokens: int = 0, kind: str = "text", files: int = 0) -> None:
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": tool, "model": model,
        "in_tokens_est": in_tokens, "out_tokens_est": out_tokens, "seconds": round(seconds, 1),
        "ok": ok, "note": note, "kind": kind,
    }
    if files:
        row["files"] = files
    _write_log(row)


def _call(tool: str, system: str, user: str, model: str, max_tokens: int, temperature: float,
          json_mode: bool, log_failures: bool = True) -> tuple[str, int, float]:
    """One Ollama chat request. Returns (text, input token estimate, seconds).
    Raises LocalLLMError on any failure. The caller logs successes."""
    if model not in MODELS:
        raise LocalLLMError(f"Unknown model '{model}'. Use one of: {', '.join(MODELS)}.")
    model_id, max_in = MODELS[model]

    in_tokens = _estimate_tokens(system) + _estimate_tokens(user)
    if in_tokens > max_in:
        if log_failures:
            _log(tool, model_id, in_tokens, 0, False, "input too large")
        raise LocalLLMError(
            f"Input is about {in_tokens} tokens, over the {max_in} limit for '{model}'. "
            "Split it into smaller pieces, or do this task yourself."
        )

    body = {
        "model": model_id,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
        "think": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    if json_mode:
        body["format"] = "json"

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        if log_failures:
            _log(tool, model_id, in_tokens, time.monotonic() - start, False, f"http {e.code}")
        raise LocalLLMError(f"Ollama returned HTTP {e.code}: {detail}. Do this task yourself.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        if log_failures:
            _log(tool, model_id, in_tokens, time.monotonic() - start, False, type(e).__name__)
        raise LocalLLMError(
            f"Local model unavailable ({e}). Ollama may be stopped, out of memory, or too slow. "
            "Do this task yourself."
        ) from e

    seconds = time.monotonic() - start
    text = (data.get("message") or {}).get("content", "").strip()
    if not text:
        if log_failures:
            _log(tool, model_id, in_tokens, seconds, False, "empty answer")
        raise LocalLLMError("Local model returned an empty answer. Do this task yourself.")
    return text, in_tokens, seconds


def _chat(tool: str, system: str, user: str, model: str = "small",
          max_tokens: int = 2048, temperature: float = 0.3, json_mode: bool = False) -> str:
    text, in_tokens, seconds = _call(tool, system, user, model, max_tokens, temperature, json_mode)
    _log(tool, MODELS[model][0], in_tokens, seconds, True, out_tokens=_estimate_tokens(text))
    return text


# ---------------------------------------------------------------- file access helpers

def _root() -> Path:
    root = Path(os.environ.get("LOCAL_LLM_ROOT") or os.getcwd()).resolve()
    if root == Path(root.anchor) or root == Path.home().resolve():
        raise LocalLLMError(
            "File tools only work inside a project folder, not your home folder or the disk root. "
            "Start claude-local from a project folder, or do this task yourself."
        )
    return root


def _blocked(path: Path, root: Path) -> str:
    """Return a reason if the file must not be read, else an empty string."""
    rel = path.relative_to(root)
    if any(part in DENY_DIRS for part in rel.parts[:-1]):
        return "blocked folder"
    name = path.name.lower()
    if (name.startswith(DENY_PREFIXES) or name.endswith(DENY_SUFFIXES) or name in DENY_NAMES):
        return "sensitive file name"
    return ""


def _expand(root: Path, patterns: list[str]) -> tuple[list[Path], list[str]]:
    """Turn paths and globs into resolved files inside root. Returns (files, skipped notes)."""
    files: list[Path] = []
    skipped: list[str] = []
    seen: set[Path] = set()
    for pat in patterns:
        full = pat if os.path.isabs(pat) else str(root / pat)
        matches = sorted(glob.glob(full, recursive=True))
        if not matches:
            skipped.append(f"{pat}: no match")
        for m in matches:
            p = Path(m).resolve()
            if not p.is_file():
                continue
            if root not in p.parents:
                skipped.append(f"{pat}: outside the project folder")
                continue
            reason = _blocked(p, root)
            if reason:
                skipped.append(f"{p.relative_to(root)}: {reason}")
                continue
            if p not in seen:
                seen.add(p)
                files.append(p)
    return files, skipped


# ---------------------------------------------------------------------------- tools

@mcp.tool()
def local_summarize(text: str, style: str = "brief", focus: str = "", model: str = "small") -> str:
    """Summarize text with a free local model. Use for long logs, docs, notes, or bulk summaries
    that do not need your full reasoning. Review the result before relying on it.
    style: brief | detailed | bullets. model: small (default, long inputs) | big (short inputs only)."""
    styles = {
        "brief": "Write a concise summary of about 150 words.",
        "detailed": "Write a thorough summary covering every main point.",
        "bullets": "Summarize as 5 to 10 short bullet points.",
    }
    system = "You are a precise summarizer. " + styles.get(style, styles["brief"])
    if focus:
        system += f" Focus on: {focus}."
    return _chat("local_summarize", system, text, model=model, max_tokens=1024)


@mcp.tool()
def local_classify(text: str, categories: list[str], explain: bool = False, model: str = "small") -> str:
    """Classify text into one of the given categories with a free local model.
    Good for sorting and tagging in bulk where categories are clear."""
    system = (
        f"Classify the text into exactly one of these categories: {', '.join(categories)}. "
        + ("Answer with the category, then one sentence explaining why." if explain
           else "Answer with the category name only.")
    )
    return _chat("local_classify", system, text, model=model, max_tokens=200, temperature=0.0)


@mcp.tool()
def local_extract(text: str, fields: list[str], model: str = "small") -> str:
    """Extract fields from text as JSON with a free local model. Use for parsing emails,
    invoices, job posts, logs. Missing fields are null. Check the JSON before using it."""
    system = (
        f"Extract these fields from the text: {', '.join(fields)}. "
        "Return one JSON object with exactly those keys. Use null for anything not found. "
        "Return JSON only."
    )
    return _chat("local_extract", system, text, model=model, max_tokens=1024,
                 temperature=0.0, json_mode=True)


@mcp.tool()
def local_run(instruction: str, text: str = "", model: str = "small", max_tokens: int = 2048) -> str:
    """General task for a free local model: drafts, boilerplate, test stubs, rewrites, conversions.
    You must review and fix the output. Do not use for design decisions or tricky logic."""
    user = instruction if not text else f"{instruction}\n\n---\n{text}"
    return _chat("local_run", "You are a careful assistant. Do exactly what is asked.", user,
                 model=model, max_tokens=max(64, min(max_tokens, 8192)))


@mcp.tool()
def local_digest_files(paths: list[str], instruction: str, max_words: int = 40,
                       model: str = "small") -> str:
    """Let the local model READ files and apply an instruction to each, so you never have to read
    them yourself. Returns one short answer per file. This is the way to save your own tokens on
    jobs over many files or big files (summaries, one line descriptions, tagging, extracting a
    detail). Pass project relative paths or globs such as "src/**/*.py". Read only, inside the
    project folder, at most 30 files per call (call again for more). Spot check a few answers
    against the source before trusting them."""
    root = _root()
    if model not in MODELS:
        raise LocalLLMError(f"Unknown model '{model}'. Use one of: {', '.join(MODELS)}.")
    if not paths:
        raise LocalLLMError("No paths given.")
    files, skipped = _expand(root, paths)
    if not files:
        raise LocalLLMError("No readable files matched. " + "; ".join(skipped[:10]))
    extra = files[MAX_FILES:]
    files = files[:MAX_FILES]
    max_words = max(5, min(max_words, 300))
    model_id, max_in = MODELS[model]
    system = (
        "You apply an instruction to one file. Answer in at most "
        f"{max_words} words, plain text, no preamble. Base the answer only on the file content."
    )

    lines: list[str] = []
    total_in, total_secs, done, stopped = 0, 0.0, 0, ""
    for p in files:
        rel = str(p.relative_to(root))
        try:
            raw = p.read_bytes()[:MAX_FILE_BYTES]
        except OSError as e:
            skipped.append(f"{rel}: unreadable ({type(e).__name__})")
            continue
        if b"\0" in raw[:8000]:
            skipped.append(f"{rel}: binary file")
            continue
        content = raw.decode("utf-8", errors="replace")
        budget_chars = (max_in - 1500) * 4
        truncated = len(content) > budget_chars
        if truncated:
            content = content[:budget_chars]
        user = f"Instruction: {instruction}\nFile: {rel}\n\n---\n{content}"
        try:
            text, in_t, secs = _call("local_digest_files", system, user, model,
                                     max_tokens=max_words * 3 + 60, temperature=0.2,
                                     json_mode=False, log_failures=False)
        except LocalLLMError as e:
            if done == 0:
                _log("local_digest_files", model_id, total_in, total_secs, False,
                     "first file failed", kind="file")
                raise
            stopped = f"STOPPED at {rel}: {e}"
            break
        total_in += in_t
        total_secs += secs
        done += 1
        flat = " ".join(text.split())
        lines.append(f"{rel}: {flat}" + (" [file truncated]" if truncated else ""))

    if done == 0:
        _log("local_digest_files", model_id, 0, 0, False, "nothing readable", kind="file")
        raise LocalLLMError("No readable text files. " + "; ".join(skipped[:10]))

    head = f"local_digest_files: {done} files read locally with {model_id}. Spot check a few answers."
    tail: list[str] = []
    if stopped:
        remaining = [str(p.relative_to(root)) for p in files[done:]]
        tail.append(f"{stopped}. Not processed ({len(remaining)}): " + ", ".join(remaining[:15])
                    + ". Do these yourself or try again.")
    if extra:
        tail.append(f"{len(extra)} more matched files were not processed (limit {MAX_FILES} per call). "
                    "Call again with the remaining paths.")
    if skipped:
        tail.append("Skipped: " + "; ".join(skipped[:10]))
    result = "\n".join([head, *lines, *tail])
    _log("local_digest_files", model_id, total_in, total_secs, True,
         "partial" if stopped else "", out_tokens=_estimate_tokens(result), kind="file", files=done)
    return result


@mcp.tool()
def local_report(tool: str, verdict: str) -> str:
    """After you review a local model's output, record how it went. verdict is one of:
    accepted (used as is), edited (needed fixes), rejected (you redid it). Call once per
    delegated result. It takes no content, only the verdict, and feeds the savings stats."""
    if verdict not in ("accepted", "edited", "rejected"):
        raise LocalLLMError("verdict must be accepted, edited, or rejected.")
    _write_log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": "local_report",
                "for": tool[:40], "verdict": verdict})
    return "recorded"


@mcp.tool()
def local_status() -> str:
    """Check whether Ollama is running and which local models are installed and loaded."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as r:
            installed = [m["name"] for m in json.loads(r.read()).get("models", [])]
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/ps", timeout=5) as r:
            loaded = [m["name"] for m in json.loads(r.read()).get("models", [])]
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LocalLLMError(f"Ollama is not reachable at {OLLAMA_URL}: {e}") from e
    return json.dumps({
        "ollama": "running", "installed": installed, "loaded": loaded,
        "bridge_models": {k: {"model": v[0], "max_input_tokens": v[1]} for k, v in MODELS.items()},
        "timeout_seconds": TIMEOUT_S,
    }, indent=2)


if __name__ == "__main__":
    mcp.run()
