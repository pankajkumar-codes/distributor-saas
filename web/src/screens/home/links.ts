// LLD-6 RM46-J7: Home follows a link from the server only when it is a path under this
// business that the web actually has a screen for; anything else gets no link at all.

/** Screens under /b/:businessId/ that exist in the web today. Each new screen adds its path. */
export const SCREENS = new Set<string>(["home"]);

/** The in-app path for `href`, or null when it isn't one of this business's screens. */
export function screenPath(href: unknown, businessId: string, screens: ReadonlySet<string> = SCREENS): string | null {
  if (typeof href !== "string") return null;
  if (/[\u0000-\u001f\u007f\\]/.test(href)) return null;
  const base = `/b/${businessId}/`;
  if (!href.startsWith(base)) return null;
  const rest = href.slice(base.length).split(/[?#]/)[0];
  if (!rest || rest.includes("//") || rest.split("/").some((part) => part === "." || part === "..")) return null;
  return screens.has(rest) ? href : null;
}
