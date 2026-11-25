import { Link } from "react-router-dom";

import { previousFy } from "../../format/dates";
import { useReturns, type ReturnRow } from "./returns";

/**
 * One return row from the server's list, looked for in this year and, if not found, last year (a late return). Used by
 * the portal guides, which need the period's name and the other return of the same period.
 */
export function useReturnRow(businessId: string, instanceId: string, enabled: boolean) {
  const now = useReturns(businessId, undefined, enabled);
  const found = now.data?.returns.find((r) => r.instance_id === instanceId);
  const before = useReturns(businessId, now.data ? previousFy(now.data.fy) : undefined, enabled && now.isSuccess && !found);
  const lastYear = before.data?.returns ?? [];
  const row = found ?? lastYear.find((r) => r.instance_id === instanceId);
  const loading = now.isPending || (!found && now.isSuccess && before.isPending && before.fetchStatus !== "idle");
  const all = found ? (now.data?.returns ?? []) : lastYear;
  // The GSTR-1 and GSTR-3B of the same period, so each guide can switch to the other.
  const sibling = (form: string): ReturnRow | undefined => (row ? all.find((r) => r.form === form && r.period === row.period) : undefined);
  return { row, loading, sibling };
}

/** The switch between the two portal guides (mocks v16 "Portal guides": GSTR-1 upload / GSTR-3B entry). */
export function GuideSwitch({ businessId, current, gstr1, gstr3b }: { businessId: string; current: "gstr1" | "gstr3b"; gstr1?: ReturnRow; gstr3b?: ReturnRow }) {
  const chip = (key: "gstr1" | "gstr3b", label: string, row?: ReturnRow) =>
    key === current ? (
      <span className="fchip" aria-current="page">
        {label}
      </span>
    ) : row ? (
      <Link className="fchip" to={key === "gstr1" ? `/b/${businessId}/filing/${row.instance_id}/portal-guide` : `/b/${businessId}/filing/${row.instance_id}/portal-guide-3b`}>
        {label}
      </Link>
    ) : null;
  return (
    <nav className="filters" aria-label="Portal guides">
      {chip("gstr1", "GSTR-1 upload", gstr1)}
      {chip("gstr3b", "GSTR-3B entry", gstr3b)}
    </nav>
  );
}

/** A numbered step, with what nobody has checked on the live portal yet said under it (`check`), or only marked (`mark`, said once above the list). */
export function GuideStep({ n, text, check, mark }: { n: number; text: string; check?: string; mark?: string }) {
  return (
    <li>
      <span className="d" aria-hidden="true">
        {n}
      </span>
      <span>
        {text}
        {mark && !check && (
          <>
            {" "}
            <span className="chip chip-warn" title={mark}>
              Not checked
            </span>
          </>
        )}
        {check && (
          <span className="sub2">
            <span className="chip chip-warn" title={check}>
              Not checked
            </span>{" "}
            {check}
          </span>
        )}
      </span>
    </li>
  );
}
