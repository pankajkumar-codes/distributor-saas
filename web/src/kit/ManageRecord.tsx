import { useState } from "react";
import { Button } from "./Button";

type Props = {
  noun: "customer" | "product";
  name: string;
  archived: boolean;
  inUse: boolean;
  dirty: boolean;
  archiveBusy: boolean;
  deleteBusy: boolean;
  onArchive: (archived: boolean) => void;
  onDelete: () => void;
};

/** Archive and Delete as two separate actions, each with its own words and a confirm step.
 *  Whether Delete is allowed stays the server's call; `inUse` only hides a button that would be refused. */
export function ManageRecord({ noun, name, archived, inUse, dirty, archiveBusy, deleteBusy, onArchive, onDelete }: Props) {
  const [asking, setAsking] = useState<"archive" | "delete" | null>(null);
  return (
    <section className="card manage" aria-labelledby="manage">
      <h2 id="manage">Archive or delete</h2>
      {dirty && <p className="hint">Save or undo your changes first.</p>}

      <div className="manage-row">
        <h3>{archived ? "Unarchive" : "Archive"}</h3>
        <p className="hint">
          {archived
            ? `Offer this ${noun} on new invoices again.`
            : `Stops offering this ${noun} on new invoices. Invoices already made keep it, and you can unarchive any time.`}
        </p>
        {asking === "archive" ? (
          <p role="group" aria-label={`Archive ${name}`}>
            Archive {name}?{" "}
            <Button type="button" variant="secondary" busy={archiveBusy} onClick={() => { onArchive(true); setAsking(null); }}>
              Yes, archive
            </Button>{" "}
            <Button type="button" variant="secondary" onClick={() => setAsking(null)}>
              Keep it active
            </Button>
          </p>
        ) : (
          <Button
            type="button"
            variant="secondary"
            busy={archiveBusy}
            disabled={dirty}
            onClick={() => (archived ? onArchive(false) : setAsking("archive"))}
          >
            {archived ? "Unarchive" : "Archive"}
          </Button>
        )}
      </div>

      <div className="manage-row">
        <h3>Delete</h3>
        {inUse ? (
          <p className="hint">This {noun} is on invoices, so it can be archived but not deleted.</p>
        ) : (
          <>
            <p className="hint">Removes this {noun} for good. This is only possible because it has never been on an invoice.</p>
            {asking === "delete" ? (
              <p role="group" aria-label={`Delete ${name}`}>
                Delete {name} for good?{" "}
                <Button type="button" variant="danger" busy={deleteBusy} onClick={onDelete}>
                  Yes, delete
                </Button>{" "}
                <Button type="button" variant="secondary" onClick={() => setAsking(null)}>
                  Keep it
                </Button>
              </p>
            ) : (
              <Button type="button" variant="danger" disabled={dirty} onClick={() => setAsking("delete")}>
                Delete
              </Button>
            )}
          </>
        )}
      </div>
    </section>
  );
}
