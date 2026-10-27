"""The jobs queue and object store this process uses (LLD-0 §3.7, HLD §6.5), chosen once
at start-up by the API and the worker.

In AWS, Terraform sets JOBS_QUEUE_URL and UPLOADS_BUCKET, and the SQS and S3 adapters
are loaded (`platform_common.aws`, the only boto3 import). Locally and in tests:
InlineQueue runs each job as soon as its request commits, and LocalObjectStore keeps
files under build/objects. Anywhere else with neither set, nothing is configured, and
the first send or upload raises rather than falling back to a fake.
"""

import os
from pathlib import Path

from platform_common import jobs
from platform_common.auth import debug_env
from platform_common.queue import InlineQueue, set_queue
from platform_common.storage import LocalObjectStore, set_store

LOCAL_OBJECTS = Path("build/objects")


def configure() -> None:
    queue_url, bucket = os.environ.get("JOBS_QUEUE_URL"), os.environ.get("UPLOADS_BUCKET")
    if queue_url or bucket:
        from platform_common import aws

        if queue_url:
            set_queue(aws.SqsQueue(queue_url))
        if bucket:
            set_store(aws.S3ObjectStore(bucket))
    if debug_env():
        if not queue_url:
            set_queue(InlineQueue(jobs.handle_message))
        if not bucket:
            set_store(LocalObjectStore(Path(os.environ.get("LOCAL_OBJECTS_DIR", LOCAL_OBJECTS))))
