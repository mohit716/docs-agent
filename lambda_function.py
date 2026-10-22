import json
from pathlib import Path

import boto3

from agent.config import load_settings
from agent.loop import run_turn
from agent.secrets import load_configured_secret
from agent.tools import KnowledgeBaseSearch, NotesStore, OpenSearchSearch, build_tools


def lambda_handler(event, context):
    print("Received event:", json.dumps(event))

    # 1. Extract and verify user identity from Cognito JWT authorizer
    try:
        claims = (
            event.get("requestContext", {})
            .get("authorizer", {})
            .get("jwt", {})
            .get("claims", {})
        )
        user_id = claims.get("sub")
        username = claims.get("username") or claims.get("cognito:username")
    except Exception as e:
        print(f"Error extracting authorizer claims: {e}")
        user_id = None

    if not user_id:
        return _response(401, "Unauthorized: Missing or invalid token.")

    # 2. Extract your query parameter
    params = event.get("queryStringParameters") or {}
    question = (params.get("q") or "").strip()
    if not question:
        return _response(400, "Add ?q=your question to the URL.")

    # Optional: If you want each user to have isolated notes in /tmp
    # user_notes_path = Path(f"/tmp/notes_{user_id}.json")

    load_configured_secret()
    settings = load_settings()
    client = boto3.client("bedrock-runtime", region_name=settings.region)
    if settings.search_backend == "opensearch":
        docs = OpenSearchSearch(
            settings.opensearch_url,
            settings.opensearch_index,
            settings.opensearch_username,
            settings.opensearch_password,
            settings.opensearch_verify_certs,
        )
    else:
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