"""
Model client with routing, for three providers.

    THESIS_PROVIDER = anthropic | openai | openrouter
    (if unset: whichever of ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY is set, in that order)

Bulk, structured work goes to the fast model; synthesis goes to the deep one.
Pin either with THESIS_MODEL_FAST / THESIS_MODEL_DEEP.

Every provider's search returns (text, citations). A citation's "cited_text" is
only ever text taken from the source page (Anthropic's search quotes, or
OpenRouter's page excerpts), never the model's own sentence, so the source
check can't be satisfied by the model quoting itself.
"""

import json
import os
import urllib.request
from typing import Optional

DEFAULT_MODELS = {
    "anthropic": ("claude-sonnet-5-5", "claude-opus-5-5"),
    "openai": ("gpt-5-mini", "gpt-5"),
    "openrouter": ("anthropic/claude-sonnet-4.5", "anthropic/claude-opus-4.1"),
}


def provider() -> str:
    p = (os.environ.get("THESIS_PROVIDER") or "").strip().lower()
    if p:
        return p
    for name, key in (("anthropic", "ANTHROPIC_API_KEY"), ("openai", "OPENAI_API_KEY"), ("openrouter", "OPENROUTER_API_KEY")):
        if os.environ.get(key):
            return name
    return "anthropic"


_fast, _deep = DEFAULT_MODELS.get(provider(), DEFAULT_MODELS["anthropic"])
FAST = os.environ.get("THESIS_MODEL_FAST", _fast)
DEEP = os.environ.get("THESIS_MODEL_DEEP", _deep)

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
    """Anthropic: Messages API with the web search tool."""

    def __init__(self):
        import anthropic
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


def _post(url: str, key: str, body: dict, extra: dict | None = None, timeout: int = 180) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json", **(extra or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


class _Shared:
    def complete_json(self, task_type: str, system: str, prompt: str, max_tokens: int = 4096):
        return _extract_json(self.complete(task_type, system, prompt, max_tokens))

    def search_and_summarise(self, query: str, task_type: str = "enrich",
                             system: str = "You are a research analyst. Return concise, factual findings.",
                             prompt_template: Optional[str] = None) -> str:
        text, _ = self.search(prompt_template.format(query=query) if prompt_template else query,
                              task_type=task_type, system=system)
        return text


class OpenAIClient(_Shared):
    """OpenAI: Responses API with its web_search tool. Citations carry URLs only."""
    URL = "https://api.openai.com/v1/responses"

    def __init__(self):
        self.key = os.environ["OPENAI_API_KEY"]

    def _call(self, task_type, system, prompt, tools=None, max_tokens=4096):
        body = {"model": MODELS.get(task_type, FAST), "instructions": system, "input": prompt,
                "max_output_tokens": max_tokens}
        if tools:
            body["tools"] = tools
        out = _post(self.URL, self.key, body)
        text, cites = [], []
        for item in out.get("output", []):
            for part in item.get("content", []) or []:
                if part.get("type") == "output_text":
                    text.append(part.get("text", ""))
                    for a in part.get("annotations", []) or []:
                        if a.get("type") == "url_citation" and a.get("url"):
                            cites.append({"url": a["url"], "title": a.get("title", ""), "cited_text": ""})
        return "".join(text), cites

    def complete(self, task_type, system, prompt, max_tokens=4096, temperature=0.3):
        return self._call(task_type, system, prompt, max_tokens=max_tokens)[0]

    def search(self, prompt, task_type="enrich", system="You are a research analyst.", max_tokens=4096):
        return self._call(task_type, system, prompt, tools=[{"type": "web_search"}], max_tokens=max_tokens)


class OpenRouterClient(_Shared):
    """OpenRouter: any model, with the web plugin. Citations carry the page excerpt it retrieved."""
    URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self):
        self.key = os.environ["OPENROUTER_API_KEY"]

    def _call(self, task_type, system, prompt, web=False, max_tokens=4096, temperature=0.3):
        body = {"model": MODELS.get(task_type, FAST), "max_tokens": max_tokens, "temperature": temperature,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        if web:
            body["plugins"] = [{"id": "web", "max_results": 5}]
        out = _post(self.URL, self.key, body, {"X-Title": "thesis-agent"})
        msg = (out.get("choices") or [{}])[0].get("message", {})
        cites = []
        for a in msg.get("annotations", []) or []:
            c = a.get("url_citation") or {}
            if c.get("url"):
                cites.append({"url": c["url"], "title": c.get("title", ""), "cited_text": c.get("content", "") or ""})
        return msg.get("content") or "", cites

    def complete(self, task_type, system, prompt, max_tokens=4096, temperature=0.3):
        return self._call(task_type, system, prompt, max_tokens=max_tokens, temperature=temperature)[0]

    def search(self, prompt, task_type="enrich", system="You are a research analyst.", max_tokens=4096):
        return self._call(task_type, system, prompt, web=True, max_tokens=max_tokens)


def get_client():
    return {"anthropic": ClaudeClient, "openai": OpenAIClient, "openrouter": OpenRouterClient}[provider()]()
