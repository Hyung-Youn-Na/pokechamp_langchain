"""
LangChain-based unified LLM backend for PokéChamp.

This module provides a single backend class that supports 50+ LLM providers
through LangChain's ``init_chat_model`` interface, replacing the need for
separate backend files (gpt_player.py, gemini_player.py, etc.).

For **Ollama Cloud** models (e.g. ``ollama/glm-5.1:cloud``), a custom
``OllamaChatModel`` wraps the ``ollama`` Python library with the same
authentication logic as ``OllamaPlayer`` — no ``langchain-ollama``
dependency required.

Usage::

    >>> from pokechamp.langchain_backend import LangChainBackend
    >>> backend = LangChainBackend("openai:gpt-4o")
    >>> player = LLMPlayer(backend="gpt-4o", llm_backend=backend)

    >>> # Ollama Cloud (reads OLLAMA_API_KEY from env)
    >>> backend = LangChainBackend("ollama:glm-5.1:cloud")
    >>> player = LLMPlayer(backend="ollama/glm-5.1:cloud", llm_backend=backend)
"""

import json
import os
import uuid
from typing import Any, Dict, List, Optional, Sequence

import ollama
from langchain.chat_models import init_chat_model
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool

# ---------------------------------------------------------------------------
# Ollama ChatModel — works with Ollama Cloud *and* local Ollama
# ---------------------------------------------------------------------------


def _ollama_client_for_model(model: str) -> ollama.Client:
    """Create an ``ollama.Client`` configured for Cloud or local.

    Mirrors ``OllamaPlayer.__init__``: if ``OLLAMA_API_KEY`` is set the
    client connects to ``https://ollama.com`` with Bearer auth; otherwise
    it falls back to ``http://localhost:11434``.
    """
    ollama_api_key = os.getenv("OLLAMA_API_KEY", "")
    if ollama_api_key:
        client = ollama.Client(
            host="https://ollama.com",
            headers={"Authorization": "Bearer " + ollama_api_key},
        )
        print(f"[OllamaChatModel] Cloud mode — model: {model}")
    else:
        client = ollama.Client(host="http://localhost:11434")
        print(f"[OllamaChatModel] Local mode — model: {model}")
    return client


def _lc_messages_to_ollama(messages: Sequence[BaseMessage]) -> list:
    """Convert LangChain messages to the ollama chat format.

    Handles tool-calling conversations correctly by preserving
    ``tool_call_id`` references on ``ToolMessage`` and including
    tool call details on ``AIMessage`` when present.
    """
    result: list = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            result.append({"role": "system", "content": msg.content})
        elif isinstance(msg, HumanMessage):
            result.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            content = msg.content or ""
            entry: Dict[str, Any] = {"role": "assistant", "content": content}
            # Preserve tool_calls so the Ollama API can correlate them
            # with subsequent ToolMessage responses.
            if msg.tool_calls:
                entry["tool_calls"] = []
                for tc in msg.tool_calls:
                    entry["tool_calls"].append(
                        {
                            "function": {
                                "name": tc.get("name", ""),
                                "arguments": tc.get("args", {}),
                            }
                        }
                    )
            result.append(entry)
        elif isinstance(msg, ToolMessage):
            entry = {"role": "tool", "content": msg.content}
            # Include tool_call_id so the model can match the response
            # to the original tool call.
            if hasattr(msg, "tool_call_id") and msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            result.append(entry)
        else:
            result.append({"role": "user", "content": msg.content})
    return result


def _lc_tools_to_ollama(tools: Sequence[BaseTool]) -> list:
    """Convert LangChain tools to the ollama tool-calling format."""
    ollama_tools: list = []
    for tool in tools:
        schema = tool.get_input_schema().schema()
        # Remove 'title' and other unnecessary keys
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        ollama_tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
        )
    return ollama_tools


