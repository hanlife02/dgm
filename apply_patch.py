"""
Apply the minimal config/portability patches to the DGM checkout.

Usage: python apply_patch.py <repo_root>
Idempotent: each patch carries a unique marker; if the marker is present the
patch is skipped, so re-running is safe.
"""
import json
import os
import shutil
import sys

REPO = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
HERE = os.path.dirname(os.path.abspath(__file__))


def patch(relpath, old, new, marker=None, count=1):
    path = os.path.join(REPO, relpath)
    with open(path) as f:
        src = f.read()
    if marker is not None and marker in src:
        print(f"skip  {relpath} [{marker}]")
        return
    if marker is None and old not in src:
        print(f"skip  {relpath} (old text absent)")
        return
    found = src.count(old)
    if found != count:
        raise SystemExit(f"FAIL {relpath}: expected {count} match(es), found {found}\n--- old ---\n{old}")
    src = src.replace(old, new)
    with open(path, "w") as f:
        f.write(src)
    print(f"patch {relpath} [{marker}] x{count}")


def copy(relpath):
    dst = os.path.join(REPO, relpath)
    if os.path.exists(dst):
        print(f"skip  {relpath} (exists)")
        return
    shutil.copy(os.path.join(HERE, relpath), dst)
    print(f"add   {relpath}")


# ---------------------------------------------------------------- new files
copy("dgm_config.py")
copy("models.json")

smoke = os.path.join(REPO, "swe_bench/subsets/smoke.json")
if not os.path.exists(smoke):
    with open(smoke, "w") as f:
        json.dump(
            [
                "django__django-10880",
                "django__django-10999",
                "django__django-11087",
            ],
            f,
            indent=4,
        )
        f.write("\n")
    print("add   swe_bench/subsets/smoke.json")

# ------------------------------------------------------------------- llm.py
patch(
    "llm.py",
    "import anthropic\nimport backoff\nimport openai\n",
    "import anthropic\nimport backoff\nimport openai\n\n"
    "from dgm_config import api_key as _api_key  # dgm-config\n"
    "from dgm_config import model_entry as _model_entry  # dgm-config\n",
    marker="# dgm-config",
)

patch(
    "llm.py",
    '''    if model.startswith("claude-"):
        print(f"Using Anthropic API with model {model}.")''',
    '''    _entry = _model_entry(model)  # dgm-config
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
        print(f"Using Anthropic API with model {model}.")''',
    marker="_entry = _model_entry(model)",
)

patch(
    "llm.py",
    '''        msg_history = []

    if "claude" in model:
        new_msg_history = msg_history + [''',
    '''        msg_history = []

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
            response = client.chat.completions.create(**_req)
            content = response.choices[0].message.content
        new_msg_history = _messages + [{"role": "assistant", "content": content}]
    elif "claude" in model:
        new_msg_history = msg_history + [''',
    marker="# Config-driven branch",
)

# ----------------------------------------------------------- llm_withtools.py
patch(
    "llm_withtools.py",
    "from tools import load_all_tools\n\n"
    "CLAUDE_MODEL = 'bedrock/us.anthropic.claude-3-5-sonnet-20241022-v2:0'",
    "from tools import load_all_tools\n\n"
    "from dgm_config import coding_model as _coding_model  # dgm-config\n\n"
    "CLAUDE_MODEL = _coding_model()",
    marker="_coding_model",
)

# Robustness: some OpenAI-compatible gateways intermittently answer with
# content=None (tokens generated but dropped) or with native tool_calls. Both
# silently end the agent loop and produce an empty patch, so retry + normalize.
_EMPTY_CONTENT_V1 = """            response = client.chat.completions.create(**_req)  # dgm-config: normalize empty content
            _choice = response.choices[0]
            if not _choice.message.content and not getattr(_choice.message, "tool_calls", None):
                print(
                    "[dgm-config] empty assistant content (finish_reason="
                    f"{getattr(_choice, 'finish_reason', None)}), retrying once",
                    flush=True,
                )
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
                            "<tool_use>\\n"
                            + repr({"tool_name": _tc.function.name, "tool_input": _tc_args})
                            + "\\n</tool_use>"
                        )
                    content = "\\n".join(_blocks)
                else:
                    content = getattr(_choice.message, "reasoning_content", None) or ""
                if not content:
                    print(
                        "[dgm-config] empty assistant content after retry: "
                        + response.model_dump_json()[:600],
                        flush=True,
                    )"""

