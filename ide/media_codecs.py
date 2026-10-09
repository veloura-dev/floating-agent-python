"""Friday IDE's pure-Python media decoders -- split out of ide.py purely
to keep that file a manageable size, with zero change in behavior.
ide.py still re-exports every name below (decode_bmp/decode_tga/
decode_jpeg/load_image/the pdf_* functions/DecodeError/IMAGE_EXTS/
_TEMP_DIRS/...) by its original name, so nothing outside this pair of
files needed to change.

Tk 8.6 (the only GUI toolkit this project depends on -- see ide.py's own
module docstring on staying stdlib-only) can only natively decode PNG/
GIF/PPM image data. Everything else the Explorer/editor can preview
(BMP, TGA, JPEG, and PDF pages) is decoded by hand, right here, in pure
Python with no third-party imaging library required -- Pillow (and a
handful of external command-line converters/PDF renderers) are used
*if* they happen to already be installed, strictly as a quality/speed
upgrade, never as a hard requirement. See load_image()'s own docstring
for the exact fallback order.

Self-contained on purpose: nothing in this file depends on anything else
in ide.py (no design-system colors, no widget classes, no app state) --
just the Python standard library plus whichever bytes it's handed to
decode.
"""

import atexit
import math
import os
import re
import shutil
import struct
import subprocess
import tkinter as tk
import zlib

# ------------------------------------------------------------------ #
#  Image decoding (pure python; Tk 8.6 only reads PNG/GIF/PPM)        #
# ------------------------------------------------------------------ #


class DecodeError(Exception):
    pass


