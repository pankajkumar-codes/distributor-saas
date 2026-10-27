"""AWS adapters for the queue and storage ports: SqsQueue and S3ObjectStore.

This is the only module that imports boto3, and only the app's start-up code imports
it, when JOBS_QUEUE_URL / UPLOADS_BUCKET are set (in AWS). Tests and local runs use
FakeQueue, InlineQueue and LocalObjectStore and never load this file.
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
        self.client = client or boto3.client("sqs")

    def send(self, body: dict) -> None:
        self.client.send_message(QueueUrl=self.queue_url, MessageBody=json.dumps(body, sort_keys=True))


class S3ObjectStore:
    """One private bucket whose default encryption is SSE-KMS with our key (H-4), so no
    call here names encryption. The signer's role needs kms:GenerateDataKey on that key."""

    def __init__(self, bucket: str, client=None, clock: Clock | None = None):
        self.bucket = bucket
        self.client = client or boto3.client("s3")
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
