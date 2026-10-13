"""
Claude API client with model routing.

Bulk, structured work goes to the fast model; synthesis goes to the strongest.
Both are overridable with environment variables so a fund can pin versions:
THESIS_MODEL_FAST and THESIS_MODEL_DEEP.
"""

import json
import os
from typing import Optional

import anthropic

FAST = os.environ.get("THESIS_MODEL_FAST", "claude-sonnet-5-5")
DEEP = os.environ.get("THESIS_MODEL_DEEP", "claude-opus-5-5")

MODELS = {
    "evaluate": FAST,     # bulk scoring, structured output
    "enrich": FAST,       # research
    "audit": FAST,        # staleness and simple checks
    "refresh": FAST,      # weekly company refresh (web search)
    "synthesise": DEEP,   # trend synthesis, brief writing
    "promote": DEEP,      # calibrated recommendations
}

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}


def _extract_json(raw: str):
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    first_brace, first_bracket = cleaned.find("{"), cleaned.find("[")
    if first_brace == -1 and first_bracket == -1:
        raise ValueError(f"No JSON found in response: {cleaned[:200]}")
    if first_bracket == -1 or (first_brace != -1 and first_brace < first_bracket):
        cleaned = cleaned[first_brace: cleaned.rfind("}") + 1]
    else:
        cleaned = cleaned[first_bracket: cleaned.rfind("]") + 1]
    return json.loads(cleaned)


class ClaudeClient:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    def complete(self, task_type: str, system: str, prompt: str,
                 max_tokens: int = 4096, temperature: float = 0.3) -> str:
        response = self.client.messages.create(
            model=MODELS.get(task_type, FAST),
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in response.content if getattr(b, "type", "") == "text")

    def complete_json(self, task_type: str, system: str, prompt: str, max_tokens: int = 4096):
        return _extract_json(self.complete(task_type, system, prompt, max_tokens))

    def search(self, prompt: str, task_type: str = "enrich",
               system: str = "You are a research analyst. Return concise, factual findings.",
               max_tokens: int = 4096) -> tuple[str, list[dict]]:
        """
        Run a prompt with Claude's web search tool.

        Returns (text, citations). Each citation is {"url", "title", "cited_text"}:
        the passage the search tool itself quoted from that page. Continues a
        paused turn (long searches) up to three times.
        """
        messages = [{"role": "user", "content": prompt}]
        text_parts, citations = [], []
        for _ in range(4):
            response = self.client.messages.create(
                model=MODELS.get(task_type, FAST),
                max_tokens=max_tokens,
                system=system,
                tools=[WEB_SEARCH_TOOL],
                messages=messages,
            )
            for block in response.content:
                if getattr(block, "type", "") != "text":
                    continue
                text_parts.append(block.text)
                for c in getattr(block, "citations", None) or []:
                    url = getattr(c, "url", None)
                    if url:
                        citations.append({
                            "url": url,
                            "title": getattr(c, "title", "") or "",
                            "cited_text": getattr(c, "cited_text", "") or "",
                        })
            if response.stop_reason != "pause_turn":
                break
            messages = messages + [{"role": "assistant", "content": response.content}]
        return "".join(text_parts), citations

    def search_and_summarise(self, query: str, task_type: str = "enrich",
                             system: str = "You are a research analyst. Return concise, factual findings.",
                             prompt_template: Optional[str] = None) -> str:
        """Backwards-compatible wrapper used by Radar, Events and the enricher."""
        text, _ = self.search(prompt_template.format(query=query) if prompt_template else query,
                              task_type=task_type, system=system)
        return text


def get_client() -> ClaudeClient:
    return ClaudeClient()
