"""D-094: the region allowlist, the endpoint check and the Bedrock model rule."""

import pytest

from platform_common.regions import (
    RegionRefused,
    bedrock_model_in_india,
    check_endpoints,
    configured_region,
    require_india_region,
)


def test_only_mumbai_and_hyderabad_pass():
    assert require_india_region("ap-south-1") == "ap-south-1" and require_india_region("ap-south-2") == "ap-south-2"
    for region in ("us-east-1", "eu-west-1", "ap-southeast-1", "ap-south-3", "", "global"):
        with pytest.raises(RegionRefused):
            require_india_region(region)


def test_the_configured_region_defaults_to_mumbai_and_refuses_a_foreign_setting():
    assert configured_region({}) == "ap-south-1"
    assert configured_region({"AWS_REGION": "ap-south-2"}) == "ap-south-2"
    assert configured_region({"AWS_DEFAULT_REGION": "ap-south-1"}) == "ap-south-1"
    for env in ({"AWS_REGION": "us-east-1"}, {"AWS_DEFAULT_REGION": "eu-west-1"}, {"AWS_REGION": "ap-south-1", "AWS_DEFAULT_REGION": "us-west-2"}):
        with pytest.raises(RegionRefused):
            configured_region(env)


@pytest.mark.parametrize("url", ["https://localhost:9297", "http://127.0.0.1:4566", "https://sqs.ap-south-1.amazonaws.com", "https://x.ap-south-2.api.aws"])
def test_endpoints_on_this_computer_or_in_india_are_fine(url):
    check_endpoints({"AWS_ENDPOINT_URL": url, "AWS_ENDPOINT_URL_S3": url, "PATH": "/usr/bin"})


@pytest.mark.parametrize("url", ["https://example.com", "https://sqs.us-east-1.amazonaws.com", "https://evil.com/ap-south-1.amazonaws.com", "https://ap-south-1.amazonaws.com.evil.com"])
def test_any_other_endpoint_is_refused(url):
    with pytest.raises(RegionRefused):
        check_endpoints({"AWS_ENDPOINT_URL_SQS": url})


@pytest.mark.parametrize(
    "model",
    [
        "anthropic.claude-test-v1:0",
        "amazon.nova-test-v1:0",
        "arn:aws:bedrock:ap-south-1::foundation-model/anthropic.claude-test-v1:0",
        "arn:aws:bedrock:ap-south-2::foundation-model/amazon.nova-test-v1:0",
    ],
)
def test_a_model_that_runs_where_the_client_is_pinned_or_a_foundation_model_in_india_is_accepted(model):
    assert bedrock_model_in_india(model)


@pytest.mark.parametrize(
    "model",
    [
        "us.anthropic.claude-test-v1:0",
        "eu.anthropic.claude-test-v1:0",
        "apac.anthropic.claude-test-v1:0",  # spans several Asia-Pacific regions, not only India
        "global.anthropic.claude-test-v1:0",
        "in.anthropic.claude-test-v1:0",  # unverified: refused until it is read from the console and approved
        "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-test-v1:0",
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-test-v1:0",
        "arn:aws:bedrock:::foundation-model/anthropic.claude-test-v1:0",
        "arn:aws:bedrock:ap-south-1::foundation-model/us.anthropic.claude-test-v1:0",  # a geography id inside an ARN
        "arn:aws:bedrock:ap-south-1::foundation-model/profile-x",
        # An inference-profile ARN is refused even in an Indian region: a system profile can be apac. or global.,
        # and an application profile can wrap one. Each needs an allowlist entry after its own review.
        "arn:aws:bedrock:ap-south-1:123456789012:inference-profile/apac.anthropic.claude-test-v1:0",
        "arn:aws:bedrock:ap-south-1:123456789012:inference-profile/global.anthropic.claude-test-v1:0",
        "arn:aws:bedrock:ap-south-1:123456789012:application-inference-profile/abc123",
        "arn:aws:bedrock:ap-south-1:123456789012:inference-profile/some-profile",
        "arn:aws:bedrock::123456789012:inference-profile/x",
        "profile-x",
        "",
        " ",
        "anthropic",
    ],
)
def test_a_profile_that_could_leave_india_or_is_not_recognised_is_refused(model):
    assert not bedrock_model_in_india(model)
