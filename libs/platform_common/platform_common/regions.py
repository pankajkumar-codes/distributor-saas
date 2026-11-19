"""Tenant data stays in India (D-094): the only AWS regions this code will talk to, and the checks that enforce it.

Pure Python, no AWS library, so the app's Bedrock reader and the AWS client builders can both use it.
Mumbai (ap-south-1) is where everything runs; Hyderabad (ap-south-2) is allowed because an in-country
model profile may exist only there. Nothing here reads a setting that could be changed at run time: the
list is code, reviewed like code.
"""

import os
import re
from collections.abc import Mapping
from urllib.parse import urlparse

INDIA_REGIONS = frozenset({"ap-south-1", "ap-south-2"})
HOME_REGION = "ap-south-1"

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})
_REGIONAL_HOST = re.compile(r"(^|\.)(" + "|".join(re.escape(r) for r in INDIA_REGIONS) + r")\.(amazonaws\.com|api\.aws)$")
# Bedrock model ids that call a model in the region of the client: "<provider>.<model>[:version]". An id that starts
# with a geography ("us.", "eu.", "apac.", "global.", ...) is an inference profile that sends the request to other
# regions, so it is not on this list on purpose. A profile that stays in India is named by its ARN below.
_PROVIDERS = frozenset({"anthropic", "amazon", "meta", "mistral", "cohere", "ai21", "deepseek"})
_MODEL_ID = re.compile(r"^([a-z0-9-]+)\.[A-Za-z0-9][A-Za-z0-9._:-]*$")
# Only a foundation-model ARN is accepted. An inference-profile ARN is refused whatever its region: a system profile
# can be a geography one (apac., global.) that routes out of India, and an application profile can wrap one, so a
# profile needs its own review and an allowlist entry here before it is used.
_BEDROCK_ARN = re.compile(r"^arn:aws:bedrock:([a-z0-9-]*)::foundation-model/([A-Za-z0-9][A-Za-z0-9._:-]*)$")


class RegionRefused(RuntimeError):
    """Something would leave India. Its message names the setting, never a value from a request."""


def require_india_region(region: str, what: str = "the AWS region") -> str:
    if region not in INDIA_REGIONS:
        raise RegionRefused(f"{what} is {region!r}; tenant data stays in {sorted(INDIA_REGIONS)} (D-094)")
    return region


def configured_region(env: Mapping[str, str] | None = None) -> str:
    """The region every AWS client is pinned to: AWS_REGION or AWS_DEFAULT_REGION when set (Lambda sets the first),
    else Mumbai. A setting outside India stops the process rather than being used."""
    env = os.environ if env is None else env
    for name in ("AWS_REGION", "AWS_DEFAULT_REGION"):
        if env.get(name):
            require_india_region(env[name], name)
    return env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or HOME_REGION


def check_endpoints(env: Mapping[str, str] | None = None) -> None:
    """An endpoint override (AWS_ENDPOINT_URL and the per-service AWS_ENDPOINT_URL_*) may point only at this
    computer (the AWS emulator) or at an Indian regional AWS host."""
    env = os.environ if env is None else env
    for name, value in env.items():
        if name != "AWS_ENDPOINT_URL" and not name.startswith("AWS_ENDPOINT_URL_"):
            continue
        host = (urlparse(value).hostname or "").lower()
        if host not in _LOCAL_HOSTS and not _REGIONAL_HOST.search(host):
            raise RegionRefused(f"{name} points outside India or this computer; tenant data stays in India (D-094)")


def bedrock_model_in_india(model_id: str) -> bool:
    """True for a plain model id (it runs in the region of the pinned client) or for the ARN of a foundation model in
    an Indian region. False for a geography-prefixed or global inference profile id, any inference-profile ARN
    (system or application) until it is allowlisted, an ARN in another region or with no region, and anything not
    recognised."""
    model_id = (model_id or "").strip()
    arn = _BEDROCK_ARN.match(model_id)
    if arn:
        return arn.group(1) in INDIA_REGIONS and bedrock_model_in_india(arn.group(2))
    found = _MODEL_ID.match(model_id)
    return bool(found) and found.group(1) in _PROVIDERS
