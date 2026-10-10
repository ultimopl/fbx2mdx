#!/usr/bin/env python3
"""Summarize a WC3 MDX (v800) file: chunks, sequences, geosets, bones, bounds.

    mdxinfo.py model.mdx [--json]
"""
import json
import struct
import sys


def read_chunks(data):
    if data[:4] != b"MDLX":
        raise SystemExit("not an MDX file")
    i = 4
    while i + 8 <= len(data):
        tag = data[i:i + 4].decode("latin1")
        size = struct.unpack_from("<I", data, i + 4)[0]
        yield tag, data[i + 8:i + 8 + size]
        i += 8 + size


def read_name(buf, off, n=80):
    return buf[off:off + n].split(b"\0", 1)[0].decode("latin1")


def parse_seqs(buf):
    out = []
    for off in range(0, len(buf), 132):
        name = read_name(buf, off)
        start, end = struct.unpack_from("<II", buf, off + 80)
        flags = struct.unpack_from("<I", buf, off + 92)[0]
        out.append({"name": name, "start": start, "end": end, "nonlooping": bool(flags)})
    return out


def parse_geosets(buf):
    out = []
    i = 0
    while i < len(buf):
        size = struct.unpack_from("<I", buf, i)[0]
        g = buf[i + 4:i + size]
        j = 0
        info = {}
        verts = []
        # VRTX, NRMS, PTYP, PCNT, PVTX, GNDX, MTGC, MATS, [TANG], [SKIN], ..., UVAS
        while j + 8 <= len(g):
            tag = g[j:j + 4].decode("latin1")
            if not tag.isalpha():
                break
            n = struct.unpack_from("<I", g, j + 4)[0]
            j += 8
            if tag == "VRTX":
                verts = struct.unpack_from("<%df" % (n * 3), g, j)
                info["vertices"] = n
                j += n * 12
            elif tag == "NRMS":
                j += n * 12
            elif tag in ("PTYP", "PCNT", "MTGC", "MATS"):
                if tag == "MATS":
                    info["matrix_refs"] = n
                j += n * 4
            elif tag == "PVTX":
                info["triangles"] = n // 3
                j += n * 2
            elif tag == "GNDX":
                j += n
            elif tag == "TANG":
                j += n * 16
            elif tag == "SKIN":
                j += n
            elif tag == "UVAS":
                info["uv_sets"] = n
                for _ in range(n):
                    j += 4  # UVBS
                    m = struct.unpack_from("<I", g, j)[0]
                    j += 4 + m * 8
                break
            else:
                break
            # MATS is followed by material id, selection group, flags, extent, extents[]
            if tag == "MATS":
                info["material"], = struct.unpack_from("<I", g, j)
                j += 12 + 28
                ne = struct.unpack_from("<I", g, j)[0]
                j += 4 + ne * 28
        if verts:
            xs, ys, zs = verts[0::3], verts[1::3], verts[2::3]
            info["min"] = [round(min(xs), 2), round(min(ys), 2), round(min(zs), 2)]
            info["max"] = [round(max(xs), 2), round(max(ys), 2), round(max(zs), 2)]
        out.append(info)
        i += size
    return out


def parse_node_names(buf, extra_size_fn=None):
    names = []
    i = 0
    while i < len(buf):
        node_size = struct.unpack_from("<I", buf, i)[0]
        names.append(read_name(buf, i + 4))
        i += node_size
        if extra_size_fn:
            i += extra_size_fn(buf, i)
    return names


def summarize(path):
    data = open(path, "rb").read()
    s = {"file": path, "chunks": {}}
    for tag, buf in read_chunks(data):
        s["chunks"][tag] = len(buf)
        if tag == "VERS":
            s["version"] = struct.unpack_from("<I", buf)[0]
        elif tag == "MODL":
            s["model_name"] = read_name(buf, 0)
            s["bounds_radius"], = struct.unpack_from("<f", buf, 80 + 260)
            mn = struct.unpack_from("<3f", buf, 80 + 264)
            mx = struct.unpack_from("<3f", buf, 80 + 276)
            s["extent"] = [[round(v, 2) for v in mn], [round(v, 2) for v in mx]]
        elif tag == "SEQS":
            s["sequences"] = parse_seqs(buf)
        elif tag == "TEXS":
            s["textures"] = [read_name(buf, o + 4, 260) for o in range(0, len(buf), 268)]
        elif tag == "GEOS":
            s["geosets"] = parse_geosets(buf)
        elif tag == "BONE":
            # bone = node + geoset id + geoset anim id
            s["bones"] = parse_node_names(buf, lambda b, i: 8)
        elif tag == "HELP":
            s["helpers"] = parse_node_names(buf)
        elif tag == "PIVT":
            s["pivots"] = len(buf) // 12
    return s


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    for path in args:
        s = summarize(path)
        if "--json" in sys.argv:
            print(json.dumps(s, indent=1))
            continue
        print("==", path, "v%s" % s.get("version"), "name=%r" % s.get("model_name"))
        print("  chunks:", " ".join("%s:%d" % kv for kv in s["chunks"].items()))
        print("  extent:", s.get("extent"), "radius", s.get("bounds_radius"))
        for q in s.get("sequences", []):
            print("  seq %-20s %6d-%-6d%s" % (q["name"], q["start"], q["end"],
                                               " nonlooping" if q["nonlooping"] else ""))
        print("  textures:", s.get("textures"))
        geos = s.get("geosets", [])
        print("  geosets: %d  verts %d  tris %d" % (
            len(geos), sum(g.get("vertices", 0) for g in geos), sum(g.get("triangles", 0) for g in geos)))
        for g in geos:
            print("    ", g)
        print("  bones: %d  helpers: %d  pivots: %s" % (
            len(s.get("bones", [])), len(s.get("helpers", [])), s.get("pivots")))
        print("  first bones:", s.get("bones", [])[:5])


if __name__ == "__main__":
    main()
