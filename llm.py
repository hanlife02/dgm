# Code adapted from https://github.com/SakanaAI/AI-Scientist/blob/main/ai_scientist/llm.py.
import json
import os
import re

import anthropic
import backoff
import openai

from dgm_config import api_key as _api_key  # dgm-config
from dgm_config import model_entry as _model_entry  # dgm-config

MAX_OUTPUT_TOKENS = 4096
AVAILABLE_LLMS = [
    # Anthropic models
    "claude-3-5-sonnet-20240620",
    "claude-3-5-sonnet-20241022",
    # OpenAI models
    "gpt-4o-mini-2024-07-18",
    "gpt-4o-2024-05-13",
    "gpt-4o-2024-08-06",
    "o1-preview-2024-09-12",
    "o1-mini-2024-09-12",
    "o1-2024-12-17",
    "o3-mini-2025-01-31",
    # OpenRouter models
    "llama3.1-405b",
    # Anthropic Claude models via Amazon Bedrock
    "bedrock/anthropic.claude-3-sonnet-20240229-v1:0",
    "bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0",
    "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
    "bedrock/anthropic.claude-3-haiku-20240307-v1:0",
    "bedrock/anthropic.claude-3-opus-20240229-v1:0",
    "bedrock/us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    # Anthropic Claude models Vertex AI
    "vertex_ai/claude-3-opus@20240229",
    "vertex_ai/claude-3-5-sonnet@20240620",
    "vertex_ai/claude-3-5-sonnet-v2@20241022",
    "vertex_ai/claude-3-sonnet@20240229",
    "vertex_ai/claude-3-haiku@20240307",
    # DeepSeek models
    "deepseek-chat",
    "deepseek-coder",
    "deepseek-reasoner",
]

def create_client(model: str):
    """
    Create and return an LLM client based on the specified model.
    Args:
        model (str): The name of the model to use.
    Returns:
        Tuple[Any, str]: A tuple containing the client instance and the client model name.
    """
    _entry = _model_entry(model)  # dgm-config
    if _entry is not None:
        _provider = _entry.get("provider", "openai_compatible")
        _base_url = _entry.get("base_url") or None
        _kwargs = {"api_key": _api_key(_entry)}
        if _base_url:
            _kwargs["base_url"] = _base_url
        if _provider == "anthropic":
            print(f"Using configured Anthropic-compatible endpoint for {model} ({_base_url}).")
            return anthropic.Anthropic(**_kwargs), model
        print(f"Using configured OpenAI-compatible endpoint for {model} ({_base_url}).")
        return openai.OpenAI(**_kwargs), model
    if model.startswith("claude-"):
        print(f"Using Anthropic API with model {model}.")
        return anthropic.Anthropic(), model
    elif model.startswith("bedrock") and "claude" in model:
        client_model = model.split("/")[-1]
        print(f"Using Amazon Bedrock with model {client_model}.")
        client = anthropic.AnthropicBedrock(
            aws_access_key=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            aws_region=os.getenv("AWS_REGION_NAME"),
        )
        return client, client_model
    elif model.startswith("vertex_ai") and "claude" in model:
        client_model = model.split("/")[-1]
        print(f"Using Vertex AI with model {client_model}.")
        return anthropic.AnthropicVertex(), client_model
    elif 'gpt' in model or model.startswith("o1-") or model.startswith("o3-"):
        print(f"Using OpenAI API with model {model}.")
        return openai.OpenAI(), model
    elif model.startswith("deepseek-"):
        print(f"Using OpenAI API with {model}.")
        client = openai.OpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com"
        )
        return client, model
    elif model == "llama3.1-405b":
        print(f"Using OpenAI API with {model}.")
        client = openai.OpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url="https://openrouter.ai/api/v1"
        ), model
    else:
        raise ValueError(f"Model {model} not supported.")

