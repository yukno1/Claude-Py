# from dotenv import load_dotenv
import select
import sys
import queue
import os

if os.name == "nt":
    import time
    import threading

from .hook import (
    trigger_hooks,
    register_hook,
    context_inject_hook,
    permission_hook,
    log_hook,
    large_output_hook,
    summary_hook,
)
from .loop import agent_loop, async_event_loop, agent_lock, print_turn_assistants
from .context import update_context
from .team import BUS
from .console import CONSOLE

# try:
#     import readline

#     readline.parse_and_bind("set bind-tty-special-chars off")
#     readline.parse_and_bind("set input-meta on")
#     readline.parse_and_bind("set output-meta on")
#     readline.parse_and_bind("set convert-meta off")
# except ImportError:
#     pass

# load_dotenv(override=True)
# if os.getenv("ANTHROPIC_BASE_URL"):
#     os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


# ---------register hooks--------------------------

register_hook("UserPromptSubmit", context_inject_hook)
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", large_output_hook)
register_hook("Stop", summary_hook)


def wait_for_cli_event() -> tuple[str, str | None]:
    prompt_visible = False
    while True:
        if BUS.peek("lead"):
            if prompt_visible:
                print()
            return "wake", None
        if os.name == "nt":
            try:
                line = _stdin_queue.get_nowait()
            except queue.Empty:
                if not prompt_visible:
                    print(
                        "\001\033[36m\002claude-py >> \001\033[0m\002",
                        end="",
                        flush=True,
                    )
                    prompt_visible = True
                time.sleep(0.25)
                continue
            if line is None:
                return "quit", None
            return "user", line
        else:
            if not prompt_visible:
                print(
                    "\001\033[36m\002claude-py >> \001\033[0m\002", end="", flush=True
                )
                prompt_visible = True
            readable, _, _ = select.select([sys.stdin], [], [], 0.25)
            if readable:
                line = sys.stdin.readline()
                if line == "":
                    return "quit", None
                return "user", line.rstrip("\n")


def print_last_assistant_message(history: list):
    if not history:
        return
    for block in history[-1].get("content", []):
        if getattr(block, "type", None) == "text":
            print(block.text)
        elif isinstance(block, dict) and block.get("type") == "text":
            print(block.get("text", ""))


def main():
    print("Enter a question, press Enter to send. Type q to quit.\n")

    # if os.name == "nt":
    #     # 后台线程持续读取 stdin，写入队列；主循环用非阻塞方式取行。
    #     # 跨平台替代 Windows 上不可用的 select.select([sys.stdin], ...)。
    #     threading.Thread(target=_read_stdin, name="stdin-reader", daemon=True).start()

    history = []
    context = update_context({}, [])
    session_state = {"active_user_request": "(no active user request)"}
    threading.Thread(
        target=async_event_loop, args=(history, context, session_state), daemon=True
    ).start()
    # had_teammates = False

    while True:
        # query = CONSOLE.ask()
        # kind, payload = wait_for_cli_event()
        # if kind == "quit":
        #     break
        # if kind == "user":
        #     if payload is None or payload.strip().lower() in {"q", "exit", ""}:
        #         break
        #     trigger_hooks("UserPromptSubmit", payload)
        #     history.append({"role": "user", "content": payload})
        # else:
        #     inbox = consume_lead_inbox()
        #     if not inbox:
        #         continue
        #     history.append(
        #         {
        #             "role": "user",
        #             "content": format_team_events(inbox),
        #         }
        #     )
        #     print(f"[wake: {len(inbox)} team event(s) -> new turn]")

        # agent_loop(history, context)
        # for block in history[-1]["content"]:
        #     if getattr(block, "type", None) == "text":
        #         print(block.text)
        # print_last_assistant_message(history)

        # if active_teammates:
        #     had_teammates = True
        # elif had_teammates and not BUS.peek("lead"):
        #     print("[all teammates shut down]")
        #     had_teammates = False
        # print()
        try:
            query = CONSOLE.ask()
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        with agent_lock:
            trigger_hooks("UserPromptSubmit", query)
            turn_start = len(history)
            session_state["active_user_request"] = query
            history.append({"role": "user", "content": query})
            agent_loop(history, context, query)
            context = update_context(context, history)
            print_turn_assistants(history, turn_start)
        print()


_stdin_queue: "queue.Queue[str | None]" = queue.Queue()


def _read_stdin():
    for line in sys.stdin:
        _stdin_queue.put(line.rstrip("\n"))
    _stdin_queue.put(None)  # EOF -> quit


if __name__ == "__main__":
    main()
