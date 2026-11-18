import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const BASE = "/api/v1/b/b-1/uploads";
const STORE = "/api/v1/dev/objects/upload";
const CHANNELS = "/api/v1/b/b-1/channels";
const channels = (over: Record<string, boolean> = {}) => ({ status: 200, body: { amazon: true, flipkart: true, meesho: true, own_invoices: true, answered: true, ...over } });
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
function open(role = "owner", path = "/b/b-1/uploads", chosen: Record<string, boolean> = {}) {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(ME, me(role));
  server.reply(CHANNELS, channels(chosen));
  server.reply(BASE, ...Array.from({ length: 5 }, () => ({ status: 200, body: { uploads: [] } })));
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
    for (const name of ["Amazon", "Flipkart", "Meesho", "Your own sales invoices"]) expect(await card(name)).toBeInTheDocument();
    expect(screen.getAllByLabelText("Choose a file")).toHaveLength(3);
    expect(screen.getAllByLabelText("Choose files")).toHaveLength(1); // your own invoices: several files
  });

  it("offers only the platforms chosen at setup", async () => {
    open("owner", "/b/b-1/uploads", { flipkart: false, meesho: false });
    expect(await card("Amazon")).toBeInTheDocument();
    expect(await card("Your own sales invoices")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Flipkart" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Meesho" })).toBeNull();
  });

  it("offers no own-invoices card to a business that sells only on a platform", async () => {
    open("owner", "/b/b-1/uploads", { amazon: false, flipkart: true, meesho: false, own_invoices: false });
    expect(await card("Flipkart")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Your own sales invoices" })).toBeNull();
    expect(screen.getAllByRole("region").map((r) => r.getAttribute("aria-labelledby") && r.querySelector("h2")?.textContent)).toEqual(["A zip of your reports", "Flipkart"]);
  });

  it("sends the person to Business details when nothing is chosen yet", async () => {
    open("owner", "/b/b-1/uploads", { amazon: false, flipkart: false, meesho: false, own_invoices: false, answered: false });
    expect(await screen.findByText(/You haven't said where you sell yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Choose it in Business details" })).toHaveAttribute("href", "/b/b-1/settings");
    expect(screen.queryAllByRole("region")).toHaveLength(0);
  });

  it("says when where-you-sell cannot be loaded, with Try again", async () => {
    resetSessionForTests();
    server = fakeApi();
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, me("owner"));
    server.reply(CHANNELS, { status: 404 }, channels());
    server.reply(BASE, ...Array.from({ length: 5 }, () => ({ status: 200, body: { uploads: [] } })));
    window.history.replaceState(null, "", "/b/b-1/uploads");
    render(<App />);
    expect(await screen.findByText(/We couldn't load where you sell/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await card("Amazon")).toBeInTheDocument();
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

  it("lists your own invoice files, Excel and PDF, with the server's word on each", async () => {
    resetSessionForTests();
    server = fakeApi();
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, me("owner"));
    server.reply(CHANNELS, channels());
    const empty = { status: 200, body: { uploads: [] } };
    server.reply(BASE, empty, empty, empty, { status: 200, body: { uploads: [upload("stored", { id: "u-2", section: "own_invoices_excel", file_name: "sales.xlsx" })] } }, { status: 200, body: { uploads: [upload("rejected", { id: "u-3", section: "own_invoices_pdf", file_name: "inv-1.pdf", reject_message: "This looks like a scan or a photo, so we can't read it. Type the rows or upload the Excel." })] } });
    window.history.replaceState(null, "", "/b/b-1/uploads");
    render(<App />);
    expect(await screen.findByText("Saved, not read yet.")).toBeInTheDocument();
    expect(screen.getByText("sales.xlsx")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("This looks like a scan or a photo");
    expect(screen.getByText("inv-1.pdf")).toBeInTheDocument();
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

  it("offers platforms CSV, Excel and zip, and your own invoices Excel and PDF but no zip", async () => {
    open();
    const own = await card("Your own sales invoices");
    expect(own.querySelector("input")!.getAttribute("accept")).toBe(".csv,.xlsx,.pdf");
    expect(own.querySelector("input")!.hasAttribute("multiple")).toBe(true);
    expect((await card("Amazon")).querySelector("input")!.getAttribute("accept")).toBe(".csv,.xlsx,.zip");
    fireEvent.change(own.querySelector("input")!, { target: { files: [new File(["x"], "invoices.zip"), new File(["x"], "notes.txt")] } });
    expect(await screen.findByText("invoices.zip: Choose a CSV, Excel or PDF file.")).toBeInTheDocument();
    expect(screen.getByText("notes.txt: Choose a CSV, Excel or PDF file.")).toBeInTheDocument();
    fireEvent.click(own.querySelector("button")!);
    expect(sent(BASE)).toHaveLength(0);
  });

  it("sends each own-invoice file to the reader for its type, and retries only the one that failed", async () => {
    open();
    const own = await card("Your own sales invoices");
    server.reply(`POST ${BASE}`, started, { status: 503 }, { status: 503 }, started);
    server.reply(STORE, { status: 204 }, { status: 204 });
    server.reply(`${BASE}/u-1/complete`, { status: 202, body: { job_id: "j-1" } }, { status: 202, body: { job_id: "j-2" } });
    fireEvent.change(own.querySelector("input")!, {
      target: { files: [new File(["a,b\n1,2\n"], "sales.xlsx"), new File(["%PDF-1.4"], "inv-1.pdf")] },
    });
    fireEvent.click(own.querySelector("button")!);
    expect(await screen.findByText(/inv-1\.pdf: /)).toBeInTheDocument();
    expect(sent(BASE).map((s) => s.body)).toEqual([
      expect.objectContaining({ section: "own_invoices_excel", file_name: "sales.xlsx" }),
      expect.objectContaining({ section: "own_invoices_pdf", file_name: "inv-1.pdf" }),
    ]);
    expect(screen.getByText(/Press Upload to send these again/)).toBeInTheDocument();
    const firstKey = sent(BASE)[1].headers.get("Idempotency-Key");
    fireEvent.click(own.querySelector("button")!);
    await vi.waitFor(() => expect(sent(BASE)).toHaveLength(3));
    expect(sent(BASE)[2].body).toMatchObject({ file_name: "inv-1.pdf", section: "own_invoices_pdf" }); // sales.xlsx is not sent again
    expect(sent(BASE)[2].headers.get("Idempotency-Key")).toBe(firstKey); // a 503 keeps the key
  });

  it("lets a CA look but not upload", async () => {
    open("ca");
    expect(await screen.findByRole("heading", { level: 1, name: "Upload your reports" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Choose a file")).toBeNull();
    expect(screen.queryByRole("button", { name: "Upload" })).toBeNull();
    expect((await screen.findAllByText("Only an owner or admin can upload files.")).length).toBeGreaterThan(0);
  });

  it("shows the not-found page to billing, as the server does", async () => {
    open("billing");
    expect(await screen.findByRole("heading", { name: "We couldn't find that page" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Upload your reports" })).toBeNull();
    expect(sent(BASE, "GET")).toHaveLength(0);
  });
});