# ------------------------------------------------------------------ #
#  BMP                                                                #
# ------------------------------------------------------------------ #
def decode_bmp(raw):
    if raw[:2] != b"BM":
        raise DecodeError("not a BMP")
    off = struct.unpack_from("<I", raw, 10)[0]
    hdr = struct.unpack_from("<I", raw, 14)[0]
    if hdr == 12:
        w, h = struct.unpack_from("<hh", raw, 18)
        bpp = struct.unpack_from("<H", raw, 24)[0]
        compression, ncolors = 0, 0
    else:
        w, h = struct.unpack_from("<ii", raw, 18)
        bpp = struct.unpack_from("<H", raw, 28)[0]
        compression = struct.unpack_from("<I", raw, 30)[0]
        ncolors = struct.unpack_from("<I", raw, 46)[0]
    if compression not in (0, 3):
        raise DecodeError("unsupported BMP compression %d" % compression)
    top_down = h < 0
    h = abs(h)
    pal = []
    if bpp <= 8:
        n = ncolors or (1 << bpp)
        psize = 3 if hdr == 12 else 4
        base = 14 + hdr
        for i in range(n):
            chunk = raw[base + i * psize:base + i * psize + 3]
            if len(chunk) < 3:
                break
            b, g, r = chunk
            pal.append((r, g, b))
    row_bytes = ((bpp * w + 31) // 32) * 4
    out = bytearray(w * h * 3)
    for y in range(h):
        src = off + y * row_bytes
        row = raw[src:src + row_bytes]
        if len(row) < row_bytes:
            break
        dst_y = y if top_down else (h - 1 - y)
        o = dst_y * w * 3
        if bpp == 24:
            for x in range(w):
                b, g, r = row[x * 3:x * 3 + 3]
                out[o] = r
                out[o + 1] = g
                out[o + 2] = b
                o += 3
        elif bpp == 32:
            for x in range(w):
                b, g, r = row[x * 4:x * 4 + 3]
                out[o] = r
                out[o + 1] = g
                out[o + 2] = b
                o += 3
        elif bpp == 8:
            for x in range(w):
                r, g, b = pal[row[x]]
                out[o] = r
                out[o + 1] = g
                out[o + 2] = b
                o += 3
        elif bpp == 4:
            for x in range(w):
                v = row[x >> 1]
                r, g, b = pal[(v >> 4) if not (x & 1) else (v & 15)]
                out[o] = r
                out[o + 1] = g
                out[o + 2] = b
                o += 3
        elif bpp == 1:
            for x in range(w):
                r, g, b = pal[(row[x >> 3] >> (7 - (x & 7))) & 1]
                out[o] = r
                out[o + 1] = g
                out[o + 2] = b
                o += 3
        elif bpp == 16:
            for x in range(w):
                v = struct.unpack_from("<H", row, x * 2)[0]
                out[o] = ((v >> 10) & 31) << 3
                out[o + 1] = ((v >> 5) & 31) << 3
                out[o + 2] = (v & 31) << 3
                o += 3
        else:
            raise DecodeError("unsupported BMP depth %d" % bpp)
    return w, h, bytes(out)


# ------------------------------------------------------------------ #
#  TGA                                                                #
# ------------------------------------------------------------------ #
def decode_tga(raw):
    idlen, imgtype = raw[0], raw[2]
    w, h = struct.unpack_from("<HH", raw, 12)
    bpp, desc = raw[16], raw[17]
    if imgtype not in (2, 10) or bpp not in (24, 32):
        raise DecodeError("unsupported TGA")
    p = 18 + idlen
    step = bpp // 8
    need = w * h * step
    if imgtype == 2:
        px = raw[p:p + need]
    else:
        buf = bytearray()
        while len(buf) < need and p < len(raw):
            pk = raw[p]
            p += 1
            n = (pk & 0x7F) + 1
            if pk & 0x80:
                buf += raw[p:p + step] * n
                p += step
            else:
                buf += raw[p:p + n * step]
                p += n * step
        px = bytes(buf)
    out = bytearray(w * h * 3)
    flip = not (desc & 0x20)
    for y in range(h):
        sy = (h - 1 - y) if flip else y
        i = sy * w * step
        o = y * w * 3
        for _x in range(w):
            out[o] = px[i + 2]
            out[o + 1] = px[i + 1]
            out[o + 2] = px[i]
            i += step
            o += 3
    return w, h, bytes(out)


# ------------------------------------------------------------------ #
#  Baseline JPEG                                                      #
# ------------------------------------------------------------------ #
ZIGZAG = (
    0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5,
    12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63)

_COS = [[0.0] * 8 for _ in range(8)]
for _u in range(8):
    _cu = (1.0 / math.sqrt(2)) if _u == 0 else 1.0
    for _x in range(8):
        _COS[_u][_x] = 0.5 * _cu * math.cos((2 * _x + 1) * _u * math.pi / 16)


class _Huff:
    __slots__ = ("lookup",)

    def __init__(self, bits, vals):
        self.lookup = {}
        code = 0
        k = 0
        for length in range(1, 17):
            for _ in range(bits[length - 1]):
                self.lookup[(length, code)] = vals[k]
                k += 1
                code += 1
            code <<= 1


class _BitReader:
    __slots__ = ("d", "p", "b", "n")

    def __init__(self, data, pos):
        self.d = data
        self.p = pos
        self.b = 0
        self.n = 0

    def bit(self):
        if self.n == 0:
            if self.p >= len(self.d):
                return 0
            c = self.d[self.p]
            self.p += 1
            if c == 0xFF:
                nxt = self.d[self.p] if self.p < len(self.d) else 0
                if nxt == 0:
                    self.p += 1
                else:
                    return 0
            self.b = c
            self.n = 8
        self.n -= 1
        return (self.b >> self.n) & 1

    def bits(self, n):
        v = 0
        for _ in range(n):
            v = (v << 1) | self.bit()
        return v

    def decode(self, table):
        code = 0
        lk = table.lookup
        for length in range(1, 17):
            code = (code << 1) | self.bit()
            v = lk.get((length, code))
            if v is not None:
                return v
        raise DecodeError("bad huffman code")

    def receive_extend(self, s):
        if s == 0:
            return 0
        v = self.bits(s)
        if v < (1 << (s - 1)):
            v -= (1 << s) - 1
        return v

    def align(self):
        self.n = 0


def _idct8(blk, out):
    tmp = [0.0] * 64
    for y in range(8):
        base = y * 8
        row = blk[base:base + 8]
        if row[1] == 0 and row[2] == 0 and row[3] == 0 and row[4] == 0 \
                and row[5] == 0 and row[6] == 0 and row[7] == 0:
            v = row[0] * 0.5 * (1.0 / math.sqrt(2))
            for x in range(8):
                tmp[base + x] = v
            continue
        for x in range(8):
            s = 0.0
            for u in range(8):
                c = row[u]
                if c:
                    s += _COS[u][x] * c
            tmp[base + x] = s
    for x in range(8):
        col = [tmp[v * 8 + x] for v in range(8)]
        for y in range(8):
            s = 0.0
            for v in range(8):
                c = col[v]
                if c:
                    s += _COS[v][y] * c
            val = int(s + 128.5)
            out[y * 8 + x] = 0 if val < 0 else (255 if val > 255 else val)


def decode_jpeg(raw, dc_only_above=2_500_000):
    """Decode a baseline JPEG. Very large images decode DC-only (1/8 scale)
    so that a preview still appears quickly in pure python."""
    if raw[:2] != b"\xff\xd8":
        raise DecodeError("not a JPEG")
    qt, huff_dc, huff_ac = {}, {}, {}
    frame = None
    restart = 0
    p = 2
    while p < len(raw) - 1:
        if raw[p] != 0xFF:
            p += 1
            continue
        marker = raw[p + 1]
        p += 2
        if marker in (0xD8, 0x01, 0xFF) or 0xD0 <= marker <= 0xD7:
            continue
        if marker == 0xD9:
            break
        if p + 2 > len(raw):
            break
        seglen = struct.unpack_from(">H", raw, p)[0]
        seg = raw[p + 2:p + seglen]
        if marker == 0xDB:
            i = 0
            while i < len(seg):
                pq, tq = seg[i] >> 4, seg[i] & 15
                i += 1
                tbl = [0] * 64
                for k in range(64):
                    if pq:
                        tbl[ZIGZAG[k]] = struct.unpack_from(">H", seg, i)[0]
                        i += 2
                    else:
                        tbl[ZIGZAG[k]] = seg[i]
                        i += 1
                qt[tq] = tbl
        elif marker in (0xC0, 0xC1):
            h, w = struct.unpack_from(">HH", seg, 1)
            nc = seg[5]
            comps = []
            for i in range(nc):
                cid = seg[6 + i * 3]
                hv = seg[7 + i * 3]
                tq = seg[8 + i * 3]
                comps.append({"id": cid, "h": hv >> 4, "v": hv & 15, "q": tq})
            frame = {"w": w, "h": h, "comps": comps}
        elif marker == 0xC2:
            raise DecodeError("progressive JPEG is not supported")
        elif marker in (0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB,
                        0xCD, 0xCE, 0xCF):
            raise DecodeError("unsupported JPEG encoding")
        elif marker == 0xC4:
            i = 0
            while i < len(seg):
                tc, th = seg[i] >> 4, seg[i] & 15
                i += 1
                bits = list(seg[i:i + 16])
                i += 16
                n = sum(bits)
                vals = list(seg[i:i + n])
                i += n
                (huff_dc if tc == 0 else huff_ac)[th] = _Huff(bits, vals)
        elif marker == 0xDD:
            restart = struct.unpack_from(">H", seg, 0)[0]
        elif marker == 0xDA:
            ns = seg[0]
            scomps = [(seg[1 + i * 2], seg[2 + i * 2] >> 4,
                       seg[2 + i * 2] & 15) for i in range(ns)]
            return _decode_scan(raw, p + seglen, frame, scomps, qt,
                                huff_dc, huff_ac, restart, dc_only_above)
        p += seglen
    raise DecodeError("no JPEG scan found")


def _decode_scan(raw, pos, frame, scomps, qt, huff_dc, huff_ac, restart,
                 dc_only_above):
    if frame is None:
        raise DecodeError("no JPEG frame header")
    W, H = frame["w"], frame["h"]
    comps = frame["comps"]
    hmax = max(c["h"] for c in comps)
    vmax = max(c["v"] for c in comps)
    mcux = (W + 8 * hmax - 1) // (8 * hmax)
    mcuy = (H + 8 * vmax - 1) // (8 * vmax)
    dc_only = (W * H) > dc_only_above
    step = 1 if dc_only else 8
    for c in comps:
        c["pw"] = mcux * c["h"] * step
        c["ph"] = mcuy * c["v"] * step
        c["data"] = bytearray(c["pw"] * c["ph"])
        c["pred"] = 0
    br = _BitReader(raw, pos)
    blk = [0] * 64
    out8 = [0] * 64
    done = 0
    for my in range(mcuy):
        for mx in range(mcux):
            if restart and done and done % restart == 0:
                br.align()
                while br.p + 1 < len(raw):
                    if raw[br.p] == 0xFF and 0xD0 <= raw[br.p + 1] <= 0xD7:
                        br.p += 2
                        break
                    br.p += 1
                for c in comps:
                    c["pred"] = 0
            for c in comps:
                sc = None
                for s in scomps:
                    if s[0] == c["id"]:
                        sc = s
                        break
                if sc is None:
                    continue
                dtab, atab = huff_dc.get(sc[1]), huff_ac.get(sc[2])
                q = qt[c["q"]]
                for by in range(c["v"]):
                    for bx in range(c["h"]):
                        for i in range(64):
                            blk[i] = 0
                        t = br.decode(dtab)
                        c["pred"] += br.receive_extend(t)
                        blk[0] = c["pred"] * q[0]
                        k = 1
                        while k < 64:
                            rs = br.decode(atab)
                            r, s = rs >> 4, rs & 15
                            if s == 0:
                                if r == 15:
                                    k += 16
                                    continue
                                break
                            k += r
                            if k > 63:
                                break
                            z = ZIGZAG[k]
                            blk[z] = br.receive_extend(s) * q[z]
                            k += 1
                        bxx = mx * c["h"] + bx
                        byy = my * c["v"] + by
                        d = c["data"]
                        pw = c["pw"]
                        if dc_only:
                            v = int(blk[0] / 8.0 + 128.5)
                            d[byy * pw + bxx] = (
                                0 if v < 0 else (255 if v > 255 else v))
                        else:
                            _idct8(blk, out8)
                            base = (byy * 8) * pw + bxx * 8
                            for yy in range(8):
                                o = base + yy * pw
                                d[o:o + 8] = bytes(out8[yy * 8:yy * 8 + 8])
            done += 1
    if dc_only:
        W = max(1, (W + 8 * hmax - 1) // (8 * hmax) * hmax)
        H = max(1, (H + 8 * vmax - 1) // (8 * vmax) * vmax)
    return _to_rgb(comps, W, H, hmax, vmax)


def _to_rgb(comps, W, H, hmax, vmax):
    out = bytearray(W * H * 3)
    if len(comps) == 1:
        c = comps[0]
        d, pw, ph = c["data"], c["pw"], c["ph"]
        for y in range(H):
            sy = min(ph - 1, y * c["v"] // vmax)
            o = y * W * 3
            row = sy * pw
            for x in range(W):
                v = d[row + min(pw - 1, x * c["h"] // hmax)]
                out[o] = v
                out[o + 1] = v
                out[o + 2] = v
                o += 3
        return W, H, bytes(out)
    Y, Cb, Cr = comps[0], comps[1], comps[2]
    dy, db, dr = Y["data"], Cb["data"], Cr["data"]
    pwy, pwb, pwr = Y["pw"], Cb["pw"], Cr["pw"]
    phy, phb, phr = Y["ph"], Cb["ph"], Cr["ph"]
    for y in range(H):
        ry = min(phy - 1, y * Y["v"] // vmax) * pwy
        rb = min(phb - 1, y * Cb["v"] // vmax) * pwb
        rr = min(phr - 1, y * Cr["v"] // vmax) * pwr
        o = y * W * 3
        for x in range(W):
            yv = dy[ry + min(pwy - 1, x * Y["h"] // hmax)]
            cb = db[rb + min(pwb - 1, x * Cb["h"] // hmax)] - 128
            cr = dr[rr + min(pwr - 1, x * Cr["h"] // hmax)] - 128
            r = yv + 1.402 * cr
            g = yv - 0.344136 * cb - 0.714136 * cr
            b = yv + 1.772 * cb
            out[o] = 0 if r < 0 else (255 if r > 255 else int(r))
            out[o + 1] = 0 if g < 0 else (255 if g > 255 else int(g))
            out[o + 2] = 0 if b < 0 else (255 if b > 255 else int(b))
            o += 3
    return W, H, bytes(out)


def to_ppm(w, h, rgb):
    return b"P6\n" + str(w).encode() + b" " + str(h).encode() + b"\n255\n" + rgb


# ------------------------------------------------------------------ #
#  PDF support                                                        #
# ------------------------------------------------------------------ #


# ------------------------------------------------------------------ #
#  Renderer discovery                                                 #
# ------------------------------------------------------------------ #
def _pdf_renderers():
    """All installed candidates, best first."""
    out = []
    if shutil.which("pdftoppm"):
        out.append(("pdftoppm", lambda pdf, page, out, dpi: [
            "pdftoppm", "-png", "-r", str(dpi),
            "-f", str(page), "-l", str(page), pdf, os.path.join(out, "pg")]))
    if shutil.which("mutool"):
        out.append(("mutool", lambda pdf, page, out, dpi: [
            "mutool", "draw", "-o", os.path.join(out, "pg-%d.png"),
            "-r", str(dpi), pdf, str(page)]))
    if shutil.which("magick"):
        out.append(("magick", lambda pdf, page, out, dpi: [
            "magick", "-density", str(dpi), f"{pdf}[{page - 1}]",
            os.path.join(out, "pg-1.png")]))
    if shutil.which("gs"):
        out.append(("ghostscript", lambda pdf, page, out, dpi: [
            "gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m",
            f"-r{dpi}", f"-dFirstPage={page}", f"-dLastPage={page}",
            "-sOutputFile=" + os.path.join(out, "pg-1.png"), pdf]))
    if shutil.which("sips"):
        out.append(("sips", lambda pdf, page, out, dpi: [
            "sips", "-s", "format", "png", pdf,
            "--out", os.path.join(out, "pg-1.png")]))
    return out


_PDF_WORKING = []          # cache: renderers proven to handle PDFs here


def pdf_find_renderer():
    """Name of the renderer that works, or None. Result is cached."""
    if _PDF_WORKING:
        return _PDF_WORKING[0][0], _PDF_WORKING[0][1]
    cands = _pdf_renderers()
    return (cands[0][0], cands[0][1]) if cands else (None, None)


def pdf_render_page(path, page, outdir, dpi=110):
    """Render one 1-based page to a PNG. Returns the path, or None.

    Each candidate is actually executed; a tool that is installed but
    cannot render PDFs (ImageMagick without Ghostscript) is skipped.
    """
    cands = _PDF_WORKING or _pdf_renderers()
    for name, build in cands:
        for f in os.listdir(outdir):
            try:
                os.remove(os.path.join(outdir, f))
            except OSError:
                pass
        try:
            subprocess.run(build(path, page, outdir, dpi), check=True,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=60)
        except Exception:  # noqa: BLE001
            continue
        pngs = sorted(f for f in os.listdir(outdir)
                      if f.lower().endswith(".png"))
        pngs = [p for p in pngs
                if os.path.getsize(os.path.join(outdir, p)) > 100]
        if pngs:
            if not _PDF_WORKING:
                _PDF_WORKING.append((name, build))
            return os.path.join(outdir, pngs[0])
    return None


# ------------------------------------------------------------------ #
#  Minimal PDF parsing (page count, pdf_metadata, text)                   #
# ------------------------------------------------------------------ #
def pdf_page_count(raw):
    counts = [int(m.group(1)) for m in
              re.finditer(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)", raw, re.S)]
    if not counts:
        counts = [int(m.group(1)) for m in
                  re.finditer(rb"/Count\s+(\d+)", raw)]
    if counts:
        return max(counts)
    n = len(re.findall(rb"/Type\s*/Page\b", raw))
    return max(1, n)


def pdf_version(raw):
    m = re.match(rb"%PDF-(\d+\.\d+)", raw[:32])
    return m.group(1).decode() if m else "?"


def pdf_is_encrypted(raw):
    return b"/Encrypt" in raw[:4096] or bool(re.search(rb"/Encrypt\s+\d+\s+\d+\s+R", raw))


def pdf_metadata(raw):
    out = {}
    for key in ("Title", "Author", "Subject", "Creator", "Producer"):
        m = re.search(rb"/" + key.encode() + rb"\s*\((.*?)(?<!\\)\)", raw, re.S)
        if m:
            try:
                val = _pdf_unescape(m.group(1)).decode("utf-8", "replace").strip()
            except Exception:  # noqa: BLE001
                continue
            if val:
                out[key] = val
    return out


def _pdf_unescape(b):
    out = bytearray()
    i = 0
    while i < len(b):
        c = b[i]
        if c == 0x5C and i + 1 < len(b):
            nxt = b[i + 1]
            mapping = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
            if nxt in mapping:
                out.append(mapping[nxt])
                i += 2
                continue
            if 0x30 <= nxt <= 0x37:
                j = i + 1
                oct_digits = b""
                while j < len(b) and len(oct_digits) < 3 and 0x30 <= b[j] <= 0x37:
                    oct_digits += bytes([b[j]])
                    j += 1
                out.append(int(oct_digits, 8) & 0xFF)
                i = j
                continue
            out.append(nxt)
            i += 2
            continue
        out.append(c)
        i += 1
    return bytes(out)


def _pdf_streams(raw):
    """Yield decompressed content streams."""
    for m in re.finditer(rb"(?<!end)stream\r?\n", raw):
        start = m.end()
        end = raw.find(b"endstream", start)
        if end < 0:
            continue
        data = raw[start:end]
        head = raw[max(0, m.start() - 600):m.start()]
        if b"/Image" in head or b"/DCTDecode" in head or b"/JPXDecode" in head:
            continue
        if b"FlateDecode" in head:
            for trim in (data, data.rstrip(b"\r\n")):
                try:
                    yield zlib.decompress(trim)
                    break
                except zlib.error:
                    try:
                        yield zlib.decompressobj().decompress(trim)
                        break
                    except zlib.error:
                        continue
        elif b"/Filter" not in head:
            yield data


_TJ = re.compile(rb"\[(.*?)\]\s*TJ", re.S)
_TJ_ONE = re.compile(rb"\((.*?)(?<!\\)\)\s*(?:Tj|')", re.S)
_STR = re.compile(rb"\((.*?)(?<!\\)\)", re.S)
_TD = re.compile(rb"(?:T\*|Td|TD|TL)")


def pdf_extract_text(raw, max_chars=400_000):
    """Best-effort text extraction. Returns (text, had_streams)."""
    chunks = []
    found = False
    total = 0
    for stream in _pdf_streams(raw):
        if b"BT" not in stream and b"Tj" not in stream and b"TJ" not in stream:
            continue
        found = True
        # walk the stream keeping line breaks roughly intact
        pos = 0
        line = []
        for m in re.finditer(
                rb"\[(?:.*?)\]\s*TJ|\((?:.*?)(?<!\\)\)\s*(?:Tj|')|T\*|Td|TD|ET",
                stream, re.S):
            tok = m.group(0)
            if tok in (b"T*", b"ET") or tok.endswith(b"Td") or tok.endswith(b"TD"):
                if line:
                    chunks.append("".join(line))
                    line = []
                continue
            pieces = _STR.findall(tok)
            for p in pieces:
                try:
                    line.append(_pdf_unescape(p).decode("utf-8", "replace"))
                except Exception:  # noqa: BLE001
                    pass
            pos = m.end()
        if line:
            chunks.append("".join(line))
        total = sum(len(c) for c in chunks)
        if total > max_chars:
            break
    text = "\n".join(c for c in chunks if c.strip())
    return text, found


def pdf_summary(path):
    """Human-readable description used when nothing can be rendered."""
    with open(path, "rb") as fh:
        raw = fh.read()
    lines = [f"PDF {pdf_version(raw)}  -  {pdf_page_count(raw)} page(s)"]
    meta = pdf_metadata(raw)
    for k, v in meta.items():
        lines.append(f"{k}: {v}")
    return "\n".join(lines), raw


_TEMP_DIRS = []


def _cleanup_temp_dirs():
    """Remove scratch directories; also runs at interpreter exit."""
    while _TEMP_DIRS:
        d = _TEMP_DIRS.pop()
        shutil.rmtree(d, ignore_errors=True)


atexit.register(_cleanup_temp_dirs)


IMAGE_EXTS = {
    # decoded natively by Tk
    "png", "gif", "ppm", "pgm", "pbm", "pnm",
    # decoded by the pure-python decoders above
    "jpg", "jpeg", "jpe", "jfif", "bmp", "dib", "tga",
    # handled by Pillow or an external converter when present
    "webp", "tif", "tiff", "ico", "avif", "heic", "heif", "jp2",
    "psd", "xcf", "exr", "dds", "pcx", "svgz",
}


def _tk_photo_from_rgb(w, h, rgb):
    """Tk accepts a raw PPM payload, so no temp file is needed."""
    return tk.PhotoImage(data=to_ppm(w, h, rgb))


def load_image(path):
    """-> (PhotoImage, width, height, note). Raises DecodeError."""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    # 1. Tk's own decoders (PNG/GIF/PPM family) - fastest path
    if ext in ("png", "gif", "ppm", "pgm", "pbm", "pnm"):
        try:
            img = tk.PhotoImage(file=path)
            return img, img.width(), img.height(), ""
        except Exception:  # noqa: BLE001
            pass
    with open(path, "rb") as fh:
        raw = fh.read()
    # 2. pure-python decoders - work with no dependencies at all
    try:
        if ext in ("bmp", "dib") or raw[:2] == b"BM":
            w, h, rgb = decode_bmp(raw)
            return _tk_photo_from_rgb(w, h, rgb), w, h, "BMP"
        if ext == "tga":
            w, h, rgb = decode_tga(raw)
            return _tk_photo_from_rgb(w, h, rgb), w, h, "TGA"
        if ext in ("jpg", "jpeg", "jpe", "jfif") or raw[:2] == b"\xff\xd8":
            w, h, rgb = decode_jpeg(raw)
            note = ""
            hdr = _jpeg_size(raw)
            if hdr and hdr[0] > w:
                note = f"1/8 preview of {hdr[0]}x{hdr[1]}"
            return _tk_photo_from_rgb(w, h, rgb), w, h, note
    except DecodeError as ex:
        first_error = str(ex)
    except Exception as ex:  # noqa: BLE001
        first_error = str(ex)
    else:
        first_error = ""
    # 3. Pillow, if the user happens to have it
    try:
        from PIL import Image  # noqa: PLC0415
        im = Image.open(path)
        im = im.convert("RGB")
        w, h = im.size
        return _tk_photo_from_rgb(w, h, im.tobytes()), w, h, "via Pillow"
    except ImportError:
        pass
    except Exception:  # noqa: BLE001
        pass
    # 4. an external converter, if one is installed
    conv = _image_converter()
    if conv:
        import tempfile  # noqa: PLC0415
        tmp = os.path.join(tempfile.mkdtemp(prefix="idev"), "c.ppm")
        try:
            subprocess.run(conv(path, tmp), check=True, timeout=60,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            img = tk.PhotoImage(file=tmp)
            return img, img.width(), img.height(), "via converter"
        except Exception:  # noqa: BLE001
            pass
    raise DecodeError(first_error or f".{ext} is not supported")


def _jpeg_size(raw):
    """(w, h) from the JPEG frame header, without decoding pixels."""
    i = 2
    while i < len(raw) - 9:
        if raw[i] != 0xFF:
            i += 1
            continue
        m = raw[i + 1]
        if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9,
                 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack_from(">HH", raw, i + 5)
            return w, h
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        try:
            i += 2 + struct.unpack_from(">H", raw, i + 2)[0]
        except Exception:  # noqa: BLE001
            return None
    return None


def _image_converter():
    for exe in ("magick", "convert", "gm", "sips"):
        if shutil.which(exe):
            if exe == "sips":
                return lambda src, dst: [
                    "sips", "-s", "format", "png", src, "--out", dst]
            if exe == "gm":
                return lambda src, dst: ["gm", "convert", src, dst]
            return lambda src, dst, e=exe: [e, src, dst]
    return None


