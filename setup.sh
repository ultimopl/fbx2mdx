#!/bin/bash
# Install fbx2mdx's dependencies into tools/fbx2mdx/deps (nothing system-wide):
#   deps/blender   portable Blender, with the export_mdl addon linked in
#   deps/node      Node.js runtime (for the MDL -> MDX step)
#   deps/npm       mdx-m3-viewer (MDL parser / MDX writer)
#
#   ./setup.sh                 # all three (skips what is already installed)
#   ./setup.sh blender viewer  # only some of them
#   BLENDER_VERSION=5.2.2 NODE_VERSION=24.21.0 ./setup.sh
#
# fbx2mdx and edit offer to run this when a dependency is found neither on the
# system nor in deps/ (see env.sh). Delete deps/ to reinstall.
# The Blender bundle runs in "portable" mode: its preferences/scripts live in
# deps/blender/portable/, so it never touches ~/.config/blender.
set -euo pipefail

here="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
deps="$here/deps"
cache="$deps/.cache"
blender_version="${BLENDER_VERSION:-5.2.1}"
node_version="${NODE_VERSION:-24.21.0}"
viewer_version="${VIEWER_VERSION:-5.12.0}"

log() { echo "[setup] $*" >&2; }

want=("$@")
[ ${#want[@]} -gt 0 ] || want=(blender node viewer)
wants() { [[ " ${want[*]} " == *" $1 "* ]]; }
for w in "${want[@]}"; do
    case "$w" in blender|node|viewer) ;; *) log "unknown component '$w' (blender|node|viewer)"; exit 2 ;; esac
done

# fetch URL SHA256 DEST: download to DEST unless already present, then verify.
fetch() {
    local url="$1" expected="$2" dest="$3"
    if [ -z "$expected" ]; then
        log "no checksum published for $url"
        exit 1
    fi
    if [ ! -f "$dest" ]; then
        log "downloading $url"
        curl -fL --progress-bar -o "$dest.part" "$url"
        mv "$dest.part" "$dest"
    fi
    if [ "$(sha256sum "$dest" | cut -d' ' -f1)" != "$expected" ]; then
        rm -f "$dest"
        log "checksum mismatch for $url"
        exit 1
    fi
}

# extract TARBALL DEST: unpack NAME.tar.xz (whose top directory is NAME) as DEST.
extract() {
    local tarball="$1" dest="$2" top
    top="$(basename "$tarball" .tar.xz)"
    rm -rf "$dest" "${cache:?}/$top"
    tar -xJf "$tarball" -C "$cache"
    mv "$cache/$top" "$dest"
    rm -f "$tarball"
}

mkdir -p "$cache"

# Blender
if ! wants blender; then
    :
elif "$deps/blender/blender" --version 2>/dev/null | grep -q "Blender ${blender_version}"; then
    log "Blender ${blender_version} ok"
else
    series="${blender_version%.*}"
    name="blender-${blender_version}-linux-x64.tar.xz"
    base="https://download.blender.org/release/Blender${series}"
    sum="$(curl -fsL "$base/blender-${blender_version}.sha256" | awk -v f="$name" '$2 == f {print $1}')"
    fetch "$base/$name" "$sum" "$cache/$name"
    log "extracting Blender"
    extract "$cache/$name" "$deps/blender"
fi
# Link the addon from scripts/ so there is a single copy to edit.
if [ -x "$deps/blender/blender" ]; then
    mkdir -p "$deps/blender/portable/scripts/addons"
    ln -sfn "../../../../../scripts/addons/export_mdl" "$deps/blender/portable/scripts/addons/export_mdl"
fi

# Node.js
if ! wants node; then
    :
elif [ "$("$deps/node/bin/node" --version 2>/dev/null)" = "v${node_version}" ]; then
    log "Node.js ${node_version} ok"
else
    name="node-v${node_version}-linux-x64.tar.xz"
    base="https://nodejs.org/dist/v${node_version}"
    sum="$(curl -fsL "$base/SHASUMS256.txt" | awk -v f="$name" '$2 == f {print $1}')"
    fetch "$base/$name" "$sum" "$cache/$name"
    log "extracting Node.js"
    extract "$cache/$name" "$deps/node"
fi

# mdx-m3-viewer
viewer="$deps/npm/node_modules/mdx-m3-viewer"
# npm from deps/node when present, else the system one.
node="$deps/node/bin/node"
[ -x "$node" ] || node="$(type -P node || true)"
if ! wants viewer; then
    :
elif grep -q "\"version\": \"${viewer_version}\"" "$viewer/package.json" 2>/dev/null; then
    log "mdx-m3-viewer ${viewer_version} ok"
else
    log "installing mdx-m3-viewer ${viewer_version}"
    mkdir -p "$deps/npm"
    if [ -z "$node" ] || [ ! -x "$(dirname "$node")/npm" ]; then
        log "mdx-m3-viewer needs npm; run: $0 node viewer"
        exit 1
    fi
    PATH="$(dirname "$node"):$PATH" "$(dirname "$node")/npm" install --prefix "$deps/npm" \
        --no-audit --no-fund --omit=dev --loglevel=error "mdx-m3-viewer@${viewer_version}" >&2
fi
rmdir "$cache" 2>/dev/null || true

# Smoke test what was installed.
if wants blender; then
    "$deps/blender/blender" -b --factory-startup --python-expr \
        "import addon_utils, bpy; addon_utils.enable('export_mdl', default_set=True); \
print('[setup] export_mdl', 'ok' if hasattr(bpy.types.Material, 'mdl_layers') else 'FAILED')" 2>&1 \
        | grep "^\[setup\]" >&2
fi
if wants viewer; then
    "$node" -e "require('$viewer/dist/cjs/parsers/mdlx/model.js'); console.error('[setup] mdx-m3-viewer ok')"
fi
log "done: $deps"
