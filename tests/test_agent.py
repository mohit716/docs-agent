import tempfile
import unittest
from pathlib import Path

from agent.config import Settings
from agent.loop import run_turn, trim_history, visible_reply
from agent.tools import (
    DocIndex,
    KnowledgeBaseSearch,
    NotesStore,
    build_tools,
    calculate,
    passages_from_retrieve,
    run_tool,
)


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
        knowledge_base_id="",
        guardrail_id="",
        guardrail_version="1",
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
            tools = _tools(Path(directory))
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
            tools = _tools(Path(directory))
            reply = run_turn(client, settings(), messages, tools)

        self.assertEqual(reply, "Hi. What do you need?")
        self.assertEqual(messages[-1]["content"], [{"text": "Hi. What do you need?"}])
        self.assertIn("plain sentences", client.calls[1]["system"][0]["text"])

    def test_guardrail_and_grounding_are_sent_after_search(self):
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
                                        "toolUseId": "d1",
                                        "name": "search_docs",
                                        "input": {"query": "wifi"},
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
                            "content": [{"text": "birch-lantern-19"}],
                        }
                    },
                },
            ]
        )
        guarded = settings()
        guarded = type(guarded)(
            **{**guarded.__dict__, "guardrail_id": "d4kbabpmm9jf"}
        )
        messages = [{"role": "user", "content": [{"text": "wifi password?"}]}]
        with tempfile.TemporaryDirectory() as directory:
            docs = Path(directory) / "docs"
            docs.mkdir()
            (docs / "guide.md").write_text(
                "## Guest Wi-Fi\n\nThe password is birch-lantern-19.\n",
                encoding="utf-8",
            )
            reply = run_turn(client, guarded, messages, _tools(Path(directory)))

        self.assertEqual(reply, "birch-lantern-19")
        config = client.calls[1]["guardrailConfig"]
        self.assertEqual(config["guardrailIdentifier"], "d4kbabpmm9jf")
        self.assertEqual(config["guardrailVersion"], "1")
        qualifiers = [
            block["guardContent"]["text"]["qualifiers"]
            for block in client.calls[1]["messages"][0]["content"]
            if "guardContent" in block
        ]
        self.assertIn(["grounding_source"], qualifiers)
        self.assertIn(["query", "guard_content"], qualifiers)

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
            tools = _tools(Path(directory))
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

    def test_search_docs_returns_the_matching_section(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs"
            docs.mkdir()
            (docs / "guide.md").write_text(
                "# Guide\n\n## Guest Wi-Fi\n\nThe password is birch-lantern-19.\n\n"
                "## Hours\n\nThe office opens at 8:15.\n",
                encoding="utf-8",
            )
            tools = build_tools(NotesStore(root / "notes.json"), DocIndex(docs))
            found = run_tool(
                tools,
                {
                    "toolUseId": "d1",
                    "name": "search_docs",
                    "input": {"query": "guest wifi password"},
                },
            )

        text = found["toolResult"]["content"][0]["text"]
        self.assertIn("birch-lantern-19", text)
        self.assertNotIn("opens at 8:15", text)

    def test_knowledge_base_search_formats_retrieve_results(self):
        class FakeRetrieve:
            def retrieve(self, **kwargs):
                self.kwargs = kwargs
                return {
                    "retrievalResults": [
                        {
                            "content": {"text": "The password is birch-lantern-19."},
                            "location": {
                                "s3Location": {
                                    "uri": "s3://docs-agent-mohit716/office-guide.md"
                                }
                            },
                        }
                    ]
                }

        client = FakeRetrieve()
        text = KnowledgeBaseSearch(client, "HR5D1WUZG4").search("guest wifi")
        self.assertEqual(client.kwargs["knowledgeBaseId"], "HR5D1WUZG4")
        self.assertIn("managedSearchConfiguration", client.kwargs["retrievalConfiguration"])
        self.assertIn("birch-lantern-19", text)
        self.assertEqual(passages_from_retrieve({"retrievalResults": []}), "No matching passages.")

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


def _tools(directory: Path):
    return build_tools(NotesStore(directory / "notes.json"), DocIndex(directory / "docs"))


if __name__ == "__main__":
    unittest.main()
