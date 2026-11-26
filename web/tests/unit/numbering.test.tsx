import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { prefixProblem, previewNumber } from "../../src/screens/settings/NumberingSection";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const NUMBERING = "/api/v1/b/b-1/numbering";
const me = (role: string) => ({ status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: "19ABCDE1234F1Z5", role }] } });
const series = (kind: string, label: string, prefix: string, issued = true) => ({
  kind, label, prefix, first_number: 1, width: 6, next_number: `${prefix}/26-11/000001`, saved: false, issued_in_app: issued,
});
const numbering = (invoicePrefix = "INV") => ({
  status: 200,
  body: {
    series: [series("invoice", "Tax invoice", invoicePrefix), series("credit_note", "Credit note", "CN"), series("debit_note", "Debit note", "DN", false)],
    scope: "gstin_kind_month", max_length: 16, max_prefix_length: 3, live: false, live_available: false,
  },
});

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
});
afterEach(() => vi.unstubAllGlobals());

function open(role = "owner") {
  server.reply(ME, me(role), me(role));
  window.history.replaceState(null, "", "/b/b-1/settings");
  render(<App />);
}

describe("invoice numbering", () => {
  it("previews Pankaj's format and checks the 16 characters before saving", () => {
    expect(previewNumber("INV", 1, 6, "gstin_kind_month", new Date(2026, 10, 27))).toBe("INV/26-11/000001");
    expect(previewNumber("INV", 41, 6, "gstin_kind_fy", new Date(2026, 10, 27))).toBe("INV000041");
    expect(prefixProblem("INVC", 3)).toMatch(/at most 3/);
    expect(prefixProblem("IN/", 3)).toMatch(/letters and digits/);
    expect(prefixProblem("SI", 3)).toBeUndefined();
  });

  it("saves a new invoice prefix and shows the saved numbering", async () => {
    server.reply(NUMBERING, numbering());
    open();
    const prefix = await screen.findByLabelText("Tax invoice prefix");
    expect(screen.getByText(/Live numbering is off/)).toBeInTheDocument();
    fireEvent.change(prefix, { target: { value: "si" } });
    expect(screen.getByText(/SI\/\d\d-\d\d\/000001/)).toBeInTheDocument();
    server.reply(`PUT ${NUMBERING}`, numbering("SI"));
    fireEvent.click(screen.getByRole("button", { name: "Save numbering" }));
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    const put = server.sent.find((s) => s.method === "PUT" && s.path === NUMBERING);
    expect(put?.body).toMatchObject({ invoice: { prefix: "SI", first_number: 1 }, credit_note: { prefix: "CN" } });
  });

  it("refuses a shared prefix on the page and leaves the fields read-only for a role that can't save", async () => {
    server.reply(NUMBERING, numbering());
    open();
    fireEvent.change(await screen.findByLabelText("Credit note prefix"), { target: { value: "INV" } });
    expect(screen.getAllByText("Each document type needs its own prefix.").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Save numbering" })).toBeDisabled();
  });

  it("is read-only for staff", async () => {
    server.reply(NUMBERING, numbering());
    open("staff");
    const section = (await screen.findByRole("heading", { name: "Invoice numbering" })).closest("section") as HTMLElement;
    expect(await within(section).findByLabelText("Tax invoice prefix")).toBeDisabled();
    expect(within(section).queryByRole("button", { name: "Save numbering" })).toBeNull();
  });
});
