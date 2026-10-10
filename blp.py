"""BLP1 writer (JPEG content) in pure Python + numpy, usable inside Blender.

Warcraft III's BLP1 JPEG is not a normal colour JPEG: it has four components
holding the raw B, G, R, A bands with no YCbCr transform (the game, the
engine's stb patch and mdx-m3-viewer all read the bands as-is). No stock
encoder writes that, so this module carries a small baseline encoder.

    write_blp(path, rgba, alpha=False, max_size=512, quality=90)

`rgba` is a float array [height, width, 4] in 0..1, top row first, already in
the colour space the texture should display in (sRGB).
"""
import math
import struct

import numpy as np

# Annex K standard luminance tables, shared by all four components.
QUANT = np.array([
    16, 11, 10, 16, 24, 40, 51, 61,
    12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56,
    14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77,
    24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101,
    72, 92, 95, 98, 112, 100, 103, 99], np.float64)

DC_BITS = [0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]
DC_VALS = list(range(12))
AC_BITS = [0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7d]
AC_VALS = [
    0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06, 0x13, 0x51, 0x61, 0x07,
    0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xa1, 0x08, 0x23, 0x42, 0xb1, 0xc1, 0x15, 0x52, 0xd1, 0xf0,
    0x24, 0x33, 0x62, 0x72, 0x82, 0x09, 0x0a, 0x16, 0x17, 0x18, 0x19, 0x1a, 0x25, 0x26, 0x27, 0x28,
    0x29, 0x2a, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3a, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49,
    0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5a, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69,
    0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7a, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
    0x8a, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9a, 0xa2, 0xa3, 0xa4, 0xa5, 0xa6, 0xa7,
    0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6, 0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3, 0xc4, 0xc5,
    0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda, 0xe1, 0xe2,
    0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0xe9, 0xea, 0xf1, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8,
    0xf9, 0xfa]
assert sum(AC_BITS) == len(AC_VALS) and sum(DC_BITS) == len(DC_VALS)


def _zigzag():
    order = sorted(((y, x) for y in range(8) for x in range(8)),
                   key=lambda p: (p[0] + p[1], p[1] if (p[0] + p[1]) % 2 == 0 else p[0]))
    return np.array([y * 8 + x for y, x in order])


ZIGZAG = _zigzag()


def _dct_matrix():
    c = np.zeros((8, 8))
    for k in range(8):
        a = math.sqrt(1 / 8) if k == 0 else math.sqrt(2 / 8)
        for n in range(8):
            c[k, n] = a * math.cos((2 * n + 1) * k * math.pi / 16)
    return c


DCT = _dct_matrix()


def _huffman(bits, vals):
    table, code, i = {}, 0, 0
    for length in range(1, 17):
        for _ in range(bits[length - 1]):
            table[vals[i]] = (code, length)
            code += 1
            i += 1
        code <<= 1
    return table


DC_TABLE = _huffman(DC_BITS, DC_VALS)
AC_TABLE = _huffman(AC_BITS, AC_VALS)


def _quant_table(quality):
    quality = min(max(int(quality), 1), 100)
    scale = 5000 / quality if quality < 50 else 200 - 2 * quality
    return np.clip(np.floor((QUANT * scale + 50) / 100), 1, 255)


def _segment(marker, payload):
    return struct.pack(">BBH", 0xFF, marker, len(payload) + 2) + payload


def jpeg_tables(quality):
    """SOI + DQT + DHT: identical for every mip, so it is the BLP's shared header."""
    q = _quant_table(quality)
    dqt = bytes([0]) + bytes(int(v) for v in q[ZIGZAG])
    dht = (bytes([0x00]) + bytes(DC_BITS) + bytes(DC_VALS) +
           bytes([0x10]) + bytes(AC_BITS) + bytes(AC_VALS))
    return b"\xFF\xD8" + _segment(0xDB, dqt) + _segment(0xC4, dht)


def _category(v):
    a = -v if v < 0 else v
    size = a.bit_length()
    return size, (v if v >= 0 else v + (1 << size) - 1)


