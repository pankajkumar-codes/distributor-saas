import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { tokenStore } from "../../src/auth/tokenStore";
import { uploadTo } from "../../src/api/upload";
import { finished, pollDelay, useJob, type Job } from "../../src/api/useJob";
import { fakeApi } from "./fakeApi";

const JOB = "/api/v1/b/b-1/jobs/j-1";
const job = (status: Job["status"], over: Partial<Job> = {}): Job => ({
  id: "j-1",
  type: "catalog.import_parse",
  status,
  attempt: 1,
  progress: null,
  result: null,
  error_code: null,
  created_at: "2026-11-02T10:00:00Z",
  updated_at: "2026-11-02T10:00:00Z",
  ...over,
});

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  server = fakeApi();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  tokenStore.clear();
});

function Show({ id }: { id: string | null }) {
  const j = useJob("b-1", id);
  return <p>{j.data ? `status ${j.data.status}` : "none"}</p>;
}
const mount = (id: string | null) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Show id={id} />
    </QueryClientProvider>,
  );

describe("useJob", () => {
  it("polls until the job is done, then stops", async () => {
    // Fake clock: the poll gaps (1 s, then 2 s) are stepped through, not waited for.
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
    server.reply(JOB, { status: 200, body: job("queued") }, { status: 200, body: job("running") }, { status: 200, body: job("done") });
    const step = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));
    const polls = () => server.paths().filter((p) => p === JOB).length;
    // Lets the fake response be read in 1 ms clock steps (the response body is read on timers).
    const shows = async (text: string) => {
      for (let i = 0; i < 50 && !screen.queryByText(text); i++) {
        await new Promise((r) => setImmediate(r));
        await step(1);
      }
      expect(screen.getByText(text)).toBeInTheDocument();
    };
    mount("j-1");
    await shows("status queued");
    // The gaps are 1 s, then 2 s, then 4 s: nothing new is asked before a gap ends.
    await step(900);
    expect(polls()).toBe(1);
    await step(100);
    await shows("status running");
    expect(polls()).toBe(2);
    await step(1800);
    expect(polls()).toBe(2);
    await step(200);
    await shows("status done");
    await step(30000);
    expect(polls()).toBe(3);
  });

  it("asks nothing without a job ID", async () => {
    mount(null);
    await new Promise((r) => setTimeout(r, 50));
    expect(server.paths()).toEqual([]);
  });

  it("keeps waiting through failed_retryable, which the runner retries, and backs off to 5 s", () => {
    expect(finished(job("failed_retryable"))).toBe(false);
    expect(finished(job("failed"))).toBe(true);
    expect(finished(job("done"))).toBe(true);
    expect([0, 1, 2, 3, 9].map(pollDelay)).toEqual([1000, 2000, 4000, 5000, 5000]);
  });
});

describe("uploadTo", () => {
  const target = { url: "https://bucket.example/", fields: { key: "b/b-1/catalog-imports/i-1", policy: "p", "x-amz-signature": "s" } };

  it("sends the policy fields before the file, with no token and no cookies", async () => {
    tokenStore.set("secret-token", 3600);
    server.reply("/", { status: 204 });
    await uploadTo(target, new File(["code,name\n"], "products.csv", { type: "text/csv" }));
    const [s] = server.sent;
    expect(s.url).toBe("https://bucket.example/");
    expect(s.headers.get("Authorization")).toBeNull();
    expect(s.request.credentials).toBe("omit");
    const raw = await s.request.text();
    const names = [...raw.matchAll(/; name="([^"]+)"/g)].map((m) => m[1]);
    expect(names).toEqual(["key", "policy", "x-amz-signature", "file"]);
    expect(raw).toContain("code,name"); // (jsdom's File loses its name on the way through undici's FormData)
  });

  it("rejects with storage's status, or status 0 when storage can't be reached", async () => {
    server.reply("/", { status: 403 });
    await expect(uploadTo(target, new File(["x"], "x.csv"))).rejects.toMatchObject({ status: 403 });
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));
    await expect(uploadTo(target, new File(["x"], "x.csv"))).rejects.toMatchObject({ status: 0, code: "network" });
  });
});
