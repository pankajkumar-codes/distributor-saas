// Runs the CloudFront viewer-request function on sample requests: node infra/modules/cdn/routing.test.mjs
import { readFileSync } from "node:fs";
import { strict as assert } from "node:assert";
import vm from "node:vm";

const code = readFileSync(new URL("./viewer_request.js", import.meta.url), "utf8");
const ctx = {};
vm.runInNewContext(code, ctx);
const route = (uri, cookies = {}) =>
  ctx.handler({ request: { uri, cookies: Object.fromEntries(Object.entries(cookies).map(([k, v]) => [k, { value: v }])) } }).uri;

const cases = [
  ["/", {}, "/_landing/index.html"],
  ["/", { other: "1" }, "/_landing/index.html"],
  ["/", { kartaa_in: "0" }, "/_landing/index.html"],
  ["/", { kartaa_in: "1" }, "/index.html"],
  ["/styles.css", {}, "/_landing/styles.css"],
  ["/fonts/fraunces-latin-wght-normal.woff2", {}, "/_landing/fonts/fraunces-latin-wght-normal.woff2"],
  ["/signin", {}, "/index.html"],
  ["/signup", { kartaa_in: "1" }, "/index.html"],
  ["/b/abc/invoices/1", {}, "/index.html"],
  ["/assets/index-AbC123.js", {}, "/assets/index-AbC123.js"],
  ["/favicon.svg", {}, "/favicon.svg"],
];
for (const [uri, cookies, want] of cases) assert.equal(route(uri, cookies), want, `${uri} ${JSON.stringify(cookies)}`);
// A request with no cookies object at all (CloudFront omits it when there are none) is a visitor.
assert.equal(ctx.handler({ request: { uri: "/" } }).uri, "/_landing/index.html");
console.log(`routing: ${cases.length + 1} cases pass`);
