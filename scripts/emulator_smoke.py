"""Optional smoke test of our AWS adapters against a local AWS emulator (R1-M11 prep). Not part of CI.

    AWS_ENDPOINT_URL=https://127.0.0.1:9297 AWS_CA_BUNDLE=<the emulator's certificate> \
    AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=ap-south-1 \
    python scripts/emulator_smoke.py

It runs the real `S3ObjectStore`, `SqsQueue` and `SesSender` from platform_common against the endpoint: put, head, read back,
presign, delete; send and receive one queue message; send one mail. It refuses any endpoint that is not on this computer, so
it can never reach real AWS or cost anything. It reports what each step did and exits 1 if any step failed.
"""

import os
import sys
import uuid
from urllib.parse import urlparse

LOCAL = {"127.0.0.1", "localhost", "::1"}


def main() -> int:
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "")
    if urlparse(endpoint).hostname not in LOCAL:
        print("Set AWS_ENDPOINT_URL to the emulator on this computer (for example https://127.0.0.1:9297). Refusing to continue.")
        return 2
    import boto3

    from platform_common.aws import S3ObjectStore, SesSender, SqsQueue, client_config
    from platform_common.storage import key_for

    failures = []

    def step(name, fn):
        try:
            print(f"ok    {name}: {fn()}")
        except Exception as exc:  # noqa: BLE001 (a smoke test reports every failure, it does not stop at the first)
            failures.append(name)
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")

    cfg = client_config()
    s3 = boto3.client("s3", config=client_config(s3={"addressing_style": "path"}))  # emulators rarely serve bucket subdomains
    bucket, business = "smoke-" + uuid.uuid4().hex[:8], uuid.uuid4()
    key = key_for(business, "exports", uuid.uuid4(), "smoke.json")
    store = S3ObjectStore(bucket, client=s3)
    step("s3 create bucket", lambda: s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": os.environ.get("AWS_DEFAULT_REGION", "ap-south-1")})["ResponseMetadata"]["HTTPStatusCode"])
    step("s3 put and head", lambda: (store.put(business, key, b'{"a":1}', "application/json"), store.head(business, key))[1])
    step("s3 read back", lambda: store.get_bytes(business, key))
    step("s3 presign get", lambda: store.presign_get(business, key, download_name="smoke.json")[:60] + "...")
    step("s3 presign post", lambda: sorted(store.presign_post(business, key, max_bytes=1000, content_type="application/json").fields)[:3])
    step("s3 delete", lambda: (store.delete(business, key), store.head(business, key))[1])
    sqs = boto3.client("sqs", config=cfg)
    url = {}
    step("sqs create queue", lambda: url.setdefault("u", sqs.create_queue(QueueName="smoke-" + uuid.uuid4().hex[:8])["QueueUrl"]))
    step("sqs send and receive", lambda: (SqsQueue(url["u"], client=sqs).send({"job": "x"}), sqs.receive_message(QueueUrl=url["u"], WaitTimeSeconds=1)["Messages"][0]["Body"])[1])
    ses = boto3.client("sesv2", config=cfg)
    step("ses verify sender", lambda: ses.create_email_identity(EmailIdentity="no-reply@example.test")["ResponseMetadata"]["HTTPStatusCode"])
    step("ses send", lambda: SesSender("no-reply@example.test", client=ses).send("someone@example.test", "Smoke", "Hello"))
    print("FAILED: " + ", ".join(failures) if failures else "all steps passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
