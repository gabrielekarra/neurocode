from __future__ import annotations

import os
from typing import Any

DEFAULT_LLM_MODEL = "gpt-4.1-mini"


class LLMError(RuntimeError):
    """Raised when the LLM client cannot complete a request."""


class LLMClient:
    """Minimal wrapper around the OpenAI Chat Completions API used inside NeuroCode."""

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        """
        Initialize the client.

        Raises:
            LLMError: if the API key is missing or the OpenAI SDK is unavailable.
        """

        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise LLMError("OPENAI_API_KEY is required to call the LLM.")
        self.model = model or os.getenv("NEUROCODE_LLM_MODEL") or DEFAULT_LLM_MODEL

        try:
            from openai import OpenAI  # type: ignore
        except Exception as exc:  # pragma: no cover - exercised via failure path
            raise LLMError("The openai package is required to use the LLM client.") from exc

        self._client: Any = OpenAI(api_key=self.api_key)

    def generate(self, prompt: str) -> str:
        """
        Submit a prompt string to the configured ChatGPT model and return the text reply.

        Args:
            prompt: User prompt to send to the model.

        Returns:
            The assistant's reply content as a string.

        Raises:
            LLMError: when the API call fails or the response is malformed.
        """

        if not prompt:
            raise LLMError("Prompt must be a non-empty string.")

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise LLMError(f"LLM call failed: {exc}") from exc

        try:
            message = response.choices[0].message  # type: ignore[assignment]
            content = message.content or ""
        except Exception as exc:
            raise LLMError("Unexpected LLM response format.") from exc

        content = content.strip()
        if not content:
            raise LLMError("LLM returned empty content.")
        return content
