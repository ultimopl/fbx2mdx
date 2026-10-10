# Sourced by fbx2mdx, edit and tests/check.sh to find the three dependencies.
#
# Each one is looked up on the system first, then in deps/ (installed by setup.sh):
#   Blender >= 5    `blender` on PATH            | deps/blender/blender
#   Node.js >= 16   `node` on PATH               | deps/node/bin/node
#   mdx-m3-viewer   $MDX_VIEWER_DIR, global npm  | deps/npm/node_modules/mdx-m3-viewer
# Standalone mode (--standalone or FBX2MDX_STANDALONE=1) skips the system lookup.
# Anything still missing triggers a warning plus an offer to install it into deps/.
#
# After `fbx2mdx_resolve`: $blender is set, and FBX2MDX_NODE / MDX_VIEWER_DIR are
# exported (the addon and mdl2mdx.js read them); `node` on PATH is the chosen one.
fbx2mdx_root="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
fbx2mdx_deps="$fbx2mdx_root/deps"

# Remove --standalone from the caller's arguments: fbx2mdx_args holds the rest.
fbx2mdx_take_flags() {
    fbx2mdx_args=()
    local a
    for a in "$@"; do
        if [ "$a" = "--standalone" ]; then
            FBX2MDX_STANDALONE=1
        else
            fbx2mdx_args+=("$a")
        fi
    done
}

fbx2mdx_major() {  # "Blender 5.2.1" / "v24.1.0" -> 5 / 24
    sed -n '1s/^[^0-9]*\([0-9]*\).*/\1/p'
}

fbx2mdx_system_blender() {
    local b="${FBX2MDX_BLENDER:-$(type -P blender)}"
    [ -n "$b" ] && [ -x "$b" ] || return 1
    [ "$("$b" --version 2>/dev/null | fbx2mdx_major)" -ge 5 ] 2>/dev/null || return 1
    echo "$b"
}

fbx2mdx_system_node() {
    local n
    n="$(type -P node)" || return 1
    [ "$("$n" --version 2>/dev/null | fbx2mdx_major)" -ge 16 ] 2>/dev/null || return 1
    echo "$n"
}

fbx2mdx_system_viewer() {
    local d
    for d in "${MDX_VIEWER_DIR:-}" "$( (npm root -g) 2>/dev/null)/mdx-m3-viewer"; do
        [ -n "$d" ] && [ -f "$d/dist/cjs/parsers/mdlx/model.js" ] && { echo "$d"; return 0; }
    done
    return 1
}

# fbx2mdx_find NAME: print the path for NAME (blender|node|viewer) and where it came from.
fbx2mdx_find() {
    local local_path
    case "$1" in
        blender) local_path="$fbx2mdx_deps/blender/blender" ;;
        node) local_path="$fbx2mdx_deps/node/bin/node" ;;
        viewer) local_path="$fbx2mdx_deps/npm/node_modules/mdx-m3-viewer" ;;
    esac
    if [ -z "${FBX2MDX_STANDALONE:-}" ] && fbx2mdx_system_"$1"; then
        return 0
    fi
    [ -e "$local_path" ] && echo "$local_path"
}

fbx2mdx_resolve() {
    local missing=() name
    blender="$(fbx2mdx_find blender)" || missing+=(blender)
    FBX2MDX_NODE="$(fbx2mdx_find node)" || missing+=(node)
    MDX_VIEWER_DIR="$(fbx2mdx_find viewer)" || missing+=(viewer)

    if [ ${#missing[@]} -gt 0 ]; then
        echo "[fbx2mdx] WARNING: missing dependencies: ${missing[*]}" >&2
        if [ -n "${FBX2MDX_STANDALONE:-}" ]; then
            echo "[fbx2mdx]   (standalone mode only looks in $fbx2mdx_deps)" >&2
        else
            echo "[fbx2mdx]   not found on the system (Blender >= 5, Node.js >= 16, mdx-m3-viewer) nor in $fbx2mdx_deps" >&2
        fi
        local reply="" sizes=()
        for name in "${missing[@]}"; do
            case "$name" in
                blender) sizes+=("Blender ~350 MB") ;;
                node) sizes+=("Node.js ~30 MB") ;;
                viewer) sizes+=("mdx-m3-viewer ~5 MB") ;;
            esac
        done
        if [ -t 0 ] && [ -t 2 ]; then
            read -r -p "[fbx2mdx] Download portable copies into deps/ ($(IFS=,; echo "${sizes[*]}" | sed 's/,/, /g'))? [y/N] " reply >&2
        fi
        if [[ ! "$reply" =~ ^[YySs] ]]; then
            echo "[fbx2mdx] install them, or run: $fbx2mdx_root/setup.sh ${missing[*]}" >&2
            exit 1
        fi
        "$fbx2mdx_root/setup.sh" "${missing[@]}" || { echo "[fbx2mdx] setup failed" >&2; exit 1; }
        for name in "${missing[@]}"; do
            case "$name" in
                blender) blender="$fbx2mdx_deps/blender/blender" ;;
                node) FBX2MDX_NODE="$fbx2mdx_deps/node/bin/node" ;;
                viewer) MDX_VIEWER_DIR="$fbx2mdx_deps/npm/node_modules/mdx-m3-viewer" ;;
            esac
        done
    fi

    # The bundle links the addon into deps/blender/portable; a system Blender is
    # pointed at scripts/ instead.
    case "$blender" in
        "$fbx2mdx_deps"/*) ;;
        *) export BLENDER_USER_SCRIPTS="$fbx2mdx_root/scripts" ;;
    esac
    export FBX2MDX_NODE MDX_VIEWER_DIR
    export PATH="$(dirname "$FBX2MDX_NODE"):$PATH"
    if [ -n "${FBX2MDX_VERBOSE:-}" ]; then
        echo "[fbx2mdx] blender=$blender node=$FBX2MDX_NODE viewer=$MDX_VIEWER_DIR" >&2
    fi
}
