"""AWS adapters: SqsQueue, S3ObjectStore, SesSender, get_parameter and cognito_client.

This is the only module that imports boto3, and it is loaded only on Lambda: by the
app's start-up code when JOBS_QUEUE_URL / UPLOADS_BUCKET / MAIL_QUEUE_URL are set, by
`secrets` for a `*_PARAM` setting, and by the mailer Lambda. Tests and local runs use
FakeQueue, InlineQueue, LocalObjectStore and FakeMailer and never load this file.
"""

import json
from datetime import timedelta

import boto3

from .clock import Clock
from .storage import (
    GET_EXPIRY_SECONDS,
    POST_EXPIRY_SECONDS,
    ObjectInfo,
    PresignedPost,
    check_key,
    content_disposition,
)


class SqsQueue:
    def __init__(self, queue_url: str, client=None):
        self.queue_url = queue_url
        self.client = client or boto3.client("sqs", config=client_config())

    def send(self, body: dict) -> None:
        self.client.send_message(QueueUrl=self.queue_url, MessageBody=json.dumps(body, sort_keys=True))


class S3ObjectStore:
    """One private bucket whose default encryption is SSE-KMS with our key (H-4), so no
    call here names encryption. The signer's role needs kms:GenerateDataKey on that key."""

    def __init__(self, bucket: str, client=None, clock: Clock | None = None):
        self.bucket = bucket
        self.client = client or boto3.client("s3", config=client_config())
        self.clock = clock or Clock()

    def presign_post(self, business_id, key, *, max_bytes, content_type=None) -> PresignedPost:
        check_key(business_id, key)
        if max_bytes < 1:
            raise ValueError("max_bytes must be at least 1")
        # generate_presigned_post adds an exact {"key": key} condition itself.
        fields, conditions = {}, [["content-length-range", 1, max_bytes]]
        if content_type is not None:
            fields["Content-Type"] = content_type
            conditions.append({"Content-Type": content_type})
        expires_at = self.clock.now() + timedelta(seconds=POST_EXPIRY_SECONDS)
        post = self.client.generate_presigned_post(
            Bucket=self.bucket, Key=key, Fields=fields, Conditions=conditions, ExpiresIn=POST_EXPIRY_SECONDS
        )
        return PresignedPost(post["url"], post["fields"], expires_at)

    def presign_get(self, business_id, key, *, download_name=None) -> str:
        check_key(business_id, key)
        params = {"Bucket": self.bucket, "Key": key}
        if download_name:
            params["ResponseContentDisposition"] = content_disposition(download_name)
        return self.client.generate_presigned_url("get_object", Params=params, ExpiresIn=GET_EXPIRY_SECONDS)

    def head(self, business_id, key) -> ObjectInfo | None:
        check_key(business_id, key)
        try:
            r = self.client.head_object(Bucket=self.bucket, Key=key)
        except self.client.exceptions.ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise
        return ObjectInfo(r["ContentLength"], r.get("ContentType"))

    def get_bytes(self, business_id, key) -> bytes:
        check_key(business_id, key)
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def put(self, business_id, key, data, content_type) -> None:
        check_key(business_id, key)
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def delete(self, business_id, key) -> None:
        check_key(business_id, key)
        self.client.delete_object(Bucket=self.bucket, Key=key)


class SesSender:
    """Sends one plain-text email through SES v2 from our verified domain. The mailer
    Lambda's role may call ses:SendEmail on that identity only (HLD §4)."""

    def __init__(self, from_address: str, client=None):
        self.from_address = from_address
        self.client = client or boto3.client("sesv2", config=client_config())

    def send(self, to: str, subject: str, body: str) -> str:
        r = self.client.send_email(
            FromEmailAddress=self.from_address,
            Destination={"ToAddresses": [to]},
            Content={"Simple": {"Subject": {"Data": subject, "Charset": "UTF-8"},
                                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}}}},
        )
        return r["MessageId"]


def client_config():
    """The one botocore Config for every client this module builds (Cognito, SQS, S3,
    SES and Parameter Store). API requests wait on these calls, so a slow one fails fast
    instead of holding the request until API Gateway's 29 s limit: 2 s to connect, 5 s
    per read (botocore's default is 60 s each), and standard retries with 3 attempts in
    all, the first included (botocore's max_attempts would count retries only).
    read_timeout bounds each socket read, not a whole transfer, so a large S3 object is
    not cut off by it.
    botocore is imported here, not at the top, so this module loads without it (the
    platform_common tests replace boto3 with a stand-in)."""
    from botocore.config import Config

    return Config(connect_timeout=2, read_timeout=5, retries={"mode": "standard", "total_max_attempts": 3})


def cognito_client():
    """The cognito-idp client identity's CognitoAuthProvider drives (LLD-1 §7.2). Built
    here because boto3 is imported only in this module (D-039)."""
    return boto3.client("cognito-idp", config=client_config())


def get_parameter(name: str) -> str:
    """A Parameter Store SecureString, decrypted (the aws/ssm key)."""
    ssm = boto3.client("ssm", config=client_config())
    return ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
