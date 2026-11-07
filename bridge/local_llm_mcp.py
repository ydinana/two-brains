"""Local LLM bridge: an MCP server that lets Claude Code hand chores to Ollama.

Claude (on the Max plan) stays in charge. It calls these tools for bulk,
mechanical work and reviews what comes back. Any failure is returned as a
tool error so Claude falls back to doing the task itself.

Safety by design:
  * Talks only to Ollama on localhost. No file access, no shell, no internet.
  * Hard timeout and no retries, so a crashed model fails fast.
  * Input size limits per model, checked before anything is sent.
  * Thinking is turned off so the reply budget goes to the answer.
  * Empty answers are errors, never silent successes.
  * Logs metadata only (tool, model, sizes, time, ok). Never the content.

Run by Claude Code (see README). Config via environment variables below.
"""

from __future__ import annotations

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

LOG_FILE = Path(__file__).with_name("bridge.log")  # *.log is git ignored

mcp = _Server("local-llm")


class LocalLLMError(_ToolError):
    """Raised for any failure. Subclassing ToolError makes the MCP server return it
    as a tool error with this exact message, so Claude reads why and falls back."""


def _estimate_tokens(text: str) -> int:
    # Rough rule: about 4 characters per token for English and code.
    return len(text) // 4 + 1


def _log(tool: str, model: str, in_tokens: int, seconds: float, ok: bool, note: str = "") -> None:
    try:
        with LOG_FILE.open("a") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": tool, "model": model,
                "in_tokens_est": in_tokens, "seconds": round(seconds, 1), "ok": ok, "note": note,
            }) + "\n")
    except OSError:
        pass  # logging must never break a tool call


def _chat(tool: str, system: str, user: str, model: str = "small",
          max_tokens: int = 2048, temperature: float = 0.3, json_mode: bool = False) -> str:
    if model not in MODELS:
        raise LocalLLMError(f"Unknown model '{model}'. Use one of: {', '.join(MODELS)}.")
    model_id, max_in = MODELS[model]

    in_tokens = _estimate_tokens(system) + _estimate_tokens(user)
    if in_tokens > max_in:
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
        _log(tool, model_id, in_tokens, time.monotonic() - start, False, f"http {e.code}")
        raise LocalLLMError(f"Ollama returned HTTP {e.code}: {detail}. Do this task yourself.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        _log(tool, model_id, in_tokens, time.monotonic() - start, False, type(e).__name__)
        raise LocalLLMError(
            f"Local model unavailable ({e}). Ollama may be stopped, out of memory, or too slow. "
            "Do this task yourself."
        ) from e

    seconds = time.monotonic() - start
    text = (data.get("message") or {}).get("content", "").strip()
    if not text:
        _log(tool, model_id, in_tokens, seconds, False, "empty answer")
        raise LocalLLMError("Local model returned an empty answer. Do this task yourself.")

    _log(tool, model_id, in_tokens, seconds, True)
    return text


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
