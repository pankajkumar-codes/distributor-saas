import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";

type Product = components["schemas"]["ProductOut"];

const DIGITS = /^[0-9]+$/;
const NOT_DIGITS = "That isn't a valid HSN: use digits only, with no spaces";

/**
 * Fix a missing HSN without leaving the invoice. It writes to the product (so the next invoice is right too);
 * the server's check is unchanged: after the save the draft is read again and the server decides whether the block is gone.
 */
export function HsnFix({
  businessId,
  productId,
  productName,
  onSaved,
}: {
  businessId: string;
  productId: string;
  productName: string;
  onSaved: () => Promise<unknown> | void;
}) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const key = ["b", businessId, "product", productId];
  const path = { business_id: businessId, product_id: productId };
  const product = useQuery<Product, ApiError>({
    queryKey: key,
    staleTime: 5 * 60_000,
    queryFn: () =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/products/{product_id}", {
          params: { path },
        }),
      ),
  });
  const save = useMutation<Product, ApiError, string>({
    mutationFn: (hsn) =>
      call(() =>
        api.PATCH("/api/v1/b/{business_id}/products/{product_id}", {
          params: {
            path,
            header: { "If-Match": String(product.data?.version) },
          },
          body: { hsn },
        }),
      ),
    onSuccess: async (p) => {
      queryClient.setQueryData(key, p);
      void queryClient.invalidateQueries({
        queryKey: ["b", businessId, "products"],
      });
      await onSaved();
    },
    onError: (e) => {
      if (e.code === "stale_record") void product.refetch();
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const hsn = value.trim();
    if (!DIGITS.test(hsn)) {
      setProblem(NOT_DIGITS);
      return;
    }
    setProblem(null);
    save.mutate(hsn);
  };

  const error =
    problem ??
    (save.error
      ? save.error.code === "stale_record"
        ? "This product was changed elsewhere. It has been reloaded: press Save HSN again."
        : errorText(save.error)
      : null);

  return (
    <form
      onSubmit={submit}
      className="hsn-fix"
      aria-label={`Fix HSN for ${productName}`}
    >
      <Field
        label={`HSN for ${productName}`}
        value={value}
        inputMode="numeric"
        onChange={(e) => setValue(e.target.value)}
        error={error ?? undefined}
      />
      <Button
        type="submit"
        variant="secondary"
        busy={save.isPending}
        disabled={value.trim() === "" || !product.data}
      >
        Save HSN
      </Button>
    </form>
  );
}
