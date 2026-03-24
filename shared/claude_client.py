"""
Claude API client with model routing.
Routes to Sonnet for bulk evaluation, Opus for synthesis and briefs.
"""

import os
import json
import anthropic
from typing import Optional


# Model routing: use the right model for the right job
MODELS = {
    "evaluate": "claude-sonnet-4-6",       # Bulk evaluation, structured output
    "enrich": "claude-sonnet-4-6",          # Research tasks
    "synthesise": "claude-opus-4-6",        # Trend synthesis, brief writing
    "audit": "claude-sonnet-4-6",           # Simple checks
    "promote": "claude-opus-4-6",           # Nuanced recommendations
}


class ClaudeClient:
    def __init__(self):
        self.client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )

    def complete(
        self,
        task_type: str,
        system: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> str:
        """Send a completion request routed to the appropriate model."""
        model = MODELS.get(task_type, "claude-sonnet-4-6")

        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )

        return response.content[0].text

    def complete_json(
        self,
        task_type: str,
        system: str,
        prompt: str,
        max_tokens: int = 4096,
    ) -> dict | list:
        """Send a completion request and parse JSON from response."""
        raw = self.complete(task_type, system, prompt, max_tokens)

        # Strip markdown fences and leading/trailing whitespace aggressively
        cleaned = raw.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        # Extract just the JSON object/array — Claude sometimes prepends newlines or text
        first_brace = cleaned.find("{")
        first_bracket = cleaned.find("[")
        if first_brace == -1 and first_bracket == -1:
            raise ValueError(f"No JSON object or array found in response: {cleaned[:200]}")
        if first_bracket == -1 or (first_brace != -1 and first_brace < first_bracket):
            start = first_brace
            end = cleaned.rfind("}") + 1
        else:
            start = first_bracket
            end = cleaned.rfind("]") + 1
        cleaned = cleaned[start:end]

        return json.loads(cleaned)

    def search_and_summarise(
        self,
        query: str,
        task_type: str = "enrich",
        system: str = "You are a research analyst. Return concise, factual findings.",
        prompt_template: Optional[str] = None,
    ) -> str:
        """
        Use Claude with web search tool to find and summarise information.
        This is the primary research mechanism for all agents.
        """
        model = MODELS.get(task_type, "claude-sonnet-4-6")

        if prompt_template:
            user_msg = prompt_template.format(query=query)
        else:
            user_msg = query

        response = self.client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": user_msg}],
        )

        # Extract text from response (may include search result blocks)
        text_parts = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)

        return "\n".join(text_parts)


def get_client() -> ClaudeClient:
    """Factory function for the Claude client."""
    return ClaudeClient()
