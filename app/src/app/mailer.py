"""The mailer Lambda (HLD §4, §7): outside the VPC, with no database, sending only
through SES from our verified domain.

It consumes the SQS mail queue that QueueMailer fills after a request commits. Each
message is rendered from its template (platform_common.mail_templates) and sent as
plain text. A message that fails is reported in the partial batch response, so only it
comes back; after five receives SQS moves it to the mail DLQ, which keeps it an hour
and raises an alarm.

Logs carry the template name and message IDs only: never the address, the parameters
or an exception's text, which can quote either (RM2-28).
"""

import json
import logging
import os
from functools import cache

from platform_common.mail_templates import render

logger = logging.getLogger()
logger.setLevel(logging.INFO)


@cache
def _sender():
    domain = os.environ.get("MAIL_FROM_DOMAIN")
    if not domain:
        raise RuntimeError("MAIL_FROM_DOMAIN is not set: no SES identity yet")
    from platform_common.aws import SesSender

    return SesSender(f"no-reply@{domain}")


def handler(event, context):  # noqa: ARG001
    failures = []
    for record in event.get("Records", []):
        message_id = record.get("messageId")
        try:
            message = json.loads(record["body"])
            template, to = message["template"], message["to"]
            subject, body = render(template, message["params"])
            ses_id = _sender().send(to, subject, body)
            logger.info("sent %s, message %s, SES %s", template, message_id, ses_id)
        except Exception as e:  # noqa: BLE001 (any failure goes back to the queue)
            logger.error("could not send message %s: %s", message_id, type(e).__name__)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}
