#!/usr/bin/env node
// Dump the skeleton/animation/geoset data of an MDL or MDX file as JSON.
//   node mdlx2json.js model.mdx > model.json
const fs = require('fs');
const path = require('path');

const viewer = process.env.MDX_VIEWER_DIR || path.join(__dirname, '..', 'deps', 'npm', 'node_modules', 'mdx-m3-viewer');
const Model = require(path.join(viewer, 'dist/cjs/parsers/mdlx/model.js')).default;

const file = process.argv[2];
const model = new Model();
if (file.toLowerCase().endsWith('.mdl')) model.load(fs.readFileSync(file, 'utf8'));
else { const b = fs.readFileSync(file); model.load(b.buffer.slice(b.byteOffset, b.byteOffset + b.length)); }

const arr = (a) => Array.from(a);
const anim = (o) => Object.fromEntries(o.animations
  .filter((a) => ['KGTR', 'KGRT', 'KGSC'].includes(a.name))
  .map((a) => [a.name, { interp: a.interpolationType, gseq: a.globalSequenceId,
    frames: arr(a.frames), values: a.values.map(arr) }]));
const node = (o) => ({ name: o.name, id: o.objectId, parent: o.parentId, anim: anim(o) });

console.log(JSON.stringify({
  sequences: model.sequences.map((s) => ({ name: s.name, interval: arr(s.interval) })),
  pivots: model.pivotPoints.map(arr),
  nodes: [...model.bones, ...model.helpers, ...model.attachments].map(node),
  geosets: model.geosets.map((g) => ({
    vertices: arr(g.vertices), vertexGroups: arr(g.vertexGroups),
    matrixGroups: arr(g.matrixGroups), matrixIndices: arr(g.matrixIndices),
  })),
}));
