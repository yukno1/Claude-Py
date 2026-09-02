from claude_py.hook import trigger_hooks
from claude_py.config import client, WORKDIR, SECONDARY_MODEL
from claude_py.task import TASK_TOOLS, TASK_TOOL_HANDLERS
from .bg import should_run_background, start_background_task
from .base_tool import BASE_TOOLS, BASE_HANDLERS
from .compactor import COMPACT_TOOL
from .team import TEAM_TOOLS, TEAM_TOOL_HANDLERS


SUB_SYSTEM = (
    f"You are a coding agent at {WORKDIR}. "
    "Complete the given task, then return a concise final answer."
)


TOOLS = [*BASE_TOOLS, *TASK_TOOLS, *TEAM_TOOLS, COMPACT_TOOL]
SUB_TOOLS = list(BASE_TOOLS)


TOOL_HANDLERS = {**BASE_HANDLERS, **TASK_TOOL_HANDLERS, **TEAM_TOOL_HANDLERS}
SUB_HANDLERS = dict(BASE_HANDLERS)


def extract_text(content) -> str:
    if not isinstance(content, list):
        return str(content)
    return "\n".join(
        getattr(block, "text", "")
        for block in content
        if getattr(block, "type", None) == "text"
    )


def run_subagent(prompt: str) -> str:
    print("\n\033[35m[Subagent started]\033[0m")
    messages = [{"role": "user", "content": prompt}]

    for _ in range(30):
        response = client.messages.create(
            model=SECONDARY_MODEL,
            system=SUB_SYSTEM,
            messages=messages,
            tools=SUB_TOOLS,
            max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        tool_calls = [block for block in response.content if block.type == "tool_use"]
        if not tool_calls:
            force = trigger_hooks("Stop", messages)
            if force:
                messages.append({"role": "user", "content": force})
                continue
            print("\033[35m[Subagent done]\033[0m")
            return extract_text(response.content) or "(no summary)"

        results = []
        for block in tool_calls:
            output = execute_tool(block, SUB_HANDLERS)
            print(f"  \033[90m[sub] {block.name}: {output[:100]}\033[0m")
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                }
            )
        messages.append({"role": "user", "content": results})

    print("\033[35m[Subagent stopped]\033[0m")
    return "Subagent stopped after 30 turns without a final answer."


def call_tool(block, handlers: dict[str, callable]) -> str:
    handler = handlers.get(block.name)
    try:
        output = handler(**block.input) if handler else f"Unknown: {block.name}"
    except Exception as error:
        output = f"Error: {error}"
    return str(output)


def execute_tool(block, handlers: dict[str, callable] = TOOL_HANDLERS) -> str:
    blocked = trigger_hooks("PreToolUse", block)
    if blocked is not None:
        return str(blocked)

    if should_run_background(block.name, block.input):
        try:
            task_id = start_background_task(block)
            output = (
                f"[Background task {task_id} started] "
                "The result will be collected on a later turn."
            )
        except Exception as error:
            output = f"Error: {error}"
    else:
        output = call_tool(block, handlers)

    trigger_hooks("PostToolUse", block, output)
    return output
