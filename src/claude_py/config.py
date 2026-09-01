from anthropic import Anthropic
from pathlib import Path


WORKDIR = Path(__file__).resolve().parent.parent.parent
MEMORY_DIR = WORKDIR / ".memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"

TASKS_DIR = WORKDIR / ".tasks"
TASKS_ROOT = TASKS_DIR.resolve()
TASK_LOCK_PATH = TASKS_DIR / ".lock"
DURABLE_PATH = WORKDIR / ".scheduled_tasks.json"

WORKTREES_DIR = WORKDIR / ".worktrees"
WORKTREES_ROOT = WORKTREES_DIR.resolve()

MAILBOX_DIR = WORKDIR / ".mailboxes"
MAILBOX_ROOT = MAILBOX_DIR.resolve()

# MODEL = os.environ["MODEL_ID"]
PRIMARY_MODEL = "qwen3.5:9b"
SECONDARY_MODEL = "qwen3:4b"
FALLBACK_MODEL = "qwen3:4b"

# CONSTANTS
DEFAULT_MAX_TOKENS = 8000
ESCALATED_MAX_TOKENS = 64000
MAX_RETRIES = 10
MAX_RECOVERY_RETRIES = 3


client = Anthropic(
    base_url="http://127.0.0.1:11434",
    api_key="ollama",
)