_EMPTY_CONTENT_V2 = """            response = client.chat.completions.create(**_req)  # dgm-config: retry empty content
            _choice = response.choices[0]
            _empty_retries = 0
            while (
                not _choice.message.content
                and not getattr(_choice.message, "tool_calls", None)
                and _empty_retries < 6
            ):
                # Gateways may intermittently return content=None even though
                # tokens were generated; retry instead of ending the agent loop.
                import time as _time
                _empty_retries += 1
                print(
                    "[dgm-config] empty assistant content (finish_reason="
                    f"{getattr(_choice, 'finish_reason', None)}), "
                    f"retry {_empty_retries}/6",
                    flush=True,
                )
                _time.sleep(1)
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
                            "<tool_use>\\n"
                            + repr({"tool_name": _tc.function.name, "tool_input": _tc_args})
                            + "\\n</tool_use>"
                        )
                    content = "\\n".join(_blocks)
                else:
                    content = getattr(_choice.message, "reasoning_content", None) or ""
                if not content:
                    print(
                        "[dgm-config] empty assistant content after retries: "
                        + response.model_dump_json()[:600],
                        flush=True,
                    )"""

_EMPTY_CONTENT_V3 = """            response = client.chat.completions.create(**_req)  # dgm-config: retry empty content (backoff)
            _choice = response.choices[0]
            _empty_retries = 0
            _backoff = 1.0
            while (
                not _choice.message.content
                and not getattr(_choice.message, "tool_calls", None)
                and _empty_retries < 12
            ):
                # The gateway has minute-long windows where every reply comes back
                # with content=None (tokens generated but dropped), so space the
                # retries out instead of hammering it (~3 minutes total).
                import time as _time
                _empty_retries += 1
                print(
                    "[dgm-config] empty assistant content (finish_reason="
                    f"{getattr(_choice, 'finish_reason', None)}), "
                    f"retry {_empty_retries}/12 in {_backoff:.0f}s",
                    flush=True,
                )
                _time.sleep(_backoff)
                _backoff = min(_backoff * 1.6, 30.0)
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
                            "<tool_use>\\n"
                            + repr({"tool_name": _tc.function.name, "tool_input": _tc_args})
                            + "\\n</tool_use>"
                        )
                    content = "\\n".join(_blocks)
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
                    )"""

# v4 = v3 with a longer backoff budget plus prompt jitter on late retries
_EMPTY_CONTENT_V4 = (
    _EMPTY_CONTENT_V3.replace(
        "# dgm-config: retry empty content (backoff)",
        "# dgm-config: retry empty content (jitter)",
    )
    .replace("_empty_retries < 12", "_empty_retries < 20")
    .replace(
        "retry {_empty_retries}/12 in {_backoff:.0f}s",
        "retry {_empty_retries}/20 in {_backoff:.0f}s",
    )
    .replace(
        "                _backoff = min(_backoff * 1.6, 30.0)\n",
        "                _backoff = min(_backoff * 1.6, 30.0)\n"
        "                if _empty_retries >= 3:\n"
        "                    _req[\"messages\"][-1] = {\n"
        "                        \"role\": \"user\",\n"
        "                        \"content\": msg\n"
        "                        + f\"\\n\\n[retry {_empty_retries}] Your previous reply was \"\n"
        "                        \"empty. Respond now with one <tool_use> block calling a tool.\",\n"
        "                    }\n",
    )
)

