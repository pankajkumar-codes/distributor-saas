"""What the audit-log screen shows for each action and target (LLD-2 §7 [D, RM42-12]).

One table for every action any module records: its label and its kind, which is the
screen's filter group (Invoices, GST Filing, Team & settings, Support). A test fails on
an action registered with `platform_common.audit` that has no label here. Targets map to
the screen that shows them, and that screen's permission, for the row's link.
"""

from platform_common.permissions import Permission

KINDS = ("invoices", "gst_filing", "team_settings", "support")

# action -> (label, kind)
ACTIONS: dict[str, tuple[str, str]] = {
    "auth.signup": ("Signed up", "team_settings"),
    "auth.signin": ("Signed in", "team_settings"),
    "auth.password_reset": ("Reset their password", "team_settings"),
    "auth.password_change": ("Changed their password", "team_settings"),
    "auth.totp_on": ("Turned on two-step sign-in", "team_settings"),
    "auth.totp_off": ("Turned off two-step sign-in", "team_settings"),
    "auth.signout_all": ("Signed out everywhere", "team_settings"),
    "business.create": ("Created the business", "team_settings"),
    "member.invite": ("Invited a member", "team_settings"),
    "member.invite_resend": ("Resent an invite", "team_settings"),
    "member.invite_cancel": ("Cancelled an invite", "team_settings"),
    "member.accept": ("Joined the business", "team_settings"),
    "member.role_change": ("Changed a member's role", "team_settings"),
    "members.deactivate": ("Deactivated a member", "team_settings"),
    "members.reactivate": ("Reactivated a member", "team_settings"),
    "returns.unlock": ("Unlocked a filed period", "gst_filing"),
    "documents.s34_override": ("Overrode the credit-note time limit", "invoices"),
    "filing.accept_warning": ("Accepted a filing warning", "gst_filing"),
    "imports.changed_line_choice": ("Chose how to treat a changed line", "gst_filing"),
    "support.view": ("Support viewed the business", "support"),
    # Rows copied from identity.audit_events (LLD-1 §3.6) keep their stock-era names.
    "tenant.created": ("Created the business", "team_settings"),
    "member.added": ("Added a member", "team_settings"),
    "member.deactivated": ("Deactivated a member", "team_settings"),
    "member.reactivated": ("Reactivated a member", "team_settings"),
    "invitation.created": ("Invited a member", "team_settings"),
    "invitation.resent": ("Resent an invite", "team_settings"),
    "invitation.revoked": ("Cancelled an invite", "team_settings"),
    "invitation.accepted": ("Joined the business", "team_settings"),
}


def actions_of_kind(kind: str) -> list[str]:
    return sorted(action for action, (_, k) in ACTIONS.items() if k == kind)


def label(action: str) -> str:
    """An action without a label still shows, by its name, rather than vanishing."""
    return ACTIONS.get(action, (action, ""))[0]


# target kind -> (SPA route under /b/{b}, permission needed to open it)
TARGETS: dict[str, tuple[str, Permission]] = {
    "document": ("/invoices/{id}", Permission.CATALOG_VIEW),
    "return_instance": ("/returns/{id}", Permission.RETURNS_PREPARE),
    "member": ("/settings/team", Permission.MEMBERS_MANAGE),
    "membership": ("/settings/team", Permission.MEMBERS_MANAGE),
    "invitation": ("/settings/team", Permission.MEMBERS_MANAGE),
    "business": ("/settings/company", Permission.SETTINGS_EDIT),
    "tenant": ("/settings/company", Permission.SETTINGS_EDIT),
    "support_grant": ("/settings/support", Permission.AUDIT_VIEW),
}
