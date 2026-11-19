/**
 * "Skip to main content": the first Tab stop on every screen, shown only while it has focus.
 * It finds the page's <main> when pressed, so no screen needs to give it an id; the page's own
 * router is not involved (no address change).
 */
export function SkipLink() {
  return (
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
  );
}
