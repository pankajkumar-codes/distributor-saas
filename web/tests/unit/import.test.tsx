import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const START = "/api/v1/b/b-1/product-imports";
const RUN = `${START}/i-1`;
const UPLOAD = "/api/v1/dev/objects/upload";
const me = { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role: "owner" }] } };

const run = (over: Record<string, unknown> = {}) => ({
  id: "i-1",
  file_name: "products.csv",
  status: "preview",
  counts: { new: 1, changed: 1, unchanged: 0, invalid: 1, conflict: 0 },
  error_code: null,
  error_message: null,
  duplicate_of: null,
  superseded_by: null,
  apply_changes: null,
  created_at: "2026-11-02T10:00:00Z",
  has_more: false,
  rows: [
    { row_number: 2, status: "new", values: { code: "SOAP-2", name: "Rose soap", gst_rate: "18", sale_rate: "40", unit: "NOS" }, product_id: null, diff: null, errors: null, outcome: null },
    { row_number: 3, status: "changed", values: { code: "SOAP-1", name: "Neem soap" }, product_id: "p-1", diff: [{ field: "sale_rate", saved: "45.00", file: "48" }], errors: null, outcome: null },
    { row_number: 4, status: "invalid", values: { code: "X", name: "" }, product_id: null, diff: null, errors: [{ field: "hsn", code: "hsn_invalid", message: "HSN is 4, 6 or 8 digits" }], outcome: null },
  ],
  ...over,
});
const job = (id: string, status: string) => ({
  status: 200,
  body: { id, type: "catalog.import_parse", status, attempt: 1, progress: null, result: null, error_code: null, created_at: "2026-11-02T10:00:00Z", updated_at: "2026-11-02T10:00:00Z" },
});

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(ME, me);
});
afterEach(() => vi.unstubAllGlobals());

function open(path = "/b/b-1/products/import") {
  window.history.replaceState(null, "", path);
  render(<App />);
}
const sent = (path: string, method = "POST") => server.sent.filter((s) => s.path === path && s.method === method);
const choose = async (name = "products.csv") =>
  fireEvent.change(await screen.findByLabelText("File"), { target: { files: [new File(["code,name\nSOAP-2,Rose soap\n"], name, { type: "text/csv" })] } });
const started = { status: 201, body: { import_id: "i-1", upload: { url: `${window.location.origin}${UPLOAD}`, fields: { key: "uploads/b/b-1/i-1", token: "t" }, expires_at: "2026-11-02T10:05:00Z" } } };

