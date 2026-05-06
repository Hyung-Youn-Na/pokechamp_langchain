from openai import OpenAI
from time import sleep
from pathlib import Path
import os
import json
import re
import yaml


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
}


def _load_config(config_path):
    path = Path(config_path)
    if path.exists():
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


class VLLMPlayer():
    def __init__(self, model=None, base_url=None, device=None, config_path=None):
        # Resolve config path relative to this file's directory
        if config_path is None:
            config_path = Path(__file__).parent / "vllm_config.yaml"

        cfg = {**_DEFAULT_CONFIG, **_load_config(config_path)}

        self.model = model if model is not None else cfg["model"]
        self.base_url = base_url if base_url is not None else cfg["base_url"]
        self.api_key = cfg["api_key"]
        self.default_temperature = cfg["temperature"]
        self.default_top_p = cfg.get("top_p")
        self.default_presence_penalty = cfg.get("presence_penalty")
        self.default_max_tokens = cfg["max_tokens"]
        self.default_json_format = cfg["json_format"]
        self.default_seed = cfg["seed"]
        self.default_stop = cfg["stop"]
        self.default_extra_body = cfg.get("extra_body")
        self.completion_tokens = 0
        self.prompt_tokens = 0

    def _strip_thinking(self, text):
        """Remove <think...</think tags from Qwen3-style thinking models."""
        return re.sub(r'<think\b[^>]*>.*?</think\s*>', '', text, flags=re.DOTALL).strip()

    def _build_create_kwargs(self, messages, temperature=None, max_tokens=None,
                             stop=None, json_format=None, seed=None):
        if temperature is None:
            temperature = self.default_temperature
        if max_tokens is None:
            max_tokens = self.default_max_tokens
        if json_format is None:
            json_format = self.default_json_format
        if seed is None:
            seed = self.default_seed
        if stop is None:
            stop = self.default_stop

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "stop": stop,
        }
        if self.default_top_p is not None:
            kwargs["top_p"] = self.default_top_p
        if self.default_presence_penalty is not None:
            kwargs["presence_penalty"] = self.default_presence_penalty
        if seed is not None:
            kwargs["seed"] = seed
        if json_format:
            kwargs["response_format"] = {"type": "json_object"}
        if self.default_extra_body:
            kwargs["extra_body"] = self.default_extra_body

        return kwargs

    def get_LLM_action(self, system_prompt, user_prompt, model, temperature=None,
                       json_format=None, seed=None, stop=None, max_tokens=None,
                       actions=None, battle=None, ps_client=None):
        client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )

        try:
            kwargs = self._build_create_kwargs(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                stop=stop,
                json_format=json_format,
                seed=seed,
            )
            response = client.chat.completions.create(**kwargs)
        except Exception as e:
            print(f'vLLM API error: {e}')
            sleep(2)
            return self.get_LLM_action(system_prompt, user_prompt, model, temperature,
                                       json_format, seed, stop, max_tokens,
                                       actions, battle, ps_client)

        outputs = response.choices[0].message.content
        outputs = self._strip_thinking(outputs)

        self.completion_tokens += response.usage.completion_tokens
        self.prompt_tokens += response.usage.prompt_tokens

        if json_format:
            start_idx = outputs.find('{')
            end_idx = outputs.rfind('}')
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_content = outputs[start_idx:end_idx + 1]
                try:
                    json.loads(json_content)
                    return json_content, True, outputs
                except json.JSONDecodeError:
                    return outputs, True, outputs
            else:
                return outputs, True, outputs

        return outputs, False, outputs

    def get_LLM_query(self, system_prompt, user_prompt, temperature=None, model=None,
                      json_format=None, seed=None, stop=None, max_tokens=None):
        client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )

        try:
            user_content = user_prompt
            if json_format is None:
                json_format = self.default_json_format
            if json_format:
                user_content += '\n{"'

            kwargs = self._build_create_kwargs(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                stop=stop,
                json_format=False,
                seed=seed,
            )
            response = client.chat.completions.create(**kwargs)
            message = response.choices[0].message.content
            message = self._strip_thinking(message)
        except Exception as e:
            print(f'vLLM API error: {e}')
            sleep(2)
            return self.get_LLM_query(system_prompt, user_prompt, temperature, model,
                                      json_format, seed, stop, max_tokens)

        if json_format:
            json_start = 0
            json_end = message.find('}') + 1
            message_json = '{"' + message[json_start:json_end]
            if len(message_json) > 0:
                return message_json, True
        return message, False
