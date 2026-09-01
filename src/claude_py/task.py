import re
from dataclasses import dataclass, asdict
from pathlib import Path
import secrets
import json
import threading
from contextlib import contextmanager
import os


if os.name == "nt":
    import msvcrt
else:
    import fcntl

from claude_py.config import TASKS_DIR, TASK_LOCK_PATH, WORKDIR, TASKS_ROOT


TASK_ID_PATTERN = re.compile(r"^task_[0-9a-f]{8}$")

TASK_TOOLS = [
    {
        "name": "create_task",
        "description": "Create a task and return its runtime-generated ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["subject"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_task",
        "description": "Add dependencies using IDs returned by create_task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "pattern": "^task_[0-9a-f]{8}$"},
                "addBlockedBy": {
                    "type": "array",
                    "items": {"type": "string", "pattern": "^task_[0-9a-f]{8}$"},
                    "minItems": 1,
                },
            },
            "required": ["task_id", "addBlockedBy"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_tasks",
        "description": "List shared tasks.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_task",
        "description": "Get one task by ID.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "claim_task",
        "description": "Claim a ready task.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "complete_task",
        "description": "Complete an owned task.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    },
]


@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str  # pending | in_progress | completed
    owner: str | None  # Agent 名（多 Agent 场景）
    blockedBy: list[str]  # 依赖的任务 ID 列表


class TaskStore:
    def __init__(self, directory: Path):
        self.directory = directory

    def _root(self, create: bool = False) -> Path:
        if create:
            self.directory.mkdir(parents=True, exist_ok=True)
        root = self.directory.resolve()
        if not root.is_relative_to(WORKDIR.resolve()):
            raise ValueError("Task store escapes the workspace")
        return root

    def _path(self, task_id: str, create_root: bool = False) -> Path:
        if not isinstance(task_id, str) or not TASK_ID_PATTERN.fullmatch(task_id):
            raise ValueError(f"Invalid task ID: {task_id!r}")
        root = self._root(create=create_root)
        path = (root / f"{task_id}.json").resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Invalid task ID: {task_id!r}")
        return path

    def exists(self, task_id: str) -> bool:
        return self._path(task_id).is_file()

    def create(self, subject: str, description: str = "") -> Task:
        subject = subject.strip()
        if not subject:
            raise ValueError("Task subject cannot be empty")

        self._root(create=True)
        for _ in range(100):
            task = Task(
                id=f"task_{secrets.token_hex(4)}",
                subject=subject,
                description=description,
                status="pending",
                owner=None,
                blockedBy=[],
            )
            try:
                with self._path(task.id, create_root=True).open(
                    "x", encoding="utf-8"
                ) as handle:
                    json.dump(asdict(task), handle, indent=2)
                return task
            except FileExistsError:
                continue
        raise RuntimeError("Could not allocate a unique task ID")

    def _depends_on(self, task_id: str, target_id: str) -> bool:
        """Return whether task_id transitively depends on target_id."""
        pending = [task_id]
        visited = set()
        while pending:
            current = pending.pop()
            if current == target_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            pending.extend(self.load(current).blockedBy)
        return False

    def update_dependencies(self, task_id: str, add_blocked_by: list[str]) -> Task:
        if not isinstance(add_blocked_by, list):
            raise ValueError("addBlockedBy must be a list of task IDs")

        task = self.load(task_id)
        if task.status != "pending" or task.owner is not None:
            raise ValueError(
                f"Task {task_id} dependencies can only be updated while "
                "pending and unowned"
            )

        dependencies = list(dict.fromkeys(add_blocked_by))
        for dependency in dependencies:
            if dependency == task_id:
                raise ValueError("Task cannot depend on itself")
            if not self.exists(dependency):
                raise ValueError(f"Dependency not found: {dependency}")
            if dependency not in task.blockedBy and self._depends_on(
                dependency, task_id
            ):
                raise ValueError(
                    f"Dependency cycle detected: {task_id} -> {dependency}"
                )

        task.blockedBy.extend(
            dependency
            for dependency in dependencies
            if dependency not in task.blockedBy
        )
        self.save(task)
        return task

    def save(self, task: Task) -> None:
        with task_store_lock():
            path = _task_path(task.id)
            temporary = path.with_name(
                f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            try:
                temporary.write_text(
                    json.dumps(asdict(task), indent=2), encoding="utf-8"
                )
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)

    def load(self, task_id: str) -> Task:
        data = json.loads(self._path(task_id).read_text(encoding="utf-8"))
        task = Task(**data)
        if task.id != task_id:
            raise ValueError(f"Task file ID does not match {task_id}")
        if task.status not in ("pending", "in_progress", "completed"):
            raise ValueError(f"Invalid task status: {task.status}")
        return task

    def list(self) -> list[Task]:
        if not self.directory.exists():
            return []
        root = self._root()
        return [self.load(path.stem) for path in sorted(root.glob("task_*.json"))]


TASKS = TaskStore(TASKS_DIR)


TASK_ID_PATTERN = re.compile(r"^task_[0-9a-f]{8}$")
task_lock = threading.RLock()
_task_store_state = threading.local()

# owner -> {"task_id": str, "cwd": Path}. A teammate gets one assignment at
# a time, and every filesystem tool resolves its cwd through this registry.
teammate_assignments: dict[str, dict[str, object]] = {}
assignment_versions: dict[str, int] = {}


@contextmanager
def task_store_lock():
    """Serialize task mutations across threads and host processes."""
    with task_lock:
        depth = getattr(_task_store_state, "depth", 0)
        if depth == 0:
            TASKS_DIR.mkdir(parents=True, exist_ok=True)
            handle = TASK_LOCK_PATH.open("a+", encoding="utf-8")
            _lock_exclusive(handle)
            _task_store_state.handle = handle
        _task_store_state.depth = depth + 1
        try:
            yield
        finally:
            _task_store_state.depth -= 1
            if _task_store_state.depth == 0:
                handle = _task_store_state.handle
                _unlock(handle)
                handle.close()
                del _task_store_state.handle


def advance_assignment_version(owner: str):
    """Invalidate old approvals without clearing an explicit plan requirement."""
    with task_lock:
        assignment_versions[owner] = assignment_versions.get(owner, 0) + 1
        gates = globals().get("plan_gates")
        request_ids = globals().get("plan_request_ids")
        team = globals().get("team_lock")
        if team is not None:
            team.acquire()
        try:
            if (
                isinstance(gates, dict)
                and owner in gates
                and gates[owner] != "not_required"
            ):
                gates[owner] = "required"
            if isinstance(request_ids, dict):
                request_ids.pop(owner, None)
        finally:
            if team is not None:
                team.release()


def create_task(subject: str, description: str = "") -> Task:
    return TASKS.create(subject, description)


def update_task(task_id: str, addBlockedBy: list[str]) -> Task:
    return TASKS.update_dependencies(task_id, addBlockedBy)


def save_task(task: Task):
    TASKS.save(task)


def load_task(task_id: str) -> Task:
    return TASKS.load(task_id)


def list_tasks() -> list[Task]:
    return TASKS.list()


def get_task(task_id: str) -> str:
    return json.dumps(asdict(load_task(task_id)), indent=2)


def incomplete_dependencies(task: Task) -> list[str]:
    incomplete = []
    for dependency in task.blockedBy:
        try:
            if load_task(dependency).status != "completed":
                incomplete.append(dependency)
        except (FileNotFoundError, ValueError):
            incomplete.append(dependency)
    return incomplete


def can_start(task_id: str) -> bool:
    """
    can_start 是 claim_task 的前置检查:
    blockedBy 里有任何一个不是 completed, 就不能认领。
    不存在的依赖视为 blocked, 避免引用错误 ID 时崩溃。
    """
    return not incomplete_dependencies(load_task(task_id))


def claim_task(task_id: str, owner: str = "agent") -> str:
    """
    Agent 开始做一个任务时，调用 claim_task:设置 owner, 状态从 pending → in_progress。
    owner 字段记录谁在做这个任务，多 Agent 场景下防止重复认领

    如果任务已被别人认领 (status != "pending"), 或者依赖没完成 (can_start 返回 False)，拒绝认领。
    """
    task = load_task(task_id)
    if task.status != "pending":
        return f"Task {task_id} is {task.status}, cannot claim"
    dependencies = incomplete_dependencies(task)
    if dependencies:
        return f"Blocked by: {dependencies}"
    task.owner = owner
    task.status = "in_progress"
    TASKS.save(task)
    print(f"  [claim] {task.subject} -> in_progress (owner: {owner})")
    return f"Claimed {task.id} ({task.subject})"


def complete_task(task_id: str, owner: str = "agent") -> str:
    """
    任务做完后，设为 completed。
    同时扫描所有其他任务, 找出刚刚被解锁的下游任务。

    完成 "schema" 后，"endpoints" 和 "docs" 的 can_start 返回 True, 它们可以开始。
    """
    task = load_task(task_id)
    if task.status != "in_progress":
        return f"Task {task_id} is {task.status}, cannot complete"
    if task.owner != owner:
        return f"Task {task_id} is owned by {task.owner}, not {owner}"
    ready_before = {
        candidate.id
        for candidate in list_tasks()
        if candidate.status == "pending"
        and candidate.blockedBy
        and can_start(candidate.id)
    }
    task.status = "completed"
    TASKS.save(task)
    unblocked = [
        candidate.subject
        for candidate in list_tasks()
        if candidate.status == "pending"
        and candidate.blockedBy
        and candidate.id not in ready_before
        and can_start(candidate.id)
    ]
    print(f"  [complete] {task.subject}")
    message = f"Completed {task.id} ({task.subject})"
    if unblocked:
        message += f"\nUnblocked: {', '.join(unblocked)}"
        print(f"  [unblocked] {', '.join(unblocked)}")
    return message


def _task_path(task_id: str) -> Path:
    if not isinstance(task_id, str) or not TASK_ID_PATTERN.fullmatch(task_id):
        raise ValueError(f"Invalid task ID: {task_id!r}")
    path = (TASKS_DIR / f"{task_id}.json").resolve()
    if not TASKS_ROOT.is_relative_to(WORKDIR.resolve()) or not path.is_relative_to(
        TASKS_ROOT
    ):
        raise ValueError(f"Invalid task ID: {task_id!r}")
    return path


def _task_depends_on(task_id: str, target_id: str) -> bool:
    """Return whether task_id transitively depends on target_id."""
    pending = [task_id]
    visited = set()
    while pending:
        current = pending.pop()
        if current == target_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(load_task(current).blockedBy)
    return False


def _owner_in_progress(owner: str) -> Task | None:
    return next(
        (
            task
            for task in list_tasks()
            if task.status == "in_progress" and task.owner == owner
        ),
        None,
    )


def run_create_task(subject: str, description: str = "") -> str:
    task = create_task(subject, description)
    print(f"  \033[34m[create] {task.subject}\033[0m")
    return f"Created {task.id}: {task.subject}"


def run_update_task(task_id: str, addBlockedBy: list[str]) -> str:
    try:
        task = update_task(task_id, addBlockedBy)
    except ValueError as exc:
        return f"Error: {exc}"
    except FileNotFoundError:
        return f"Error: Task {task_id} not found"
    dependencies = ", ".join(task.blockedBy) or "(none)"
    print(f"  \033[34m[update] {task.subject} blockedBy: {dependencies}\033[0m")
    return f"Updated {task.id} blockedBy: {dependencies}"


def run_list_tasks() -> str:
    tasks = list_tasks()
    if not tasks:
        return "No tasks. Use create_task to add some."
    lines = []
    for t in tasks:
        icon = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}.get(
            t.status, "[?]"
        )
        deps = f" (blockedBy: {', '.join(t.blockedBy)})" if t.blockedBy else ""
        owner = f" [{t.owner}]" if t.owner else ""
        worktree = f" (worktree: {t.worktree})" if t.worktree else ""
        lines.append(
            f"  {icon} {t.id}: {t.subject} [{t.status}]{owner}{deps}{worktree}"
        )
    return "\n".join(lines)


