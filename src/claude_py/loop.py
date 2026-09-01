import threading
import datetime


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
from .cron import (
    poll_due_jobs,
    consume_cron_queue,
    has_cron_queue,
    load_durable_jobs,
    acknowledge_cron_jobs,
    restore_cron_jobs,
)


COMPACTOR = ContextCompactor(client, PRIMARY_MODEL, TRANSCRIPT_DIR, TOOL_RESULTS_DIR)
MAX_REACTIVE_RETRIES = 1
RUNTIME_STOP = threading.Event()
runtime_threads: list[threading.Thread] = []
runtime_started = False
runtime_lock = threading.Lock()
agent_lock = threading.Lock()
session_history: list = []


def cron_scheduler_loop(stop_event: threading.Event = RUNTIME_STOP):
    while not stop_event.wait(1.0):
        poll_due_jobs(datetime.now())


def agent_loop(messages: list, context: dict):
    """Main loop with error recovery wrapping LLM calls."""
    system = get_system_prompt(context)
    state = RecoveryState()
    max_tokens = DEFAULT_MAX_TOKENS

    fired = consume_cron_queue()
    scheduled_start = len(messages)
    for job in fired:
        messages.append({"role": "user", "content": f"[Scheduled] {job.prompt}"})
        print(f"  [cron] delivered {job.id}: {job.prompt[:60]}")

    waiting_for_ack = list(fired)

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
            if waiting_for_ack:
                del messages[scheduled_start:]
                restore_cron_jobs(waiting_for_ack)

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
        if waiting_for_ack:
            try:
                acknowledge_cron_jobs(waiting_for_ack)
            except Exception as error:
                print(f"  [cron] acknowledgement failed: {error}")
            waiting_for_ack = []

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


def print_latest_assistant_text(messages: list):
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            print(content)
        else:
            for block in content:
                if getattr(block, "type", None) == "text":
                    print(block.text)
                elif isinstance(block, dict) and block.get("type") == "text":
                    print(block.get("text", ""))
        return


def run_agent_turn_locked(user_query: str | None = None):
    if user_query is not None:
        trigger_hooks("UserPromptSubmit", user_query)
        session_history.append({"role": "user", "content": user_query})
    agent_loop(session_history)
    print_latest_assistant_text(session_history)
    print()


def queue_processor_loop(stop_event: threading.Event = RUNTIME_STOP):
    while not stop_event.wait(0.2):
        if not has_cron_queue() or not agent_lock.acquire(blocking=False):
            continue
        try:
            if has_cron_queue():
                run_agent_turn_locked()
        finally:
            agent_lock.release()


def start_runtime_threads():
    global runtime_started
    with runtime_lock:
        if runtime_started:
            return
        load_durable_jobs()
        RUNTIME_STOP.clear()
        runtime_threads.extend(
            [
                threading.Thread(
                    target=cron_scheduler_loop,
                    name="cron-scheduler",
                    daemon=True,
                ),
                threading.Thread(
                    target=queue_processor_loop,
                    name="cron-queue-processor",
                    daemon=True,
                ),
            ]
        )
        for thread in runtime_threads:
            thread.start()
        runtime_started = True


def stop_runtime_threads():
    global runtime_started
    with runtime_lock:
        if not runtime_started:
            return
        RUNTIME_STOP.set()
        for thread in runtime_threads:
            thread.join(timeout=1)
        runtime_threads.clear()
        runtime_started = False
