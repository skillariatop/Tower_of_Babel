"""
Unified LLM adapter — single interface for OpenRouter (cloud) and Ollama (local).
Provider is selected by settings.llm_provider ("openrouter" | "ollama").

Usage:
    from orchestrator.llm import llm
    text = await llm.complete("Your prompt here")
    obj  = await llm.complete_json("Return JSON: ...", schema_hint="...")
"""

import json
import logging
from typing import Any

import httpx

from bot.config import settings

log = logging.getLogger("tower.llm")

_SYSTEM_PROMPT = """You are the AI Orchestrator for Tower of Babel — an open-source
collaborative development system. Your job is to help decompose community decisions
into concrete GitHub Issues, summarize discussions, and assist with project management.

Rules you must follow:
- You assist humans; you do not make governance decisions.
- Always return well-structured, actionable output.
- Be concise. Developers read fast.
- When returning JSON, return ONLY valid JSON with no markdown fences."""


class LLMAdapter:
    async def complete(self, prompt: str, system: str | None = None) -> str:
        sys_prompt = system or _SYSTEM_PROMPT
        if settings.llm_provider == "ollama":
            return await self._ollama(sys_prompt, prompt)
        return await self._openrouter(sys_prompt, prompt)

    async def complete_json(
        self, prompt: str, system: str | None = None
    ) -> Any:
        raw = await self.complete(prompt, system)
        # Strip accidental markdown fences
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            log.error("LLM returned invalid JSON: %s\nRaw: %s", exc, raw[:300])
            raise

    # ------------------------------------------------------------------ #
    #  OpenRouter                                                          #
    # ------------------------------------------------------------------ #

    async def _openrouter(self, system: str, user: str) -> str:
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "HTTP-Referer": "https://github.com/skillariatop/Tower_of_Babel",
                    "X-Title": "Tower of Babel Orchestrator",
                },
                json={
                    "model": settings.openrouter_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.3,
                },
            )
            r.raise_for_status()
            data = r.json()
        content: str = data["choices"][0]["message"]["content"]
        log.debug("OpenRouter response (%d chars)", len(content))
        return content

    # ------------------------------------------------------------------ #
    #  Ollama                                                              #
    # ------------------------------------------------------------------ #

    async def _ollama(self, system: str, user: str) -> str:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{settings.ollama_base_url}/api/chat",
                json={
                    "model": settings.ollama_model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "options": {"temperature": 0.3},
                },
            )
            r.raise_for_status()
            data = r.json()
        content: str = data["message"]["content"]
        log.debug("Ollama response (%d chars)", len(content))
        return content


llm = LLMAdapter()
