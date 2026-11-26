// Ringfence build: React (JSX) -> one same-origin bundle, plus the design system's tokens, component CSS and fonts.
// No CDN, no runtime fetches: the output satisfies the server CSP (script-src 'self'; style-src 'self').
//   node build.mjs            -> ../smartparser/webapp/ringfence/
import { build } from "esbuild";
import { readFileSync, writeFileSync, mkdirSync, copyFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, "..", "smartparser", "webapp", "ringfence");
mkdirSync(join(out, "fonts"), { recursive: true });

// tokens.json (Ringfence design system) -> tokens.css, resolving {references}
const t = JSON.parse(readFileSync(join(here, "assets", "tokens.json"), "utf8"));
const colours = Object.fromEntries(t.color.tokens.map((x) => [x.name, x.value]));
const resolve = (v, seen = 0) => (/^\{(.+)\}$/.test(v) && seen < 5 ? resolve(colours[v.slice(1, -1)], seen + 1) : v);
const lines = [];
for (const [k, v] of Object.entries(colours)) lines.push(`  --${k}: ${resolve(v)};`);
for (const group of ["spacing", "radius", "shadow", "size"]) for (const x of t[group].tokens) lines.push(`  --${x.name}: ${x.value};`);
lines.push(`  --font-sans: ${t.type.families.sans};`, `  --font-mono: ${t.type.families.mono};`);
const faces = t.type.fonts.map((f) => `@font-face { font-family: "${f.family}"; src: url("fonts/${f.file.split("/").pop()}") format("woff2"); font-weight: ${f.weight}; font-style: ${f.style}; font-display: swap; }`);
writeFileSync(join(out, "tokens.css"), `/* generated from the Ringfence tokens.json - do not edit */\n${faces.join("\n")}\n:root {\n${lines.join("\n")}\n}\n`);

copyFileSync(join(here, "assets", "bundle.css"), join(out, "bundle.css"));
copyFileSync(join(here, "src", "app.css"), join(out, "app.css"));
copyFileSync(join(here, "src", "index.html"), join(out, "index.html"));
for (const f of readdirSync(join(here, "assets", "fonts"))) copyFileSync(join(here, "assets", "fonts", f), join(out, "fonts", f));

await build({
  entryPoints: [join(here, "src", "main.jsx")], bundle: true, minify: true, sourcemap: false, format: "iife",
  target: ["es2019"], outfile: join(out, "app.js"), jsx: "automatic", define: { "process.env.NODE_ENV": '"production"' },
  legalComments: "eof", logLevel: "info",
});
console.log("ringfence built ->", out);
