"""CognitoAuthProvider against botocore's Stubber (LLD-1 §7.2). Nothing reaches AWS:
the stubbed client checks each call's parameters against Cognito's API model.
"""

import logging

import boto3
import pytest
from botocore.stub import Stubber

from app.modules.identity.cognito import CognitoAuthProvider
from platform_common.authprovider import AuthRefused

POOL, CLIENT = "ap-south-1_TestPool", "testclient"
ISSUER = f"https://cognito-idp.ap-south-1.amazonaws.com/{POOL}"
EMAIL, SUB = "asha@example.com", "0f6c2a3e-1111-4222-8333-444455556666"
SESSION = "session-string-" + "x" * 32  # the model wants at least 20 characters
SECRET = "JBSWY3DPEHPK3PXPJBSWY3DP"
TOKENS = {"AccessToken": "access", "ExpiresIn": 300, "TokenType": "Bearer", "RefreshToken": "refresh"}


@pytest.fixture()
def stub():
    client = boto3.client("cognito-idp", region_name="ap-south-1", aws_access_key_id="x", aws_secret_access_key="x")
    with Stubber(client) as s:
        yield s, CognitoAuthProvider(client, POOL, CLIENT, ISSUER, fetch_json=lambda url: {"keys": [], "url": url})
        s.assert_no_pending_responses()


def error(s, operation, code, message="refused", expected=None):
    s.add_client_error(operation, service_error_code=code, service_message=message, expected_params=expected)


def test_create_user_suppresses_cognito_mail_and_sets_a_permanent_password(stub):
    s, idp = stub
    s.add_response(
        "admin_create_user",
        {"User": {"Username": SUB, "Attributes": [{"Name": "sub", "Value": SUB}]}},
        {
            "UserPoolId": POOL,
            "Username": EMAIL,
            "UserAttributes": [{"Name": "email", "Value": EMAIL}, {"Name": "email_verified", "Value": "true"}],
            "MessageAction": "SUPPRESS",
        },
    )
    s.add_response(
        "admin_set_user_password", {}, {"UserPoolId": POOL, "Username": SUB, "Password": "pw", "Permanent": True}
    )
    assert idp.create_user(EMAIL, "pw") == SUB


def test_create_user_maps_an_existing_user(stub):
    s, idp = stub
    error(s, "admin_create_user", "UsernameExistsException")
    with pytest.raises(AuthRefused, match="user_exists"):
        idp.create_user(EMAIL, "pw")


def test_get_sub_and_an_unknown_email(stub):
    s, idp = stub
    s.add_response(
        "admin_get_user",
        {"Username": SUB, "UserAttributes": [{"Name": "email", "Value": EMAIL}, {"Name": "sub", "Value": SUB}]},
        {"UserPoolId": POOL, "Username": EMAIL},
    )
    error(s, "admin_get_user", "UserNotFoundException")
    assert idp.get_sub(EMAIL) == SUB
    assert idp.get_sub("nobody@example.com") is None


def test_initiate_auth_returns_tokens_or_the_totp_challenge(stub):
    s, idp = stub
    expected = {
        "UserPoolId": POOL,
        "ClientId": CLIENT,
        "AuthFlow": "ADMIN_USER_PASSWORD_AUTH",
        "AuthParameters": {"USERNAME": EMAIL, "PASSWORD": "pw"},
    }
    s.add_response("admin_initiate_auth", {"AuthenticationResult": TOKENS}, expected)
    s.add_response("admin_initiate_auth", {"ChallengeName": "SOFTWARE_TOKEN_MFA", "Session": SESSION}, expected)
    done = idp.initiate_auth(EMAIL, "pw")
    assert (done.access_token, done.refresh_token, done.expires_in, done.needs_totp) == (
        "access",
        "refresh",
        300,
        False,
    )
    assert idp.initiate_auth(EMAIL, "pw").challenge == SESSION


@pytest.mark.parametrize(
    "cognito, ours",
    [
        ("NotAuthorizedException", "not_authorized"),
        ("UserNotFoundException", "not_authorized"),
        ("PasswordResetRequiredException", "not_authorized"),
        ("TooManyRequestsException", "rate_limited"),
    ],
)
def test_initiate_auth_refusals(stub, cognito, ours):
    s, idp = stub
    error(s, "admin_initiate_auth", cognito, "Incorrect username or password.")
    with pytest.raises(AuthRefused) as e:
        idp.initiate_auth(EMAIL, "pw")
    assert e.value.code == ours


@pytest.mark.parametrize(
    "cognito, ours",
    [
        ("CodeMismatchException", "totp_not_accepted"),
        ("ExpiredCodeException", "totp_not_accepted"),
        ("NotAuthorizedException", "challenge_expired"),  # an expired session, or another user's
    ],
)
def test_respond_totp(stub, cognito, ours):
    s, idp = stub
    s.add_response(
        "admin_respond_to_auth_challenge",
        {"AuthenticationResult": TOKENS},
        {
            "UserPoolId": POOL,
            "ClientId": CLIENT,
            "ChallengeName": "SOFTWARE_TOKEN_MFA",
            "Session": SESSION,
            "ChallengeResponses": {"USERNAME": EMAIL, "SOFTWARE_TOKEN_MFA_CODE": "123456"},
        },
    )
    assert idp.respond_totp(EMAIL, SESSION, "123456").access_token == "access"
    error(s, "admin_respond_to_auth_challenge", cognito, "Invalid session for the user.")
    with pytest.raises(AuthRefused) as e:
        idp.respond_totp(EMAIL, SESSION, "000000")
    assert e.value.code == ours


