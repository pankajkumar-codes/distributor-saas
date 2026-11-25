import { todayIst } from "../format/dates";
import { useReturns, type ReturnRow } from "../screens/filing/returns";
import type { ReturnLinks } from "./nav";

/** The return to work on next for one form: the earliest open one whose period has ended, else the earliest open one. */
function next(rows: ReturnRow[], form: string, today: string): ReturnRow | undefined {
  const open = rows.filter((r) => r.form === form && (r.status === "open" || r.status === "unlocked")).sort((a, b) => a.period_end.localeCompare(b.period_end));
  return open.find((r) => r.period_end < today) ?? open[0];
}

/**
 * The sidebar's GSTR-1 and GSTR-3B links. It only reads returns another screen (Home, Your GST
 * filing) has already loaded: the shell never fetches on its own, so it adds no request to any
 * page. Until the list is in the cache both links go to Your GST filing.
 */
export function useReturnLinks(businessId: string, enabled: boolean): ReturnLinks {
  const { data } = useReturns(businessId, undefined, false);
  if (!enabled || !data) return {};
  const today = todayIst();
  const g1 = next(data.returns, "GSTR1", today);
  const g3 = next(data.returns, "GSTR3B", today);
  const base = `/b/${businessId}/filing`;
  return {
    gstr1: g1 && `${base}/${g1.instance_id}`,
    gstr1Id: g1?.instance_id,
    w3b: g3 && `${base}/${g3.instance_id}/worksheet`,
    w3bId: g3?.instance_id,
  };
}
