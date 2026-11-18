import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { Banner } from "../../kit/Banner";
import { BUSINESS_TYPES, type BusinessType } from "../../kit/BusinessTypeField";
import { Button } from "../../kit/Button";

type Profile = components["schemas"]["ProfileOut"];

/** Who can change the business profile (settings.edit); billing can write invoices but not this. */
const SETTERS = new Set(["owner", "admin"]);

/**
 * Invoicing needs the business type (D-080). Ask for it on the invoice page itself, so nobody has to leave a half-filled
 * form: shown before the form when the profile has none, and after a refused save. Choosing saves it through the
 * profile call and then `onChosen` carries on. Roles that cannot edit the profile are told who can.
 */
export function BusinessTypePrompt({ businessId, role, refused, onChosen }: { businessId: string; role: string; refused: boolean; onChosen: () => void }) {
  const queryClient = useQueryClient();
  const path = { business_id: businessId };
  const canSet = SETTERS.has(role);
  const profile = useQuery<Profile, ApiError>({
    queryKey: ["b", businessId, "profile"],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/profile", { params: { path } })),
    enabled: canSet,
  });
  const [choice, setChoice] = useState<BusinessType | "">("");
  const save = useMutation<{ profile: Profile }, ApiError, BusinessType>({
    mutationFn: (business_type) =>
      call(() =>
        api.PATCH("/api/v1/b/{business_id}/profile", {
          params: { path, header: { "If-Match": String(profile.data?.version) } },
          body: { business_type },
        }),
      ),
    onSuccess: (out) => {
      queryClient.setQueryData(["b", businessId, "profile"], out.profile);
      onChosen();
    },
    onError: (e) => {
      if (e.code === "stale_record") profile.refetch();
    },
  });

  if (!canSet) {
    return refused ? (
      <Banner tone="error">Invoicing needs your business type. Ask the owner or an admin to choose Distributor or Retail in Business setup, then save again. What you typed is still here.</Banner>
    ) : null;
  }
  if (profile.data?.business_type) return null;
  if (!profile.data && !refused) return null;

  return (
    <section className="card" aria-labelledby="bt-title">
      <h2 id="bt-title">Choose your business type to start invoicing</h2>
      <p className="hint">One choice, once. You can change it later in Business setup.{refused ? " What you typed is kept." : ""}</p>
      <div className="field">
        <label htmlFor="bt-choice">Business type</label>
        <select id="bt-choice" value={choice} onChange={(e) => setChoice(e.target.value as BusinessType | "")}>
          <option value="">Choose one</option>
          {BUSINESS_TYPES.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <Button type="button" busy={save.isPending} disabled={!choice || !profile.data} onClick={() => choice && save.mutate(choice)}>
        {refused ? "Save and save my draft" : "Save business type"}
      </Button>
      {save.error && <Banner tone="error">{errorText(save.error)}</Banner>}
    </section>
  );
}
