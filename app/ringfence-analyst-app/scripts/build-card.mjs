// Builds the design-system card bundle: dist-card/analyst-app.js (one classic script, React included).
// It defines window.RingfenceAnalystApp; the design system's bundle.js exposes it as window.Ringfence.AnalystApp.
import { build } from 'esbuild';
import { readFileSync, writeFileSync } from 'node:fs';

await build({
  entryPoints: ['src/card-entry.jsx'], bundle: true, minify: true, format: 'iife', globalName: 'RingfenceAnalystApp',
  jsx: 'automatic', loader: { '.js': 'jsx', '.css': 'text' }, define: { 'process.env.NODE_ENV': '"production"' },
  target: ['es2019'], legalComments: 'none', outfile: 'dist-card/analyst-app.js', logLevel: 'warning'
});
let js = readFileSync('dist-card/analyst-app.js', 'utf8');
js = js.replace(/<\/script/gi, '<\\/script').replace(/<!--/g, '<\\!--');
js += '\n;(function(){var R=window.Ringfence=window.Ringfence||{};R.AnalystApp=window.RingfenceAnalystApp;})();\n';
writeFileSync('dist-card/analyst-app.js', js);
console.log('dist-card/analyst-app.js', (js.length / 1024).toFixed(0) + ' KB');
