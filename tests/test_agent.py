import tempfile
import unittest
import os
from unittest.mock import patch
from pathlib import Path

from agent.config import Settings
from agent.loop import (
    attach_source,
    files_used,
    labeled_passages,
    run_turn,
    source_names,
    trim_history,
    visible_reply,
    with_source,
)
from agent.tools import (
    DocIndex,
    KnowledgeBaseSearch,
    NotesStore,
    OpenSearchSearch,
    build_tools,
    calculate,
    passages_from_retrieve,
    run_tool,
)
from agent.textract import TextractTextExtractor, text_from_response
from agent.secrets import load_configured_secret
from agent.dynamodb import DocumentJobStore, document_id_for


class FakeDynamoClient:
    class exceptions:
        class ConditionalCheckFailedException(Exception):
            pass

    def __init__(self):
        self.calls = []

    def update_item(self, **kwargs):
        self.calls.append(kwargs)


class DynamoDBTests(unittest.TestCase):
    def test_document_id_is_stable_and_changes_with_location(self):
        first = document_id_for("bucket", "uploads/file.pdf")
        self.assertEqual(first, document_id_for("bucket", "uploads/file.pdf"))
        self.assertNotEqual(first, document_id_for("bucket", "uploads/other.pdf"))

    def test_claim_writes_processing_state(self):
        client = FakeDynamoClient()
        store = DocumentJobStore("document-jobs", client=client)

        document_id, claimed = store.claim("bucket", "uploads/file.pdf")

        self.assertTrue(claimed)
        self.assertEqual(document_id, document_id_for("bucket", "uploads/file.pdf"))
        self.assertEqual(client.calls[0]["TableName"], "document-jobs")
        values = client.calls[0]["ExpressionAttributeValues"]
        self.assertEqual(values[":processing"], {"S": "PROCESSING"})

    def test_mark_complete_writes_output_key(self):
        client = FakeDynamoClient()
        store = DocumentJobStore("document-jobs", client=client)

        store.mark_complete("doc-id", "extracted/file.txt")

        values = client.calls[0]["ExpressionAttributeValues"]
        self.assertEqual(values[":status"], {"S": "COMPLETE"})
        self.assertEqual(values[":output_key"], {"S": "extracted/file.txt"})


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class SecretsTests(unittest.TestCase):
    def test_secret_values_fill_missing_environment_variables(self):
        with patch.dict(
            "os.environ",
            {"DOCS_AGENT_SECRET_ID": "docs-agent/test"},
            clear=True,
        ), patch(
            "agent.secrets.boto3.client"
        ) as client:
            client.return_value.get_secret_value.return_value = {
                "SecretString": '{"RDS_HOST": "db.example", "RDS_PORT": 5432}'
            }
            load_configured_secret()
            self.assertEqual(os.environ["RDS_HOST"], "db.example")
            self.assertEqual(os.environ["RDS_PORT"], "5432")

    def test_existing_environment_values_are_not_overwritten(self):
        with patch.dict(
            "os.environ",
            {"DOCS_AGENT_SECRET_ID": "docs-agent/test", "RDS_HOST": "local"},
            clear=True,
        ), patch(
            "agent.secrets.boto3.client"
        ) as client:
            client.return_value.get_secret_value.return_value = {
                "SecretString": '{"RDS_HOST": "remote"}'
            }
            load_configured_secret()
            self.assertEqual(os.environ["RDS_HOST"], "local")


class TextractTests(unittest.TestCase):
    def test_extract_bytes_sends_document_and_returns_lines(self):
        client = FakeTextractClient(
            {"Blocks": [
                {"BlockType": "LINE", "Text": "First line"},
                {"BlockType": "WORD", "Text": "ignored"},
                {"BlockType": "LINE", "Text": "Second line"},
            ]}
        )

        text = TextractTextExtractor(client=client).extract_bytes(b"pdf-data")

        self.assertEqual(text, "First line\nSecond line")
        self.assertEqual(
            client.calls,
            [{"Document": {"Bytes": b"pdf-data"}}],
        )

    def test_extract_s3_object_validates_location(self):
        with self.assertRaisesRegex(ValueError, "bucket and key"):
            TextractTextExtractor(client=FakeTextractClient({})).extract_s3_object(
                "", "document.pdf"
            )

    def test_text_from_response_ignores_empty_lines(self):
        self.assertEqual(
            text_from_response({"Blocks": [{"BlockType": "LINE", "Text": "  "}]}),
            "",
        )


class FakeTextractClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def detect_document_text(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


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

        self.assertEqual(reply, "birch-lantern-19\n\nSource: guide.md")
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

    def test_masked_document_answer_still_names_the_file(self):
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
                                        "input": {"query": "bucket"},
                                    }
                                }
                            ],
                        }
                    },
                },
                {
                    "stopReason": "guardrail_intervened",
                    "output": {
                        "message": {
                            "role": "assistant",
                            "content": [{"text": "The bucket is in {ADDRESS}."}],
                        }
                    },
                },
            ]
        )
        messages = [{"role": "user", "content": [{"text": "which bucket?"}]}]
        with tempfile.TemporaryDirectory() as directory:
            docs = Path(directory) / "docs"
            docs.mkdir()
            (docs / "docs-agent-notes.md").write_text(
                "## Bucket\n\nThe bucket is docs-agent-mohit716.\n",
                encoding="utf-8",
            )
            reply = run_turn(client, settings(), messages, _tools(Path(directory)))

        self.assertEqual(
            reply,
            "The bucket is in {ADDRESS}.\n\nSource: docs-agent-notes.md",
        )

    def test_blocked_reply_has_no_source_line(self):
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
                    "stopReason": "guardrail_intervened",
                    "output": {
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"text": "Sorry, the model cannot answer this question."}
                            ],
                        }
                    },
                },
            ]
        )
        messages = [{"role": "user", "content": [{"text": "capital of France?"}]}]
        with tempfile.TemporaryDirectory() as directory:
            docs = Path(directory) / "docs"
            docs.mkdir()
            (docs / "guide.md").write_text(
                "## Guest Wi-Fi\n\nThe password is birch-lantern-19.\n",
                encoding="utf-8",
            )
            reply = run_turn(client, settings(), messages, _tools(Path(directory)))

        self.assertEqual(reply, "Sorry, the model cannot answer this question.")

    def test_unanswered_passage_has_no_source_line(self):
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
                                        "input": {"query": "hours"},
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
                            "content": [
                                {
                                    "text": (
                                        "The documents do not contain information about refunds.\n\n"
                                        "Source: guide.md"
                                    )
                                }
                            ],
                        }
                    },
                },
            ]
        )
        messages = [{"role": "user", "content": [{"text": "How long does a refund take?"}]}]
        with tempfile.TemporaryDirectory() as directory:
            docs = Path(directory) / "docs"
            docs.mkdir()
            (docs / "guide.md").write_text(
                "## Hours\n\nThe office opens at 8:15.\n",
                encoding="utf-8",
            )
            reply = run_turn(client, settings(), messages, _tools(Path(directory)))

        self.assertEqual(reply, "The documents do not contain information about refunds.")
        self.assertNotIn("Source:", reply)
        self.assertEqual(
            attach_source("The password is birch-lantern-19.", ["guide.md"]),
            "The password is birch-lantern-19.\n\nSource: guide.md",
        )

    def test_source_line_names_only_the_used_file(self):
        passages = (
            "[stripe-payouts.md]\nThe first payout waits 7 to 14 days.\n\n"
            "[stripe-refunds.md]\nA refund takes 5 to 10 days."
        )
        reply = "The first payout waits 7 to 14 days."
        self.assertEqual(
            files_used(reply, labeled_passages(passages)),
            ["stripe-payouts.md"],
        )
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
                                        "input": {"query": "days"},
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
                            "content": [{"text": reply}],
                        }
                    },
                },
            ]
        )
        messages = [{"role": "user", "content": [{"text": "How long is the first payout?"}]}]
        with tempfile.TemporaryDirectory() as directory:
            docs = Path(directory) / "docs"
            docs.mkdir()
            (docs / "stripe-payouts.md").write_text(
                "The first payout waits 7 to 14 days.\n",
                encoding="utf-8",
            )
            (docs / "stripe-refunds.md").write_text(
                "A refund takes 5 to 10 days.\n",
                encoding="utf-8",
            )
            answer = run_turn(client, settings(), messages, _tools(Path(directory)))

        self.assertEqual(answer, reply + "\n\nSource: stripe-payouts.md")

    def test_source_line_uses_the_file_name(self):
        self.assertEqual(
            source_names(
                "[https://docs-agent-mohit716.s3.amazonaws.com/docs-agent-notes.md]\n"
                "The bucket is docs-agent-mohit716.\n\n"
                "[s3://docs-agent-mohit716/office-guide.md]\n"
                "The password is birch-lantern-19."
            ),
            ["docs-agent-notes.md", "office-guide.md"],
        )
        self.assertEqual(source_names("No matching passages."), [])
        self.assertEqual(
            with_source("The bucket is docs-agent-mohit716.", ["docs-agent-notes.md"]),
            "The bucket is docs-agent-mohit716.\n\nSource: docs-agent-notes.md",
        )
        self.assertEqual(
            with_source("Answer\n\nSource: guide.md", ["guide.md"]),
            "Answer\n\nSource: guide.md",
        )

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

    def test_opensearch_search_formats_hits(self):
        class FakeOpenSearch:
            def search(self, **kwargs):
                self.kwargs = kwargs
                return {
                    "hits": {
                        "hits": [
                            {
                                "_source": {
                                    "file_name": "guide.md",
                                    "section": "Guest Wi-Fi",
                                    "text": "The password is birch-lantern-19.",
                                }
                            }
                        ]
                    }
                }

        client = FakeOpenSearch()
        text = OpenSearchSearch("http://localhost:9200", "documents", client=client).search(
            "guest wifi"
        )
        self.assertEqual(client.kwargs["index"], "documents")
        self.assertIn("birch-lantern-19", text)
        self.assertIn("Guest Wi-Fi", text)

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
