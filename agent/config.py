import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    region: str
    model_id: str
    max_tokens: int
    temperature: float
    history_limit: int
    knowledge_base_id: str
    guardrail_id: str
    guardrail_version: str
    search_backend: str = "auto"
    opensearch_url: str = "http://localhost:9200"
    opensearch_index: str = "documents"
    opensearch_username: str = ""
    opensearch_password: str = ""
    opensearch_verify_certs: bool = False


def load_settings() -> Settings:
    return Settings(
        region=os.getenv("AWS_REGION", "us-east-1"),
        model_id=os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-lite-v1:0"),
        max_tokens=int(os.getenv("BEDROCK_MAX_TOKENS", "1024")),
        temperature=float(os.getenv("BEDROCK_TEMPERATURE", "0.2")),
        history_limit=int(os.getenv("BEDROCK_HISTORY_MESSAGES", "24")),
        knowledge_base_id=os.getenv("BEDROCK_KNOWLEDGE_BASE_ID", "").strip(),
        guardrail_id=os.getenv("BEDROCK_GUARDRAIL_ID", "").strip(),
        guardrail_version=os.getenv("BEDROCK_GUARDRAIL_VERSION", "1").strip() or "1",
        search_backend=os.getenv("SEARCH_BACKEND", "auto").strip().lower() or "auto",
        opensearch_url=os.getenv("OPENSEARCH_URL", "http://localhost:9200").strip(),
        opensearch_index=os.getenv("OPENSEARCH_INDEX", "documents").strip() or "documents",
        opensearch_username=os.getenv("OPENSEARCH_USERNAME", "").strip(),
        opensearch_password=os.getenv("OPENSEARCH_PASSWORD", ""),
        opensearch_verify_certs=os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower()
        in {"1", "true", "yes"},
    )