def jpeg_scan(bands, quality):
    """SOF0 + SOS + entropy-coded data + EOI for a uint8 [h, w, 4] raw-band image."""
    h, w, ncomp = bands.shape
    ph, pw = -(-h // 8) * 8, -(-w // 8) * 8
    data = np.pad(bands, ((0, ph - h), (0, pw - w), (0, 0)), mode="edge").astype(np.float64) - 128.0
    by, bx = ph // 8, pw // 8
    blocks = data.reshape(by, 8, bx, 8, ncomp).transpose(0, 2, 4, 1, 3)   # by, bx, comp, 8, 8
    coef = DCT @ blocks @ DCT.T
    q = _quant_table(quality).reshape(8, 8)
    quant = np.round(coef / q).astype(np.int64).reshape(by, bx, ncomp, 64)[..., ZIGZAG]
    rows = quant.reshape(-1, 64).tolist()   # MCU order: block row, block column, component

    out = bytearray()
    acc = nbits = 0

    def put(code, length):
        nonlocal acc, nbits
        acc = (acc << length) | code
        nbits += length
        while nbits >= 8:
            nbits -= 8
            byte = (acc >> nbits) & 0xFF
            out.append(byte)
            if byte == 0xFF:
                out.append(0)
        acc &= (1 << nbits) - 1

    prev = [0] * ncomp
    for i, row in enumerate(rows):
        c = i % ncomp
        diff = row[0] - prev[c]
        prev[c] = row[0]
        size, bits = _category(diff)
        put(*DC_TABLE[size])
        if size:
            put(bits, size)
        run = 0
        for v in row[1:]:
            if v == 0:
                run += 1
                continue
            while run > 15:
                put(*AC_TABLE[0xF0])
                run -= 16
            size, bits = _category(v)
            put(*AC_TABLE[(run << 4) | size])
            put(bits, size)
            run = 0
        if run:
            put(*AC_TABLE[0x00])
    if nbits:
        put((1 << (8 - nbits)) - 1, 8 - nbits)

    sof = struct.pack(">BHHB", 8, h, w, ncomp) + b"".join(bytes([c + 1, 0x11, 0]) for c in range(ncomp))
    sos = bytes([ncomp]) + b"".join(bytes([c + 1, 0x00]) for c in range(ncomp)) + bytes([0, 63, 0])
    return _segment(0xC0, sof) + _segment(0xDA, sos) + bytes(out) + b"\xFF\xD9"


def _halve(img):
    """2x2 average along each even-sized axis (a 1-pixel axis is left alone)."""
    if img.shape[0] > 1 and img.shape[0] % 2 == 0:
        img = (img[0::2] + img[1::2]) / 2
    if img.shape[1] > 1 and img.shape[1] % 2 == 0:
        img = (img[:, 0::2] + img[:, 1::2]) / 2
    return img


def _resize(img, nh, nw):
    """Downscale by 2x2 averaging while possible, then bilinear to the exact size."""
    while img.shape[0] >= 2 * nh and img.shape[1] >= 2 * nw and img.shape[0] % 2 == 0 and img.shape[1] % 2 == 0:
        img = _halve(img)
    h, w = img.shape[:2]
    if (h, w) == (nh, nw):
        return img
    ys = np.clip((np.arange(nh) + 0.5) * h / nh - 0.5, 0, h - 1)
    xs = np.clip((np.arange(nw) + 0.5) * w / nw - 0.5, 0, w - 1)
    y0, x0 = np.floor(ys).astype(int), np.floor(xs).astype(int)
    y1, x1 = np.minimum(y0 + 1, h - 1), np.minimum(x0 + 1, w - 1)
    fy, fx = (ys - y0)[:, None, None], (xs - x0)[None, :, None]
    top = img[y0][:, x0] * (1 - fx) + img[y0][:, x1] * fx
    bot = img[y1][:, x0] * (1 - fx) + img[y1][:, x1] * fx
    return top * (1 - fy) + bot * fy


def _pow2(n, limit):
    return max(1, min(limit, 1 << max(0, round(math.log2(max(n, 1))))))


def mip_chain(rgba, max_size):
    h, w = rgba.shape[:2]
    img = _resize(np.asarray(rgba, np.float64), _pow2(h, max_size), _pow2(w, max_size))
    mips = [img]
    while len(mips) < 16 and (img.shape[0] > 1 or img.shape[1] > 1):
        img = _halve(img)
        mips.append(img)
    return mips


def write_blp(path, rgba, alpha=False, max_size=512, quality=90):
    """Write a BLP1 JPEG texture with a full mip chain; returns (width, height)."""
    rgba = np.asarray(rgba, np.float64)
    if not alpha:
        rgba = rgba.copy()
        rgba[..., 3] = 1.0
    mips = mip_chain(rgba, max_size)
    tables = jpeg_tables(quality)
    blobs = []
    for m in mips:
        bands = np.clip(np.round(m * 255), 0, 255).astype(np.uint8)[..., [2, 1, 0, 3]]   # BGRA
        blobs.append(jpeg_scan(bands, quality))

    h, w = mips[0].shape[:2]
    head_size = 7 * 4 + 16 * 4 * 2
    offsets, sizes, pos = [], [], head_size + 4 + len(tables)
    for b in blobs:
        offsets.append(pos)
        sizes.append(len(b))
        pos += len(b)
    offsets += [0] * (16 - len(blobs))
    sizes += [0] * (16 - len(blobs))
    with open(path, "wb") as f:
        f.write(b"BLP1" + struct.pack("<6I", 0, 8 if alpha else 0, w, h, 4 if alpha else 5, 1))
        f.write(struct.pack("<16I", *offsets) + struct.pack("<16I", *sizes))
        f.write(struct.pack("<I", len(tables)) + tables)
        for b in blobs:
            f.write(b)
    return w, h
