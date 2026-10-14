"""
Thin wrapper around the Gemini API. Kept as one function so swapping
providers later (Groq, local Ollama, etc.) is a one-file change.
"""

import json
import os
import re

from pathlib import Path
import google.generativeai as genai
from dotenv import load_dotenv

# Ensure .env is loaded regardless of working directory
_backend_dir = Path(__file__).resolve().parent
_env_path = _backend_dir / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path)
load_dotenv(dotenv_path=_backend_dir.parent / ".env")
load_dotenv()

_configured = False


def _ensure_configured():
    global _configured
    if not _configured:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            # Try reloading directly from backend/.env
            if _env_path.exists():
                load_dotenv(dotenv_path=_env_path, override=True)
                api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY not set. Copy backend/.env.example to backend/.env "
                "and add a free key from https://aistudio.google.com/apikey"
            )
        genai.configure(api_key=api_key)
        _configured = True


DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
FALLBACK_MODELS = [DEFAULT_MODEL, "gemini-3.5-flash-lite", "gemini-flash-latest", "gemini-3.8-flash", "gemini-2.5-pro"]


def _generate_with_fallback(prompt: str, preferred_model: str = None):
    _ensure_configured()
    candidates = [preferred_model] if preferred_model else []
    for m in FALLBACK_MODELS:
        if m not in candidates:
            candidates.append(m)

    last_exc = None
    for model_name in candidates:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response
        except Exception as e:
            last_exc = e
            err_msg = str(e).lower()
            # If model is deprecated, not found (404), or quota-limited (429), try next candidate
            if (
                "not found" in err_msg
                or "no longer available" in err_msg
                or "404" in err_msg
                or "429" in err_msg
                or "quota" in err_msg
                or "resource_exhausted" in err_msg
            ):
                continue
            raise e

    if last_exc:
        raise last_exc
    raise RuntimeError("Failed to generate content with available Gemini models.")


def ask_gemini(question, context_snippets, model_name=None):
    _ensure_configured()

    blocks = []
    for s in context_snippets:
        block = f"### {s['qualified_name']}  ({s['file']}:{s['start_line']})\n```python\n{s['source']}\n```"
        history = s.get("history") or []
        if history:
            hist_lines = "\n".join(
                f"- {h['commit']} · {h['author']} · {h['date'][:10]}: {h['message']}"
                for h in history
            )
            block += f"\n\nRecent commit history for this function:\n{hist_lines}"
        blocks.append(block)
    context_text = "\n\n".join(blocks)

    prompt = f"""You are a senior engineer explaining an unfamiliar codebase to a new teammate.
Use ONLY the code excerpts and commit history below — do not invent commits or functions that
aren't shown. When commit history is available and the question is a "why" question, ground your
answer in the actual commit messages rather than guessing at intent. Be concise and concrete, and
reference function names directly.

CODE EXCERPTS:
{context_text}

QUESTION: {question}

ANSWER:"""

    response = _generate_with_fallback(prompt, preferred_model=model_name or DEFAULT_MODEL)
    return response.text


def select_relevant_components(prompt, model_name=None):
    """
    Stage 1 retrieval: ask the LLM to identify which repository components
    are relevant to a user question.  Expects the prompt to request JSON
    output.  Parses the model's response and returns a dict with lists of
    files, functions, classes, constants, and imports.
    """
    _ensure_configured()
    response = _generate_with_fallback(prompt, preferred_model=model_name or DEFAULT_MODEL)
    text = response.text.strip()

    # Strip markdown code fences if the model wrapped its JSON in them
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```\s*$', '', text)

    # Find JSON object boundaries (handles leading/trailing prose)
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    result = json.loads(text)

    # Ensure all expected keys exist and are lists
    for key in ("files", "functions", "classes", "constants", "imports"):
        if key not in result or not isinstance(result[key], list):
            result[key] = []

    return result


def generate_response(prompt, model_name=None):
    """
    Send a fully-assembled prompt to Gemini and return the text response.
    Used as the final answering step after the retrieval pipeline has
    constructed a focused context.
    """
    _ensure_configured()
    response = _generate_with_fallback(prompt, preferred_model=model_name or DEFAULT_MODEL)
    return response.text
