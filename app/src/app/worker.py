"""The worker Lambda (TD-3, LLD-0 §3.7): the jobs queue, and the outbox sweep.

`handler` takes either an SQS batch, whose `job.run` messages it hands to
platform_common.jobs, or the 1-minute EventBridge event that sweeps the outbox. A
message that should be retried is reported in the partial batch response, so only that
message comes back; SQS moves it to the DLQ after five receives.

Job handlers are registered by the modules that own them; importing app.api loads
every module, so the worker sees the same handlers as the API.
"""

import json
import logging

import app.api  # noqa: F401 (registers modules, their job handlers, the resolver and the runtime)
from platform_common import jobs, outbox

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _lease_seconds(context) -> int:
    """HLD §7: the lease is this invocation's timeout plus a minute."""
    remaining_ms = getattr(context, "get_remaining_time_in_millis", None)
    if remaining_ms is None:
        return jobs.DEFAULT_LEASE_SECONDS
    return int(remaining_ms() / 1000) + 60


def sqs_handler(event, context):
    failures = []
    lease = _lease_seconds(context)
    for record in event.get("Records", []):
        try:
            outcome = jobs.handle_message(json.loads(record["body"]), lease_seconds=lease)
            logger.info("message %s: %s", record.get("messageId"), outcome)
            if outcome == jobs.RETRY:
                failures.append({"itemIdentifier": record["messageId"]})
        except Exception:
            logger.exception("could not process message %s", record.get("messageId"))
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def handler(event, context):
    if "Records" in event:
        return sqs_handler(event, context)
    if event.get("task") == "sweep_outbox":
        return {"resent": outbox.sweep()}
    raise ValueError(f"unknown worker event {sorted(event)!r}")
