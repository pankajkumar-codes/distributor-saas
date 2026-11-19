import { Link } from "react-router-dom";

import { useRun } from "./useHeldRows";
import type { Upload } from "./sections";

/**
 * Under a file on the Upload page: how many of its rows are held and a link to the screen where they are decided.
 * Shows nothing while loading, on a failed read, or when no row is held (the page itself says what it knows).
 */
export function HeldLink({ businessId, upload }: { businessId: string; upload: Upload }) {
  const ids = upload.run_ids ?? (upload.run_id ? [upload.run_id] : []);
  if (upload.status !== "parsed" || ids.length === 0) return null;
  return (
    <>
      {ids.map((id, i) => (
        <RunHeld key={id} businessId={businessId} runId={id} label={ids.length > 1 ? ` in file ${i + 1}` : ""} />
      ))}
    </>
  );
}

function RunHeld({ businessId, runId, label }: { businessId: string; runId: string; label: string }) {
  const run = useRun(businessId, runId);
  const held = run.data && run.data.status === "staged" ? (run.data.counts.held ?? 0) : 0;
  if (held === 0) return null;
  return (
    <p className="held-link">
      <span className="chip chip-warn">
        {held} row{held === 1 ? "" : "s"} held{label}
      </span>{" "}
      <Link to={`/b/${businessId}/uploads/runs/${runId}/held`}>Review held rows{label}</Link>
    </p>
  );
}
