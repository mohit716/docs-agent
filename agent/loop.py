import copy
import re
from collections.abc import Callable

from agent.config import Settings
from agent.tools import Tool, run_tool

SYSTEM_PROMPT = (
    "You are a personal assistant for one person, running on their computer. "
    "Write the reply they should read, in plain text. "
    "Do not use <thinking> tags, and do not describe the question back to them. "
    "Answer general questions and write code in the reply when they ask. "
    "For questions about the office documents, call search_docs and answer only from the passages it returns. "
    "If search_docs finds nothing, say the documents do not contain the answer. "
    "Use the other tools for the current time, arithmetic, and saving or looking up notes. "
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
    grounding_source = ""

    for _ in range(MAX_TOOL_ROUNDS):
        request: dict = {
            "modelId": settings.model_id,
            "messages": with_grounding(
                messages,
                latest_user_question(messages),
                grounding_source if settings.guardrail_id else "",
            ),
            "system": [{"text": system_text}],
            "inferenceConfig": {
                "maxTokens": settings.max_tokens,
                "temperature": settings.temperature,
            },
            "toolConfig": {"tools": specs},
        }
        if settings.guardrail_id:
            request["guardrailConfig"] = {
                "guardrailIdentifier": settings.guardrail_id,
                "guardrailVersion": settings.guardrail_version,
            }
        response = client.converse(**request)
        message = response["output"]["message"]
        messages.append(message)
        if response.get("stopReason") == "guardrail_intervened":
            reply = visible_reply(text_of(message)) or (
                "Sorry, the model cannot answer this question."
            )
            message["content"] = [{"text": reply}]
            return reply
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
        source_parts = []
        for block in message.get("content", []):
            tool_use = block.get("toolUse")
            if not tool_use:
                continue
            if on_tool:
                on_tool(tool_use.get("name", ""))
            result = run_tool(tools, tool_use)
            results.append(result)
            if tool_use.get("name") == "search_docs":
                source_parts.extend(_result_text(result))
        if source_parts:
            grounding_source = "\n\n".join(source_parts)
        if not results:
            return text_of(message) or "The model asked for a tool but did not name one."
        messages.append({"role": "user", "content": results})

    return "Stopped after too many tool calls. Rephrase the request or use /reset."


def with_grounding(messages: list[dict], query: str, source: str) -> list[dict]:
    """Mark the retrieved passages as the guardrail grounding source for this call."""
    if not source or not query:
        return messages
    cloned = copy.deepcopy(messages)
    for message in reversed(cloned):
        if message.get("role") != "user" or _is_tool_result(message):
            continue
        message.setdefault("content", []).extend(
            [
                {
                    "guardContent": {
                        "text": {
                            "text": source,
                            "qualifiers": ["grounding_source"],
                        }
                    }
                },
                {
                    "guardContent": {
                        "text": {
                            "text": query,
                            "qualifiers": ["query", "guard_content"],
                        }
                    }
                },
            ]
        )
        break
    return cloned


def latest_user_question(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        for block in message.get("content") or []:
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return ""


def _result_text(result: dict) -> list[str]:
    tool_result = result.get("toolResult") or {}
    if tool_result.get("status") == "error":
        return []
    return [
        block["text"]
        for block in tool_result.get("content") or []
        if isinstance(block.get("text"), str) and block["text"]
    ]


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
