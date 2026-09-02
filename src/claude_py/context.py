from .config import MEMORY_INDEX, WORKDIR
from .tool import TOOL_HANDLERS
from .skill import SKILL_LOADER
from .mcp import mcp_clients


def update_context(context: dict, messages: list) -> dict:
    memories = ""
    if MEMORY_INDEX.exists():
        content = MEMORY_INDEX.read_text().strip()
        if content:
            memories = content

    catalog = SKILL_LOADER.catalog()
    if catalog == "(no skills found)":
        catalog = ""

    return {
        "enabled_tools": list(TOOL_HANDLERS.keys()),
        "workspace": str(WORKDIR),
        "memories": memories,
        "skills": catalog,
        "mcp_clients": mcp_clients,
    }
