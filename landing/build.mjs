// Builds the landing page into landing/dist: index.html from the template and site.config.json, the stylesheet,
// the favicon and the two self-hosted fonts. No dependencies; the fonts come from web/node_modules (npm ci in web/).
// Usage: node landing/build.mjs   (add --check to also fail on anything third-party in the output)
import { copyFileSync, mkdirSync, readFileSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, "dist");
const config = JSON.parse(readFileSync(join(here, "site.config.json"), "utf8"));

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const isTodo = (v) => /^TODO\b/i.test(String(v ?? "").trim()) || !String(v ?? "").trim();
const todo = (v) => `<mark class="todo">${esc(String(v ?? "").trim() || "TODO: fill in site.config.json")}</mark>`;
// A real value shows as text, or as a link when it looks like a URL or an email address.
const show = (v, label) => {
  if (isTodo(v)) return todo(v);
  const s = String(v).trim();
  if (/^https?:\/\//.test(s) || s.startsWith("/")) return `<a href="${esc(s)}">${esc(label)}</a>`;
  if (s.includes("@")) return `<a href="mailto:${esc(s)}">${esc(s)}</a>`;
  return esc(s);
};

const values = {
  signup_url: esc(config.signup_url),
  signin_url: esc(config.signin_url),
  support_contact: isTodo(config.support_contact) ? `Support: ${todo(config.support_contact)}` : `Support: ${show(config.support_contact, "Contact support")}`,
  legal_entity: isTodo(config.legal_entity) ? todo(config.legal_entity) : esc(config.legal_entity),
  privacy_terms: `${isTodo(config.privacy_url) ? "Privacy policy " + todo(config.privacy_url) : show(config.privacy_url, "Privacy policy")} · ${isTodo(config.terms_url) ? "Terms of use " + todo(config.terms_url) : show(config.terms_url, "Terms of use")}`,
  hosting_line: isTodo(config.hosting_line) ? todo(config.hosting_line) : esc(config.hosting_line),
};

let html = readFileSync(join(here, "index.template.html"), "utf8");
html = html.replace(/\{\{(\w+)\}\}/g, (_, k) => {
  if (!(k in values)) throw new Error(`Unknown placeholder {{${k}}} in the template`);
  return values[k];
});

rmSync(out, { recursive: true, force: true });
mkdirSync(join(out, "fonts"), { recursive: true });
writeFileSync(join(out, "index.html"), html);
copyFileSync(join(here, "styles.css"), join(out, "styles.css"));
copyFileSync(join(here, "favicon.svg"), join(out, "favicon.svg"));
const fonts = join(here, "..", "web", "node_modules", "@fontsource-variable");
for (const [pkg, file] of [["fraunces", "fraunces-latin-wght-normal.woff2"], ["hanken-grotesk", "hanken-grotesk-latin-wght-normal.woff2"]]) {
  const src = join(fonts, pkg, "files", file);
  if (!existsSync(src)) throw new Error(`Missing ${src}: run npm ci in web/ first`);
  copyFileSync(src, join(out, "fonts", file));
}

if (process.argv.includes("--check")) {
  const problems = [];
  const all = html + readFileSync(join(out, "styles.css"), "utf8");
  if (/<script\b/i.test(html)) problems.push("a script tag");
  if (/https?:\/\/(?!www\.w3\.org\/2000\/svg)/i.test(all)) problems.push("an absolute http(s) URL (third-party fonts, scripts or links)");
  if (/\{\{/.test(html)) problems.push("an unfilled placeholder");
  if (problems.length) {
    console.error("landing check failed: " + problems.join("; "));
    process.exit(1);
  }
  console.log("landing check passed: no scripts, no third-party URLs, no unfilled placeholders");
}
console.log(`landing built into ${out}`);