def run_get_task(task_id: str) -> str:
    try:
        return get_task(task_id)
    except ValueError as exc:
        return f"Error: {exc}"
    except FileNotFoundError:
        return f"Error: Task {task_id} not found"


def run_claim_task(task_id: str) -> str:
    try:
        return claim_task(task_id, owner="agent")
    except ValueError as exc:
        return f"Error: {exc}"
    except FileNotFoundError:
        return f"Error: Task {task_id} not found"


def run_complete_task(task_id: str) -> str:
    try:
        return complete_task(task_id, owner="agent")
    except ValueError as exc:
        return f"Error: {exc}"
    except FileNotFoundError:
        return f"Error: Task {task_id} not found"


TASK_TOOL_HANDLERS = {
    "create_task": run_create_task,
    "update_task": run_update_task,
    "list_tasks": run_list_tasks,
    "get_task": run_get_task,
    "claim_task": run_claim_task,
    "complete_task": run_complete_task,
}


def _lock_exclusive(handle):
    """Acquire a blocking exclusive lock on an open file handle."""
    if os.name == "nt":
        # msvcrt.locking 锁定的是从当前文件指针开始的字节区间，
        # 且要求该区间已有数据，因此先确保文件里至少有一个字节。
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write("\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock(handle):
    if os.name == "nt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
