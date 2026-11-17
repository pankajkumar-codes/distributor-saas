import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const CHANNELS = "/api/v1/b/b-1/channels";
const LIST = "/api/v1/b/b-1/uploads";
const BUNDLES = "/api/v1/b/b-1/upload-bundles";
const ONE = `${BUNDLES}/bd-1`;
const STORE = "/api/v1/dev/objects/upload";
const me = (role: string) => ({ status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vaashi Essentials", gstin: null, role }] } });
const file = (n: number, name: string, over: Record<string, unknown> = {}) => ({
  n,
  file_name: name,
  size_bytes: 2048,
  found_section: "amazon",
  section: "amazon",
  state: "used",
  moved: false,
  reason: null,
  reason_code: null,
  note: null,
  upload_id: null,
  ...over,
});
const bundle = (status: string, files: unknown[] = [], over: Record<string, unknown> = {}) => ({
  status: 200,
  body: {
    id: "bd-1",
    file_name: "reports.zip",
    size_bytes: 4096,
    status,
    reject_reason: null,
    reject_message: null,
    selectable_sections: ["amazon", "flipkart", "own_invoices_excel", "own_invoices_pdf"],
    files,
    created_at: new Date().toISOString(),
    ...over,
  },
});
const started = { status: 201, body: { bundle_id: "bd-1", upload: { url: `${window.location.origin}${STORE}`, fields: { key: "k", token: "t" }, expires_at: "2099-01-01T00:00:00Z" } } };

let server: ReturnType<typeof fakeApi>;
function open(role = "owner", path = "/b/b-1/uploads") {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(ME, me(role));
  server.reply(CHANNELS, { status: 200, body: { amazon: true, flipkart: true, meesho: true, own_invoices: true, answered: true } });
  server.reply(LIST, ...Array.from({ length: 12 }, () => ({ status: 200, body: { uploads: [] } })));
  window.history.replaceState(null, "", path);
  render(<App />);
}
afterEach(() => vi.unstubAllGlobals());
beforeEach(() => window.history.replaceState(null, "", "/"));
const sent = (path: string, method: string) => server.sent.filter((s) => s.path === path && s.method === method);
const card = async () => within((await screen.findByRole("region", { name: "A zip of your reports" })) as HTMLElement);

describe("a zip of reports", () => {
  it("sends the zip to the storage link, completes it, and follows the bundle in the address", async () => {
    open();
    server.reply(`POST ${BUNDLES}`, started);
    server.reply(`POST ${ONE}/complete`, { status: 202, body: { job_id: "j-1" } });
    server.reply(STORE, { status: 204 });
    server.reply(`GET ${ONE}`, bundle("received"));
    const z = await card();
    fireEvent.change(z.getByLabelText("Choose a zip file"), { target: { files: [new File(["PK"], "reports.zip")] } });
    fireEvent.click(z.getByRole("button", { name: "Send the zip" }));
    expect(await z.findByText(/Sorting your files/)).toBeInTheDocument();
    expect(window.location.search).toBe("?bundle=bd-1");
    expect(sent(BUNDLES, "POST")[0].body).toEqual({ file_name: "reports.zip", size_bytes: 2 });
    expect(sent(BUNDLES, "POST")[0].headers.get("Idempotency-Key")).toBeTruthy();
    expect(sent(`${ONE}/complete`, "POST")).toHaveLength(1);
  });

  it("refuses a file that is not a zip before sending anything", async () => {
    open();
    const z = await card();
    fireEvent.change(z.getByLabelText("Choose a zip file"), { target: { files: [new File(["x"], "reports.xlsx")] } });
    expect(z.getByText("That isn't a zip file.")).toBeInTheDocument();
    fireEvent.click(z.getByRole("button", { name: "Send the zip" }));
    expect(sent(BUNDLES, "POST")).toHaveLength(0);
  });

  it("shows how every file was sorted, in the server's words, before anything is read", async () => {
    open("owner", "/b/b-1/uploads?bundle=bd-1");
    server.reply(
      `GET ${ONE}`,
      bundle("classified", [
        file(1, "amazon-oct.csv"),
        file(2, "invoice-1.pdf", { section: "own_invoices_pdf", found_section: "own_invoices_pdf", note: "Will be read as your invoices. Any we can't read clearly are held for you to look at." }),
        file(3, "notes.txt", { section: null, found_section: null, state: "not_used", reason_code: "not_a_report", reason: "We could not tell which report this is." }),
        file(4, "meesho.xlsx", { section: null, state: "not_selected", reason: "This report is not selected for your business." }),
      ]),
    );
    const z = await card();
    expect(await z.findByText("amazon-oct.csv")).toBeInTheDocument();
    expect(z.getByText(/Will be read as your invoices\. Any we can't read clearly are held/)).toBeInTheDocument();
    expect(z.getByText(/We could not tell which report this is/)).toBeInTheDocument();
    expect(z.getByText(/not selected for your business/)).toBeInTheDocument();
    expect(z.getByRole("button", { name: "Read 2 files" })).toBeEnabled();
    expect(sent(`${ONE}/stage`, "POST")).toHaveLength(0);
  });

  it("moves a file to another report, and shows the server's refusal in words", async () => {
    open("owner", "/b/b-1/uploads?bundle=bd-1");
    server.reply(`GET ${ONE}`, bundle("classified", [file(1, "amazon-oct.csv")]));
    server.reply(
      `PATCH ${ONE}/files/1`,
      bundle("classified", [file(1, "amazon-oct.csv", { section: "flipkart", moved: true })]),
      { status: 422, body: { error: { code: "reader_refused", message: "That isn't a Meesho report.", field: "section" } } },
    );
    const z = await card();
    const select = await z.findByLabelText("What amazon-oct.csv is");
    fireEvent.change(select, { target: { value: "flipkart" } });
    await vi.waitFor(() => expect(select).toHaveValue("flipkart"));
    expect(sent(`${ONE}/files/1`, "PATCH")[0].body).toEqual({ section: "flipkart" });
    fireEvent.change(select, { target: { value: "amazon" } });
    expect(await z.findByText("That isn't a Meesho report.")).toBeInTheDocument();
  });

  it("drops a file with null, and asks for the rest to be read", async () => {
    open("owner", "/b/b-1/uploads?bundle=bd-1");
    server.reply(`GET ${ONE}`, bundle("classified", [file(1, "amazon-oct.csv"), file(2, "flipkart.xlsx", { section: "flipkart" })]));
    server.reply(
      `PATCH ${ONE}/files/2`,
      bundle("classified", [file(1, "amazon-oct.csv"), file(2, "flipkart.xlsx", { section: null, state: "dropped", moved: true })]),
    );
    server.reply(`POST ${ONE}/stage`, { status: 202, body: { job_id: "j-2" } });
    server.reply(`GET ${ONE}`, bundle("staged", [file(1, "amazon-oct.csv", { upload_id: "u-1" }), file(2, "flipkart.xlsx", { state: "dropped", section: null })]));
    const z = await card();
    fireEvent.change(await z.findByLabelText("What flipkart.xlsx is"), { target: { value: "" } });
    await vi.waitFor(() => expect(sent(`${ONE}/files/2`, "PATCH")).toHaveLength(1));
    expect(sent(`${ONE}/files/2`, "PATCH")[0].body).toEqual({ section: null });
    fireEvent.click(await z.findByRole("button", { name: "Read 1 file" }));
    expect(await z.findByText(/Sent for reading: 1 file from reports\.zip/)).toBeInTheDocument();
    expect(sent(`${ONE}/stage`, "POST")).toHaveLength(1);
    expect(z.queryByRole("combobox")).toBeNull(); // nothing can be moved once staged
  });

  it("says why a zip was refused, in the server's words, and offers another", async () => {
    open("owner", "/b/b-1/uploads?bundle=bd-1");
    server.reply(`GET ${ONE}`, bundle("rejected", [], { reject_reason: "too_many_files", reject_message: "This zip has more files than we read at once." }));
    const z = await card();
    expect(await z.findByText("This zip has more files than we read at once.")).toBeInTheDocument();
    fireEvent.click(z.getByRole("button", { name: "Send another zip" }));
    expect(await z.findByLabelText("Choose a zip file")).toBeInTheDocument();
    expect(window.location.search).toBe("");
  });

  it("is not offered to someone who cannot upload", async () => {
    open("ca");
    await screen.findByRole("heading", { level: 1, name: "Upload your reports" });
    expect(screen.queryByRole("region", { name: "A zip of your reports" })).toBeNull();
  });
});
