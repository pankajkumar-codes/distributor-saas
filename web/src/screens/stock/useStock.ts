import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

export type StockItem = components["schemas"]["StockItemOut"];
type StockPage = components["schemas"]["StockPageOut"];
export type Only = "no_stock" | "price_needed";
export const stockKey = (businessId: string) => ["b", businessId, "stock"] as const;

/** One page of the stock list (pages of five, mocks v16). Filter and search are the server's. */
export function useStockList(businessId: string, opts: { q: string; only: Only | null; page: number; size: number; enabled: boolean }) {
  return useQuery<StockPage, ApiError>({
    queryKey: [...stockKey(businessId), "list", { q: opts.q, only: opts.only, page: opts.page }],
    enabled: opts.enabled && Boolean(businessId),
    placeholderData: keepPreviousData,
    queryFn: () =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/stock", {
          params: { path: { business_id: businessId }, query: { q: opts.q || undefined, only: opts.only ?? undefined, limit: opts.size, offset: opts.page * opts.size } },
        }),
      ),
  });
}

/**
 * Which products have no stock, and which still need a selling price, for the invoice page's notes.
 * One look at the first page of each filter; a product beyond the first page just gets no note.
 */
function useFlag(businessId: string, only: Only, enabled: boolean) {
  return useQuery<StockPage, ApiError>({
    queryKey: [...stockKey(businessId), "flags", only],
    enabled: enabled && Boolean(businessId),
    staleTime: 30_000,
    retry: false,
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/stock", { params: { path: { business_id: businessId }, query: { only, limit: 100 } } })),
  });
}

export function useStockFlags(businessId: string, enabled: boolean) {
  const none = useFlag(businessId, "no_stock", enabled);
  const price = useFlag(businessId, "price_needed", enabled);
  return {
    noStock: new Set(none.data?.items.map((i) => i.product_id) ?? []),
    priceNeeded: new Set(price.data?.items.map((i) => i.product_id) ?? []),
  };
}

/**
 * Sets the selling price per 1 qty (excluding GST). The product's version is read first, so the save
 * is the same guarded PATCH the product page makes; the rate is sent as the text typed.
 */
export function useSetPrice(businessId: string) {
  const queryClient = useQueryClient();
  return useMutation<unknown, ApiError, { productId: string; rate: string }>({
    mutationFn: async ({ productId, rate }) => {
      const path = { business_id: businessId, product_id: productId };
      const product = await call(() => api.GET("/api/v1/b/{business_id}/products/{product_id}", { params: { path } }));
      return call(() => api.PATCH("/api/v1/b/{business_id}/products/{product_id}", { params: { path, header: { "If-Match": String(product.version) } }, body: { sale_rate: rate } }));
    },
    onSuccess: (_o, v) => {
      queryClient.invalidateQueries({ queryKey: stockKey(businessId) });
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "products"] });
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "product", v.productId] });
    },
  });
}
