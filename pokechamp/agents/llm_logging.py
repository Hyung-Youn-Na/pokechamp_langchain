"""LLM prompt/output logging callback for LangGraph agents.

Provides ``LLMLoggingCallback`` — a LangChain ``BaseCallbackHandler``
that intercepts every LLM call made inside a LangGraph graph and writes
structured JSON logs to a file, matching the ``llm_log.jsonl`` format
used by ``LLMPlayer._log_llm_call()``.

Usage::

    from pokechamp.agents.llm_logging import LLMLoggingCallback

    callback = LLMLoggingCallback(
        log_dir="./battle_log/langchain",
        battle_tag="battle-gen9ou-12345",
        turn=5,
    )
    result = graph.invoke(state, config={"callbacks": [callback]})

The callback writes one line per LLM call to ``{log_dir}/langgraph_llm_log.jsonl``.
"""

from __future__ import annotations

import datetime
import json
import os
import threading
from typing import Any, Dict, List, Optional, Sequence, Union

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import LLMResult


def _messages_to_dict(messages: Sequence[BaseMessage]) -> List[Dict[str, Any]]:
    """Convert LangChain messages to a serialisable list of dicts."""
    result = []
    for msg in messages:
        entry: Dict[str, Any] = {
            "role": msg.type,  # "system", "human", "ai", "tool"
            "content": msg.content,
        }
        if isinstance(msg, AIMessage) and msg.tool_calls:
            entry["tool_calls"] = msg.tool_calls
        if isinstance(msg, ToolMessage):
            entry["tool_call_id"] = msg.tool_call_id
            entry["name"] = msg.name
        result.append(entry)
    return result


class LLMLoggingCallback(BaseCallbackHandler):
    """LangChain callback that logs every LLM prompt and response.

    Thread-safe — uses a lock around file writes so concurrent agent
    nodes don't interleave output.
    """

    def __init__(
        self,
        log_dir: str,
        battle_tag: str = "",
        turn: int = 0,
        log_file_name: str = "langgraph_llm_log.jsonl",
    ):
        """
        Args:
            log_dir: Directory to write the log file into.
            battle_tag: Current battle identifier.
            turn: Current turn number.
            log_file_name: Name of the JSONL log file.
        """
        self.log_dir = log_dir
        self.battle_tag = battle_tag
        self.turn = turn
        self.log_file_name = log_file_name
        self._lock = threading.Lock()
        self._call_counter = 0

        # Stash prompts from on_llm_start so on_llm_end can pair them
        self._pending_prompts: Dict[str, List[str]] = {}

        # Ensure log directory exists
        os.makedirs(self.log_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Callback interface
    # ------------------------------------------------------------------

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Called when an LLM invocation starts. Store the prompts."""
        run_key = str(run_id) if run_id else str(len(self._pending_prompts))

        # Also grab messages if available (from invoke with message objects)
        messages = kwargs.get("messages", None)
        self._pending_prompts[run_key] = {
            "prompts_text": prompts,
            "messages": _messages_to_dict(messages) if messages else None,
            "invocation_params": kwargs.get("invocation_params", {}),
            "start_time": datetime.datetime.now().isoformat(),
        }

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Called when an LLM invocation finishes. Log everything."""
        run_key = str(run_id) if run_id else ""
        pending = self._pending_prompts.pop(run_key, None)

        self._call_counter += 1

        # Extract prompt information
        system_prompt = ""
        user_prompt = ""
        messages_log = None

        if pending:
            messages_log = pending.get("messages")
            start_time = pending.get("start_time", "")

            # Try to extract system/user from messages
            if messages_log:
                for msg in messages_log:
                    if msg.get("role") == "system":
                        system_prompt += msg.get("content", "")
                    elif msg.get("role") == "human":
                        user_prompt += msg.get("content", "")
                # If no messages structure, fall back to prompts_text
            if not system_prompt and not user_prompt:
                prompts_text = pending.get("prompts_text", [])
                if prompts_text:
                    user_prompt = "\n---\n".join(prompts_text)
        else:
            start_time = ""

        # Extract LLM response
        llm_response = ""
        tool_calls_log = []

        if response.generations:
            for gen_list in response.generations:
                for gen in gen_list:
                    msg = gen.message
                    llm_response += msg.content or ""

                    # Capture tool calls from the response
                    if isinstance(msg, AIMessage) and msg.tool_calls:
                        for tc in msg.tool_calls:
                            tool_calls_log.append(
                                {
                                    "name": tc.get("name", ""),
                                    "args": tc.get("args", {}),
                                    "id": tc.get("id", ""),
                                }
                            )

        # Extract token usage
        token_usage = {}
        if response.llm_output and "token_usage" in response.llm_output:
            token_usage = response.llm_output["token_usage"]
        elif response.generations:
            for gen_list in response.generations:
                for gen in gen_list:
                    msg = gen.message
                    if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                        token_usage = {
                            "prompt_tokens": msg.usage_metadata.get(
                                "input_tokens", 0
                            ),
                            "completion_tokens": msg.usage_metadata.get(
                                "output_tokens", 0
                            ),
                            "total_tokens": msg.usage_metadata.get("total_tokens", 0),
                        }

        # Build the log entry — compatible with LLMPlayer._log_llm_call format
        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "start_time": start_time,
            "battle_tag": self.battle_tag,
            "turn": self.turn,
            "llm_call_in_turn": self._call_counter,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "llm_response": llm_response,
            "tool_calls": tool_calls_log if tool_calls_log else None,
            "token_usage": token_usage if token_usage else None,
            "messages_full": messages_log,  # Complete message history for debugging
        }

        self._write_log(log_entry)

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Log LLM errors."""
        run_key = str(run_id) if run_id else ""
        self._pending_prompts.pop(run_key, None)

        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "battle_tag": self.battle_tag,
            "turn": self.turn,
            "error": str(error),
            "error_type": type(error).__name__,
        }
        self._write_log(log_entry)

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Log tool invocations for full traceability."""
        tool_name = serialized.get("name", kwargs.get("name", "unknown"))

        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "battle_tag": self.battle_tag,
            "turn": self.turn,
            "tool_call": {
                "tool": tool_name,
                "input": input_str if isinstance(input_str, str) else str(input_str),
            },
        }
        self._write_log(log_entry, file_name="langgraph_tool_log.jsonl")

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Log tool outputs."""
        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "battle_tag": self.battle_tag,
            "turn": self.turn,
            "tool_result": output if isinstance(output, str) else str(output),
        }
        self._write_log(log_entry, file_name="langgraph_tool_log.jsonl")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _write_log(
        self, entry: Dict[str, Any], file_name: Optional[str] = None
    ) -> None:
        """Append a JSON log entry to the log file (thread-safe)."""
        fname = file_name or self.log_file_name
        log_path = os.path.join(self.log_dir, fname)
        with self._lock:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
