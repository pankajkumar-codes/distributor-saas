import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

beforeEach(() => {
  resetSessionForTests();
  fakeApi();
});
afterEach(() => vi.unstubAllGlobals());

describe("the browser tab title", () => {
  it.each([
    ["/signup", "Create your account", "Create your account"],
    ["/signin", "Sign in", "Sign in"],
    ["/reset", "Reset your password", "Reset your password"],
  ])("names the screen at %s", async (path, heading, title) => {
    window.history.replaceState(null, "", path);
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: heading });
    expect(document.title).toBe(`${title} · Business Hub`);
  });
});
