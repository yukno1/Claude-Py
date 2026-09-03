# -- Hooks and Permission Checks --

# Hooks are intentionally outside tool handlers. The loop can add permission,
# logging, and stop behavior without changing each individual tool.

import re
import threading

from claude_py.config import WORKDIR
from claude_py.console import CONSOLE, terminal_print


HOOKS = {"UserPromptSubmit": [], "PreToolUse": [], "PostToolUse": [], "Stop": []}

DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
DESTRUCTIVE_COMMAND_WORD = re.compile(
    r"(?i)(?:^|[;&|()\n])\s*(?:rm|del)(?=\s|$|[;&|()])"
)
DESTRUCTIVE = ["rm ", "> /etc/", "chmod 777"]


def register_hook(event: str, callback):
    HOOKS[event].append(callback)


def trigger_hooks(event: str, *args, skip_permission: bool = False):
    for callback in HOOKS[event]:
        if skip_permission and callback is permission_hook:
            continue
        result = callback(*args)
        if result is not None:
            return result
    return None


def contains_destructive_command(command: str) -> bool:
    return bool(DESTRUCTIVE_COMMAND_WORD.search(command))


# def check_permission(block, prompt_user: bool = True) -> str | None:
#     if block.name == "bash":
#         command = block.input.get("command", "")
#         for pattern in DENY_LIST:
#             if pattern in command:
#                 return f"Permission denied by deny list: {pattern}"
#         if contains_destructive_command(command) or any(
#             keyword in command for keyword in DESTRUCTIVE
#         ):
#             if not prompt_user:
#                 return "Permission required: ask Lead to run this command."
#             print(f"\n[permission] {block.name}({block.input})")
#             if input("Allow? [y/N] ").strip().lower() not in {"y", "yes"}:
#                 return "Permission denied by user"

#     if block.name in {"read_file", "write_file", "edit_file"}:
#         raw_path = block.input.get("path", "")
#         if not (WORKDIR / raw_path).resolve().is_relative_to(WORKDIR.resolve()):
#             if not prompt_user:
#                 return "Permission required: path is outside the workspace."
#             print(f"\n[permission] {block.name}({block.input})")
#             if input("\033[33mAllow? [y/N] \033[0m").strip().lower() not in {
#                 "y",
#                 "yes",
#             }:
#                 return "Permission denied by user"
#     return None


def permission_hook(block):
    # The permission layer sees the raw tool_use before dispatch. It can deny,
    # ask the user, or allow execution to continue.
    from claude_py import mcp

    if block.name == "bash":
        command = block.input.get("command", "")
        if not isinstance(command, str):
            return "Permission denied: shell command must be a string"
        for pattern in DENY_LIST:
            if pattern in command:
                return f"Permission denied: '{pattern}' is on the deny list"
        if threading.current_thread() is not threading.main_thread():
            return (
                "Permission denied: interactive shell approval is unavailable "
                "during an asynchronous turn"
            )
        terminal_print("\n\033[33m[permission] shell command\033[0m")
        terminal_print(f"  {command}")
        choice = CONSOLE.ask("  Allow? [y/N] ").strip().lower()
        if choice not in ("y", "yes"):
            return "Permission denied by user"
    if block.name in ("read_file", "write_file", "edit_file"):
        path = block.input.get("path", "")
        if not isinstance(path, str):
            return "Permission denied: path must be a string"
        if not (WORKDIR / path).resolve().is_relative_to(WORKDIR):
            return "Permission denied: path is outside the workspace"
    if (
        block.name.startswith("mcp__")
        and mcp.mcp_tool_policies.get(block.name, "confirm") != "allow"
    ):
        if threading.current_thread() is not threading.main_thread():
            return (
                "Permission denied: interactive MCP approval is unavailable "
                "during an asynchronous turn"
            )
        terminal_print(f"\n\033[33m[permission] MCP tool: {block.name}\033[0m")
        choice = CONSOLE.ask("  Allow? [y/N] ").strip().lower()
        if choice not in ("y", "yes"):
            return "Permission denied by user"
    return None


def log_hook(block):
    preview = str(list(block.input.values())[:2])[:60]
    print(f"\033[90m[HOOK] {block.name}({preview})\033[0m")
    return None


def large_output_hook(block, output):
    if len(str(output)) > 100000:
        print(
            f"\033[33m[HOOK] Large output from {block.name}: {len(str(output))} chars\033[0m"
        )
    return None


def context_inject_hook(query: str):
    print(f"\033[36m[HOOK] UserPromptSubmit: working in {WORKDIR}\033[0m")
    return None


def summary_hook(messages: list):
    tool_count = sum(
        1
        for message in messages
        for block in (
            message.get("content") if isinstance(message.get("content"), list) else []
        )
        if isinstance(block, dict) and block.get("type") == "tool_result"
    )
    print(f"\033[34m[HOOK] Stop: session used {tool_count} tool calls\033[0m")
    return None
