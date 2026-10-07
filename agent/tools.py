import ast
import json
import operator
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], str]

    def spec(self) -> dict[str, Any]:
        return {
            "toolSpec": {
                "name": self.name,
                "description": self.description,
                "inputSchema": {"json": self.schema},
            }
        }


class NotesStore:
    """Local notes. This stands in until a Bedrock Knowledge Base is connected."""

    def __init__(self, path: Path):
        self.path = path

    def remember(self, text: str) -> str:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("note text is empty")
        notes = self._load()
        notes.append(
            {
                "text": cleaned,
                "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(notes, indent=2), encoding="utf-8")
        return f"Saved note {len(notes)}."

    def recall(self, query: str = "") -> str:
        notes = self._load()
        if query.strip():
            needle = query.strip().lower()
            notes = [note for note in notes if needle in note["text"].lower()]
        if not notes:
            return "No matching notes."
        return "\n".join(f"{note['saved_at']}: {note['text']}" for note in notes[-20:])

    def _load(self) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("notes file is not a list")
        return data


def get_current_time(timezone: str | None = None) -> str:
    if timezone:
        try:
            now = datetime.now(ZoneInfo(timezone))
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {timezone}") from exc
    else:
        now = datetime.now().astimezone()
    return now.isoformat(timespec="seconds")


def calculate(expression: str) -> str:
    if len(expression) > 200:
        raise ValueError("expression is too long")
    tree = ast.parse(expression, mode="eval")
    return _format_number(_eval_math(tree))


def _eval_math(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_math(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        if isinstance(node.op, ast.Pow):
            base = _eval_math(node.left)
            exponent = _eval_math(node.right)
            if abs(base) > 1_000_000 or abs(exponent) > 32:
                raise ValueError("power is too large")
            return _BINOPS[ast.Pow](base, exponent)
        return _BINOPS[type(node.op)](_eval_math(node.left), _eval_math(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval_math(node.operand))
    raise ValueError("only numbers and + - * / % ** are allowed")


def _format_number(value: float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


class DocIndex:
    """Keyword search over local text files. A stand-in for a Bedrock Knowledge Base."""

    def __init__(self, directory: Path):
        self.directory = directory

    def search(self, query: str) -> str:
        terms = _query_terms(query)
        if not terms:
            raise ValueError("search query is empty")
        chunks = self._chunks()
        if not chunks:
            return "No documents are available."
        ranked = []
        for name, body in chunks:
            words = _words(body)
            hits = sum(1 for term in terms if term in words)
            if hits:
                ranked.append((hits, name, body))
        if not ranked:
            return "No matching passages."
        ranked.sort(key=lambda item: (-item[0], item[1]))
        parts = [f"[{name}]\n{body}" for _, name, body in ranked[:3]]
        return "\n\n".join(parts)

    def _chunks(self) -> list[tuple[str, str]]:
        if not self.directory.is_dir():
            return []
        chunks: list[tuple[str, str]] = []
        for path in sorted(self.directory.glob("*")):
            if path.suffix.lower() not in {".md", ".txt"} or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for part in re.split(r"\n(?=#+\s)", text):
                body = part.strip()
                if body:
                    chunks.append((path.name, body))
        return chunks


def _words(text: str) -> set[str]:
    lowered = text.lower()
    words = set(re.findall(r"[a-z0-9]+", lowered))
    for match in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)+", lowered):
        words.add(match.replace("-", ""))
    return words


def _query_terms(query: str) -> list[str]:
    skip = {"the", "and", "for", "what", "when", "where", "how", "who", "does", "with"}
    return [
        term
        for term in re.findall(r"[a-z0-9]+", query.lower())
        if len(term) >= 3 and term not in skip
    ]


def build_tools(notes: NotesStore, docs: DocIndex) -> list[Tool]:
    return [
        Tool(
            name="search_docs",
            description=(
                "Search the local office documents and return matching passages. "
                "Use this before answering questions about office hours, wifi, equipment, or time off."
            ),
            schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Words to look up in the documents, for example guest wifi password.",
                    }
                },
                "required": ["query"],
            },
            handler=lambda payload: docs.search(str(payload.get("query", ""))),
        ),
        Tool(
            name="get_current_time",
            description="Return the current date and time. Use this when the user asks what time it is.",
            schema={
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone such as America/New_York. Omit for local time.",
                    }
                },
            },
            handler=lambda payload: get_current_time(payload.get("timezone") or None),
        ),
        Tool(
            name="calculate",
            description="Evaluate an arithmetic expression using + - * / % and **.",
            schema={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Arithmetic expression, for example (12 + 8) * 1.5",
                    }
                },
                "required": ["expression"],
            },
            handler=lambda payload: calculate(str(payload.get("expression", ""))),
        ),
        Tool(
            name="remember",
            description="Save a short note on this machine for later. Use this when the user asks you to remember something.",
            schema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The note to store.",
                    }
                },
                "required": ["text"],
            },
            handler=lambda payload: notes.remember(str(payload.get("text", ""))),
        ),
        Tool(
            name="recall",
            description="Look up notes saved earlier on this machine.",
            schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional text that must appear in the note. Omit to list recent notes.",
                    }
                },
            },
            handler=lambda payload: notes.recall(str(payload.get("query", ""))),
        ),
    ]


def run_tool(tools: list[Tool], tool_use: dict[str, Any]) -> dict[str, Any]:
    tool_use_id = tool_use["toolUseId"]
    name = tool_use.get("name", "")
    payload = tool_use.get("input") or {}
    if not isinstance(payload, dict):
        return _error_result(tool_use_id, "tool input must be an object")

    match = next((tool for tool in tools if tool.name == name), None)
    if match is None:
        return _error_result(tool_use_id, f"unknown tool: {name}")

    try:
        text = match.handler(payload)
    except Exception as exc:
        return _error_result(tool_use_id, str(exc))

    return {
        "toolResult": {
            "toolUseId": tool_use_id,
            "content": [{"text": text}],
        }
    }


def _error_result(tool_use_id: str, message: str) -> dict[str, Any]:
    return {
        "toolResult": {
            "toolUseId": tool_use_id,
            "content": [{"text": message}],
            "status": "error",
        }
    }
