"""Keys the app signs with (D-040): the code and rate-counter HMAC keys.

In AWS, Terraform keeps each key in a Parameter Store SecureString and sets
`<NAME>_PARAM` to the parameter's name; the value is read once per container through the
ssm endpoint. A plain `<NAME>` environment variable still wins, for local runs and tests.
Reading a parameter happens on Lambda only, so a stray `_PARAM` setting in CI fails
instead of reaching AWS.
"""

import os
from functools import cache

from .auth import on_lambda


def secret(name: str) -> str | None:
    """The value of `name`, from the environment or from the parameter `<name>_PARAM`
    names; None when neither is set."""
    value = os.environ.get(name)
    if value:
        return value
    parameter = os.environ.get(f"{name}_PARAM")
    if not parameter:
        return None
    if not on_lambda():
        raise RuntimeError(f"{name}_PARAM is read from Parameter Store on Lambda only; set {name} here")
    return _parameter(parameter)


@cache
def _parameter(parameter: str) -> str:
    from . import aws

    return aws.get_parameter(parameter)
