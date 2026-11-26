// Ringfence design tokens (assets/tokens.json, from the Ringfence design system) -> src/styles/tokens.css
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const t = JSON.parse(readFileSync(join(root, "assets", "tokens.json"), "utf8"));
const colours = Object.fromEntries(t.color.tokens.map((x) => [x.name, x.value]));
const resolve = (v, n = 0) => (/^\{(.+)\}$/.test(v) && n < 5 ? resolve(colours[v.slice(1, -1)], n + 1) : v);
const lines = Object.entries(colours).map(([k, v]) => `  --${k}: ${resolve(v)};`);
for (const g of ["spacing", "radius", "shadow", "size"]) for (const x of t[g].tokens) lines.push(`  --${x.name}: ${x.value};`);
lines.push(`  --font-sans: ${t.type.families.sans};`, `  --font-mono: ${t.type.families.mono};`);
const faces = t.type.fonts.map((f) => `@font-face { font-family: "${f.family}"; src: url("/rf/fonts/${f.file.split("/").pop()}") format("woff2"); font-weight: ${f.weight}; font-style: ${f.style}; font-display: swap; }`);
writeFileSync(join(root, "src", "styles", "tokens.css"), `/* generated from assets/tokens.json (npm run tokens) - do not edit */\n${faces.join("\n")}\n:root {\n${lines.join("\n")}\n}\n`);
console.log("tokens.css generated");
