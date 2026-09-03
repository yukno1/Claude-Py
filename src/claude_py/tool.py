from claude_py.task import TASK_TOOLS, TASK_TOOL_HANDLERS
from .bg import should_run_background, start_background_task
from .base_tool import BASE_TOOLS, BASE_HANDLERS
from .compactor import COMPACT_TOOL
from .team import TEAM_TOOLS, TEAM_TOOL_HANDLERS


TOOLS = [*BASE_TOOLS, *TASK_TOOLS, *TEAM_TOOLS, COMPACT_TOOL]


TOOL_HANDLERS = {**BASE_HANDLERS, **TASK_TOOL_HANDLERS, **TEAM_TOOL_HANDLERS}


def call_tool(block, handlers: dict[str, callable]) -> str:
    handler = handlers.get(block.name)
    try:
        output = handler(**block.input) if handler else f"Unknown: {block.name}"
    except Exception as error:
        output = f"Error: {error}"
    return str(output)


def execute_tool(block, handlers: dict[str, callable] = TOOL_HANDLERS) -> str:
    from claude_py.hook import trigger_hooks

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


def has_tool_use(content) -> bool:
    # Do not rely on stop_reason alone; the concrete tool_use block is the
    # continuation signal used by the loop.
    return any(getattr(block, "type", None) == "tool_use" for block in content)


def call_tool_handler(handler, args: dict, name: str) -> str:
    if not handler:
        return f"Unknown tool: {name}"
    try:
        return str(handler(**(args or {})))
    except Exception as exc:
        return f"Error: {type(exc).__name__}: {exc}"
