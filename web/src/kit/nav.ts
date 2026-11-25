/**
 * The sidebar of mocks v16 (Ledger): every signed-in screen, grouped Home / Sell / GST filing /
 * Settings. Icons are the mock's own stroke paths, as fixed strings (never user data).
 */
export type NavKey =
  | "home" | "invoice" | "drafts" | "issued" | "customers" | "products" | "stock" | "purchases"
  | "filing" | "gstr1" | "w3b" | "uploads" | "fileperiod" | "periodfiles" | "setup";

export type NavItem = { key: NavKey; label: string; path: string; icon: string; invoicing?: boolean };

const I = {
  home: '<path d="M4 11l8-6 8 6v9H4z"/>',
  invoice: '<path d="M12 5v14M5 12h14"/>',
  drafts: '<path d="M6 3h9l3 3v15H6z"/><path d="M9 11h6M9 15h4"/>',
  issued: '<path d="M7 3h10v18l-2.5-1.5L12 21l-2.5-1.5L7 21z"/><path d="M10 8h4M10 12h4"/>',
  customers: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c1-4 4-5.5 7-5.5s6 1.5 7 5.5"/>',
  products: '<path d="M4 8l8-4 8 4-8 4z"/><path d="M4 8v8l8 4 8-4V8"/>',
  stock: '<path d="M4 20h16M6 20V10h4v10M14 20V5h4v15"/>',
  purchases: '<path d="M5 4h14v16H5z"/><path d="M9 9h6M9 13h6"/>',
  filing: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>',
  gstr1: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 9h8M8 13h5"/>',
  w3b: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 15l3-3 2 2 3-4"/>',
  uploads: '<path d="M12 16V5M7 10l5-5 5 5M5 20h14"/>',
  fileperiod: '<path d="M6 3h9l3 3v15H6z"/><path d="M9 14l2 2 4-4"/>',
  periodfiles: '<path d="M4 6h16v13H4z"/><path d="M4 10h16"/>',
  setup:
    '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>',
};

export const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  { label: "Home", items: [{ key: "home", label: "Home", path: "/home", icon: I.home }] },
  {
    label: "Sell",
    items: [
      { key: "invoice", label: "New invoice", path: "/invoices/new", icon: I.invoice, invoicing: true },
      { key: "drafts", label: "Draft invoices", path: "/drafts", icon: I.drafts, invoicing: true },
      { key: "issued", label: "Issued invoices", path: "/documents", icon: I.issued, invoicing: true },
      { key: "customers", label: "Customers", path: "/customers", icon: I.customers },
      { key: "products", label: "Products", path: "/products", icon: I.products },
      { key: "stock", label: "Stock", path: "/stock", icon: I.stock, invoicing: true },
      { key: "purchases", label: "Purchase invoices", path: "/purchases", icon: I.purchases, invoicing: true },
    ],
  },
  {
    label: "GST filing",
    items: [
      { key: "filing", label: "Your GST filing", path: "/filing", icon: I.filing },
      { key: "gstr1", label: "GSTR-1", path: "/filing", icon: I.gstr1 },
      { key: "w3b", label: "GSTR-3B worksheet", path: "/filing", icon: I.w3b },
      { key: "uploads", label: "Upload your reports", path: "/uploads", icon: I.uploads },
      { key: "fileperiod", label: "File from own invoices", path: "/file-period", icon: I.fileperiod, invoicing: true },
      { key: "periodfiles", label: "Monthly/quarterly files", path: "/period-files", icon: I.periodfiles, invoicing: true },
    ],
  },
  { label: "Settings", items: [{ key: "setup", label: "Settings", path: "/settings", icon: I.setup }] },
];

const byKey = Object.fromEntries(NAV_GROUPS.flatMap((g) => g.items).map((i) => [i.key, i])) as Record<NavKey, NavItem>;

/** The phone's bottom tab bar (mocks v16): five tabs, each lighting up for its group of screens. */
export const PHONE_TABS: (NavItem & { short: string; covers: NavKey[] })[] = [
  { ...byKey.home, short: "Home", covers: ["home"] },
  { ...byKey.invoice, short: "New", covers: ["invoice"] },
  { ...byKey.issued, short: "Invoices", covers: ["drafts", "issued", "customers", "products", "stock", "purchases"] },
  { ...byKey.gstr1, short: "GST", covers: ["filing", "gstr1", "w3b", "uploads", "fileperiod", "periodfiles"] },
  { ...byKey.setup, short: "More", covers: ["setup"] },
];

/** The open GSTR-1 and GSTR-3B the sidebar links to, when the server has one. */
export type ReturnLinks = { gstr1?: string; w3b?: string; gstr1Id?: string; w3bId?: string };

/**
 * Which sidebar item a page belongs to, from the path after /b/{id}. A child page marks its
 * parent (a customer marks Customers, held rows mark Upload, team and audit mark Settings).
 */
export function currentNav(sub: string, returns: ReturnLinks = {}): NavKey | null {
  const seg = sub.split("/").filter(Boolean);
  const [a, b, c] = seg;
  switch (a) {
    case "home":
      return "home";
    case "invoices":
      return "invoice";
    case "drafts":
      return "drafts";
    case "documents":
      return "issued";
    case "customers":
      return "customers";
    case "products":
      return "products";
    case "stock":
      return "stock";
    case "purchases":
      return "purchases";
    case "uploads":
      return "uploads";
    case "file-period":
      return "fileperiod";
    case "period-files":
      return "periodfiles";
    case "settings":
    case "onboarding":
      return "setup";
    case "filing":
      if (!b) return "filing";
      if (c === "worksheet" || c === "portal-guide-3b" || b === returns.w3bId) return "w3b";
      return "gstr1";
    default:
      return null;
  }
}
