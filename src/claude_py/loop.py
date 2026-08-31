from .tool import TOOLS, execute_tool
from .compactor import ContextCompactor
from .hook import trigger_hooks
from .memory import (
    extract_memories,
    consolidate_memories,
)
from .config import (
    PRIMARY_MODEL,
    TRANSCRIPT_DIR,
    TOOL_RESULTS_DIR,
    client,
    DEFAULT_MAX_TOKENS,
    ESCALATED_MAX_TOKENS,
    MAX_RECOVERY_RETRIES,
)
from .prompt import get_system_prompt
from .context import update_context
from .recovery import (
    RecoveryState,
    with_retry,
    is_prompt_too_long_error,
    reactive_compact,
    CONTINUATION_PROMPT,
)
from .bg import inject_background_results


COMPACTOR = ContextCompactor(client, PRIMARY_MODEL, TRANSCRIPT_DIR, TOOL_RESULTS_DIR)
MAX_REACTIVE_RETRIES = 1


def agent_loop(messages: list, context: dict):
    """Main loop with error recovery wrapping LLM calls."""
    system = get_system_prompt(context)
    state = RecoveryState()
    max_tokens = DEFAULT_MAX_TOKENS

    while True:
        inject_background_results(messages)
        # ── LLM call: with_retry handles 429/529, outer handles rest ──
        try:
            response = with_retry(
                lambda: client.messages.create(
                    model=PRIMARY_MODEL,
                    system=system,
                    messages=messages,
                    tools=TOOLS,
                    max_tokens=max_tokens,
                ),
                state,
            )
        except Exception as e:
            # Path 2: prompt_too_long -> reactive compact (once)
            if is_prompt_too_long_error(e):
                if not state.has_attempted_reactive_compact:
                    messages[:] = reactive_compact(messages)
                    state.has_attempted_reactive_compact = True
                    continue
                print("  \033[31m[unrecoverable] still too long after compact\033[0m")
                messages.append(
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": "[Error] Context too large, cannot continue.",
                            }
                        ],
                    }
                )
                return
            # Unrecoverable
            name = type(e).__name__
            print(f"  \033[31m[unrecoverable] {name}: {str(e)[:100]}\033[0m")
            messages.append(
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": f"[Error] {name}: {str(e)[:200]}"}
                    ],
                }
            )
            return

        # ── Path 1: max_tokens -> escalate or continue ──
        if response.stop_reason == "max_tokens":
            # First escalation: don't append truncated output, retry same request
            if not state.has_escalated:
                max_tokens = ESCALATED_MAX_TOKENS
                state.has_escalated = True
                print(
                    f"  \033[33m[max_tokens] escalating"
                    f" {DEFAULT_MAX_TOKENS} -> {ESCALATED_MAX_TOKENS}\033[0m"
                )
                continue
            # 64K still truncated: save truncated output + continuation prompt
            messages.append({"role": "assistant", "content": response.content})
            if state.recovery_count < MAX_RECOVERY_RETRIES:
                messages.append({"role": "user", "content": CONTINUATION_PROMPT})
                state.recovery_count += 1
                print(
                    f"  \033[33m[max_tokens] continuation"
                    f" {state.recovery_count}/{MAX_RECOVERY_RETRIES}\033[0m"
                )
                continue
            print("  \033[31m[max_tokens] recovery limit reached\033[0m")
            return

        # Normal completion: append assistant response
        messages.append(
            {
                "role": "assistant",
                "content": response.content,
            }
        )

        tool_calls = [block for block in response.content if block.type == "tool_use"]
        if not tool_calls:
            force = trigger_hooks("Stop", messages)
            if force:
                messages.append({"role": "user", "content": force})
                continue
            if extract_memories(messages):
                consolidate_memories()
            return

        # ── Tool execution ──
        results = []
        for block in tool_calls:
            output = execute_tool(block)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                }
            )
        messages.append({"role": "user", "content": results})

        # Re-evaluate context and prompt after each tool round
        context = update_context(context, messages)
        system = get_system_prompt(context)