# already-patched checkouts: v3 (12x/3min) -> v4 (20x/~7min + jitter)
patch(
    "llm.py",
    _EMPTY_CONTENT_V3,
    _EMPTY_CONTENT_V4,
    marker="# dgm-config: retry empty content (jitter)",
)

# already-patched checkouts: v2 (fixed 6x / 1s) -> v4
patch(
    "llm.py",
    _EMPTY_CONTENT_V2,
    _EMPTY_CONTENT_V4,
    marker="# dgm-config: retry empty content (jitter)",
)

# already-patched checkouts: v1 (single retry) -> v4
patch(
    "llm.py",
    _EMPTY_CONTENT_V1,
    _EMPTY_CONTENT_V4,
    marker="# dgm-config: retry empty content (jitter)",
)
# fresh checkouts
patch(
    "llm.py",
    """            response = client.chat.completions.create(**_req)
            content = response.choices[0].message.content""",
    _EMPTY_CONTENT_V4,
    marker="# dgm-config: retry empty content (jitter)",
)

# Robustness: with the text <tool_use> protocol a model sometimes answers with
# prose only ("I'll start by exploring..."), which ends the loop with zero work
# done and therefore an empty patch. Nudge it (bounded) instead of stopping.
patch(
    "llm_withtools.py",
    """        # Tool use
        tool_use = check_for_tool_use(response, model=client_model)
        while tool_use:
            # Process tool call
            tool_name = tool_use['tool_name']
            tool_input = tool_use['tool_input']
            tool_result = process_tool_call(tools_dict, tool_name, tool_input)

            # Get tool response
            tool_msg = f'Tool Used: {tool_name}\\nTool Input: {tool_input}\\nTool Result: {tool_result}'
            logging(tool_msg)
            response, new_msg_history = get_response_from_llm(
                msg=tool_msg,
                client=client,
                model=client_model,
                system_message=system_message,
                print_debug=False,
                msg_history=new_msg_history,
            )
            logging(f"Output: {response}")

            # Check for next tool use
            tool_use = check_for_tool_use(response, model=client_model)""",
    """        # Tool use
        _NUDGE = (
            "Your previous reply did not contain a tool call, so no work was done. "
            "Continue the task now and include exactly one <tool_use> block with a "
            "tool call. Only omit the tool call once every change has been saved "
            "and verified."
        )
        _MAX_NUDGES = 3  # dgm-config: nudge when a reply has no tool call
        tool_use = check_for_tool_use(response, model=client_model)
        _nudges = 0
        while True:
            if tool_use:
                # Process tool call
                tool_name = tool_use['tool_name']
                tool_input = tool_use['tool_input']
                tool_result = process_tool_call(tools_dict, tool_name, tool_input)

                # Get tool response
                tool_msg = f'Tool Used: {tool_name}\\nTool Input: {tool_input}\\nTool Result: {tool_result}'
                logging(tool_msg)
                response, new_msg_history = get_response_from_llm(
                    msg=tool_msg,
                    client=client,
                    model=client_model,
                    system_message=system_message,
                    print_debug=False,
                    msg_history=new_msg_history,
                )
                logging(f"Output: {response}")
            elif _nudges < _MAX_NUDGES:
                _nudges += 1
                logging(f"No tool call in the reply; nudging ({_nudges}/{_MAX_NUDGES})")
                response, new_msg_history = get_response_from_llm(
                    msg=_NUDGE,
                    client=client,
                    model=client_model,
                    system_message=system_message,
                    print_debug=False,
                    msg_history=new_msg_history,
                )
                logging(f"Output: {response}")
            else:
                break

            # Check for next tool use
            tool_use = check_for_tool_use(response, model=client_model)""",
    marker="# dgm-config: nudge when a reply has no tool call",
)