# Get N responses from a single message, used for ensembling.
@backoff.on_exception(backoff.expo, (openai.RateLimitError, openai.APITimeoutError))
def get_batch_responses_from_llm(
        msg,
        client,
        model,
        system_message,
        print_debug=False,
        msg_history=None,
        temperature=0.75,
        n_responses=1,
):
    if msg_history is None:
        msg_history = []

    if model in [
        "gpt-4o-2024-05-13",
        "gpt-4o-mini-2024-07-18",
        "gpt-4o-2024-08-06",
    ]:
        new_msg_history = msg_history + [{"role": "user", "content": msg}]
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_message},
                *new_msg_history,
            ],
            temperature=temperature,
            max_tokens=MAX_OUTPUT_TOKENS,
            n=n_responses,
            stop=None,
            seed=0,
        )
        content = [r.message.content for r in response.choices]
        new_msg_history = [
            new_msg_history + [{"role": "assistant", "content": c}] for c in content
        ]
    elif model == "llama-3-1-405b-instruct":
        new_msg_history = msg_history + [{"role": "user", "content": msg}]
        response = client.chat.completions.create(
            model="meta-llama/llama-3.1-405b-instruct",
            messages=[
                {"role": "system", "content": system_message},
                *new_msg_history,
            ],
            temperature=temperature,
            max_tokens=MAX_OUTPUT_TOKENS,
            n=n_responses,
            stop=None,
        )
        content = [r.message.content for r in response.choices]
        new_msg_history = [
            new_msg_history + [{"role": "assistant", "content": c}] for c in content
        ]
    else:
        content, new_msg_history = [], []
        for _ in range(n_responses):
            c, hist = get_response_from_llm(
                msg,
                client,
                model,
                system_message,
                print_debug=False,
                msg_history=None,
                temperature=temperature,
            )
            content.append(c)
            new_msg_history.append(hist)

    if print_debug:
        print()
        print("*" * 20 + " LLM START " + "*" * 20)
        for j, msg in enumerate(new_msg_history[0]):
            print(f'{j}, {msg["role"]}: {msg["content"]}')
        print(content)
        print("*" * 21 + " LLM END " + "*" * 21)
        print()

    return content, new_msg_history

@backoff.on_exception(
    backoff.expo,
    (openai.RateLimitError, openai.APITimeoutError, anthropic.RateLimitError, anthropic.APIStatusError),
    max_time=120,
)
def _dgm_tool_specs():
    """dgm-config: OpenAI-style tool schemas for the agent's own tools.

    The gateway's tool-call parser discards parsed calls when the request
    declares no tools, which surfaces as an empty reply with billed tokens.
    Declaring them makes the server return `tool_calls` instead, which the
    code below maps back to <tool_use> blocks.
    """
    try:
        from tools.bash import tool_info as _bash_info
        from tools.edit import tool_info as _editor_info

        specs = [_bash_info(), _editor_info()]
    except Exception:
        return None
    out = []
    for spec in specs:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec["description"],
                    "parameters": spec["input_schema"],
                },
            }
        )
    return out


