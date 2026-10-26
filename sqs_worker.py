from agent.dynamodb import DocumentJobStore
from agent.sqs import load_sqs_settings, process_sqs_event


def lambda_handler(event, context):
    settings = load_sqs_settings()
    job_store = (
        DocumentJobStore(
            settings.dynamodb_document_table,
            region=settings.region,
        )
        if settings.dynamodb_document_table
        else None
    )
    return process_sqs_event(
        event,
        output_prefix=settings.output_prefix,
        job_store=job_store,
    )
