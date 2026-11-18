import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

export type Gate = components["schemas"]["PeriodGateOut"];
export type GateItem = components["schemas"]["GateConfirmIn"]["item"];
export type GateKind = Gate["kind"];

const gateKey = (businessId: string, kind: string, start: string) => ["b", businessId, "period-gate", kind, start] as const;

/** GET …/period-gate: whether a period's file button is open, and why not. Asked again after every answer. */
export function useGate(businessId: string, kind: GateKind, start: string, enabled: boolean) {
  return useQuery<Gate, ApiError>({
    queryKey: gateKey(businessId, kind, start),
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/period-gate", { params: { path: { business_id: businessId }, query: { kind, start } } })),
    enabled: enabled && start !== "",
    retry: false,
  });
}

/** PUT …/period-gate: the business says an item is true, or takes it back. The answer is the gate as it now stands. */
export function useConfirm(businessId: string, kind: GateKind, start: string) {
  const queryClient = useQueryClient();
  return useMutation<Gate, ApiError, { item: GateItem; confirmed: boolean }>({
    mutationFn: (body) => call(() => api.PUT("/api/v1/b/{business_id}/period-gate", { params: { path: { business_id: businessId } }, body: { kind, start, ...body } })),
    onSuccess: (gate) => queryClient.setQueryData(gateKey(businessId, kind, start), gate),
  });
}

/** POST …/period-gate/file: the button. Refused by the server while the gate is closed. */
export function useOpenFile(businessId: string, kind: GateKind, start: string) {
  const queryClient = useQueryClient();
  return useMutation<Gate, ApiError>({
    mutationFn: () => call(() => api.POST("/api/v1/b/{business_id}/period-gate/file", { params: { path: { business_id: businessId } }, body: { kind, start } })),
    onSuccess: (gate) => queryClient.setQueryData(gateKey(businessId, kind, start), gate),
    onError: () => queryClient.invalidateQueries({ queryKey: gateKey(businessId, kind, start) }),
  });
}

/** POST …/uploads/none-this-month: the business says a marketplace had no sales in a month. The gate is asked again. */
export function useNoSales(businessId: string, kind: GateKind, start: string) {
  const queryClient = useQueryClient();
  return useMutation<unknown, ApiError, { platform: "amazon" | "flipkart" | "meesho"; month: string }>({
    mutationFn: ({ platform, month }) =>
      call(() => api.POST("/api/v1/b/{business_id}/uploads/none-this-month", { params: { path: { business_id: businessId } }, body: { section: platform, month } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: gateKey(businessId, kind, start) }),
  });
}