def test_refresh_keeps_the_cookie_s_token_and_revoke_names_the_client(stub):
    s, idp = stub
    result = {k: v for k, v in TOKENS.items() if k != "RefreshToken"}  # rotation is off
    s.add_response(
        "admin_initiate_auth",
        {"AuthenticationResult": result},
        {
            "UserPoolId": POOL,
            "ClientId": CLIENT,
            "AuthFlow": "REFRESH_TOKEN_AUTH",
            "AuthParameters": {"REFRESH_TOKEN": "refresh"},
        },
    )
    s.add_response("revoke_token", {}, {"Token": "refresh", "ClientId": CLIENT})
    assert idp.refresh("refresh").refresh_token is None
    idp.revoke_refresh("refresh")


@pytest.mark.parametrize(
    "cognito, message, ours",
    [
        ("NotAuthorizedException", "Incorrect username or password.", "not_authorized"),
        ("NotAuthorizedException", "Access Token has expired", "token_invalid"),
        ("NotAuthorizedException", "Access Token has been revoked", "token_invalid"),
        ("InvalidPasswordException", "Password does not conform to policy", "password_rejected"),
        ("LimitExceededException", "Attempt limit exceeded", "rate_limited"),
    ],
)
def test_change_password_refusals_each_have_their_own_code(stub, cognito, message, ours):  # Staff 2, #55
    s, idp = stub
    error(
        s, "change_password", cognito, message, {"PreviousPassword": "a", "ProposedPassword": "b", "AccessToken": "t"}
    )
    with pytest.raises(AuthRefused) as e:
        idp.change_password("t", "a", "b")
    assert e.value.code == ours


def test_set_password_and_global_sign_out_use_the_sub(stub):
    s, idp = stub
    s.add_response(
        "admin_set_user_password", {}, {"UserPoolId": POOL, "Username": SUB, "Password": "pw", "Permanent": True}
    )
    s.add_response("admin_user_global_sign_out", {}, {"UserPoolId": POOL, "Username": SUB})
    idp.set_password(SUB, "pw")
    idp.global_sign_out(SUB)


def test_totp_enrolment_turns_the_factor_on_only_after_a_good_code(stub):
    s, idp = stub
    s.add_response("associate_software_token", {"SecretCode": SECRET}, {"AccessToken": "t"})
    error(s, "verify_software_token", "CodeMismatchException", expected={"AccessToken": "t", "UserCode": "000000"})
    s.add_response("verify_software_token", {"Status": "SUCCESS"}, {"AccessToken": "t", "UserCode": "123456"})
    s.add_response(
        "set_user_mfa_preference",
        {},
        {"AccessToken": "t", "SoftwareTokenMfaSettings": {"Enabled": True, "PreferredMfa": True}},
    )
    assert idp.associate_totp("t") == SECRET
    assert idp.verify_totp("t", "000000") is False  # no preference call after a wrong code
    assert idp.verify_totp("t", "123456") is True


def test_totp_calls_with_an_expired_token_are_token_invalid(stub):
    s, idp = stub
    error(s, "associate_software_token", "NotAuthorizedException", "Access Token has expired")
    with pytest.raises(AuthRefused, match="token_invalid"):
        idp.associate_totp("t")


def test_remove_totp_disables_it_and_deletes_the_device(stub):
    s, idp = stub
    s.add_response(
        "admin_set_user_mfa_preference",
        {},
        {"UserPoolId": POOL, "Username": SUB, "SoftwareTokenMfaSettings": {"Enabled": False, "PreferredMfa": False}},
    )
    s.add_response("admin_delete_software_token", {}, {"UserPoolId": POOL, "Username": SUB})
    idp.remove_totp(SUB)


def test_an_unknown_error_is_a_500_with_the_request_id_and_no_message(stub, caplog):
    s, idp = stub
    s.add_client_error(
        "admin_user_global_sign_out",
        service_error_code="InternalErrorException",
        service_message="secret detail asha@example.com",
        response_meta={"RequestId": "req-123"},
    )
    caplog.set_level(logging.ERROR)
    with pytest.raises(RuntimeError):
        idp.global_sign_out(SUB)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "req-123" in text and "InternalErrorException" in text and "asha@example.com" not in text


def test_jwks_is_fetched_once_from_the_issuer(stub):
    _, idp = stub
    first = idp.jwks()
    assert first["url"] == f"{ISSUER}/.well-known/jwks.json" and idp.jwks() is first


def test_the_api_role_allows_exactly_the_admin_calls_the_adapter_makes():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[6]
    source = (root / "app/src/app/modules/identity/cognito.py").read_text()
    made = {"".join(w.capitalize() for w in op.split("_")) for op in re.findall(r'"(admin_[a-z_]+)"', source)}
    made = {m.replace("Mfa", "MFA") for m in made}
    policy = (root / "infra/modules/stack/main.tf").read_text()
    allowed = set(re.findall(r'"cognito-idp:(Admin\w+)"', policy))
    assert made == allowed, (sorted(made - allowed), sorted(allowed - made))
