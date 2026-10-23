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

### Optional Secrets Manager configuration

Set `DOCS_AGENT_SECRET_ID` to the ARN or name of a Secrets Manager secret
containing a JSON object. The CLI and Lambda load its values at startup, while
explicit environment variables take precedence. For example:

```json
{
  "RDS_HOST": "your-rds-endpoint",
  "RDS_PORT": "5432",
  "RDS_DB": "postgres",
  "RDS_USER": "postgres",
  "RDS_PASSWORD": "your-password",
  "AWS_BEARER_TOKEN_BEDROCK": "your-bedrock-token"
}
```

The runtime IAM identity needs `secretsmanager:GetSecretValue` for that secret.
Leave `DOCS_AGENT_SECRET_ID` blank to keep using the existing `.env`
configuration.

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

## Optional document OCR with Textract

`TextractTextExtractor` provides boilerplate for extracting text from a local
image or PDF, or directly from an S3 object:

```python
from agent.textract import TextractTextExtractor

extractor = TextractTextExtractor(region_name="us-east-1")
text = extractor.extract_s3_object("your-document-bucket", "uploads/example.pdf")
print(text)
```

The runtime identity needs `textract:DetectDocumentText` and, for S3 input,
permission to read the object. This helper is intentionally separate from
`search_docs`; the extracted text can be written to S3 and synchronized to the
Bedrock Knowledge Base as part of an upload workflow.

## Optional SQS document worker

The repository includes SQS boilerplate for a separate Lambda worker in
`sqs_worker.py`. It is intended for this flow:

```text
S3 notification -> SQS -> sqs_worker.py -> Textract -> extracted text in S3
```

Configure the worker with:

```text
SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/ACCOUNT_ID/queue-name
OCR_OUTPUT_PREFIX=extracted/
```

The worker expects S3 event notifications wrapped in SQS messages. Configure
the S3 notification to exclude the `extracted/` prefix, or the worker can
process its own output repeatedly. It also accepts direct `{bucket, key}` jobs
sent by `DocumentJobQueue`. Enable the Lambda event source mapping with
partial batch responses so failed messages are retried individually.

The sending helper can enqueue a document job:

```python
from agent.sqs import DocumentJobQueue

queue = DocumentJobQueue("https://sqs.us-east-1.amazonaws.com/ACCOUNT_ID/queue-name")
queue.send_document_job("docs-agent-mohit716", "uploads/example.pdf")
```

The worker role needs `textract:DetectDocumentText`, `s3:GetObject`, and
`s3:PutObject` for the relevant bucket prefixes. Its execution role also needs
the standard SQS receive/delete permissions supplied by the Lambda event
source mapping. This worker does not start a Bedrock Knowledge Base sync;
that should be added after the OCR output format and data-source prefixes are
confirmed.
