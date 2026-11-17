// Starts every Playwright run from empty browser-test data, so the real-backend tests never run
// out of unpractised topics. Only ever touches <repo>/data/e2e: never data/ or practice data.
import { mkdirSync, rmSync } from "node:fs";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const target = resolve(join(root, "data", "e2e"));
if (
  !target.endsWith(`${sep}data${sep}e2e`) ||
  dirname(dirname(target)) !== root
) {
  console.error(`Refusing to reset unexpected path: ${target}`);
  process.exit(1);
}
rmSync(target, { recursive: true, force: true });
mkdirSync(target, { recursive: true });
console.log(`Reset browser-test data at ${target}`);
