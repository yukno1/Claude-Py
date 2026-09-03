import json


def extract_text(content) -> str:
    if not isinstance(content, list):
        return str(content)
    return "\n".join(
        getattr(block, "text", "")
        for block in content
        if getattr(block, "type", None) == "text"
    )


def block_text(block) -> str:
    if isinstance(block, dict):
        return str(block.get("text", "")) if block.get("type") == "text" else ""
    return (
        str(getattr(block, "text", ""))
        if getattr(block, "type", None) == "text"
        else ""
    )


def message_text(message: dict) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(filter(None, (block_text(block) for block in content)))
    return ""


def last_assistant_text(content) -> str:
    for block in content:
        if getattr(block, "type", None) == "text":
            return block.text.strip()
        if isinstance(block, dict) and block.get("type") == "text":
            return str(block.get("text", "")).strip()
    return ""


def block_type(block):
    return (
        block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
    )


def has_tool_use(content) -> bool:
    # Do not rely on stop_reason alone; the concrete tool_use block is the
    # continuation signal used by the loop.
    return any(getattr(block, "type", None) == "tool_use" for block in content)


def estimate_size(messages: list) -> int:
    return len(json.dumps(messages, default=str))
