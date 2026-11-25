import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { currentNav, NAV_GROUPS, PHONE_TABS } from "../../src/kit/nav";
import { Pager } from "../../src/kit/Pager";
import { Tabs } from "../../src/kit/Tabs";

describe("the v16 sidebar", () => {
  it("has the mock's groups and items, in order", () => {
    expect(NAV_GROUPS.map((g) => g.label)).toEqual(["Home", "Sell", "GST filing", "Settings"]);
    expect(NAV_GROUPS[1].items.map((i) => i.label)).toEqual([
      "New invoice", "Draft invoices", "Issued invoices", "Customers", "Products", "Stock", "Purchase invoices",
    ]);
    expect(NAV_GROUPS[2].items.map((i) => i.label)).toEqual([
      "Your GST filing", "GSTR-1", "GSTR-3B worksheet", "Upload your reports", "File from own invoices", "Monthly/quarterly files",
    ]);
    expect(PHONE_TABS.map((t) => t.short)).toEqual(["Home", "New", "Invoices", "GST", "More"]);
  });

  it("marks a child page's parent", () => {
    expect(currentNav("/home")).toBe("home");
    expect(currentNav("/customers/c-1")).toBe("customers");
    expect(currentNav("/products/import")).toBe("products");
    expect(currentNav("/documents/d-1")).toBe("issued");
    expect(currentNav("/invoices/new")).toBe("invoice");
    expect(currentNav("/uploads/runs/r-1/held")).toBe("uploads");
    expect(currentNav("/settings/team")).toBe("setup");
    expect(currentNav("/settings/plan")).toBe("setup");
    expect(currentNav("/filing")).toBe("filing");
    expect(currentNav("/filing/i-1")).toBe("gstr1");
    expect(currentNav("/filing/i-2/worksheet")).toBe("w3b");
    expect(currentNav("/filing/i-2/portal-guide-3b")).toBe("w3b");
    expect(currentNav("/filing/i-3", { w3bId: "i-3" })).toBe("w3b");
    expect(currentNav("/nowhere")).toBeNull();
  });
});

describe("Pager", () => {
  it("counts rows and stops at both ends", () => {
    const onPage = vi.fn();
    const { rerender } = render(<Pager page={0} size={5} shown={5} total={12} noun="products" onPage={onPage} />);
    expect(screen.getByText("1–5 of 12 products")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onPage).toHaveBeenCalledWith(1);
    rerender(<Pager page={2} size={5} shown={2} total={12} noun="products" onPage={onPage} />);
    expect(screen.getByText("11–12 of 12 products")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("works from has-more when the server gives no total, and says when there is nothing", () => {
    const { rerender } = render(<Pager page={1} size={5} shown={5} hasMore noun="customers" onPage={() => {}} />);
    expect(screen.getByText("Customers 6–10")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
    rerender(<Pager page={0} size={5} shown={0} noun="customers" onPage={() => {}} />);
    expect(screen.getByText("No customers")).toBeInTheDocument();
  });
});

describe("Tabs", () => {
  function Host() {
    const [at, setAt] = useState(0);
    return (
      <Tabs
        label="Return"
        current={at}
        onChange={setAt}
        tabs={[
          { label: "Checks", panel: <p>checks body</p> },
          { label: "Documents issued", panel: <p>table 13 body</p> },
          { label: "File and lock", panel: <p>file body</p> },
        ]}
      />
    );
  }

  it("draws only the chosen panel and moves with the arrow keys", () => {
    render(<Host />);
    expect(screen.getByRole("tab", { name: "Checks" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("checks body")).toBeInTheDocument();
    expect(screen.queryByText("file body")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "File and lock" }));
    expect(screen.getByRole("tabpanel")).toHaveTextContent("file body");
    fireEvent.keyDown(screen.getByRole("tab", { name: "File and lock" }), { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Checks" })).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(screen.getByRole("tab", { name: "Checks" }), { key: "End" });
    expect(screen.getByRole("tab", { name: "File and lock" })).toHaveFocus();
  });
});
