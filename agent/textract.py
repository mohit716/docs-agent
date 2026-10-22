from typing import Any


class TextractTextExtractor:
    """Extract plain text from images or PDFs with Amazon Textract."""

    def __init__(self, client=None, region_name: str | None = None):
        if client is None:
            import boto3

            client = boto3.client("textract", region_name=region_name)
        self.client = client

    def extract_bytes(self, document: bytes) -> str:
        if not document:
            raise ValueError("document is empty")
        response = self.client.detect_document_text(
            Document={"Bytes": document}
        )
        return text_from_response(response)

    def extract_s3_object(self, bucket: str, key: str) -> str:
        bucket = bucket.strip()
        key = key.strip()
        if not bucket or not key:
            raise ValueError("S3 bucket and key are required")
        response = self.client.detect_document_text(
            Document={"S3Object": {"Bucket": bucket, "Name": key}}
        )
        return text_from_response(response)


def text_from_response(response: dict[str, Any]) -> str:
    lines = [
        (block.get("Text") or "").strip()
        for block in response.get("Blocks", [])
        if block.get("BlockType") == "LINE"
    ]
    return "\n".join(line for line in lines if line)
