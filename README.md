# docs-agent

A local chat agent for one person. It calls the Amazon Bedrock Converse API. `search_docs` can use a local OpenSearch container, a Managed Knowledge Base, or the files in `docs/`. A guardrail is applied when `BEDROCK_GUARDRAIL_ID` is set.

The default model is Nova Lite in US East (N. Virginia). You pay for tokens only. At personal use that stays under about $1 a month.

## Setup

1. In the AWS console, set the region to US East (N. Virginia) and open [Amazon Bedrock](https://console.aws.amazon.com/bedrock/).
2. In the left pane, open **API keys**, then **Long-term API keys**, and choose **Generate long-term API keys**. Copy the key. It is shown once.
3. Copy `.env.example` to `.env` and paste the key as `AWS_BEARER_TOKEN_BEDROCK`.
4. Install and run:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

`/reset` clears the conversation. `/exit` quits.

## Document search with OpenSearch

OpenSearch is optional. The default `SEARCH_BACKEND=auto` uses the Bedrock
Knowledge Base when `BEDROCK_KNOWLEDGE_BASE_ID` is set, and otherwise uses the
local file index. To run OpenSearch locally:

```powershell
docker compose up -d
$env:SEARCH_BACKEND = "opensearch"
python index_documents.py
python main.py
```

The indexer reads Markdown and text files from `docs/` and stores each section
in the `documents` index. Configure a different instance or index with:

```text
SEARCH_BACKEND=opensearch
OPENSEARCH_URL=http://localhost:9200
OPENSEARCH_INDEX=documents
```

The Docker compose file disables security for local development only. Use
Amazon OpenSearch Service or a secured OpenSearch deployment for Lambda and
production. A Lambda function cannot connect to OpenSearch running only on
your laptop; set `OPENSEARCH_URL` to a network-accessible OpenSearch endpoint.

When `RDS_HOST` is set, notes and the chat are stored in that Postgres database and loaded again on the next start. `/reset` deletes the saved chat. Without `RDS_HOST`, notes stay in `data/notes.json` and the chat lasts only until the program exits.

## Tools

The model can call these on your machine:

- `search_docs`, over the files in `docs/`
- `get_current_time`
- `calculate`
- `remember` and `recall`, stored in RDS when `RDS_HOST` is set, otherwise in `data/notes.json`

## Change the model

Set `BEDROCK_MODEL_ID` in `.env`. These inference profiles work in `us-east-1`:

- `us.amazon.nova-lite-v1:0`
- `us.amazon.nova-pro-v1:0`

The model must support the Bedrock Converse API with tool use.