# Observability: chat_with_agent_manualtools swallowed every exception, so a
# failing LLM/tool turn looked like a normal "Output: None" and produced an
# empty patch with no diagnostic.
patch(
    "llm_withtools.py",
    """            tool_use = check_for_tool_use(response, model=client_model)

    except Exception:
        pass

    return new_msg_history""",
    """            tool_use = check_for_tool_use(response, model=client_model)

    except Exception as _e:  # dgm-config: log instead of silently swallowing
        import traceback as _traceback
        logging(f"Agent loop error: {_e}\\n{_traceback.format_exc()}")

    return new_msg_history""",
    marker="Agent loop error",
)

# --------------------------------------------------------- self_improve_step.py
patch(
    "self_improve_step.py",
    "import docker\n\nfrom llm import create_client",
    "import docker\n\n"
    "from dgm_config import diagnose_model as _diagnose_model_cfg  # dgm-config\n"
    "from dgm_config import int_setting as _int_setting  # dgm-config\n"
    "from llm import create_client",
    marker="_diagnose_model_cfg  # dgm-config",
)
patch(
    "self_improve_step.py",
    "dataset = None\ndiagnose_model = 'o1-2024-12-17'",
    "dataset = None\ndiagnose_model = _diagnose_model_cfg()",
    marker="diagnose_model = _diagnose_model_cfg()",
)
patch(
    "self_improve_step.py",
    "        max_workers=min(5, len(test_task_list)),",
    "        max_workers=max(1, min(_int_setting('concurrency', 'harness_workers', 1), len(test_task_list))),",
    marker=None,
)
patch(
    "self_improve_step.py",
    "            max_workers=min(5, len(test_task_list_more)),",
    "            max_workers=max(1, min(_int_setting('concurrency', 'harness_workers', 1), len(test_task_list_more))),",
    marker=None,
)
patch(
    "self_improve_step.py",
    "        num_evals_parallel=5,",
    "        num_evals_parallel=_int_setting('concurrency', 'num_evals_parallel', 1),",
    marker="num_evals_parallel=_int_setting",
    count=2,
)
patch(
    "self_improve_step.py",
    "        max_workers=min(10, len(test_task_list)),",
    "        max_workers=max(1, min(_int_setting('concurrency', 'harness_workers', 1), len(test_task_list))),",
    marker=None,
)
patch(
    "self_improve_step.py",
    "            max_workers=50,",
    "            max_workers=_int_setting('concurrency', 'harness_workers', 1),",
    marker="max_workers=_int_setting('concurrency', 'harness_workers', 1),",
)
patch(
    "self_improve_step.py",
    "        num_evals_parallel=min(5, num_evals),",
    "        num_evals_parallel=max(1, min(_int_setting('concurrency', 'num_evals_parallel', 1), num_evals)),",
    marker=None,
    count=2,
)
patch(
    "self_improve_step.py",
    "        output_dir=output_dir,\n        dnames_workers=5,",
    "        output_dir=output_dir,\n        dnames_workers=1,\n"
    "        num_eval_procs=_int_setting('concurrency', 'eval_procs', 1),",
    marker="num_eval_procs=_int_setting('concurrency', 'eval_procs', 1),",
)
patch(
    "self_improve_step.py",
    "            output_dir=output_dir,\n            dnames_workers=5,",
    "            output_dir=output_dir,\n            dnames_workers=1,\n"
    "            num_eval_procs=_int_setting('concurrency', 'eval_procs', 1),",
    marker="            num_eval_procs=_int_setting('concurrency', 'eval_procs', 1),",
)

# --------------------------------------------------------------- DGM_outer.py
patch(
    "DGM_outer.py",
    "from utils.evo_utils import load_dgm_metadata, is_compiled_self_improve",
    "from dgm_config import subset as _subset  # dgm-config\n"
    "from utils.evo_utils import load_dgm_metadata, is_compiled_self_improve",
    marker="_subset  # dgm-config",
)
patch(
    "DGM_outer.py",
    '''        swe_issues_sm = load_json_file("./swe_bench/subsets/small.json")
        swe_issues_med = load_json_file("./swe_bench/subsets/medium.json")''',
    '''        swe_issues_sm = load_json_file(f"./swe_bench/subsets/{_subset('small', 'small.json')}")
        swe_issues_med = load_json_file(f"./swe_bench/subsets/{_subset('medium', 'medium.json')}")''',
    marker="_subset('small'",
)

