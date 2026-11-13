import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const BASE = "/api/v1/b/b-1/uploads";
const STORE = "/api/v1/dev/objects/upload";
const me = (role: string) => ({ status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vaashi Essentials", gstin: null, role }] } });
const upload = (status: string, over: Record<string, unknown> = {}) => ({
  id: "u-1",
  section: "amazon",
  file_name: "amazon-oct.csv",
  size_bytes: 12,
  status,
  reject_reason: null,
  reject_message: null,
  run_id: null,
  raw_available: true,
  created_at: "2026-11-02T10:00:00Z",
  ...over,
});
const started = { status: 201, body: { upload_id: "u-1", upload: { url: `${window.location.origin}${STORE}`, fields: { key: "k", token: "t" }, expires_at: "2026-11-02T10:05:00Z" } } };

let server: ReturnType<typeof fakeApi>;
function open(role = "owner", path = "/b/b-1/uploads") {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(ME, me(role));
  server.reply(BASE, { status: 200, body: { uploads: [] } }, { status: 200, body: { uploads: [] } }, { status: 200, body: { uploads: [] } }, { status: 200, body: { uploads: [] } });
  window.history.replaceState(null, "", path);
  render(<App />);
}
afterEach(() => vi.unstubAllGlobals());
beforeEach(() => window.history.replaceState(null, "", "/"));

const sent = (path: string, method = "POST") => server.sent.filter((s) => s.path === path && s.method === method);
const card = async (name: string) => (await screen.findByRole("region", { name })) as HTMLElement;
const pick = (input: HTMLElement, name: string, body = "a,b\n1,2\n") => fireEvent.change(input, { target: { files: [new File([body], name)] } });

describe("upload page", () => {
  it("has one heading, a labelled card per section, and labelled file inputs", async () => {
    open();
    expect(await screen.findByRole("heading", { level: 1, name: "Upload your reports" })).toBeInTheDocument();
    for (const name of ["Amazon", "Flipkart", "Meesho", "Your own sales invoices (Excel)"]) expect(await card(name)).toBeInTheDocument();
    expect(screen.getAllByLabelText("Choose a file")).toHaveLength(4);
  });

  it("sends the file straight to storage, completes it, and shows the server's reading of it", async () => {
    open();
    server.reply(BASE, started);
    server.reply(STORE, { status: 204 });
    server.reply(`${BASE}/u-1/complete`, { status: 202, body: { job_id: "j-1" } });
    server.reply(`${BASE}/u-1`, { status: 200, body: upload("parsed") });
    const amazon = await card("Amazon");
    pick(amazon.querySelector("input")!, "amazon-oct.csv");
    fireEvent.click(amazon.querySelector("button")!);
    expect(await screen.findByText("Read.")).toBeInTheDocument();
    expect(sent(BASE)[0].body).toEqual({ section: "amazon", file_name: "amazon-oct.csv", size_bytes: 8 });
    expect(sent(BASE)[0].headers.get("Idempotency-Key")).toBeTruthy();
    expect(sent(STORE)).toHaveLength(1);
    expect(sent(`${BASE}/u-1/complete`)).toHaveLength(1);
    expect(window.location.search).toBe("?amazon=u-1"); // a reload resumes here
  });

  it("keeps the idempotency key when the server asked for a retry, and uses a new one after a failed send or a new file", async () => {
    open();
    server.reply(BASE, { status: 503 }, started, started);
    server.reply(STORE, { status: 403 });
    const amazon = await card("Amazon");
    const input = amazon.querySelector("input")!;
    const button = amazon.querySelector("button")!;
    pick(input, "a.csv");
    fireEvent.click(button);
    await screen.findByRole("alert"); // 503
    fireEvent.click(button);
    await vi.waitFor(() => expect(sent(STORE)).toHaveLength(1));
    await vi.waitFor(() => expect(sent(BASE)).toHaveLength(2));
    await screen.findByRole("alert"); // storage said 403
    const [first, second] = sent(BASE).map((s) => s.headers.get("Idempotency-Key"));
    expect(second).toBe(first); // same file, retry after a 503
    fireEvent.click(button);
    await vi.waitFor(() => expect(sent(BASE)).toHaveLength(3));
    expect(sent(BASE)[2].headers.get("Idempotency-Key")).not.toBe(second); // the failed send rotated it
  });

  it("shows the server's plain reason for a rejected file", async () => {
    open("owner", "/b/b-1/uploads?amazon=u-1");
    server.reply(`${BASE}/u-1`, { status: 200, body: upload("rejected", { reject_message: "This file is for a different GSTIN." }) });
    expect(await screen.findByText("This file is for a different GSTIN.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("amazon-oct.csv");
  });

  it("polls a file that is still being read, and ends on the server's answer", async () => {
    open("owner", "/b/b-1/uploads?amazon=u-1");
    server.reply(`${BASE}/u-1`, { status: 200, body: upload("parsing") }, { status: 200, body: upload("parsed") });
    expect(await screen.findByText(/Reading your file/)).toBeInTheDocument();
    expect(await screen.findByText("Read.", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(sent(`${BASE}/u-1`, "GET")).toHaveLength(2);
  });

  it("says a stored upload is saved but not read yet", async () => {
    open("owner", "/b/b-1/uploads?own_invoices_excel=u-1");
    server.reply(`${BASE}/u-1`, { status: 200, body: upload("stored", { section: "own_invoices_excel" }) });
    expect(await screen.findByText("Saved, not read yet.")).toBeInTheDocument();
  });

  it("refuses a wrong type or an empty file in the browser before sending anything", async () => {
    open();
    const amazon = await card("Amazon");
    pick(amazon.querySelector("input")!, "notes.txt");
    expect(await screen.findByText("Choose a CSV, Excel or zip file.")).toBeInTheDocument();
    fireEvent.click(amazon.querySelector("button")!);
    pick(amazon.querySelector("input")!, "empty.csv", "");
    expect(await screen.findByText("That file is empty.")).toBeInTheDocument();
    expect(sent(BASE)).toHaveLength(0);
  });

  it("offers each section only the types the server takes: no zip for own invoices", async () => {
    open();
    const own = await card("Your own sales invoices (Excel)");
    expect(own.querySelector("input")!.getAttribute("accept")).toBe(".csv,.xlsx");
    expect((await card("Amazon")).querySelector("input")!.getAttribute("accept")).toBe(".csv,.xlsx,.zip");
    pick(own.querySelector("input")!, "invoices.zip");
    expect(await screen.findByText("Choose a CSV or Excel file.")).toBeInTheDocument();
    fireEvent.click(own.querySelector("button")!);
    expect(sent(BASE)).toHaveLength(0);
  });

  it("lets a CA look but not upload", async () => {
    open("ca");
    expect(await screen.findByRole("heading", { level: 1, name: "Upload your reports" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Choose a file")).toBeNull();
    expect(screen.queryByRole("button", { name: "Upload" })).toBeNull();
    expect(screen.getAllByText("Only an owner or admin can upload files.").length).toBeGreaterThan(0);
  });

  it("shows the not-found page to billing, as the server does", async () => {
    open("billing");
    expect(await screen.findByRole("heading", { name: "We couldn't find that page" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Upload your reports" })).toBeNull();
    expect(sent(BASE, "GET")).toHaveLength(0);
  });
});
