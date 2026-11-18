import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { errorText, type ApiError } from "../api/errors";
import { Button } from "./Button";
import { ErrorDetail } from "./ErrorDetail";

type Props = {
  name: string;
  editTo: string;
  archived: boolean;
  inUse: boolean;
  /** Query key prefix to refresh after a change, e.g. ["b", id, "customers"]. */
  listKey: readonly unknown[];
  archive: (archived: boolean) => Promise<unknown>;
  remove: () => Promise<unknown>;
};

/** Edit, Archive and Delete for one row of a list: separate buttons, a question before Archive or Delete,
 *  and the server's own words when it refuses. `inUse` only hides a Delete the server would refuse. */
export function RowActions({ name, editTo, archived, inUse, listKey, archive, remove }: Props) {
  const queryClient = useQueryClient();
  const [asking, setAsking] = useState<"archive" | "delete" | null>(null);
  const done = () => {
    setAsking(null);
    queryClient.invalidateQueries({ queryKey: [...listKey] });
  };
  const archiveM = useMutation<unknown, ApiError, boolean>({ mutationFn: archive, onSuccess: done });
  const removeM = useMutation<unknown, ApiError>({
    mutationFn: remove,
    onSuccess: done,
    onError: (e) => {
      setAsking(null);
      if (e.code === "stale_record") queryClient.invalidateQueries({ queryKey: [...listKey] });
    },
  });
  const error = archiveM.error ?? removeM.error;

  if (asking === "archive" || asking === "delete") {
    const deleting = asking === "delete";
    return (
      <div className="row-actions" role="group" aria-label={`${deleting ? "Delete" : "Archive"} ${name}`}>
        <span>
          {deleting ? `Delete ${name} for good?` : `Archive ${name}? It won't be offered on new invoices.`}
        </span>
        <Button
          type="button"
          variant={deleting ? "danger" : "secondary"}
          busy={deleting ? removeM.isPending : archiveM.isPending}
          onClick={() => (deleting ? removeM.mutate() : archiveM.mutate(true))}
        >
          {deleting ? "Yes, delete" : "Yes, archive"}
        </Button>
        <Button type="button" variant="secondary" onClick={() => setAsking(null)}>
          {deleting ? "Keep it" : "Keep it active"}
        </Button>
      </div>
    );
  }

  return (
    <div className="row-actions">
      <Link className="btn btn-secondary" to={editTo} aria-label={`Edit ${name}`}>
        Edit
      </Link>
      <Button
        type="button"
        variant="secondary"
        busy={archiveM.isPending}
        aria-label={`${archived ? "Unarchive" : "Archive"} ${name}`}
        onClick={() => (archived ? archiveM.mutate(false) : setAsking("archive"))}
      >
        {archived ? "Unarchive" : "Archive"}
      </Button>
      {!inUse && (
        <Button type="button" variant="danger" aria-label={`Delete ${name}`} onClick={() => setAsking("delete")}>
          Delete
        </Button>
      )}
      {inUse && <span className="hint">On invoices: archive only</span>}
      {error && (
        <p role="alert" className="error">
          {errorText(error)}
          <ErrorDetail error={error} />
        </p>
      )}
    </div>
  );
}