# ------------------------------------------------- swe_bench/harness.py + report
# Portability bug: harness.py relocates into a directory literal-name "/dgm" by
# climbing with os.chdir('..'). Our repo is mounted at its real path, so the
# climb reaches '/' where chdir('..') never moves -> infinite loop that wrote
# 6.8 GB of "Changed directory to: /" into the run log.
patch(
    "swe_bench/harness.py",
    """        # If not in dgm directory, try to change to it
        if not tmp_currdir.endswith('/dgm'):
            try:
                os.chdir('dgm')
                tmp_currdir = os.path.abspath(os.getcwd())
                logger.info(f"Changed directory to: {tmp_currdir}")
            except Exception as e:
                pass
        # If still not in dgm directory, go up until we find it
        while not tmp_currdir.endswith('/dgm'):
            os.chdir('..')
            tmp_currdir = os.path.abspath(os.getcwd())
            logger.info(f"Changed directory to: {tmp_currdir}")""",
    """        # If not in dgm directory, try to change to it
        # dgm-config: bounded — stop once the agent files are present, at '/', or
        # after a few hops (os.chdir('..') at '/' never moves).
        _has_agent_files = os.path.exists('coding_agent.py')
        if not tmp_currdir.endswith('/dgm') and not _has_agent_files:
            try:
                os.chdir('dgm')
                tmp_currdir = os.path.abspath(os.getcwd())
                logger.info(f"Changed directory to: {tmp_currdir}")
            except Exception as e:
                pass
        # If still not in dgm directory, go up until we find it
        _hops = 0  # dgm-config: bounded climb
        while (
            not tmp_currdir.endswith('/dgm')
            and not os.path.exists('coding_agent.py')
            and tmp_currdir != '/'
            and _hops < 8
        ):
            os.chdir('..')
            _hops += 1
            tmp_currdir = os.path.abspath(os.getcwd())
            logger.info(f"Changed directory to: {tmp_currdir}")""",
    marker="# dgm-config: bounded climb",
)
# The eval container installs DGM's own requirements with pip, but it gets no
# proxy env vars, so pip times out and the whole instance eval fails with
# "Script failed with exit code 1".
patch(
    "swe_bench/harness.py",
    """        # Install this repo requirements
        safe_log("Installing more requirements")
        exec_result = container.exec_run("python -m pip install -r /dgm/requirements.txt", workdir='/')
        log_container_output(exec_result)""",
    """        # Install this repo requirements
        safe_log("Installing more requirements")
        _proxy_env = {  # dgm-config: proxy for pip in the eval container
            k: os.environ[k]
            for k in (
                "http_proxy", "https_proxy", "no_proxy", "HTTP_PROXY",
                "HTTPS_PROXY", "NO_PROXY",
            )
            if os.environ.get(k)
        }
        exec_result = container.exec_run(
            "python -m pip install -r /dgm/requirements.txt",
            workdir='/',
            environment=_proxy_env,
        )
        log_container_output(exec_result)""",
    marker="# dgm-config: proxy for pip in the eval container",
)
# harness.py copies a fixed file list into the eval container; the config loader
# and its models.json must be part of it or the agent dies on import.
patch(
    "swe_bench/harness.py",
    """        copy_to_container(container, 'llm.py', '/dgm/llm.py')
        copy_to_container(container, 'llm_withtools.py', '/dgm/llm_withtools.py')""",
    """        copy_to_container(container, 'llm.py', '/dgm/llm.py')
        copy_to_container(container, 'llm_withtools.py', '/dgm/llm_withtools.py')
        copy_to_container(container, 'dgm_config.py', '/dgm/dgm_config.py')  # dgm-config
        copy_to_container(container, 'models.json', '/dgm/models.json')  # dgm-config""",
    marker="copy_to_container(container, 'dgm_config.py'",
)
patch(
    "swe_bench/harness.py",
    'parser.add_argument("--max_workers", type=int, default=4,',
    'parser.add_argument("--max_workers", type=int, default=2,',
    marker='"--max_workers", type=int, default=2,',
)
patch(
    "swe_bench/report.py",
    "num_eval_procs=5,",
    "num_eval_procs=2,",
    marker="num_eval_procs=2,",
)
patch(
    "swe_bench/report.py",
    "parser.add_argument('--num_eval_procs', type=int, default=5,",
    "parser.add_argument('--num_eval_procs', type=int, default=2,",
    marker="'--num_eval_procs', type=int, default=2,",
)

