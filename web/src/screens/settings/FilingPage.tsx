import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDate, quarterStartIst, todayIst } from "../../format/dates";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { RadioGroup } from "../../kit/RadioGroup";
import { TopBar } from "../../kit/TopBar";
import { warningText } from "../onboarding/warnings";

type Profile = components["schemas"]["FilingProfileOut"];
type Changed = components["schemas"]["FrequencyOut"];
type Frequency = components["schemas"]["FrequencyIn"]["frequency"];

export const FREQUENCY_LABEL: Record<Frequency, string> = { quarterly: "Every quarter (QRMP)", monthly: "Every month" };
// The server refuses these roles with a 404 anyway (settings.edit, docs/PERMISSIONS.md);
// hiding the form only spares them a form they can't use.
const EDITORS = new Set(["owner", "admin"]);

/**
 * Filing settings (LLD-1 §8.2). Every date and rule is the server's: the change window comes
 * from `window`, and the quarters offered are only the one it names and the one India is in
 * now. Whether a start date is allowed, and what rule 61A says about it, the server decides
 * and explains.
 */
export function FilingPage() {
  const { businessId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const queryClient = useQueryClient();
  const profile = useQuery<Profile, ApiError>({
    queryKey: ["b", businessId, "filing-profile"],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/filing-profile", { params: { path: { business_id: businessId } } })),
    enabled: Boolean(business),
  });
  const [frequency, setFrequency] = useState<Frequency | "">("");
  const [startsOn, setStartsOn] = useState("");
  const key = useRef(crypto.randomUUID()); // one per choice; a retry of the same choice reuses it
  const [done, setDone] = useState<Changed | null>(null);

  const change = useMutation<Changed, ApiError, { frequency: Frequency; effective_from: string }>({
    mutationFn: (body) =>
      call(() =>
        api.POST("/api/v1/b/{business_id}/filing-profile/frequency", {
          params: { path: { business_id: businessId }, header: { "Idempotency-Key": key.current } },
          body,
        }),
      ),
    onSuccess: (out) => {
      setDone(out);
      key.current = crypto.randomUUID();
      setFrequency("");
      setStartsOn("");
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "filing-profile"] });
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "home"] });
    },
  });
  const choose = (next: () => void) => {
    next();
    key.current = crypto.randomUUID();
    change.reset();
    setDone(null);
  };

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (businesses.error) {
    return (
      <main className="page">
        <Banner tone="error">{errorText(businesses.error)}</Banner>
      </main>
    );
  }
  if (!business || profile.error?.status === 404) return <NotFound />;

  const data = profile.data;
  const quarters = data ? [...new Set([data.window.for_quarter, quarterStartIst()])].sort() : [];
  const start = startsOn || data?.window.for_quarter || "";
  const err = (field: string) => (change.error?.field === field ? change.error.message || errorText(change.error) : undefined);
  const formError = change.error && !["frequency", "effective_from"].includes(change.error.field ?? "") ? change.error : null;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (frequency && start) change.mutate({ frequency, effective_from: start });
  };

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page">
        <p className="step">
          <Link to={`/b/${businessId}/home`}>Home</Link>
        </p>
        <h1>Filing frequency</h1>
        {profile.error && (
          <Banner tone="error">
            {errorText(profile.error)}{" "}
            <Button type="button" variant="link" onClick={() => profile.refetch()}>
              Try again
            </Button>
          </Banner>
        )}
        {profile.isPending && <p aria-busy="true">Loading…</p>}

        {data && !data.gstin && (
          <Banner>
            You can choose a filing frequency once your business has a GSTIN. Adding a GSTIN to a business registered with an
            enrolment number isn't available in the app yet.
          </Banner>
        )}

        {data?.gstin && (
          <>
            <p role="status">
              {data.current
                ? `${FREQUENCY_LABEL[data.current.frequency as Frequency] ?? data.current.frequency}, from ${formatDate(data.current.effective_from)}.`
                : "You haven't chosen a filing frequency yet."}
            </p>
            {data.window.opens && data.window.closes ? (
              <p>
                A change for the quarter starting {formatDate(data.window.for_quarter)} can be made on the GST portal from{" "}
                {formatDate(data.window.opens)} to {formatDate(data.window.closes)}.
              </p>
            ) : null}
            {data.warnings.length > 0 && (
              <Banner>
                <ul>
                  {data.warnings.map((w) => (
                    <li key={w}>{warningText(w)}</li>
                  ))}
                </ul>
              </Banner>
            )}

            {done && (
              <Banner>
                Saved: {FREQUENCY_LABEL[done.row.frequency]}, from {formatDate(done.row.effective_from)}.
                {done.superseded_instances.length > 0 &&
                  ` ${done.superseded_instances.length} empty return period${done.superseded_instances.length === 1 ? " was" : "s were"} replaced to match.`}
                {done.warnings.length > 0 && (
                  <ul>
                    {done.warnings.map((w) => (
                      <li key={w}>{warningText(w)}</li>
                    ))}
                  </ul>
                )}
              </Banner>
            )}

            {EDITORS.has(business.role) && (
              <form onSubmit={submit} noValidate>
                <h2>{data.current ? "Change frequency" : "Choose frequency"}</h2>
                <RadioGroup<Frequency>
                  legend="How often do you file GSTR-1?"
                  name="frequency"
                  options={[
                    { value: "quarterly", label: FREQUENCY_LABEL.quarterly },
                    { value: "monthly", label: FREQUENCY_LABEL.monthly },
                  ]}
                  value={frequency}
                  onChange={(v) => choose(() => setFrequency(v))}
                  error={err("frequency")}
                />
                <RadioGroup<string>
                  legend="Starting from the quarter that begins"
                  name="effective_from"
                  options={quarters.map((q) => ({ value: q, label: formatDate(q) }))}
                  value={start}
                  onChange={(v) => choose(() => setStartsOn(v))}
                  hint="If you're not sure which quarter, ask your CA."
                  error={err("effective_from")}
                />
                {formError && <Banner tone="error">{formError.message || errorText(formError)}</Banner>}
                <div className="actions">
                  <Button type="submit" busy={change.isPending} disabled={!frequency}>
                    Save frequency
                  </Button>
                </div>
              </form>
            )}

            {data.history.length > 0 && (
              <>
                <h2>History</h2>
                <table className="products">
                  <thead>
                    <tr>
                      <th scope="col">Frequency</th>
                      <th scope="col">From</th>
                      <th scope="col">Chosen on</th>
                      <th scope="col">Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.history.map((h) => (
                      <tr key={h.id}>
                        <td data-label="Frequency">{FREQUENCY_LABEL[h.frequency]}</td>
                        <td data-label="From">{formatDate(h.effective_from)}</td>
                        <td data-label="Chosen on">{formatDate(todayIst(new Date(h.chosen_at)))}</td>
                        <td data-label="Notes">{h.warnings.map(warningText).join(" ") || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </>
        )}
      </main>
    </>
  );
}
