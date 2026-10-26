"""Password policy (L1-9) and one-time codes (L1-4)."""

import pytest

from app.modules.identity import codes
from app.modules.identity.service.passwords import MAX_LENGTH, MIN_LENGTH, _common, check_password
from platform_common.errors import Invalid


def test_the_bundled_list_has_ten_thousand_entries():
    assert len(_common()) >= 10_000
    assert "password" in _common()


@pytest.mark.parametrize(
    "password",
    ["correct horse battery", "x" * MIN_LENGTH, "é" * MIN_LENGTH, "a" * MAX_LENGTH, "no classes needed here"],
)
def test_long_uncommon_passwords_pass_with_no_class_rules(password):
    check_password(password)


@pytest.mark.parametrize(
    ("password", "fix_word"),
    [
        ("short", "at least"),
        ("x" * (MIN_LENGTH - 1), "at least"),
        ("x" * (MAX_LENGTH + 1), "at most"),
        ("1234567890", "common"),
        ("QWERTYUIOP", "common"),  # the list is compared case-insensitively
        (" correct horse battery", "spaces"),
        ("correct horse battery\t", "spaces"),
    ],
)
def test_weak_passwords_are_refused_with_a_fix(password, fix_word):
    with pytest.raises(Invalid) as e:
        check_password(password)
    assert (e.value.code, e.value.status, e.value.field) == ("password_weak", 422, "password")
    assert fix_word in e.value.fix
    assert password not in str(e.value.body())  # the password is never echoed


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


def test_matches_and_dummy_compare(monkeypatch):
    stored = codes.code_hmac("signup", "asha@example.com", "042424")
    assert codes.matches(stored, "signup", "asha@example.com", "042424")
    assert not codes.matches(stored, "signup", "asha@example.com", "000000")
    calls = []
    real = codes.hmac.compare_digest
    monkeypatch.setattr(codes.hmac, "compare_digest", lambda a, b: calls.append(b) or real(a, b))
    assert not codes.matches(None, "signup", "asha@example.com", "042424")
    assert calls == [codes._DUMMY]  # one compare even with no row


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
