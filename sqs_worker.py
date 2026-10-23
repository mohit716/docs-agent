from agent.sqs import load_sqs_settings, process_sqs_event


def lambda_handler(event, context):
    settings = load_sqs_settings()
    return process_sqs_event(
        event,
        output_prefix=settings.output_prefix,
    )
