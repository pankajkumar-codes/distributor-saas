import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SkipLink } from "../../src/kit/SkipLink";

describe("the skip link", () => {
  it("is the first link and moves focus to the page's main area", () => {
    render(
      <>
        <SkipLink />
        <nav>
          <a href="/x">Menu</a>
        </nav>
        <main>
          <h1>Page</h1>
        </main>
      </>,
    );
    const links = screen.getAllByRole("link");
    expect(links[0]).toHaveTextContent("Skip to main content");
    fireEvent.click(links[0]);
    expect(document.activeElement).toBe(screen.getByRole("main"));
  });

  it("sits in a landmark and gives the main area the id it points at", async () => {
    render(
      <>
        <SkipLink />
        <main>
          <h1>Page</h1>
        </main>
      </>,
    );
    expect(screen.getByRole("navigation", { name: "Skip links" })).toContainElement(
      screen.getByRole("link", { name: "Skip to main content" }),
    );
    await waitFor(() => expect(screen.getByRole("main")).toHaveAttribute("id", "main"));
  });
});
