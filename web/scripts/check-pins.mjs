// Every dependency in package.json is an exact version (LLD-1 §11, RM41-5): no ^, ~,
// ranges, tags, URLs or git refs. The lockfile pins the rest; `npm ci` refuses a drift.
import { readFileSync } from "node:fs";

const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url)));
const exact = /^\d+\.\d+\.\d+$/;
const loose = Object.entries({ ...pkg.dependencies, ...pkg.devDependencies })
  .filter(([, version]) => !exact.test(version))
  .map(([name, version]) => `${name}@${version}`);

if (loose.length) {
  console.error(`not pinned to an exact version: ${loose.join(", ")}`);
  process.exit(1);
}
console.log("web dependencies: all pinned exactly");
