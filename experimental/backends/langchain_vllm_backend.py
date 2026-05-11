import json
import re
import time
from pathlib import Path
from typing import Optional

import yaml
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from experimental.tracing.langfuse_setup import create_callback_handler

_DEFAULT_CONFIG = {
    "model": "Qwen/Qwen3.6-27B",
    "base_url": "http://172.17.0.1:18043/v1",
    "api_key": "vllm",
    "temperature": 0.7,
    "top_p": 0.8,
    "presence_penalty": 1.5,
    "max_tokens": 32768,
    "json_format": False,
    "seed": None,
    "stop": [],
    "extra_body": {
        "top_k": 20,
        "chat_template_kwargs": {"enable_thinking": False},
    },
    "max_retries": 3,
}


def _load_config(config_path: str) -> dict:
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.DOTALL)


def _strip_thinking(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


class LangChainVLLMBackend:
    """LLM backend using LangChain ChatOpenAI connected to a vLLM server.

    Implements the same interface as VLLMPlayer: get_LLM_action() and get_LLM_query().
    Optionally delegates to a LangGraph decision pipeline when use_graph=True.
    """

    def __init__(
        self,
        use_graph: bool = False,
        langfuse_handler=None,
        config_path: Optional[str] = None,
    ):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "langchain_config.yaml"
        cfg = {**_DEFAULT_CONFIG, **_load_config(str(config_path))}

        self.model = cfg["model"]
        self.base_url = cfg["base_url"]
        self.api_key = cfg["api_key"]
        self.default_temperature = cfg["temperature"]
        self.default_max_tokens = cfg["max_tokens"]
        self.default_json_format = cfg["json_format"]
        self.default_seed = cfg.get("seed")
        self.default_stop = cfg.get("stop", [])
        self.extra_body = cfg.get("extra_body", {})
        self.max_retries = cfg.get("max_retries", 3)

        self.completion_tokens = 0
        self.prompt_tokens = 0

        self.use_graph = use_graph
        self.langfuse_handler = langfuse_handler or create_callback_handler()

        llm_kwargs = dict(
            model=self.model,
            base_url=self.base_url,
            api_key=self.api_key,
            temperature=self.default_temperature,
        )
        if self.extra_body:
            llm_kwargs["extra_body"] = self.extra_body
        self._llm = ChatOpenAI(**llm_kwargs)

        self._node_llms: dict[str, ChatOpenAI] = {}
        node_overrides = cfg.pop("nodes", {}) or {}
        for node_name, overrides in node_overrides.items():
            node_cfg = {**llm_kwargs, **overrides}
            self._node_llms[node_name] = ChatOpenAI(**node_cfg)

        self._graph = None
        if use_graph:
            from experimental.graph.battle_graph import create_battle_graph

            self._graph = create_battle_graph(max_retries=self.max_retries)

        self._experiment_name = "langchain_experiment"
        self._battle_num = 0
        self._turn_count = 0
        self._session_id: str | None = None
        self._trace_tags: list[str] = []
        self._trace_metadata: dict = {}
        self._latencies: list[float] = []

    def set_battle_context(self, battle_num: int, experiment_name: str | None = None, metadata: dict | None = None):
        if experiment_name:
            self._experiment_name = experiment_name
        self._battle_num = battle_num
        self._turn_count = 0
        self._session_id = f"{self._experiment_name}_battle_{battle_num:03d}"
        self._trace_tags = [self._experiment_name, f"battle_{battle_num:03d}"]
        self._trace_metadata = {
            "experiment": self._experiment_name,
            "battle_number": str(battle_num),
            "model": self.model,
            **(metadata or {}),
        }
        self._latencies = []

    def _new_turn_handler(self) -> object:
        self._turn_count += 1
        return create_callback_handler()

    def _build_config(self, handler=None) -> dict:
        if handler is None:
            handler = self.langfuse_handler
        config = {
            "callbacks": [handler],
            "tags": self._trace_tags,
            "metadata": self._trace_metadata,
        }
        return config

    def _invoke(self, messages, temperature=None, max_tokens=None, stop=None, seed=None, config=None):
        if max_tokens is None:
            max_tokens = self.default_max_tokens
        bind_kwargs = {"max_tokens": max_tokens}
        if temperature is not None:
            bind_kwargs["temperature"] = temperature
        if stop is not None:
            bind_kwargs["stop"] = stop
        if seed is not None:
            bind_kwargs["seed"] = seed
        llm = self._llm.bind(**bind_kwargs)
        t0 = time.monotonic()
        resp = llm.invoke(
            messages,
            config=config or self._build_config(),
        )
        self._latencies.append(time.monotonic() - t0)
        self._track_tokens(resp)
        return resp

    def _track_tokens(self, resp):
        usage = getattr(resp, "usage_metadata", None) or {}
        if isinstance(usage, dict):
            self.completion_tokens += usage.get("output_tokens", 0)
            self.prompt_tokens += usage.get("input_tokens", 0)
        elif hasattr(resp, "response_metadata"):
            token_usage = resp.response_metadata.get("token_usage", {})
            self.completion_tokens += token_usage.get("completion_tokens", 0)
            self.prompt_tokens += token_usage.get("prompt_tokens", 0)

    def get_LLM_action(
        self,
        system_prompt,
        user_prompt,
        model,
        temperature=None,
        json_format=None,
        seed=None,
        stop=None,
        max_tokens=None,
        actions=None,
        battle=None,
        ps_client=None,
    ):
        if temperature is None:
            temperature = self.default_temperature
        if max_tokens is None:
            max_tokens = self.default_max_tokens
        if json_format is None:
            json_format = self.default_json_format
        if stop is None:
            stop = self.default_stop
        if seed is None:
            seed = self.default_seed

        turn_handler = self._new_turn_handler()

        if self.use_graph and self._graph is not None:
            return self._invoke_graph(
                system_prompt, user_prompt, model, temperature,
                json_format, max_tokens, actions, turn_handler,
            )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        resp = self._invoke(messages, max_tokens=max_tokens, config=self._build_config(turn_handler))
        outputs = _strip_thinking(resp.content)

        if json_format:
            return self._extract_json(outputs)

        return outputs, False, outputs

    def _invoke_graph(
        self, system_prompt, user_prompt, model, temperature,
        json_format, max_tokens, actions, turn_handler,
    ):
        initial_state = {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "model": self.model,
            "temperature": temperature,
            "json_format": json_format,
            "max_tokens": max_tokens,
            "actions": actions,
            # New structured node outputs
            "battlefield_report": None,
            "role_analysis": None,
            "matchup_assessment": None,
            "damage_evaluation": None,
            "tactical_plans": None,
            "opponent_prediction": None,
            "plan_evaluation": None,
            # Legacy fields (backward compat)
            "battle_analysis": None,
            "candidate_moves": None,
            "evaluation_notes": None,
            "final_action": None,
            "raw_outputs": [],
            "retry_count": 0,
            "needs_revision": False,
            # Backend-injected
            "llm": self._llm,
            "_track_tokens_fn": self._track_tokens,
            "node_llms": self._node_llms,
        }
        t0 = time.monotonic()
        result = self._graph.invoke(initial_state, config=self._build_config(turn_handler))
        self._latencies.append(time.monotonic() - t0)
        action = result.get("final_action", "")
        action = _strip_thinking(action)

        if json_format:
            return self._extract_json(action)
        return action, False, action

    def _extract_json(self, text: str):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            json_content = text[start : end + 1]
            try:
                json.loads(json_content)
                return json_content, True, text
            except json.JSONDecodeError:
                return text, True, text
        return text, True, text

    def get_LLM_query(
        self,
        system_prompt,
        user_prompt,
        temperature=None,
        model=None,
        json_format=None,
        seed=None,
        stop=None,
        max_tokens=None,
    ):
        if temperature is None:
            temperature = self.default_temperature
        if json_format is None:
            json_format = self.default_json_format
        if max_tokens is None:
            max_tokens = self.default_max_tokens

        user_content = user_prompt
        if json_format:
            user_content += '\n{"'

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ]

        resp = self._invoke(messages, max_tokens=max_tokens, config=self._build_config())
        message = _strip_thinking(resp.content)

        if json_format:
            json_end = message.find("}") + 1
            message_json = '{"' + message[:json_end]
            if len(message_json) > 0:
                return message_json, True
        return message, False
