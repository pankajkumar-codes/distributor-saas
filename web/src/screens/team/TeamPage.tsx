import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { errorText, type ApiError } from "../../api/errors";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDateTimeIst } from "../../format/dates";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { ErrorDetail } from "../../kit/ErrorDetail";
import { Field } from "../../kit/Field";
import { NotFound } from "../../kit/NotFound";
import { SelectField } from "../../kit/SelectField";
import { TopBar } from "../../kit/TopBar";
import { useCancelInvite, useChangeRole, useInvite, useMembers, useResend, useSetActive, type InviteRole, type Member, type Role } from "./useTeam";
import { NoAccess } from "../../kit/NoAccess";
import { useFormKey } from "../../kit/formKey";
import { Loading } from "../../kit/Loading";

// members.manage (docs/PERMISSIONS.md); the server answers anyone else 404.
export const TEAM_MANAGERS = new Set(["owner", "admin"]);

const ROLE_LABEL: Record<string, string> = { owner: "Owner", admin: "Admin", billing: "Billing", ca: "CA" };
const INVITE_ROLES: { value: InviteRole; label: string }[] = [
  { value: "admin", label: "Admin: everything except owner-only actions" },
  { value: "billing", label: "Billing: products, customers and invoices" },
  { value: "ca", label: "CA: reads, and prepares and files returns" },
];
const INVITE_STATUS: Record<string, string> = { pending: "Waiting", expired: "Expired", accepted: "Accepted", cancelled: "Cancelled" };
const words = (e: ApiError) => e.fix ?? (e.message || errorText(e));

function InviteForm({ businessId }: { businessId: string }) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<InviteRole | "">("");
  const [name, setName] = useState("");
  const formKey = useFormKey(`invite:${businessId}`); // one send per fill of the form, however many times it is pressed
  const [sentTo, setSentTo] = useState<string | null>(null);
  const invite = useInvite(businessId);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!role) return;
    invite.mutate(
      { email: email.trim(), role, display_name: name.trim() || undefined, key: formKey.current() },
      {
        onSuccess: (sent) => {
          setSentTo(sent.email);
          setEmail("");
          setName("");
          setRole("");
          formKey.reset();
        },
      },
    );
  };
  return (
    <section aria-labelledby="invite-h">
      <h2 id="invite-h">Invite someone</h2>
      <p className="hint">We email them a link. It works for 7 days, once, and only for that email address. We don't show the link here.</p>
      <form onSubmit={submit} noValidate>
        <Field label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" />
        <Field label="Name (optional)" value={name} onChange={(e) => setName(e.target.value)} />
        <SelectField label="Role" placeholder="Choose a role" options={INVITE_ROLES} value={role} onChange={(e) => setRole(e.target.value as InviteRole | "")} />
        {invite.error && <Banner tone="error">{words(invite.error)}</Banner>}
        {sentTo && !invite.error && <Banner>Invitation sent to {sentTo}.</Banner>}
        <Button type="submit" busy={invite.isPending} disabled={!email.trim() || !role} aria-describedby={!email.trim() || !role ? "invite-need" : undefined}>
          Send invitation
        </Button>
        {(!email.trim() || !role) && (
          <p className="hint" id="invite-need">
            {!email.trim() && !role ? "Enter an email and choose a role to send the invitation." : !email.trim() ? "Enter an email to send the invitation." : "Choose a role to send the invitation."}
          </p>
        )}
      </form>
    </section>
  );
}

