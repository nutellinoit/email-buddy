"""
LLM provider abstraction using LiteLLM for unified access to
Ollama, LM Studio, and any OpenAI-compatible backend.
"""

import logging
from typing import Any, Dict, List, Optional, Type, TypeVar

import instructor
import litellm
from pydantic import BaseModel

from ..config import config

logger = logging.getLogger(__name__)

# Suppress verbose LiteLLM logging
litellm.suppress_debug_info = True


def _get_litellm_params() -> Dict[str, Any]:
    """Build LiteLLM completion parameters from application config."""
    return {
        "model": config.LITELLM_MODEL,
        "api_base": config.LITELLM_API_BASE,
        "api_key": config.LITELLM_API_KEY,
        "timeout": config.LITELLM_TIMEOUT,
    }


def get_model_name() -> str:
    """Return the resolved model name for logging."""
    return _get_litellm_params()["model"]


def is_llm_available() -> bool:
    """Check provider availability with a lightweight completion call."""
    try:
        params = _get_litellm_params()
        response = litellm.completion(
            model=params["model"],
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
            timeout=10,
            api_base=params.get("api_base"),
            api_key=params.get("api_key"),
        )
        return bool(response.choices)
    except Exception as e:
        logger.error(f"LLM availability check failed: {e}")
        return False


def llm_complete(
    messages: List[Dict[str, str]],
    temperature: float = 0.1,
    max_tokens: int = 500,
    system_prompt: Optional[str] = None,
) -> Optional[str]:
    """
    Get a completion from the configured LLM provider via LiteLLM.

    Args:
        messages: List of message dicts with 'role' and 'content'.
        temperature: Sampling temperature (0.0-1.0).
        max_tokens: Maximum tokens in the response.
        system_prompt: Optional system prompt prepended to messages.

    Returns:
        The completion text, or None on error.
    """
    try:
        params = _get_litellm_params()

        # Prepend system prompt if provided
        full_messages: List[Dict[str, str]] = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        response = litellm.completion(
            model=params["model"],
            messages=full_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            api_base=params.get("api_base"),
            api_key=params.get("api_key"),
            timeout=params.get("timeout"),
        )

        if response.choices:
            return response.choices[0].message.content

        logger.error("Empty response from LLM")
        return None

    except Exception as e:
        logger.error(f"LLM completion failed: {e}")
        return None


T = TypeVar("T", bound=BaseModel)


def llm_complete_structured(
    response_model: Type[T],
    messages: List[Dict[str, str]],
    temperature: float = 0.1,
    max_tokens: int = 500,
    system_prompt: Optional[str] = None,
    max_retries: int = 2,
) -> Optional[T]:
    """
    Get a structured completion from the configured LLM provider.

    Uses Instructor + LiteLLM to return a validated Pydantic model.

    Args:
        response_model: Pydantic model class for the expected response.
        messages: List of message dicts with 'role' and 'content'.
        temperature: Sampling temperature (0.0-1.0).
        max_tokens: Maximum tokens in the response.
        system_prompt: Optional system prompt prepended to messages.
        max_retries: Number of retries on validation failure.

    Returns:
        An instance of response_model, or None on error.
    """
    try:
        params = _get_litellm_params()

        full_messages: List[Dict[str, str]] = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        client = instructor.from_litellm(litellm.completion, mode=instructor.Mode.TOOLS)

        result = client.chat.completions.create(
            model=params["model"],
            messages=full_messages,
            response_model=response_model,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            api_base=params.get("api_base"),
            api_key=params.get("api_key"),
            timeout=params.get("timeout"),
        )

        return result

    except Exception as e:
        logger.error(f"Structured LLM completion failed: {e}")
        return None


class _ProbeResponse(BaseModel):
    """Minimal schema used to verify structured output capability at startup."""

    value: str


def verify_llm_structured_output() -> None:
    """Probe call to verify Instructor TOOLS mode works with the configured model.

    Sends a minimal structured completion request. If the model cannot produce
    a valid tool call response, raises RuntimeError so the app can fail fast.

    Raises:
        RuntimeError: If the model does not support structured output via TOOLS mode.
    """
    try:
        result = llm_complete_structured(
            _ProbeResponse,
            messages=[{"role": "user", "content": "Reply with value 'ok'"}],
            temperature=0.0,
            max_tokens=20,
            max_retries=1,
        )
        if result is None or not result.value:
            raise RuntimeError(
                f"Model {get_model_name()} failed structured output probe. "
                "Ensure the model supports tool/function calling."
            )
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(
            f"Model {get_model_name()} does not support TOOLS mode: {e}. "
            "Try a model with native tool calling support (e.g. llama3.1:8b)."
        ) from e
