import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { CheckboxGroup } from "../../kit/CheckboxGroup";
import { PLATFORM_OPTIONS, type Channels } from "../onboarding/BusinessPage";

type ChannelsOut = components["schemas"]["ChannelsOut"];
const pick = (c: ChannelsOut): Channels => ({ amazon: c.amazon, flipkart: c.flipkart, meesho: c.meesho, own_invoices: c.own_invoices });
const same = (a: Channels, b: Channels) => PLATFORM_OPTIONS.every((o) => a[o.value] === b[o.value]);

/** Where the business sells (ON-2). Its own save, since the server keeps it apart from the profile. Anyone who can open Settings can see it; the server decides who can change it. */
export function PlatformsSection({ businessId, canEdit }: { businessId: string; canEdit: boolean }) {
  const queryClient = useQueryClient();
  const key = ["b", businessId, "channels"];
  const saved = useQuery<ChannelsOut, ApiError>({
    queryKey: key,
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/channels", { params: { path: { business_id: businessId } } })),
  });
  const [edited, setEdited] = useState<Channels | null>(null);
  const shown = edited ?? (saved.data ? pick(saved.data) : null);
  const save = useMutation<ChannelsOut, ApiError, Channels>({
    mutationFn: (body) => call(() => api.PUT("/api/v1/b/{business_id}/channels", { params: { path: { business_id: businessId } }, body })),
    onSuccess: (out) => {
      queryClient.setQueryData(key, out);
      void queryClient.invalidateQueries({ queryKey: ["b", businessId, "home"] }); // the checklist counts this answer
      setEdited(null);
    },
  });
  const none = shown ? !Object.values(shown).some(Boolean) : false;
  const dirty = Boolean(shown && saved.data && !same(shown, pick(saved.data)));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (shown && dirty && !none) save.mutate(shown);
  };

  return (
    <section className="card" aria-labelledby="platforms">
      <h2 id="platforms">Where you sell</h2>
      {saved.isError && <Banner tone="error">We couldn't load this. {errorText(saved.error)}</Banner>}
      {shown && (
        <form onSubmit={submit} noValidate>
          <CheckboxGroup<keyof Channels>
            legend="Which platforms do you sell on?"
            options={PLATFORM_OPTIONS}
            value={shown}
            onChange={(v) => {
              if (save.isSuccess || save.isError) save.reset();
              setEdited(v);
            }}
            hint="Tick every one that applies. At least one is needed."
            error={none ? "Pick at least one to continue." : undefined}
            disabled={!canEdit}
          />
          {save.isError && <Banner tone="error">{errorText(save.error)}</Banner>}
          {save.isSuccess && <Banner>Saved. Deadlines updated.</Banner>}
          {canEdit && (
            <div className="actions">
              <Button type="submit" busy={save.isPending} disabled={!dirty || none}>
                Save where you sell
              </Button>
            </div>
          )}
        </form>
      )}
    </section>
  );
}
