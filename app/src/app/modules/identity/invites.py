"""Sends the invitation email through Cognito.

Cognito's AdminCreateUser creates the invitee's login and emails them a temporary
password; they sign in, and the app then shows their pending invitations (matched on
their verified email). If the person already has a login, no email is needed: the
invitation simply appears when they next sign in.

Locally and in tests nothing is sent; RecordingSender keeps what would have gone out.
"""

import logging
import os
from dataclasses import dataclass, field

from platform_common.auth import DEBUG_ENVS, platform_env

log = logging.getLogger(__name__)


class DeliveryFailed(Exception):
    pass


@dataclass
class RecordingSender:
    sent: list[tuple[str, bool]] = field(default_factory=list)
    fail: bool = False

    def send(self, email: str, *, resend: bool) -> None:
        if self.fail:
            raise DeliveryFailed("simulated failure")
        self.sent.append((email, resend))


class CognitoSender:
    def __init__(self, user_pool_id: str):
        self.user_pool_id = user_pool_id

    def send(self, email: str, *, resend: bool) -> None:
        import boto3  # provided by the Lambda runtime
        from botocore.exceptions import BotoCoreError, ClientError

        client = boto3.client("cognito-idp")
        params = {
            "UserPoolId": self.user_pool_id,
            "Username": email,
            "UserAttributes": [
                {"Name": "email", "Value": email},
                # The address is the one the owner typed; Cognito proves the person
                # controls it by delivering the temporary password there.
                {"Name": "email_verified", "Value": "true"},
            ],
            "DesiredDeliveryMediums": ["EMAIL"],
        }
        if resend:
            params["MessageAction"] = "RESEND"
        try:
            client.admin_create_user(**params)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code == "UsernameExistsException":
                return  # already has a login; the invitation shows up when they sign in
            if resend and code == "UnsupportedUserStateException":
                return  # they already set a password; nothing to resend
            log.warning("cognito invite failed: %s", code)
            raise DeliveryFailed(code or "cognito error") from exc
        except BotoCoreError as exc:
            log.warning("cognito invite failed: %s", type(exc).__name__)
            raise DeliveryFailed(type(exc).__name__) from exc


_recording = RecordingSender()


def sender():
    pool = os.environ.get("COGNITO_USER_POOL_ID")
    if pool:
        return CognitoSender(pool)
    if platform_env() in DEBUG_ENVS:
        return _recording
    raise DeliveryFailed("COGNITO_USER_POOL_ID is not configured")
