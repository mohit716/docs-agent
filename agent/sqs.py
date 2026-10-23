import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote_plus

import boto3

from agent.textract import TextractTextExtractor


@dataclass(frozen=True)
class SqsSettings:
    region: str
    queue_url: str
    output_prefix: str


def load_sqs_settings() -> SqsSettings:
    return SqsSettings(
        region=os.getenv("AWS_REGION", "us-east-1"),
        queue_url=os.getenv("SQS_QUEUE_URL", "").strip(),
        output_prefix=os.getenv("OCR_OUTPUT_PREFIX", "extracted/").strip()
        or "extracted/",
    )


class DocumentJobQueue:
    """Send document-processing jobs to an Amazon SQS queue."""

    def __init__(self, queue_url: str, region: str | None = None, client=None):
        if not queue_url.strip():
            raise ValueError("SQS_QUEUE_URL is required")
        self.queue_url = queue_url
        self.client = client or boto3.client("sqs", region_name=region)

    def send_document_job(self, bucket: str, key: str, **metadata: Any) -> str:
        bucket = bucket.strip()
        key = key.strip()
        if not bucket or not key:
            raise ValueError("S3 bucket and key are required")
        body = {"bucket": bucket, "key": key, **metadata}
        response = self.client.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps(body),
        )
        return response["MessageId"]


def process_sqs_event(
    event: dict[str, Any],
    *,
    textract_client=None,
    s3_client=None,
    output_prefix: str = "extracted/",
) -> dict[str, list[dict[str, str]]]:
    """Process S3 notifications delivered through an SQS Lambda event.

    Returning batchItemFailures lets Lambda retry only records that failed.
    """
    extractor = TextractTextExtractor(client=textract_client)
    s3 = s3_client or boto3.client("s3")
    failures = []

    for record in event.get("Records") or []:
        message_id = str(record.get("messageId", "")).strip()
        try:
            for bucket, key in s3_objects_from_sqs_record(record):
                text = extractor.extract_s3_object(bucket, key)
                output_key = extracted_key(key, output_prefix)
                s3.put_object(
                    Bucket=bucket,
                    Key=output_key,
                    Body=text.encode("utf-8"),
                    ContentType="text/plain; charset=utf-8",
                )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            print(f"Invalid SQS document message {message_id!r}: {exc}")
            failures.append({"itemIdentifier": message_id})
        except Exception as exc:
            print(f"Document processing failed for SQS message {message_id!r}: {exc}")
            failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": failures}


def s3_objects_from_sqs_record(record: dict[str, Any]) -> list[tuple[str, str]]:
    """Extract S3 locations from a direct job or S3 notification wrapped by SQS."""
    body = record["body"]
    notification = json.loads(body) if isinstance(body, str) else body
    if notification.get("bucket") and notification.get("key"):
        return [(notification["bucket"], notification["key"])]
    locations = []
    for item in notification.get("Records") or []:
        s3 = item["s3"]
        bucket = s3["bucket"]["name"]
        key = unquote_plus(s3["object"]["key"])
        if bucket and key:
            locations.append((bucket, key))
    if not locations:
        raise ValueError("SQS message contains no S3 object records")
    return locations


def extracted_key(source_key: str, output_prefix: str) -> str:
    prefix = output_prefix.strip("/")
    return f"{prefix}/{source_key.rsplit('/', 1)[-1]}.txt" if prefix else f"{source_key}.txt"
