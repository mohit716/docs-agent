import tempfile
import unittest
from pathlib import Path

from agent.config import Settings
from agent.loop import run_turn, trim_history, visible_reply
from agent.tools import NotesStore, build_tools, calculate, run_tool


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def settings() -> Settings:
    return Settings(
        region="us-east-1",
        model_id="us.amazon.nova-lite-v1:0",
        max_tokens=256,
        temperature=0.2,
        history_limit=24,
    )


class LoopTests(unittest.TestCase):
    def test_tool_call_then_answer(self):
        client = FakeClient(
            [
                {
                    "stopReason": "tool_use",
                    "output": {
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "toolUse": {
                                        "toolUseId": "t1",
                                        "name": "calculate",
                                        "input": {"expression": "2 + 2"},
                                    }
                                }
                            ],
                        }
                    },
                },
                {
                    "stopReason": "end_turn",
                    "output": {
                        "message": {
                            "role": "assistant",
                            "content": [{"text": "4"}],
                        }
                    },
                },
            ]
        )
        used = []
        messages = [{"role": "user", "content": [{"text": "what is 2 + 2?"}]}]
        with tempfile.TemporaryDirectory() as directory:
            tools = build_tools(NotesStore(Path(directory) / "notes.json"))
            reply = run_turn(client, settings(), messages, tools, on_tool=used.append)

        self.assertEqual(reply, "4")
        self.assertEqual(used, ["calculate"])
        tool_result = messages[2]["content"][0]["toolResult"]
        self.assertEqual(tool_result["content"][0]["text"], "4")
        self.assertEqual(client.calls[0]["modelId"], "us.amazon.nova-lite-v1:0")

    def test_thinking_only_reply_is_retried(self):
        client = FakeClient(
            [
                {
                    "stopReason": "end_turn",
                    "output": {
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "text": (
                                        "<thinking>The user said hello. "
                                        "I should greet them.</thinking>"
                                    )
                                }
                            ],
                        }
                    },
                },
                {
                    "stopReason": "end_turn",
                    "output": {
                        "message": {
                            "role": "assistant",
                            "content": [{"text": "Hi. What do you need?"}],
                        }
                    },
                },
            ]
        )
        messages = [{"role": "user", "content": [{"text": "hi"}]}]
        with tempfile.TemporaryDirectory() as directory:
            tools = build_tools(NotesStore(Path(directory) / "notes.json"))
            reply = run_turn(client, settings(), messages, tools)

        self.assertEqual(reply, "Hi. What do you need?")
        self.assertEqual(messages[-1]["content"], [{"text": "Hi. What do you need?"}])
        self.assertIn("plain sentences", client.calls[1]["system"][0]["text"])

    def test_visible_reply_keeps_text_after_thinking(self):
        raw = "<thinking>draft</thinking>\n\nYes. I can help you write code."
        self.assertEqual(visible_reply(raw), "Yes. I can help you write code.")

    def test_unknown_tool_returns_error_result(self):
        result = run_tool(
            [],
            {"toolUseId": "missing", "name": "nope", "input": {}},
        )
        self.assertEqual(result["toolResult"]["status"], "error")


class ToolTests(unittest.TestCase):
    def test_calculate_allows_arithmetic_only(self):
        self.assertEqual(calculate("(12 + 8) * 1.5"), "30")
        with self.assertRaises(ValueError):
            calculate("__import__('os').system('echo hi')")

    def test_notes_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = NotesStore(Path(directory) / "notes.json")
            tools = build_tools(store)
            saved = run_tool(
                tools,
                {
                    "toolUseId": "n1",
                    "name": "remember",
                    "input": {"text": "desk lamp is on the left"},
                },
            )
            found = run_tool(
                tools,
                {"toolUseId": "n2", "name": "recall", "input": {"query": "lamp"}},
            )

        self.assertIn("Saved note 1", saved["toolResult"]["content"][0]["text"])
        self.assertIn("desk lamp is on the left", found["toolResult"]["content"][0]["text"])

    def test_trim_drops_leading_tool_result(self):
        messages = [
            {"role": "assistant", "content": [{"text": "old"}]},
            {
                "role": "user",
                "content": [{"toolResult": {"toolUseId": "x", "content": [{"text": "1"}]}}],
            },
            {"role": "user", "content": [{"text": "keep me"}]},
        ]
        trim_history(messages, limit=10)
        self.assertEqual(messages, [{"role": "user", "content": [{"text": "keep me"}]}])


if __name__ == "__main__":
    unittest.main()
