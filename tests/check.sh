#!/bin/bash
# Convert a model and measure how closely the MDX animation follows Blender.
#   tests/check.sh INPUT [extra convert.py options...]
set -e
here="$(cd "$(dirname "$0")/.." && pwd)"
source "$here/env.sh"
fbx2mdx_take_flags "$@"
set -- ${fbx2mdx_args[@]+"${fbx2mdx_args[@]}"}
fbx2mdx_resolve
in="$1"; shift
out="$here/work/test/$(basename "${in%.*}" | tr ' ' '_')"
mkdir -p "$(dirname "$out")"
"$blender" -b --factory-startup --python "$here/convert.py" -- "$in" "$out.mdl" --save-blend "$out.blend" "$@" 2>&1 | grep -E "^\[fbx2mdx\]|Error|Traceback" || true
node "$here/mdl2mdx.js" "$out.mdl" "$out.mdx"
python3 "$here/mdxinfo.py" "$out.mdx" | sed -n '1,12p'
node "$here/tests/mdlx2json.js" "$out.mdx" > "$out.json"
"$blender" -b "$out.blend" --python "$here/tests/verify_anim.py" -- "$out.json" 3 2>&1 | grep -E "^(REST|SEQ)|Error|Traceback" || true
