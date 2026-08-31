#!/usr/bin/env python3
"""
s09_memory.py - Memory

    +-----------+   selected memories   +------------+
    | .memory/  | --------------------> | Agent Loop |
    +-----------+ <-------------------- +------------+
                   extracted memories
"""


# from dotenv import load_dotenv

from .hook import (
    trigger_hooks,
    register_hook,
    context_inject_hook,
    permission_hook,
    log_hook,
    large_output_hook,
    summary_hook,
)
from .loop import agent_loop
from .context import update_context


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


def main():
    print("Enter a question, press Enter to send. Type q to quit.\n")

    history = []
    context = update_context({}, [])
    while True:
        try:
            # \001/\002 tell Readline the ANSI escapes have zero display width.
            query = input("\001\033[36m\002claude-py >> \001\033[0m\002")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        trigger_hooks("UserPromptSubmit", query)
        history.append({"role": "user", "content": query})
        agent_loop(history, context)
        for block in history[-1]["content"]:
            if getattr(block, "type", None) == "text":
                print(block.text)
        print()


if __name__ == "__main__":
    main()