class OllamaChatModel(BaseChatModel):
    """LangChain-compatible chat model backed by the ``ollama`` library.

    Supports **Ollama Cloud** (via ``OLLAMA_API_KEY`` env var) and local
    Ollama, matching the authentication logic of ``OllamaPlayer``.
    Tool calling is supported for models that implement it.
    """

    model: str = "llama3.1"
    temperature: float = 0.7
    num_ctx: int = 8192
    num_predict: int = 8192

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "ollama"

    def bind_tools(
        self,
        tools: Sequence[BaseTool],
        **kwargs: Any,
    ) -> "OllamaChatModel":
        """Bind tools so they are passed to ``_generate`` via kwargs."""
        return self.bind(tools=list(tools), **kwargs)

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Invoke the Ollama API and return a LangChain ``ChatResult``."""
        client = _ollama_client_for_model(self.model)
        ollama_messages = _lc_messages_to_ollama(messages)

        options: Dict[str, Any] = {
            "temperature": self.temperature,
            "num_predict": self.num_predict,
            "num_ctx": self.num_ctx,
        }
        if stop:
            options["stop"] = stop

        # Handle bound tools (from .bind_tools())
        ollama_tools = None
        if "tools" in kwargs and kwargs["tools"]:
            ollama_tools = _lc_tools_to_ollama(kwargs["tools"])

        response = client.chat(
            model=self.model,
            messages=ollama_messages,
            tools=ollama_tools,
            options=options,
            think=False,
            stream=False,
        )

        # Extract content
        content = ""
        tool_calls: List[Dict[str, Any]] = []

        if hasattr(response, "message"):
            if hasattr(response.message, "content"):
                content = response.message.content or ""
            # Extract tool calls if present
            if hasattr(response.message, "tool_calls") and response.message.tool_calls:
                for tc in response.message.tool_calls:
                    func = (
                        tc.function
                        if hasattr(tc, "function")
                        else tc.get("function", {})
                    )
                    name = func.name if hasattr(func, "name") else func.get("name", "")
                    args = (
                        func.arguments
                        if hasattr(func, "arguments")
                        else func.get("arguments", {})
                    )
                    tool_calls.append(
                        {
                            "name": name,
                            "args": (
                                args
                                if isinstance(args, dict)
                                else json.loads(args) if isinstance(args, str) else {}
                            ),
                            "id": f"call_{uuid.uuid4().hex[:8]}",
                            "type": "tool_call",
                        }
                    )

        # Build token usage metadata
        usage_metadata: Dict[str, int] = {}
        input_tokens = 0
        output_tokens = 0
        if hasattr(response, "prompt_eval_count") and response.prompt_eval_count:
            input_tokens = int(response.prompt_eval_count)
            usage_metadata["input_tokens"] = input_tokens
        if hasattr(response, "eval_count") and response.eval_count:
            output_tokens = int(response.eval_count)
            usage_metadata["output_tokens"] = output_tokens
        if usage_metadata:
            usage_metadata["total_tokens"] = input_tokens + output_tokens

        ai_message = AIMessage(
            content=content,
            tool_calls=tool_calls,
            usage_metadata=usage_metadata if usage_metadata else None,
        )

        return ChatResult(generations=[ChatGeneration(message=ai_message)])


# ---------------------------------------------------------------------------
# LangChainBackend — unified backend with Ollama support
# ---------------------------------------------------------------------------


def _is_ollama_spec(model_spec: str) -> bool:
    """Return True if the model spec targets the Ollama provider."""
    return model_spec.startswith("ollama:")


class LangChainBackend:
    """Unified LLM backend with transparent Ollama Cloud support.

    Supports any provider that LangChain supports via the
    ``"provider:model"`` naming convention, for example:

    - ``"openai:gpt-4o"``
    - ``"google_genai:gemini-2.5-flash"``
    - ``"ollama:glm-5.1:cloud"``  *(uses OllamaChatModel)*
    - ``"openrouter:anthropic/claude-sonnet-4-5"``

    Ollama models are handled by ``OllamaChatModel`` which reuses the
    same Cloud authentication as ``OllamaPlayer`` (``OLLAMA_API_KEY``
    env var → ``https://ollama.com`` with Bearer token).
    """

    def __init__(
        self,
        model_spec: str,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        **kwargs,
    ):
        """Initialize with a LangChain model specifier.

        Args:
            model_spec: A ``"provider:model"`` string.  Ollama specs
                (``"ollama:..."``) are routed to ``OllamaChatModel``.
            temperature: Sampling temperature passed to the underlying
                model.  Defaults to 0.3.
            max_tokens: Maximum number of tokens the model may generate.
                Defaults to 8192.
            **kwargs: Extra keyword arguments forwarded to
                ``init_chat_model`` (non-Ollama providers only).
        """
        self.model_spec = model_spec
        self.temperature = temperature
        self.max_tokens = max_tokens

        if _is_ollama_spec(model_spec):
            # Extract model name after "ollama:" prefix
            model_name = model_spec[len("ollama:"):]
            self.chat_model = OllamaChatModel(
                model=model_name,
                temperature=temperature,
                num_predict=max_tokens,
            )
        else:
            self.chat_model = init_chat_model(
                model_spec,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

        self.completion_tokens = 0
        self.prompt_tokens = 0

    def get_LLM_action(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = "gpt-4o",
        temperature: float = 0.7,
        json_format: bool = False,
        seed: Optional[int] = None,
        stop: Optional[List[str]] = None,
        max_tokens: int = 200,
        actions=None,
        battle=None,
        ps_client=None,
    ) -> tuple:
        """Call the LLM and return a response tuple.

        Returns the same ``(output_str, json_flag, raw_message)`` tuple as
        ``GPTPlayer.get_LLM_action()``, ensuring drop-in compatibility with
        ``LLMPlayer.get_LLM_action()`` which unpacks exactly these three
        values.
        """
        if stop is None:
            stop = []

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        invoke_kwargs = {}
        if temperature is not None:
            invoke_kwargs["temperature"] = temperature
        if max_tokens is not None:
            invoke_kwargs["max_tokens"] = max_tokens
        if seed is not None:
            invoke_kwargs["seed"] = seed
        if stop:
            invoke_kwargs["stop"] = stop

        # Request JSON output when needed.  LangChain models support
        # ``response_format`` via ``.bind()`` for OpenAI-compatible APIs.
        if json_format:
            invoke_kwargs["response_format"] = {"type": "json_object"}

        response = self.chat_model.invoke(messages, **invoke_kwargs)
        output = response.content

        # Track token usage when available
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            self.completion_tokens += response.usage_metadata.get("output_tokens", 0)
            self.prompt_tokens += response.usage_metadata.get("input_tokens", 0)

        return output, json_format, output

    def get_LLM_query(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        model: str = "gpt-4o",
        json_format: bool = False,
        seed: Optional[int] = None,
        stop: Optional[List[str]] = None,
        max_tokens: int = 200,
    ) -> tuple:
        """Simple LLM query returning ``(message, json_flag)``.

        This mirrors ``GPTPlayer.get_LLM_query()`` for compatibility with
        code paths that use the query interface (e.g. minimax value eval).
        """
        if stop is None:
            stop = []

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        invoke_kwargs = {}
        if temperature is not None:
            invoke_kwargs["temperature"] = temperature
        if max_tokens is not None:
            invoke_kwargs["max_tokens"] = max_tokens
        if seed is not None:
            invoke_kwargs["seed"] = seed
        if stop:
            invoke_kwargs["stop"] = stop

        response = self.chat_model.invoke(messages, **invoke_kwargs)
        message = response.content

        if json_format:
            # Extract first JSON object from response, matching GPTPlayer
            json_start = message.find("{")
            json_end = message.find("}", json_start) + 1
            if json_start >= 0 and json_end > json_start:
                message_json = message[json_start:json_end]
                return message_json, True
            return message, False

        return message, False
