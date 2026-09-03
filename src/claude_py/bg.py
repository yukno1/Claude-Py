# -- Background Tasks --

# Slow tools return a placeholder tool_result immediately. Their real output is
# later injected as a task_notification, so the main loop can keep moving.

import threading

from .file import resolve_agent_cwd
from .bash import _run_bash_process, _format_bash_result
from .hook import trigger_hooks

_bg_counter = 0
background_tasks: dict[str, dict] = {}
background_results: dict[str, str] = {}
background_lock = threading.Lock()


class BackgroundManager:
    def __init__(self):
        self.tasks: dict[str, dict] = {}
        self.results: dict[str, str] = {}
        self._ready: list[str] = []
        self._counter = 0
        self._lock = threading.Lock()

    def start(self, block) -> str:
        if block.name != "bash":
            raise ValueError("Only Bash commands can run in the background")
        command = block.input.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("Bash command cannot be empty")

        with self._lock:
            self._counter += 1
            task_id = f"bg_{self._counter:04d}"
            self.tasks[task_id] = {
                "tool_use_id": block.id,
                "command": command,
                "status": "running",
            }

        thread = threading.Thread(
            target=self._run,
            args=(task_id, command),
            daemon=True,
        )
        try:
            thread.start()
        except Exception:
            with self._lock:
                self.tasks.pop(task_id, None)
            raise
        print(f"  [background] started {task_id}: {command[:60]}")
        return task_id

    def _run(self, task_id: str, command: str):
        try:
            output, exit_code = _run_bash_process(command)
            result = _format_bash_result(output, exit_code)
            status = "completed" if exit_code == 0 else "failed"
        except Exception as error:
            result = f"Error: {type(error).__name__}: {error}"
            status = "failed"

        with self._lock:
            task = self.tasks.get(task_id)
            if task is None:
                return
            task["status"] = status
            self.results[task_id] = result
            self._ready.append(task_id)

    def collect(self) -> list[str]:
        with self._lock:
            ready = []
            for task_id in self._ready:
                task = self.tasks.pop(task_id, None)
                result = self.results.pop(task_id, "")
                if task is not None:
                    ready.append((task_id, task, result))
            self._ready.clear()

        notifications = []
        for task_id, task, result in ready:
            notifications.append(
                f"<task_notification>\n"
                f"  <task_id>{task_id}</task_id>\n"
                f"  <status>{task['status']}</status>\n"
                f"  <command>{task['command']}</command>\n"
                f"  <summary>{result[:500]}</summary>\n"
                f"</task_notification>"
            )
            print(f"  [background] collected {task_id}: {task['status']}")
        return notifications


BACKGROUND = BackgroundManager()
background_tasks = BACKGROUND.tasks
background_results = BACKGROUND.results


def should_run_background(tool_name: str, tool_input: dict) -> bool:
    return tool_name == "bash" and tool_input.get("run_in_background") is True


def start_background_task(block, handlers: dict) -> str:
    # return BACKGROUND.start(block)
    global _bg_counter
    command = block.input.get("command", block.name)
    cwd, cwd_error = resolve_agent_cwd()

    def worker():
        try:
            if block.name != "bash":
                raise ValueError("only bash can run in the background")
            if cwd_error:
                raise ValueError(cwd_error.removeprefix("Error: "))
            output, exit_code = _run_bash_process(str(block.input["command"]), cwd)
            result = _format_bash_result(output, exit_code)
            status = "completed" if exit_code == 0 else "failed"
        except Exception as exc:
            result = f"Error: {type(exc).__name__}: {exc}"
            status = "failed"
        try:
            trigger_hooks("PostToolUse", block, result)
        except Exception as exc:
            result = (
                f"Error: PostToolUse hook failed: {type(exc).__name__}: {exc}\n{result}"
            )
            status = "failed"
        with background_lock:
            task = background_tasks.get(bg_id)
            if task is None:
                return
            task["status"] = status
            background_results[bg_id] = str(result)

    with background_lock:
        _bg_counter += 1
        bg_id = f"bg_{_bg_counter:04d}"
        background_tasks[bg_id] = {
            "tool_use_id": block.id,
            "command": command,
            "status": "running",
            "cwd": str(cwd) if cwd else None,
        }
    thread = threading.Thread(target=worker, daemon=True)
    try:
        thread.start()
    except Exception:
        with background_lock:
            background_tasks.pop(bg_id, None)
            background_results.pop(bg_id, None)
        raise
    print(f"  \033[33m[background] {bg_id}: {str(command)[:60]}\033[0m")
    return bg_id


def collect_background_results() -> list[str]:
    # return BACKGROUND.collect()
    with background_lock:
        ready = [
            bg_id
            for bg_id, task in background_tasks.items()
            if task["status"] in {"completed", "failed"}
        ]
        completed = [
            (bg_id, background_tasks.pop(bg_id), background_results.pop(bg_id, ""))
            for bg_id in ready
        ]
    notifications = []
    for bg_id, task, output in completed:
        summary = output[:200] if len(output) > 200 else output
        notifications.append(
            f"<task_notification>\n"
            f"  <task_id>{bg_id}</task_id>\n"
            f"  <status>{task['status']}</status>\n"
            f"  <command>{task['command']}</command>\n"
            f"  <summary>{summary}</summary>\n"
            f"</task_notification>"
        )
    return notifications


def inject_background_results(messages: list) -> int:
    notifications = collect_background_results()
    if not notifications:
        return 0

    blocks = [{"type": "text", "text": item} for item in notifications]
    if messages and messages[-1].get("role") == "user":
        content = messages[-1].get("content", "")
        if isinstance(content, list):
            content.extend(blocks)
        else:
            messages[-1]["content"] = [
                {"type": "text", "text": str(content)},
                *blocks,
            ]
    else:
        messages.append({"role": "user", "content": blocks})
    return len(notifications)


def has_pending_background() -> bool:
    """Return whether terminal background work is waiting for delivery."""
    with background_lock:
        return any(
            task["status"] in {"completed", "failed"}
            for task in background_tasks.values()
        )
