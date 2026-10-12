"""documents: builds invoice PDFs from invoice-finalized events on SQS and stores
them privately in S3. The PDF template waits on approved invoice/tax requirements."""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def sqs_handler(event, context):  # noqa: ARG001
    failures = []
    for record in event.get("Records", []):
        try:
            message = json.loads(record["body"])
            logger.info("received %s", message.get("type"))
        except Exception:
            logger.exception("could not process message %s", record.get("messageId"))
            failures.append({"itemIdentifier": record["messageId"]})
    # Partial batch response: only failed messages are retried.
    return {"batchItemFailures": failures}
