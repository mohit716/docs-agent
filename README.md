# docs-agent

A local chat agent for one person. It calls the Amazon Bedrock Converse API. `search_docs` reads a Managed Knowledge Base when `BEDROCK_KNOWLEDGE_BASE_ID` is set, and otherwise searches `docs/office-guide.md`.

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

## Tools

The model can call these on your machine:

- `search_docs`, over the files in `docs/`
- `get_current_time`
- `calculate`
- `remember` and `recall`, stored in `data/notes.json`

## Change the model

Set `BEDROCK_MODEL_ID` in `.env`. These inference profiles work in `us-east-1`:

- `us.amazon.nova-lite-v1:0`
- `us.amazon.nova-pro-v1:0`

The model must support the Bedrock Converse API with tool use.
