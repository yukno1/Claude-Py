from anthropic import Anthropic
from pathlib import Path


WORKDIR = Path(__file__).resolve().parent.parent.parent
MEMORY_DIR = WORKDIR / ".memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"

# MODEL = os.environ["MODEL_ID"]
MODEL = "qwen3.5:9b"


client = Anthropic(
    base_url="http://127.0.0.1:11434",
    api_key="ollama",
)
