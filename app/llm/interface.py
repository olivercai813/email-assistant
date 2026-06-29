"""Configurable LLM interface supporting OpenAI, Anthropic, Grok, and Gemini."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from app.config import LLMProvider, Settings
from app.utils.logging import get_logger
from app.utils.retry import with_retry

logger = get_logger(__name__)


class LLMInterface(ABC):
    """Abstract interface for structured LLM calls."""

    @abstractmethod
    def invoke_structured(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Invoke the LLM and return parsed JSON."""


class _LangChainLLM(LLMInterface):
    """LangChain-backed LLM implementation."""

    def __init__(self, chat_model: Any, settings: Settings) -> None:
        self._model = chat_model
        self._settings = settings

    @with_retry(
        attempts=3,
        delay=2.0,
        exceptions=(Exception,),
    )
    def invoke_structured(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = self._model.invoke(messages)
        content = response.content

        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )

        return _parse_json_response(str(content))


def get_llm(settings: Settings) -> LLMInterface:
    """Factory for the configured LLM provider."""
    if settings.llm_provider == LLMProvider.OPENAI:
        logger.info("Using OpenAI model: %s", settings.openai_model)
        model = ChatOpenAI(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            temperature=0.2,
        )
    elif settings.llm_provider == LLMProvider.ANTHROPIC:
        logger.info("Using Anthropic model: %s", settings.anthropic_model)
        model = ChatAnthropic(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            temperature=0.2,
        )
    elif settings.llm_provider == LLMProvider.GROK:
        logger.info("Using Grok model: %s", settings.grok_model)
        model = ChatOpenAI(
            api_key=settings.grok_api_key,
            base_url=settings.grok_base_url,
            model=settings.grok_model,
            temperature=0.2,
        )
    elif settings.llm_provider == LLMProvider.GEMINI:
        logger.info("Using Gemini model: %s", settings.gemini_model)
        model = ChatGoogleGenerativeAI(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            temperature=0.2,
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")

    return _LangChainLLM(model, settings)


def _parse_json_response(text: str) -> dict[str, Any]:
    """Extract and parse JSON from an LLM response."""
    cleaned = text.strip()

    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise ValueError(f"LLM did not return valid JSON: {text[:200]}...")
