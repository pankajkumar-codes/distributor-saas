"""The worker Lambda: SQS jobs from the outbox (TD-3).

Today it only logs each message's type; job handlers per module come with their
slices (invoice PDFs in LLD-4)."""

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
