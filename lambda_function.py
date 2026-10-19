import json
from pathlib import Path

import boto3

from agent.config import load_settings
from agent.loop import run_turn
from agent.tools import KnowledgeBaseSearch, NotesStore, build_tools


def lambda_handler(event, context):
    params = event.get("queryStringParameters") or {}
    question = (params.get("q") or "").strip()
    if not question:
        return _response(400, "Add ?q=your question to the URL.")

    settings = load_settings()
    client = boto3.client("bedrock-runtime", region_name=settings.region)
    docs = KnowledgeBaseSearch(
        boto3.client("bedrock-agent-runtime", region_name=settings.region),
        settings.knowledge_base_id,
    )
    tools = build_tools(NotesStore(Path("/tmp/notes.json")), docs)
    messages = [{"role": "user", "content": [{"text": question}]}]
    reply = run_turn(client, settings, messages, tools)
    return _response(200, reply)


def _response(status, text):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "text/plain"},
        "body": text,
    }