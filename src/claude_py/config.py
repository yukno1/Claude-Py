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
CONTEXT_LIMIT = 50000
DEFAULT_MAX_TOKENS = 8000
ESCALATED_MAX_TOKENS = 16000
MAX_RETRIES = 3
MAX_CONSECUTIVE_529 = 2
MAX_RECOVERY_RETRIES = 2
BASE_DELAY_MS = 500
CONTEXT_LIMIT = 50000
KEEP_RECENT_TOOL_RESULTS = 3
PERSIST_THRESHOLD = 30000
CONTINUATION_PROMPT = (
    "Continue from the previous response. Do not repeat completed work."
)
PROMPT = "\033[36mclaude-py >> \033[0m"
# \001/\002 tell Readline the ANSI escapes have zero display width.
READLINE_PROMPT = "\001\033[36m\002claude-py >> \001\033[0m\002"
CLI_ACTIVE = True

client = Anthropic(
    base_url="http://127.0.0.1:11434",
    api_key="ollama",
)
