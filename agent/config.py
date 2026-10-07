import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    region: str
    model_id: str
    max_tokens: int
    temperature: float
    history_limit: int


def load_settings() -> Settings:
    return Settings(
        region=os.getenv("AWS_REGION", "us-east-1"),
        model_id=os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-lite-v1:0"),
        max_tokens=int(os.getenv("BEDROCK_MAX_TOKENS", "1024")),
        temperature=float(os.getenv("BEDROCK_TEMPERATURE", "0.2")),
        history_limit=int(os.getenv("BEDROCK_HISTORY_MESSAGES", "24")),
    )
