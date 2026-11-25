import { useState, type FormEvent } from "react";

import { errorText } from "../../api/errors";
import { canLockReturns, canUnlockReturns } from "../../auth/roles";
import { formatDate } from "../../format/dates";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { FileResult } from "./ExportPanel";
import { useChanges, useLockFile, useMarkFiled, useUnlock } from "./export";
import { Panel } from "./ledger";
import type { ReturnDetail } from "./returns";

type Instance = ReturnDetail["instance"];

const TABLE: Record<string, string> = { b2b: "business sales", b2cl: "large consumer sales", cdnr: "credit notes to businesses", cdnur: "credit notes to consumers" };
const SUMMARY: Record<string, string> = { b2cs: "other consumer sales", hsn_b2b: "HSN summary, business sales", hsn_b2c: "HSN summary, consumer sales" };

function Docs({ title, docs }: { title: string; docs: { section: string; number: string }[] }) {
  if (docs.length === 0) return null;
  return (
    <p>
      <b>{title}:</b> {docs.map((d) => `${d.number} (${TABLE[d.section] ?? d.section})`).join(", ")}
    </p>
  );
}

/** What differs from the file the user took, by document number, so they can say why before the return is locked. */
function Difference({ businessId, instanceId }: { businessId: string; instanceId: string }) {
  const changes = useChanges(businessId, instanceId, true);
  if (changes.isPending) return <p aria-busy="true">Loading what changed…</p>;
  if (changes.isError) return <Banner tone="error">We couldn't load what changed. {errorText(changes.error)}</Banner>;
  const c = changes.data;
  const d = c.difference;
  return (
    <div className="stack">
      <p>
        {c.reference === null
          ? "No file has been made for this return yet, so everything in it counts as new."
          : `Compared with the file you took (${c.reference.purpose === "lock" ? "the one kept when it was last locked" : "your latest file"}, version ${c.reference.version}):`}
      </p>
      <Docs title="Not in the file" docs={d.added} />
      <Docs title="In the file, no longer in the return" docs={d.removed} />
      <Docs title="Different from the file" docs={d.changed} />
      {d.summaries.length > 0 && <p><b>Totals that differ:</b> {d.summaries.map((s) => SUMMARY[s] ?? s).join(", ")}.</p>}
    </div>
  );
}

function MarkFiled({ businessId, instance }: { businessId: string; instance: Instance }) {
  const [filedOn, setFiledOn] = useState("");
  const [arn, setArn] = useState("");
  const [reason, setReason] = useState("");
  const mark = useMarkFiled(businessId, instance.instance_id);
  // Once the server has said the return differs, keep asking for the reason, even if a later try fails for another cause
  // (a bad ARN, say); otherwise the reason box would vanish and the user would lose what they typed.
  const [differs, setDiffers] = useState(false);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    mark.mutate(
      { filed_on: filedOn, arn: arn.trim(), ...(differs ? { reason: reason.trim() } : {}) },
      { onError: (err) => err.code === "changed_since_export" && setDiffers(true) },
    );
  };
  const fieldError = (name: string) => (mark.isError && mark.error.field === name ? errorText(mark.error) : undefined);
  return (
    <form onSubmit={submit} noValidate className="pad">
      <p className="hint">File the return on the GST portal first. Then tell us when you filed it and the ARN the portal gave you, and we lock this return as it is.</p>
      <div className="f2">
        <Field label="Date you filed it" type="date" value={filedOn} min={instance.period_end} onChange={(e) => setFiledOn(e.target.value)} error={fieldError("filed_on")} required />
        <Field label="ARN from the portal" value={arn} onChange={(e) => setArn(e.target.value)} error={fieldError("arn")} maxLength={32} autoComplete="off" required />
      </div>
      {differs && (
        <>
          <Banner tone="error">
            This return is not the same as the file you took. If you filed something different on the portal, say why and we will lock the return with that written down. Otherwise make the file again above.
          </Banner>
          <Difference businessId={businessId} instanceId={instance.instance_id} />
          <Field label="Why is what you filed different?" value={reason} onChange={(e) => setReason(e.target.value)} error={fieldError("accept_changed")} />
        </>
      )}
      {mark.isError && !differs && !mark.error.field && <Banner tone="error">{errorText(mark.error)}</Banner>}
      <Button type="submit" variant="secondary" busy={mark.isPending} disabled={!filedOn || !arn.trim() || (differs && !reason.trim())}>
        {differs ? "Lock with this reason" : "Mark as filed and lock"}
      </Button>
    </form>
  );
}

function Locked({ businessId, instance, role }: { businessId: string; instance: Instance; role: string }) {
  const kept = useLockFile(businessId, instance.instance_id);
  const unlock = useUnlock(businessId, instance.instance_id);
  const [reason, setReason] = useState("");
  const [asking, setAsking] = useState(false);
  return (
    <div>
      <div className="kv">
        <span>Filed on</span>
        <span className="num">{instance.filed_on ? formatDate(instance.filed_on) : "—"}</span>
      </div>
      <div className="kv">
        <span>ARN from the portal</span>
        <span className="num">{instance.arn ?? "—"}</span>
      </div>
      <div className="pad stack">
      <p className="hint">This return is locked: new invoices dated in this period are refused.</p>
      <div className="row">
        <Button variant="secondary" className="btn-sm" busy={kept.isPending} onClick={() => kept.mutate()}>
          Download the file we kept
        </Button>
      </div>
      {kept.isError && <Banner tone="error">{errorText(kept.error)}</Banner>}
      {kept.data && <FileResult file={kept.data} title={`The file kept when you filed (version ${kept.data.version})`} />}
      {canUnlockReturns(role) &&
        (asking ? (
          <form
            className="stack"
            noValidate
            onSubmit={(e) => {
              e.preventDefault();
              unlock.mutate(reason.trim());
            }}
          >
            <Field label="Why are you unlocking this return?" value={reason} onChange={(e) => setReason(e.target.value)} hint="For example, the portal asked you to file again. Your earlier file and ARN are kept." />
            {unlock.isError && <Banner tone="error">{errorText(unlock.error)}</Banner>}
            <Button type="submit" busy={unlock.isPending} disabled={!reason.trim()}>
              Unlock this return
            </Button>
          </form>
        ) : (
          <p className="hint">
            <Button variant="link" onClick={() => setAsking(true)}>
              Unlock this return
            </Button>{" "}
            You give a reason. Your earlier file and ARN are kept.
          </p>
        ))}
      </div>
    </div>
  );
}

/** Record that the return was filed on the portal and lock it, or show that it is locked (R1-M8 S6). */
export function FiledPanel({ businessId, instance, role }: { businessId: string; instance: Instance; role: string }) {
  if (instance.status !== "open" && instance.status !== "unlocked" && instance.status !== "filed_locked") return null;
  return (
    <Panel title={instance.status === "filed_locked" ? "Filed" : "After you file on the portal"} aside={instance.status === "filed_locked" ? <span className="chip chip-ok">Filed and locked</span> : undefined}>
      {instance.status === "unlocked" && <Banner>This return was unlocked. File it again on the portal if you need to, then mark it filed again.</Banner>}
      {instance.status === "filed_locked" ? (
        <Locked businessId={businessId} instance={instance} role={role} />
      ) : canLockReturns(role) ? (
        <MarkFiled businessId={businessId} instance={instance} />
      ) : (
        <p className="pad hint">The owner, an admin or the CA marks a return filed once it is filed on the portal.</p>
      )}
    </Panel>
  );
}
