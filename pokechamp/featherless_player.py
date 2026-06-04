from openai import OpenAI
from time import sleep
from openai import RateLimitError
import os
import json

FEATHERLESS_BASE_URL = "https://api.featherless.ai/v1"

# Models that use extended thinking (internal reasoning tokens count toward max_tokens)
THINKING_MODELS = {'deepseek-ai/DeepSeek-V4-Pro', 'deepseek-ai/DeepSeek-V4-Flash'}
THINKING_MODEL_MIN_TOKENS = 8192


class FeatherlessPlayer():
    def __init__(self, api_key="", model='deepseek-ai/DeepSeek-V4-Pro'):
        if api_key == "":
            self.api_key = os.getenv('FEATHERLESS_API_KEY')
        else:
            self.api_key = api_key
        self.model = model
        self.completion_tokens = 0
        self.prompt_tokens = 0

    def _get_effective_max_tokens(self, model, max_tokens):
        if model in THINKING_MODELS and max_tokens < THINKING_MODEL_MIN_TOKENS:
            return THINKING_MODEL_MIN_TOKENS
        return max_tokens

    def get_LLM_action(self, system_prompt, user_prompt, model=None, temperature=0.7, json_format=False, seed=None, stop=[], max_tokens=200, actions=None, battle=None, ps_client=None) -> str:
        if model is None:
            model = self.model
        model = model.removeprefix("featherless/")
        max_tokens = self._get_effective_max_tokens(model, max_tokens)
        client = OpenAI(
            base_url=FEATHERLESS_BASE_URL,
            api_key=self.api_key,
        )

        try:
            if json_format:
                response = client.chat.completions.create(
                    response_format={"type": "json_object"},
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=temperature,
                    stream=False,
                    stop=stop,
                    max_tokens=max_tokens,
                )
            else:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=temperature,
                    stream=False,
                    stop=stop,
                    max_tokens=max_tokens,
                )
        except RateLimitError:
            sleep(5)
            print('featherless rate limit error')
            return self.get_LLM_action(system_prompt, user_prompt, model, temperature, json_format, seed, stop, max_tokens, actions, battle, ps_client)
        except Exception as e:
            print(f'Featherless API error: {e}')
            sleep(2)
            return self.get_LLM_action(system_prompt, user_prompt, model, temperature, json_format, seed, stop, max_tokens, actions, battle, ps_client)

        outputs = response.choices[0].message.content

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

    def get_LLM_query(self, system_prompt, user_prompt, temperature=0.7, model=None, json_format=False, seed=None, stop=[], max_tokens=200):
        if model is None:
            model = self.model
        model = model.removeprefix("featherless/")
        max_tokens = self._get_effective_max_tokens(model, max_tokens)
        client = OpenAI(
            base_url=FEATHERLESS_BASE_URL,
            api_key=self.api_key,
        )

        try:
            output_padding = ''
            if json_format:
                output_padding = '\n{"'

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt + output_padding}
                ],
                temperature=temperature,
                stream=False,
                stop=stop,
                max_tokens=max_tokens,
            )
            message = response.choices[0].message.content
        except RateLimitError:
            sleep(5)
            print('featherless rate limit error')
            return self.get_LLM_query(system_prompt, user_prompt, temperature, model, json_format, seed, stop, max_tokens)
        except Exception as e:
            print(f'Featherless API error: {e}')
            sleep(2)
            return self.get_LLM_query(system_prompt, user_prompt, temperature, model, json_format, seed, stop, max_tokens)

        if json_format:
            json_start = 0
            json_end = message.find('}') + 1
            message_json = '{"' + message[json_start:json_end]
            if len(message_json) > 0:
                return message_json, True
        return message, False