describe("importing products", () => {
  it("uploads, waits for the check, previews the server's outcomes, then imports once", async () => {
    server.reply(START, { status: 503 }, started);
    server.reply(UPLOAD, { status: 204 });
    server.reply(`${RUN}/complete`, { status: 202, body: { job_id: "j-1" } });
    server.reply("/api/v1/b/b-1/jobs/j-1", job("j-1", "done"));
    server.reply(RUN, { status: 200, body: run({ status: "parsing", rows: [], counts: null }) }, { status: 200, body: run() });
    open();
    await choose();
    fireEvent.click(screen.getByRole("button", { name: "Upload and check" }));
    expect(await screen.findByText(/Something went wrong on our side/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Upload and check" }));

    const changed = (await screen.findByText("Neem soap", {}, { timeout: 4000 })).closest("tr")!;
    expect(within(changed).getByText("45.00 → 48")).toBeInTheDocument();
    expect(within(screen.getByText("4").closest("tr")!).getByText("HSN is 4, 6 or 8 digits")).toBeInTheDocument();
    expect(window.location.search).toBe("?run=i-1&job=j-1");
    const [first, second] = sent(START);
    expect(second.headers.get("Idempotency-Key")).toBe(first.headers.get("Idempotency-Key"));
    expect(first.body).toEqual({ file_name: "products.csv", size_bytes: "code,name\nSOAP-2,Rose soap\n".length });

    server.reply(`${RUN}/confirm`, { status: 202, body: { job_id: "j-2" } });
    server.reply("/api/v1/b/b-1/jobs/j-2", job("j-2", "done"));
    server.reply(RUN, {
      status: 200,
      body: run({
        status: "applied",
        apply_changes: false,
        counts: { new: 1, changed: 1, unchanged: 0, invalid: 1, conflict: 0, applied: 1, stale: 0, skipped: 1 },
        rows: run().rows.map((r) => ({ ...r, outcome: r.status === "new" ? "applied" : "skipped" })),
      }),
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /Also apply the 1 changes/ }));
    fireEvent.click(screen.getByRole("button", { name: "Import 1 product" }));
    expect(await screen.findByText(/Imported: 1 applied, 1 skipped, 0 not applied/)).toBeInTheDocument();
    expect(sent(`${RUN}/confirm`)).toHaveLength(1);
    expect(sent(`${RUN}/confirm`)[0].body).toEqual({ apply_changes: false });
    expect(sent(`${RUN}/confirm`)[0].headers.get("Idempotency-Key")).toBeNull();
  });

  it("asks for the file again when storage refuses the upload", async () => {
    server.reply(START, started);
    server.reply(UPLOAD, { status: 403 });
    open();
    await choose();
    fireEvent.click(screen.getByRole("button", { name: "Upload and check" }));
    expect(await screen.findByText("The upload was refused. Choose the file again.")).toBeInTheDocument();
    expect(sent(`${RUN}/complete`)).toHaveLength(0);
  });

  it("filters the preview rows on the server and keeps the filter in the URL", async () => {
    server.reply(RUN, { status: 200, body: run() }, { status: 200, body: run({ rows: run().rows.slice(2) }) });
    open("/b/b-1/products/import?run=i-1");
    await screen.findByText("Rose soap");
    fireEvent.click(screen.getByRole("button", { name: "Has errors (1)" }));
    await vi.waitFor(() => expect(sent(RUN, "GET")).toHaveLength(2));
    expect(new URL(sent(RUN, "GET")[1].url).searchParams.get("rows")).toBe("invalid");
    expect(new URLSearchParams(window.location.search).get("rows")).toBe("invalid");
  });

  it("treats already_applied as done only when this run shows applied with the same choice", async () => {
    server.reply(
      RUN,
      { status: 200, body: run() },
      { status: 200, body: run({ status: "applying", apply_changes: false }) },
    );
    server.reply(`${RUN}/confirm`, { status: 409, body: { error: { code: "import_already_applied", message: "This import was already confirmed with a different choice" } } });
    open("/b/b-1/products/import?run=i-1");
    await screen.findByText("Rose soap");
    fireEvent.click(screen.getByRole("button", { name: "Import 2 products" }));
    expect(await screen.findByText("This import was already confirmed with a different choice")).toBeInTheDocument();
  });

  it("shows the result quietly when the 409 was this run, already applied with this choice", async () => {
    server.reply(
      RUN,
      { status: 200, body: run() },
      { status: 200, body: run({ status: "applied", apply_changes: true, counts: { ...run().counts, applied: 2, stale: 1, skipped: 0 } }) },
    );
    server.reply(`${RUN}/confirm`, { status: 409, body: { error: { code: "import_already_applied", message: "Already confirmed" } } });
    open("/b/b-1/products/import?run=i-1");
    await screen.findByText("Rose soap");
    fireEvent.click(screen.getByRole("button", { name: "Import 2 products" }));
    expect(await screen.findByText(/2 applied, 0 skipped, 1 not applied/)).toBeInTheDocument();
    expect(screen.getByText(/upload the file again for a fresh preview/)).toBeInTheDocument();
    expect(screen.queryByText("Already confirmed")).toBeNull();
  });

  it("shows why a row wasn't applied, and a run that failed after confirm", async () => {
    const stale = { ...run().rows[0], outcome: "stale", errors: [{ field: "gst_rate", code: "rate_not_allowed", message: "The GST rate list changed after the preview" }] };
    server.reply(RUN, { status: 200, body: run({ status: "applied", apply_changes: true, counts: { ...run().counts, applied: 0, stale: 1, skipped: 2 }, rows: [stale] }) });
    open("/b/b-1/products/import?run=i-1");
    const row = (await screen.findByText("Rose soap")).closest("tr")!;
    expect(within(row).getByText("Not imported: changed after the preview")).toBeInTheDocument();
    expect(within(row).getByText("The GST rate list changed after the preview")).toBeInTheDocument();
  });

  it("offers a new import when the run failed after confirm, with the server's words", async () => {
    server.reply(RUN, { status: 200, body: run({ status: "failed", error_code: "apply_failed", error_message: "The import couldn't be applied; nothing was saved", rows: [] }) });
    open("/b/b-1/products/import?run=i-1");
    expect(await screen.findByText(/The import couldn't be applied; nothing was saved/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start a new import" })).toBeInTheDocument();
  });

  it("says when the same file was already imported, in the server's words", async () => {
    server.reply(RUN, {
      status: 200,
      body: run({ status: "discarded", error_code: "already_imported", error_message: "This file was already imported; nothing was added", duplicate_of: "i-0", rows: [] }),
    });
    open("/b/b-1/products/import?run=i-1");
    expect(await screen.findByText(/This file was already imported; nothing was added/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start a new import" }));
    expect(screen.getByLabelText("File")).toBeInTheDocument();
    expect(window.location.search).toBe("");
  });

  it("discards a preview", async () => {
    server.reply(RUN, { status: 200, body: run() }, { status: 200, body: run({ status: "discarded", error_message: "Discarded by the user", rows: [] }) });
    server.reply(`${RUN}/discard`, { status: 200, body: {} });
    open("/b/b-1/products/import?run=i-1");
    await screen.findByText("Rose soap");
    fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(await screen.findByText(/Discarded by the user/)).toBeInTheDocument();
  });

  it("is NotFound for an import the server doesn't know", async () => {
    server.reply(RUN, { status: 404, body: { error: { code: "not_found", message: "" } } });
    open("/b/b-1/products/import?run=i-1");
    expect(await screen.findByText(/couldn't find that page/i)).toBeInTheDocument();
  });
});
