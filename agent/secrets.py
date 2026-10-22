import json
import os
from typing import Any

import boto3


SECRET_ID_ENV = "DOCS_AGENT_SECRET_ID"


def load_configured_secret() -> None:
    """Load JSON secret values into environment variables when configured.

    Existing environment variables take precedence so local development and
    gradual migration remain supported.
    """
    secret_id = os.getenv(SECRET_ID_ENV, "").strip()
    if not secret_id:
        return

    response = boto3.client(
        "secretsmanager",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    ).get_secret_value(SecretId=secret_id)
    secret_string = response.get("SecretString")
    if not secret_string:
        raise ValueError(f"Secret {secret_id!r} does not contain SecretString")

    try:
        values: Any = json.loads(secret_string)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Secret {secret_id!r} must contain a JSON object"
        ) from exc
    if not isinstance(values, dict):
        raise ValueError(f"Secret {secret_id!r} must contain a JSON object")

    for key, value in values.items():
        if not isinstance(key, str) or not isinstance(value, (str, int, float, bool)):
            raise ValueError(
                f"Secret {secret_id!r} contains an unsupported value for {key!r}"
            )
        os.environ.setdefault(key, str(value))
