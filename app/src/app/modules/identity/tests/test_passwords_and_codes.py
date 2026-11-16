"""Password policy (L1-9) and one-time codes (L1-4)."""

import pytest

from app.modules.identity import codes
from app.modules.identity.service.passwords import PasswordWeak, Policy, _common, check_password

POLICY = Policy(10, 128, True, True, True, True, "!@#$%^&*()-_=+[]{}.,?")


def test_the_bundled_list_has_ten_thousand_entries():
    assert len(_common()) >= 10_000
    assert "password" in _common()


@pytest.mark.parametrize("password", ["Correct-Horse-42!", "Aa1!" + "x" * 6, "Aa1!" + "é" * 6, "Aa1!" + "a" * 124])
def test_passwords_meeting_every_rule_pass(password):
    check_password(password, POLICY)


@pytest.mark.parametrize(
    ("password", "unmet"),
    [
        ("short", ["length", "upper", "digit", "special"]),
        ("alllowercase123!", ["upper"]),
        ("ALLUPPERCASE123!", ["lower"]),
        ("NoDigitsHere!!", ["digit"]),
        ("NoSpecial12345", ["special"]),
        ("Aa1!" + "x" * 125, ["too_long"]),
        (" Correct-Horse-42!", ["edge_space"]),
    ],
)
def test_weak_passwords_list_every_unmet_rule(password, unmet):
    with pytest.raises(PasswordWeak) as e:
        check_password(password, POLICY)
    assert (e.value.code, e.value.status, e.value.field) == ("password_weak", 422, "password")
    assert e.value.unmet == unmet
    assert password not in str(e.value.body())  # the password is never echoed
    assert e.value.body()["error"]["unmet"] == unmet


def test_a_rule_the_policy_switches_off_is_not_checked():
    loose = Policy(10, 128, False, False, False, False, "!")
    check_password("alllowercasewords", loose)


def test_a_common_password_is_refused_when_the_policy_lets_it_through_otherwise():
    loose = Policy(8, 128, False, False, False, False, "!")
    with pytest.raises(PasswordWeak) as e:
        check_password("Password", loose)
    assert e.value.unmet == ["common"]


def test_the_field_name_is_the_callers():
    with pytest.raises(PasswordWeak) as e:
        check_password("x", POLICY, field="new_password")
    assert e.value.field == "new_password"


def test_the_licence_notice_ships_next_to_the_list():
    from app.modules.identity.service import passwords

    notice = passwords._LIST.with_suffix(".LICENSE").read_text()
    assert "MIT License" in notice and "Daniel Miessler" in notice


def test_new_codes_are_six_zero_padded_digits(monkeypatch):
    seen = {codes.new_code() for _ in range(200)}
    assert all(len(c) == 6 and c.isdigit() for c in seen)
    monkeypatch.setattr(codes.secrets, "randbelow", lambda n: 42)
    assert codes.new_code() == "000042"


def test_hmac_binds_purpose_and_normalised_email():
    h = codes.code_hmac("signup", " Asha@Example.com ", "042424")
    assert h == codes.code_hmac("signup", "asha@example.com", "042424")
    assert h != codes.code_hmac("reset", "asha@example.com", "042424")
    assert h != codes.code_hmac("signup", "ravi@example.com", "042424")
    assert h != codes.code_hmac("signup", "asha@example.com", "042425")
    assert b"042424" not in h and len(h) == 32
    with pytest.raises(ValueError):
        codes.code_hmac("login", "asha@example.com", "042424")


def test_hmac_key_comes_from_env_and_fails_closed_outside_local(monkeypatch):
    monkeypatch.setenv("PLATFORM_ENV", "test")
    dev = codes.code_hmac("signup", "a@example.com", "123456")
    monkeypatch.setenv("CODE_HMAC_KEY", "another-key")
    assert codes.code_hmac("signup", "a@example.com", "123456") != dev
    monkeypatch.delenv("CODE_HMAC_KEY")
    monkeypatch.setenv("PLATFORM_ENV", "prod")
    with pytest.raises(RuntimeError, match="CODE_HMAC_KEY"):
        codes.code_hmac("signup", "a@example.com", "123456")


@pytest.mark.parametrize("env", [None, "local", "test"])
def test_hmac_key_never_falls_back_to_the_dev_key_on_lambda(monkeypatch, env):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "saas-staging-api")
    monkeypatch.delenv("CODE_HMAC_KEY", raising=False)
    if env is None:
        monkeypatch.delenv("PLATFORM_ENV", raising=False)
    else:
        monkeypatch.setenv("PLATFORM_ENV", env)
    with pytest.raises(RuntimeError):
        codes.code_hmac("signup", "a@example.com", "123456")
    monkeypatch.setenv("CODE_HMAC_KEY", "real-key")
    monkeypatch.setenv("PLATFORM_ENV", "staging")
    assert codes.code_hmac("signup", "a@example.com", "123456")


def test_hmac_key_fails_closed_when_platform_env_is_unset(monkeypatch):
    monkeypatch.delenv("PLATFORM_ENV", raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.delenv("CODE_HMAC_KEY", raising=False)
    with pytest.raises(RuntimeError, match="CODE_HMAC_KEY"):
        codes.code_hmac("signup", "a@example.com", "123456")
