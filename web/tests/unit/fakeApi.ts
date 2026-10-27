import { vi } from "vitest";

// A stand-in for the API: tests queue replies per path and read back what was sent.
export type Reply = { status: number; body?: unknown; headers?: Record<string, string>; wait?: Promise<void> };
export type Sent = { path: string; method: string; headers: Headers; body: Record<string, string> | null };

export function fakeApi() {
  const sent: Sent[] = [];
  const replies: Record<string, Reply[]> = {};
  const fetch = vi.fn(async (input: Request | string, init?: RequestInit) => {
    const request = typeof input === "string" ? new Request(input, init) : input;
    const path = new URL(request.url).pathname;
    const text = await request.clone().text();
    sent.push({ path, method: request.method, headers: request.headers, body: text ? JSON.parse(text) : null });
    // With nothing queued, refresh says "no session" and anything else is a server error.
    const answer: Reply = replies[path]?.shift() ?? { status: path === "/api/v1/auth/refresh" ? 401 : 500 };
    await answer.wait; // lets a test hold a reply back to look at the loading state
    return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
      status: answer.status,
      headers: { "Content-Type": "application/json", ...answer.headers },
    });
  });
  vi.stubGlobal("fetch", fetch);
  return {
    sent,
    reply(path: string, ...answers: Reply[]) {
      replies[path] = [...(replies[path] ?? []), ...answers];
    },
    paths: () => sent.map((s) => s.path),
  };
}
