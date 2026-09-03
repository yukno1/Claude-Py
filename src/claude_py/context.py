from .mcp import mcp_clients
from .memory import (
    read_memory_index,
    load_memories,
    extract_memories,
    consolidate_memories,
)
from .team import active_teammates


def update_context(context: dict, messages: list) -> dict:
    return {
        "memory_catalog": read_memory_index(),
        "memories": load_memories(messages),
        "connected_mcp": list(mcp_clients.keys()),
        "active_teammates": list(active_teammates.keys()),
    }


def remember_after_turn(messages: list) -> None:
    if extract_memories(messages):
        consolidate_memories()
