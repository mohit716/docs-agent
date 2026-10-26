import hashlib
from datetime import datetime, timezone


class DocumentJobStore:
    """Track document processing state and claim duplicate SQS deliveries."""

    def __init__(self, table_name: str, *, region: str | None = None, client=None):
        table_name = table_name.strip()
        if not table_name:
            raise ValueError("DynamoDB table name is required")
        if client is None:
            import boto3

            client = boto3.client("dynamodb", region_name=region)
        self.table_name = table_name
        self.client = client

    def claim(self, bucket: str, key: str) -> tuple[str, bool]:
        document_id = document_id_for(bucket, key)
        now = datetime.now(timezone.utc).isoformat()
        try:
            self.client.update_item(
                TableName=self.table_name,
                Key={"document_id": {"S": document_id}},
                UpdateExpression=(
                    "SET #status = :processing, bucket = :bucket, "
                    "#key = :key, updated_at = :now, created_at = if_not_exists(created_at, :now)"
                ),
                ConditionExpression=(
                    "attribute_not_exists(document_id) OR #status = :failed"
                ),
                ExpressionAttributeNames={"#status": "status", "#key": "key"},
                ExpressionAttributeValues={
                    ":processing": {"S": "PROCESSING"},
                    ":failed": {"S": "FAILED"},
                    ":bucket": {"S": bucket},
                    ":key": {"S": key},
                    ":now": {"S": now},
                },
            )
            return document_id, True
        except self.client.exceptions.ConditionalCheckFailedException:
            return document_id, False

    def mark_complete(self, document_id: str, output_key: str) -> None:
        self._mark(
            document_id,
            "COMPLETE",
            output_key=output_key,
        )

    def mark_failed(self, document_id: str, error: Exception) -> None:
        self._mark(document_id, "FAILED", error=str(error)[:1000])

    def _mark(self, document_id: str, status: str, **fields: str) -> None:
        names = {"#status": "status"}
        values = {":status": {"S": status}, ":now": {"S": _now()}}
        updates = ["#status = :status", "updated_at = :now"]
        for name, value in fields.items():
            attribute = f"#{name}"
            placeholder = f":{name}"
            names[attribute] = name
            values[placeholder] = {"S": value}
            updates.append(f"{attribute} = {placeholder}")
        self.client.update_item(
            TableName=self.table_name,
            Key={"document_id": {"S": document_id}},
            UpdateExpression="SET " + ", ".join(updates),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )


def document_id_for(bucket: str, key: str) -> str:
    """Create a stable, DynamoDB-safe identifier for an S3 object."""
    location = f"{bucket.strip()}:{key.strip()}".encode("utf-8")
    return hashlib.sha256(location).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
