"""The jobs queue and object store this process uses (LLD-0 §3.7, HLD §6.5), chosen once
at start-up by the API and the worker.

In AWS, Terraform sets JOBS_QUEUE_URL and UPLOADS_BUCKET, and the SQS and S3 adapters
are loaded (`platform_common.aws`; ruff TID251 keeps boto3 out of other modules).
They load only on Lambda: anywhere else, either variable being set is an error, so a
test or CI job that somehow gets one fails instead of calling AWS.

Locally and in tests: InlineQueue runs each job as soon as its request commits, and
LocalObjectStore keeps files under build/objects. Anywhere else with neither set,
nothing is configured, and the first send or upload raises rather than falling back to
a fake.
"""

import os
from pathlib import Path

from platform_common import jobs
from platform_common.auth import debug_env, on_lambda
from platform_common.queue import InlineQueue, set_queue
from platform_common.storage import LocalObjectStore, set_store

LOCAL_OBJECTS = Path("build/objects")
AWS_SETTINGS = ("JOBS_QUEUE_URL", "UPLOADS_BUCKET")


def configure() -> None:
    queue_url, bucket = (os.environ.get(name) for name in AWS_SETTINGS)
    if queue_url or bucket:
        if not on_lambda():
            raise RuntimeError(f"{' / '.join(AWS_SETTINGS)} are for Lambda only; unset them here")
        from platform_common import aws

        if queue_url:
            set_queue(aws.SqsQueue(queue_url))
        if bucket:
            set_store(aws.S3ObjectStore(bucket))
    elif debug_env():
        set_queue(InlineQueue(jobs.handle_message))
        set_store(LocalObjectStore(Path(os.environ.get("LOCAL_OBJECTS_DIR", LOCAL_OBJECTS))))
