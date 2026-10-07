import re
from collections.abc import Callable

from agent.config import Settings
from agent.tools import Tool, run_tool

SYSTEM_PROMPT = (
    "You are a personal assistant for one person, running on their computer. "
    "Write the reply they should read, in plain text. "
    "Do not use <thinking> tags, and do not describe the question back to them. "
    "Answer general questions and write code in the reply when they ask. "
    "Use tools only for the current time, arithmetic, and saving or looking up notes. "
    "Notes are local memory on this computer. Do not invent tool results."
)

_THINKING = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)
_OPEN_THINKING = re.compile(r"<thinking>.*", re.DOTALL | re.IGNORECASE)

MAX_TOOL_ROUNDS = 6


def run_turn(
    client,
    settings: Settings,
    messages: list[dict],
    tools: list[Tool],
    on_tool: Callable[[str], None] | None = None,
) -> str:
    """Send the current message list to Bedrock and resolve tool calls."""
    trim_history(messages, settings.history_limit)
    specs = [tool.spec() for tool in tools]
    system_text = SYSTEM_PROMPT
    empty_replies = 0

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.converse(
            modelId=settings.model_id,
            messages=messages,
            system=[{"text": system_text}],
            inferenceConfig={
                "maxTokens": settings.max_tokens,
                "temperature": settings.temperature,
            },
            toolConfig={"tools": specs},
        )
        message = response["output"]["message"]
        messages.append(message)
        if response.get("stopReason") != "tool_use":
            reply = visible_reply(text_of(message))
            if reply:
                message["content"] = [{"text": reply}]
                return reply
            messages.pop()
            empty_replies += 1
            if empty_replies > 1:
                return "I didn't get a usable reply. Ask again."
            system_text = (
                SYSTEM_PROMPT
                + " The last draft was discarded. Answer in plain sentences only."
            )
            continue

        results = []
        for block in message.get("content", []):
            tool_use = block.get("toolUse")
            if not tool_use:
                continue
            if on_tool:
                on_tool(tool_use.get("name", ""))
            results.append(run_tool(tools, tool_use))
        if not results:
            return text_of(message) or "The model asked for a tool but did not name one."
        messages.append({"role": "user", "content": results})

    return "Stopped after too many tool calls. Rephrase the request or use /reset."


def text_of(message: dict) -> str:
    parts = [
        block["text"]
        for block in message.get("content", [])
        if isinstance(block.get("text"), str) and block["text"]
    ]
    return "\n".join(parts)


def visible_reply(text: str) -> str:
    """Drop Nova's private <thinking> notes and keep the user-facing text."""
    cleaned = _THINKING.sub("", text)
    cleaned = _OPEN_THINKING.sub("", cleaned)
    return cleaned.strip()


def trim_history(messages: list[dict], limit: int) -> None:
    """Drop oldest messages without leaving a tool result at the start."""
    while len(messages) > limit:
        messages.pop(0)
    while messages and (messages[0].get("role") != "user" or _is_tool_result(messages[0])):
        messages.pop(0)


def _is_tool_result(message: dict) -> bool:
    return any("toolResult" in block for block in message.get("content", []))
