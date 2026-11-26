import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SyntheticEvent } from "react";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";

type Product = components["schemas"]["ProductOut"];

const DIGITS = /^[0-9]+$/;
const NOT_DIGITS = "That isn't a valid HSN: use digits only, with no spaces";
const MONEY = /^[0-9]{1,12}(\.[0-9]{1,2})?$/;
const NOT_MONEY = "Enter the MRP as a number with up to 2 decimals, like 118 or 118.50";

type FixProps = {
  businessId: string;
  productId: string;
  productName: string;
  onSaved: (product: Product) => Promise<unknown> | void;
};

/**
 * Fix a missing HSN without leaving the invoice. It writes to the product (so the next invoice is right too);
 * the server's check is unchanged: after the save the draft is read again and the server decides whether the block is gone.
 */
export const HsnFix = (p: FixProps) => <ProductFieldFix {...p} field="hsn" />;

/** The same for a missing MRP (D-106): saved on the product; the invoice line then takes the rate the MRP implies. */
export const MrpFix = (p: FixProps) => <ProductFieldFix {...p} field="mrp" />;

function ProductFieldFix({ businessId, productId, productName, onSaved, field }: FixProps & { field: "hsn" | "mrp" }) {
  const isHsn = field === "hsn";
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
  // The version is taken when Save is pressed and passed to mutate(), not read here (#418, as #417).
  const save = useMutation<Product, ApiError, { value: string; version: string }>({
    mutationFn: ({ value: v, version }) =>
      call(() =>
        api.PATCH("/api/v1/b/{business_id}/products/{product_id}", {
          params: {
            path,
            header: { "If-Match": version },
          },
          body: isHsn ? { hsn: v } : { mrp: v },
        }),
      ),
    onSuccess: async (p) => {
      queryClient.setQueryData(key, p);
      void queryClient.invalidateQueries({
        queryKey: ["b", businessId, "products"],
      });
      await onSaved(p);
    },
    onError: (e) => {
      if (e.code === "stale_record") void product.refetch();
    },
  });

  // Not a <form>: this sits inside the invoice's own form, and a form inside a form is invalid HTML (the browser can
  // submit the outer one, saving the draft or reloading the page instead). Enter in the box and the button both save.
  const submit = (e: SyntheticEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const v = value.trim();
    if (!(isHsn ? DIGITS : MONEY).test(v)) {
      setProblem(isHsn ? NOT_DIGITS : NOT_MONEY);
      return;
    }
    setProblem(null);
    save.mutate({ value: v, version: String(product.data?.version) });
  };

  const error =
    problem ??
    (save.error
      ? save.error.code === "stale_record"
        ? `This product was changed elsewhere. It has been reloaded: press Save ${isHsn ? "HSN" : "MRP"} again.`
        : errorText(save.error)
      : null);

  return (
    <div role="group" className="hsn-fix" aria-label={`Fix ${isHsn ? "HSN" : "MRP"} for ${productName}`}>
      <Field
        label={isHsn ? `HSN for ${productName}` : `MRP per unit, incl. GST, for ${productName} (₹)`}
        value={value}
        inputMode={isHsn ? "numeric" : "decimal"}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && value.trim() !== "" && product.data) submit(e);
          else if (e.key === "Enter") e.preventDefault(); // never the invoice's own submit
        }}
        error={error ?? undefined}
      />
      <Button
        type="button"
        onClick={submit}
        variant="secondary"
        busy={save.isPending}
        disabled={value.trim() === "" || !product.data}
      >
        {isHsn ? "Save HSN" : "Save MRP"}
      </Button>
    </div>
  );
}