function MemberRow({ businessId, m, viewerIsOwner }: { businessId: string; m: Member; viewerIsOwner: boolean }) {
  const change = useChangeRole(businessId);
  const setActive = useSetActive(businessId);
  const [role, setRole] = useState<Role>(m.role as Role);
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const active = m.status === "active";
  // The server's rules: a CA changes only through a new invite, and only an owner can change an owner.
  const canChangeRole = active && m.role !== "ca" && (m.role !== "owner" || viewerIsOwner);
  const canToggle = m.role !== "owner" || viewerIsOwner;
  const roleOptions = [...(viewerIsOwner ? [{ value: "owner", label: "Owner" }] : []), { value: "admin", label: "Admin" }, { value: "billing", label: "Billing" }];
  return (
    <li className="card">
      <p>
        <strong>{m.name ?? m.email ?? "Member"}</strong> {m.name && m.email && <span className="hint">{m.email}</span>}{" "}
        <span className="chip">{ROLE_LABEL[m.role] ?? m.role}</span>
        {!active && <span className="chip chip-warn"> Deactivated</span>}
      </p>
      {m.can_do.length > 0 && (
        <details>
          <summary>What this role can do</summary>
          <ul>
            {m.can_do.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </details>
      )}
      {!active && m.deactivation_reason && (
        <p className="hint">
          Deactivated{m.deactivated_by_name ? ` by ${m.deactivated_by_name}` : ""}{m.deactivated_at ? ` on ${formatDateTimeIst(m.deactivated_at)}` : ""}: {m.deactivation_reason}
        </p>
      )}
      {canChangeRole && (
        <div className="actions">
          <SelectField label={`Role for ${m.name ?? m.email ?? "this member"}`} options={roleOptions} value={role} onChange={(e) => setRole(e.target.value as Role)} />
          <Button type="button" busy={change.isPending} disabled={role === m.role} onClick={() => change.mutate({ userId: m.user_id, role })}>
            Save role
          </Button>
        </div>
      )}
      {m.role === "ca" && active && <p className="hint">A CA's role changes only through a new invitation.</p>}
      {change.error && <Banner tone="error">{words(change.error)}</Banner>}
      {canToggle &&
        (asking ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setActive.mutate({ userId: m.user_id, active: !active, reason: reason.trim() }, { onSuccess: () => { setAsking(false); setReason(""); } });
            }}
          >
            <Field label={active ? "Why are you deactivating them?" : "Why are you reactivating them?"} value={reason} onChange={(e) => setReason(e.target.value)} hint="Kept in the audit log." />
            <Button type="submit" busy={setActive.isPending} disabled={!reason.trim()}>
              {active ? "Deactivate" : "Reactivate"}
            </Button>{" "}
            <Button type="button" variant="link" onClick={() => setAsking(false)}>
              Never mind
            </Button>
          </form>
        ) : (
          <Button type="button" variant="link" onClick={() => setAsking(true)}>
            {active ? "Deactivate" : "Reactivate"} {m.name ?? m.email ?? "this member"}
          </Button>
        ))}
      {setActive.error && <Banner tone="error">{words(setActive.error)}</Banner>}
    </li>
  );
}

/**
 * The team (R4-M1): invite by email, see who is on the team and what each role can do, change a role among the four fixed
 * roles, deactivate and reactivate. Owner and admin only. The server enforces every rule; this screen hides what a role can't do.
 */
export function TeamPage() {
  const { businessId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const allowed = Boolean(business && TEAM_MANAGERS.has(business.role));
  const team = useMembers(businessId, allowed);
  const resend = useResend(businessId);
  const cancel = useCancelInvite(businessId);

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!business) return <NotFound />;
  if (!allowed) return <NoAccess businessId={businessId} />;
  if (team.error?.status === 404) return <NotFound />;
  const invites = (team.data?.invites ?? []).filter((i) => i.status !== "accepted");

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <p className="step">
          <Link to={`/b/${businessId}/home`}>Home</Link>
        </p>
        <h1>Your team</h1>
        <p className="hint">Four roles: owner, admin, billing and CA. A role gives a fixed set of things; you can't pick them one by one.</p>
        <InviteForm businessId={businessId} />
        {team.error && (
          <Banner tone="error">
            {errorText(team.error)}
            <ErrorDetail error={team.error} />
          </Banner>
        )}
        {team.isPending && <Loading query={team} />}
        {team.data && (
          <>
            <section aria-labelledby="members-h">
              <h2 id="members-h">Members</h2>
              <ul className="list">
                {team.data.members.map((m) => (
                  <MemberRow key={m.user_id} businessId={businessId} m={m} viewerIsOwner={business.role === "owner"} />
                ))}
              </ul>
            </section>
            {invites.length > 0 && (
              <section aria-labelledby="invites-h">
                <h2 id="invites-h">Invitations</h2>
                <ul className="list">
                  {invites.map((i) => (
                    <li key={i.id}>
                      {i.email} · {ROLE_LABEL[i.role] ?? i.role} · {INVITE_STATUS[i.status] ?? i.status}
                      {i.status === "pending" && <span className="hint"> · until {formatDateTimeIst(i.expires_at)}</span>}{" "}
                      {i.status !== "cancelled" && i.status !== "accepted" && (
                        <>
                          {i.status === "pending" && (
                            <Button type="button" variant="link" disabled={resend.isPending} onClick={() => resend.mutate(i.id)} aria-label={`Resend the invitation to ${i.email}`}>
                              Resend
                            </Button>
                          )}{" "}
                          {i.status === "pending" && (
                            <Button type="button" variant="link" disabled={cancel.isPending} onClick={() => cancel.mutate(i.id)} aria-label={`Cancel the invitation to ${i.email}`}>
                              Cancel
                            </Button>
                          )}
                        </>
                      )}
                    </li>
                  ))}
                </ul>
                {resend.error && <Banner tone="error">{words(resend.error)}</Banner>}
                {cancel.error && <Banner tone="error">{words(cancel.error)}</Banner>}
              </section>
            )}
          </>
        )}
      </main>
    </>
  );
}
