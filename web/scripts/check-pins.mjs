// Every dependency in package.json is an exact version (LLD-1 §11, RM41-5): no ^, ~,
// ranges, tags, URLs or git refs. The lockfile pins the rest; `npm ci` refuses a drift.
import { readFileSync } from "node:fs";

const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url)));
const exact = /^\d+\.\d+\.\d+$/;
const loose = [];

// Each section on its own, so a pinned devDependency can't hide a loose runtime entry.
for (const section of ["dependencies", "devDependencies", "optionalDependencies"]) {
  for (const [name, version] of Object.entries(pkg[section] ?? {})) {
    if (!exact.test(version)) loose.push(`${section}: ${name}@${version}`);
  }
}

// Overrides nest; every version string inside them must be exact too.
function checkOverrides(node, path) {
  for (const [key, value] of Object.entries(node)) {
    if (typeof value === "string") {
      if (!exact.test(value)) loose.push(`overrides: ${[...path, key].join(" > ")}@${value}`);
    } else checkOverrides(value, [...path, key]);
  }
}
checkOverrides(pkg.overrides ?? {}, []);

if (loose.length) {
  console.error(`not pinned to an exact version: ${loose.join(", ")}`);
  process.exit(1);
}
console.log("web dependencies: all pinned exactly");