def get_response_from_llm(
        msg,
        client,
        model,
        system_message,
        print_debug=False,
        msg_history=None,
        temperature=0.7,
):
    if msg_history is None:
        msg_history = []

    _entry = _model_entry(model)  # dgm-config
    if _entry is not None:
        # Config-driven branch: any OpenAI-/Anthropic-compatible endpoint
        # declared in models.json (create_client built the matching client).
        _real_model = _entry.get("model") or model
        _messages = list(msg_history) + [{"role": "user", "content": msg}]
        _temperature = _entry.get("temperature", temperature)
        if _entry.get("provider") == "anthropic":
            _req = {"model": _real_model, "system": system_message, "messages": _messages}
            if _temperature is not None:
                _req["temperature"] = _temperature
            _req["max_tokens"] = _entry.get("max_tokens") or MAX_OUTPUT_TOKENS
            response = client.messages.create(**_req)
            content = response.content[0].text
        else:
            _req = {
                "model": _real_model,
                "messages": [{"role": "system", "content": system_message}] + _messages,
            }
            if _temperature is not None:
                _req["temperature"] = _temperature
            _max_tokens = _entry.get("max_tokens", MAX_OUTPUT_TOKENS)
            if _max_tokens is not None:
                _req["max_tokens"] = _max_tokens
            # dgm-config: declare the agent's tools (see _dgm_tool_specs).
            _tools = _dgm_tool_specs()
            if _tools:
                _req["tools"] = _tools
            response = client.chat.completions.create(**_req)
            _choice = response.choices[0]
            _empty_retries = 0
            _backoff = 1.0
            # dgm-config: the gateway can drop output for tens of minutes; the
            # budget is configurable so long storms are survived instead of
            # silently producing an empty patch.
            _max_empty_retries = int(os.environ.get("DGM_EMPTY_RETRIES", "20"))
            _empty_backoff_max = float(os.environ.get("DGM_EMPTY_BACKOFF_MAX", "30"))
            while (
                not _choice.message.content
                and not getattr(_choice.message, "tool_calls", None)
                and _empty_retries < _max_empty_retries
            ):
                # The gateway has minute-long windows where every reply comes back
                # with content=None (tokens generated but dropped), so space the
                # retries out instead of hammering it (~3 minutes total).
                import time as _time
                _empty_retries += 1
                if _empty_retries == 1:
                    # dgm-config: dump the first empty reply for offline replay.
                    try:
                        import json as _json, os as _os
                        _u = getattr(response, "usage", None)
                        _dump = {
                            "request": _req,
                            "finish_reason": getattr(_choice, "finish_reason", None),
                            "usage": _u.model_dump() if _u else None,
                            "raw": response.model_dump_json(),
                        }
                        _path = _os.path.join("/dgm", "empty_req.json")
                        with open(_path, "w") as _fh:
                            _json.dump(_dump, _fh)
                        print(f"[dgm-config] dumped empty request to {_path}", flush=True)
                    except Exception as _exc:  # noqa: BLE001
                        print(f"[dgm-config] dump failed: {_exc}", flush=True)
                print(
                    "[dgm-config] empty assistant content (finish_reason="
                    f"{getattr(_choice, 'finish_reason', None)}), "
                    f"retry {_empty_retries}/{_max_empty_retries} in {_backoff:.0f}s",
                    flush=True,
                )
                _time.sleep(_backoff)
                _backoff = min(_backoff * 1.6, _empty_backoff_max)
                if _empty_retries >= 3:
                    _req["messages"][-1] = {
                        "role": "user",
                        "content": msg
                        + f"\n\n[retry {_empty_retries}] Your previous reply was "
                        "empty. Respond now with one <tool_use> block calling a tool.",
                    }
                response = client.chat.completions.create(**_req)
                _choice = response.choices[0]
            content = _choice.message.content
            if not content:
                _tcs = getattr(_choice.message, "tool_calls", None)
                if _tcs:
                    # Native tool call -> <tool_use> text block (DGM's format).
                    import json as _json
                    _blocks = []
                    for _tc in _tcs:
                        _tc_args = _tc.function.arguments or "{}"
                        try:
                            _tc_args = _json.loads(_tc_args)
                        except Exception:
                            pass
                        _blocks.append(
                            "<tool_use>\n"
                            + repr({"tool_name": _tc.function.name, "tool_input": _tc_args})
                            + "\n</tool_use>"
                        )
                    content = "\n".join(_blocks)
                else:
                    _msg_extra = getattr(_choice.message, "model_extra", None) or {}
                    content = (
                        getattr(_choice.message, "reasoning_content", None)
                        or _msg_extra.get("reasoning_content")
                        or _msg_extra.get("reasoning")
                        or ""
                    )
                if not content:
                    print(
                        "[dgm-config] empty assistant content after retries: "
                        + response.model_dump_json()[:600],
                        flush=True,
                    )
        new_msg_history = _messages + [{"role": "assistant", "content": content}]
    elif "claude" in model:
        new_msg_history = msg_history + [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": msg,
                    }
                ],
            }
        ]
        response = client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=temperature,
            system=system_message,
            messages=new_msg_history,
        )
        content = response.content[0].text
        new_msg_history = new_msg_history + [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": content,
                    }
                ],
            }
        ]
    elif model.startswith("gpt-4o-"):
        new_msg_history = msg_history + [{"role": "user", "content": msg}]
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_message},
                *new_msg_history,
            ],
            temperature=temperature,
            max_tokens=MAX_OUTPUT_TOKENS,
            n=1,
            stop=None,
            seed=0,
        )
        content = response.choices[0].message.content
        new_msg_history = new_msg_history + [{"role": "assistant", "content": content}]
    elif model.startswith("o1-") or model.startswith("o3-"):
        new_msg_history = msg_history + [{"role": "user", "content": system_message + msg}]
        response = client.chat.completions.create(
            model=model,
            messages=[
                # {"role": "user", "content": system_message},
                *new_msg_history,
            ],
            temperature=1,
            # max_completion_tokens=MAX_OUTPUT_TOKENS,
            n=1,
            # stop=None,
            seed=0,
        )
        content = response.choices[0].message.content
        new_msg_history = new_msg_history + [{"role": "assistant", "content": content}]
    elif model in ["deepseek-chat", "deepseek-coder"]:
        new_msg_history = msg_history + [{"role": "user", "content": msg}]
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_message},
                *new_msg_history,
            ],
            temperature=temperature,
            max_tokens=MAX_OUTPUT_TOKENS,
            n=1,
            stop=None,
        )
        content = response.choices[0].message.content
        new_msg_history = new_msg_history + [{"role": "assistant", "content": content}]
    elif model in ["deepseek-reasoner"]:
        new_msg_history = msg_history + [{"role": "user", "content": msg}]
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_message},
                *new_msg_history,
            ],
            n=1,
            stop=None,
        )
        content = response.choices[0].message.content
        new_msg_history = new_msg_history + [{"role": "assistant", "content": content}]
        reasoning_content = response.choices[0].message.reasoning_content
    elif model.startswith("llama3.1-"):
        llama_size = model.split("-")[-1]
        client_model = f"meta-llama/llama-3.1-{llama_size}-instruct"
        new_msg_history = msg_history + [{"role": "user", "content": msg}]
        response = client.chat.completions.create(
            model=client_model,
            messages=[
                {"role": "system", "content": system_message},
                *new_msg_history,
            ],
            temperature=temperature,
            max_tokens=MAX_OUTPUT_TOKENS,
            n=1,
            stop=None,
        )
        content = response.choices[0].message.content
        new_msg_history = new_msg_history + [{"role": "assistant", "content": content}]
        resoning_content = response.choices[0].message.reasoning_content
    else:
        raise ValueError(f"Model {model} not supported.")
    if print_debug:
        print()
        print("*" * 20 + " LLM START " + "*" * 20)
        print(f'User: {new_msg_history[-2]["content"]}')
        print(f'Assistant: {new_msg_history[-1]["content"]}')
        print("*" * 21 + " LLM END " + "*" * 21)
        print()
    return content, new_msg_history

