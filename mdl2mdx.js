#!/usr/bin/env node
// Convert an MDL text model to binary MDX using mdx-m3-viewer (installed by setup.sh).
//   node mdl2mdx.js in.mdl out.mdx
const fs = require('fs');
const path = require('path');

const viewer = process.env.MDX_VIEWER_DIR || path.join(__dirname, 'deps', 'npm', 'node_modules', 'mdx-m3-viewer');
const Model = require(path.join(viewer, 'dist/cjs/parsers/mdlx/model.js')).default;

const [input, output] = process.argv.slice(2);
if (!input || !output) {
  console.error('usage: mdl2mdx.js in.mdl out.mdx');
  process.exit(2);
}

const model = new Model();
model.load(fs.readFileSync(input, 'utf8'));
fs.writeFileSync(output, model.saveMdx());
console.log(`[mdl2mdx] wrote ${output}`);
