"""The emails the mailer Lambda sends (LLD-1 §2 mailer/templates), as plain text.

The wording is a first draft for the PO to review; it names no product (not chosen yet)
and no code lifetime (that is refdata). A code never appears in a subject line, which
mail apps show in notifications and lists.

`render` is also the check every Mailer runs before a message leaves the request, so a
missing, extra or non-string parameter fails in tests rather than in the mailer.
"""

from string import Template

_IGNORE = "If this wasn't you, you can ignore this email."
_SECURE = "If you didn't do this, reset your password now."

# name -> (subject, body, defaults for parameters that may be empty)
_TEMPLATES: dict[str, tuple[str, str, dict[str, str]]] = {
    "signup_code": ("Your sign-up code", f"Your sign-up code is $code.\n\n{_IGNORE}", {}),
    "already_registered": (
        "You already have an account",
        "Someone, perhaps you, tried to sign up with this email address. You already have an account:"
        f" sign in, or reset your password if you've forgotten it.\n\n{_IGNORE}",
        {},
    ),
    "reset_code": (
        "Your password reset code",
        f"Your password reset code is $code.\n\n{_IGNORE} Your password hasn't changed.",
        {},
    ),
    "reset_no_account": (
        "Password reset",
        "Someone asked to reset the password for this email address, but no account uses it."
        f" If that was you, you may have signed up with a different address.\n\n{_IGNORE}",
        {},
    ),
    "password_changed": (
        "Your password was changed",
        f"Your password was just changed, and you've been signed out everywhere else.\n\n{_SECURE}",
        {},
    ),
    "totp_on": ("Two-step sign-in is on", f"Two-step sign-in with an authenticator app is now on.\n\n{_SECURE}", {}),
    "totp_off": ("Two-step sign-in is off", f"Two-step sign-in with an authenticator app is now off.\n\n{_SECURE}", {}),
    "invitation": (
        "$inviter_name invited you to join $business_name",
        "$inviter_name invited you to join $business_name as $role_label.\n\nAccept the invitation: $link\n\n"
        "If you weren't expecting this, you can ignore this email.",
        {"business_name": "their business"},
    ),
}

TEMPLATES = frozenset(_TEMPLATES)


def _one_line(value: str) -> str:
    """No control characters, so a name can't add lines to a subject or the body."""
    return " ".join("".join(c if c.isprintable() else " " for c in value).split())


def render(template: str, params: dict[str, str]) -> tuple[str, str]:
    """(subject, body). Raises ValueError for an unknown template or wrong parameters."""
    if template not in _TEMPLATES:
        raise ValueError(f"unknown mail template {template!r}")
    subject, body, defaults = _TEMPLATES[template]
    expected = set(Template(subject).get_identifiers()) | set(Template(body).get_identifiers())
    if set(params) != expected or not all(isinstance(v, str) for v in params.values()):
        raise ValueError(f"mail template {template!r} takes exactly the string params {sorted(expected)}")
    values = {k: _one_line(v) or defaults.get(k, "") for k, v in params.items()}
    return Template(subject).substitute(values), Template(body).substitute(values)