def extract_json_between_markers(llm_output):
    inside_json_block = False
    json_lines = []
    
    # Split the output into lines and iterate
    for line in llm_output.split('\n'):
        striped_line = line.strip()
        
        # Check for start of JSON code block
        if striped_line.startswith("```json"):
            inside_json_block = True
            continue
        
        # Check for end of code block
        if inside_json_block and striped_line.startswith("```"):
            # We've reached the closing triple backticks.
            inside_json_block = False
            break
        
        # If we're inside the JSON block, collect the lines
        if inside_json_block:
            json_lines.append(line)
    
    # If we never found a JSON code block, fallback to any JSON-like content
    if not json_lines:
        # Fallback: Try a regex that finds any JSON-like object in the text
        fallback_pattern = r"\{.*?\}"
        matches = re.findall(fallback_pattern, llm_output, re.DOTALL)
        for candidate in matches:
            candidate = candidate.strip()
            if candidate:
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    # Attempt to clean control characters and re-try
                    candidate_clean = re.sub(r"[\x00-\x1F\x7F]", "", candidate)
                    try:
                        return json.loads(candidate_clean)
                    except json.JSONDecodeError:
                        continue
        return None

    # Join all lines in the JSON block into a single string
    json_string = "\n".join(json_lines).strip()
    
    # Try to parse the collected JSON lines
    try:
        return json.loads(json_string)
    except json.JSONDecodeError:
        # Attempt to remove invalid control characters and re-parse
        json_string_clean = re.sub(r"[\x00-\x1F\x7F]", "", json_string)
        try:
            return json.loads(json_string_clean)
        except json.JSONDecodeError:
            return None