# ------------------------------------------- utils/eval_utils.py generic content
patch(
    "utils/eval_utils.py",
    """            content = msg['content'][0]['text']""",
    """            content = msg['content']
            if isinstance(content, list):
                content = content[0]['text'] if content else ''""",
    marker="isinstance(content, list)",
)

# ------------------- utils/docker_utils.py: proxy build args for the dgm image
patch(
    "utils/docker_utils.py",
    "import io\nimport logging",
    "import io\nimport logging\nimport os  # dgm-config",
    marker="import os  # dgm-config",
)
patch(
    "utils/docker_utils.py",
    "            image, logs = client.images.build(path=repo_path, tag=image_name, rm=True)",
    """            _proxy_buildargs = {  # dgm-config (docker-py drops proxy env vars)
                k: os.environ[k]
                for k in (
                    "http_proxy", "https_proxy", "no_proxy", "all_proxy",
                    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
                )
                if os.environ.get(k)
            }
            image, logs = client.images.build(
                path=repo_path, tag=image_name, rm=True, buildargs=_proxy_buildargs
            )""",
    marker="_proxy_buildargs",
)

# ------------------- Dockerfile: reproducible base + optional apt/pip mirrors
patch(
    "Dockerfile",
    """FROM python:3.10-slim

# Install system-level dependencies, including git
RUN apt-get update && apt-get install -y \\""",
    """# dgm-config: pin the Debian release so the mirror rewrite below is stable
FROM python:3.10-slim-bookworm

# dgm-config: optional apt/pip mirrors for hosts where deb.debian.org / pypi.org
# are unreachable. utils/docker_utils.py passes DGM_APT_MIRROR and
# DGM_PIP_INDEX_URL as build args; both default to empty (upstream behaviour).
ARG APT_MIRROR=
RUN if [ -n "$APT_MIRROR" ]; then \\
      for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources /etc/apt/sources.list.d/*.list; do \\
        if [ -f "$f" ]; then \\
          sed -i "s|deb.debian.org|$APT_MIRROR|g; s|security.debian.org|$APT_MIRROR|g" "$f"; \\
        fi; \\
      done; \\
    fi
ARG PIP_INDEX_URL=
RUN if [ -n "$PIP_INDEX_URL" ]; then pip config set global.index-url "$PIP_INDEX_URL"; fi

# Install system-level dependencies, including git
RUN apt-get update && apt-get install -y \\""",
    marker="ARG APT_MIRROR=",
)
patch(
    "utils/docker_utils.py",
    """            image, logs = client.images.build(
                path=repo_path, tag=image_name, rm=True, buildargs=_proxy_buildargs
            )""",
    """            if os.environ.get("DGM_APT_MIRROR"):  # dgm-config: mirror build args
                _proxy_buildargs["APT_MIRROR"] = os.environ["DGM_APT_MIRROR"]
            if os.environ.get("DGM_PIP_INDEX_URL"):
                _proxy_buildargs["PIP_INDEX_URL"] = os.environ["DGM_PIP_INDEX_URL"]
            image, logs = client.images.build(
                path=repo_path, tag=image_name, rm=True, buildargs=_proxy_buildargs
            )""",
    marker="DGM_APT_MIRROR",
)

print("done")
