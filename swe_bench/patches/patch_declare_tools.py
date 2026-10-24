"""dgm-config: fix the gateway eating native tool calls (empty replies).

Root cause, confirmed by replaying a captured failing request:

  * the model emits native DeepSeek DSML tool calls, e.g.
        <​|DSML| calls><​|DSML| invoke name="bash">...
  * the gateway runs a tool-call parser, which strips that call out of
    `content`
  * because the request declares no `tools`, the parsed call is then thrown
    away entirely -> content=null, tool_calls=null, tokens still billed
    (finish_reason "stop", completion_tokens ~50-220). That was ~1/3 of calls.

Replaying the same request with `tools` declared returned a proper
`tool_calls` message 5/5 times and zero empties.

So: declare the agent's own tool schemas (tools/bash.py, tools/edit.py) on the
chat-completions path. llm.py already converts native tool_calls back into
DGM's <tool_use> blocks, so the rest of the agent is unchanged.
"""
import pathlib
import sys

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
p = root / "llm.py"
src = p.read_text()

MARKER = "dgm-config: declare the agent's tools"
if MARKER in src:
    print("skip  llm.py (tools declaration already patched)")
    raise SystemExit(0)

HELPER = '''def _dgm_tool_specs():
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


'''
ANCHOR = "def get_response_from_llm("
if ANCHOR not in src:
    raise SystemExit("FAIL: get_response_from_llm not found in llm.py")
src = src.replace(ANCHOR, HELPER + ANCHOR, 1)

OLD_CALL = "            response = client.chat.completions.create(**_req)  # dgm-config: retry empty content (jitter)"
NEW_CALL = """            # dgm-config: declare the agent's tools (see _dgm_tool_specs).
            _tools = _dgm_tool_specs()
            if _tools:
                _req["tools"] = _tools
            response = client.chat.completions.create(**_req)"""
if OLD_CALL not in src:
    raise SystemExit("FAIL: chat.completions.create call not found in llm.py")
src = src.replace(OLD_CALL, NEW_CALL, 1)

p.write_text(src)
print("patch llm.py (declare tools so native tool calls are returned)")
