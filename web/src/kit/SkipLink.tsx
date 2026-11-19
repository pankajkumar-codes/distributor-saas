import { useEffect } from "react";

/**
 * "Skip to main content": the first Tab stop on every screen, shown only while it has focus.
 * It sits in its own labelled landmark so every element on the page is inside a region, and it
 * gives whichever <main> is on screen the id "main" so the link's target always exists (screens
 * come and go with the router, so this watches the page instead of asking each screen for an id).
 */
function markMain() {
  const main = document.querySelector("main");
  if (main && main.id !== "main") main.id = "main";
}

export function SkipLink() {
  useEffect(() => {
    markMain();
    const watcher = new MutationObserver(markMain);
    watcher.observe(document.body, { childList: true, subtree: true });
    return () => watcher.disconnect();
  }, []);
  return (
    <nav aria-label="Skip links" className="skip-nav">
      <a
        className="skip-link"
        href="#main"
        onClick={(e) => {
          const main = document.querySelector("main");
          if (!main) return;
          e.preventDefault();
          if (!main.hasAttribute("tabindex")) main.setAttribute("tabindex", "-1");
          main.focus();
          main.scrollIntoView?.({ block: "start" });
        }}
      >
        Skip to main content
      </a>
    </nav>
  );
}
