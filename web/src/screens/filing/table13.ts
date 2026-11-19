import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { returnKey } from "./returns";

export type Table13 = components["schemas"]["Table13Out"];
export type DocRow = components["schemas"]["DocRowOut"];
export type DocRowIn = components["schemas"]["DocRowIn"];

const path = (businessId: string, instanceId: string) => ({ business_id: businessId, instance_id: instanceId });

/** The kinds of document a person may add by hand (the server's list; the labels come back with each row). */
export const NATURES: { value: number; label: string }[] = [
  { value: 1, label: "Invoices for outward supply" },
  { value: 2, label: "Invoices for inward supply from an unregistered person" },
  { value: 3, label: "Revised invoice" },
  { value: 4, label: "Debit note" },
  { value: 5, label: "Credit note" },
  { value: 6, label: "Receipt voucher" },
  { value: 7, label: "Payment voucher" },
  { value: 8, label: "Refund voucher" },
  { value: 9, label: "Delivery challan for job work" },
  { value: 10, label: "Delivery challan for supply on approval" },
  { value: 11, label: "Delivery challan in case of liquid gas" },
  { value: 12, label: "Delivery challan in other cases" },
];

/** GET …/table13: the series found in the return's documents, with earlier edits laid over them. */
export function useTable13(businessId: string, instanceId: string, enabled: boolean) {
  return useQuery<Table13, ApiError>({
    queryKey: [...returnKey(businessId, instanceId), "table13"],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/returns/{instance_id}/table13", { params: { path: path(businessId, instanceId) } })),
    enabled,
    retry: false,
  });
}

/** PUT …/table13: confirm the rows as the next version. The return is read again so its gate (check C-08) updates. */
export function useConfirmTable13(businessId: string, instanceId: string) {
  const queryClient = useQueryClient();
  return useMutation<Table13, ApiError, DocRowIn[]>({
    mutationFn: (rows) => call(() => api.PUT("/api/v1/b/{business_id}/returns/{instance_id}/table13", { params: { path: path(businessId, instanceId) }, body: { rows } })),
    onSuccess: () => Promise.all([queryClient.invalidateQueries({ queryKey: returnKey(businessId, instanceId) }), queryClient.invalidateQueries({ queryKey: ["b", businessId, "returns"] })]),
  });
}

export type Draft = { key: number; nature: number; from_no: string; to_no: string; total: string; cancelled: string; counted: boolean; manual: boolean; source: DocRow["source"]; label: string; missing: number; ca: boolean };

export const toDraft = (r: DocRow, key: number): Draft => ({
  key, nature: r.nature, from_no: r.from_no, to_no: r.to_no, total: String(r.total_issued), cancelled: String(r.cancelled), counted: r.counted, manual: r.manual, source: r.source, label: r.nature_label, missing: r.missing, ca: r.needs_ca_check,
});

const COUNT = /^\d{1,8}$/;
const NUMBER = /^[A-Za-z0-9/-]{1,16}$/;

/** What the server would refuse, said before the button is pressed (the server still has the last word). */
export function problem(d: Draft): string | null {
  if (!NUMBER.test(d.from_no) || !NUMBER.test(d.to_no)) return "The from and to numbers must be 1 to 16 letters, digits, - or /.";
  if (!COUNT.test(d.total) || !COUNT.test(d.cancelled)) return "Total and cancelled must be whole numbers.";
  if (Number(d.cancelled) > Number(d.total)) return "Cancelled cannot be more than the total.";
  return null;
}

export const toBody = (d: Draft): DocRowIn => ({ nature: d.nature, from_no: d.from_no.trim(), to_no: d.to_no.trim(), total_issued: Number(d.total), cancelled: Number(d.cancelled), counted: d.counted, manual: d.manual });
