"""Mail templates and QueueMailer (HLD §7, D-040). Nothing here can send mail."""

import pytest

from platform_common.mail_templates import TEMPLATES, render
from platform_common.mailer import FakeMailer, QueueMailer
from platform_common.queue import FakeQueue

PARAMS = {
    "signup_code": {"code": "042424"},
    "reset_code": {"code": "042424"},
    "invitation": {"business_name": "Vashi Essentials", "inviter_name": "Asha", "role_label": "Billing",
                   "link": "https://app.example.in/invite/t0ken"},
}


@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_every_template_renders_and_keeps_codes_out_of_the_subject(template):
    subject, body = render(template, PARAMS.get(template, {}))
    assert subject and body and "$" not in subject + body
    assert "042424" not in subject
    if "code" in PARAMS.get(template, {}):
        assert "042424" in body


@pytest.mark.parametrize(
    ("template", "params"),
    [("signup_code", {}), ("signup_code", {"code": "1", "extra": "x"}), ("password_changed", {"code": "1"}),
     ("reset_code", {"code": 42}), ("no_such_template", {})],
)
def test_missing_extra_or_non_string_params_are_refused(template, params):
    with pytest.raises(ValueError):
        render(template, params)
    with pytest.raises(ValueError):
        FakeMailer().send(template, "a@example.com", params)


def test_a_name_cannot_add_lines_and_an_empty_business_name_reads_naturally():
    params = {**PARAMS["invitation"], "inviter_name": "Asha\r\nBcc: x@example.com", "business_name": ""}
    subject, body = render("invitation", params)
    assert subject == "Asha Bcc: x@example.com invited you to join their business"
    assert "\r" not in body and "Bcc: x@example.com invited" in body


def test_queue_mailer_queues_the_message_for_the_mailer_lambda():
    queue = FakeQueue()
    QueueMailer(queue).send("signup_code", "a@example.com", {"code": "042424"})
    assert queue.sent == [{"template": "signup_code", "to": "a@example.com", "params": {"code": "042424"}}]
    with pytest.raises(ValueError):
        QueueMailer(queue).send("signup_code", "not-an-address", {"code": "1"})
    assert len(queue.sent) == 1
