"""Shared test fixtures. No third-party dependencies at all.

Image fixtures are either written by the pure-python encoders below or
stored as base64 blobs, so the suite runs on a bare Python install
(notably Windows, where Pillow is usually absent).
"""
import base64
import os
import struct
import zlib

# repo root, derived from this file so the suite can live anywhere
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VECTOR_MAIN = '''"""Demo module."""
import math


class Vector:
    def __init__(self, x=0.0, y=0.0):
        self.x, self.y = x, y

    def length(self) -> float:
        return math.hypot(self.x, self.y)


def main():
    v = Vector(3, 4)
    print(f"|v| = {v.length()}")
    return 0


if __name__ == "__main__":
    main()
'''


def make_code_workspace(w):
    """Workspace used by the core/language/runner suite."""
    os.makedirs(os.path.join(w, "src"), exist_ok=True)
    os.makedirs(os.path.join(w, "empty_dir"), exist_ok=True)
    with open(os.path.join(w, "src", "main.py"), "w") as fh:
        fh.write(VECTOR_MAIN)
    with open(os.path.join(w, "README.md"), "w") as fh:
        fh.write("# readme\nsearchable_token here\n")
    with open(os.path.join(w, "notes.txt"), "w") as fh:
        fh.write("searchable_token in text\n")
    with open(os.path.join(w, "blob.bin"), "wb") as fh:
        fh.write(bytes(range(256)) * 12)
    with open(os.path.join(w, "unicode.py"), "w", encoding="utf-8") as fh:
        fh.write('# \u00e9moji \u2728\nx = "\u65e5\u672c\u8a9e"\n')
    with open(os.path.join(w, "big.py"), "w") as fh:
        fh.write("".join("def f_%d():\n    return %d\n" % (i, i)
                         for i in range(4000)))
    return w


def make_fs_workspace(w):
    """Workspace used by the filesystem/context-menu suite."""
    os.makedirs(os.path.join(w, "src"), exist_ok=True)
    with open(os.path.join(w, "src", "a.py"), "w") as fh:
        fh.write("print(1)\n")
    with open(os.path.join(w, "b.txt"), "w") as fh:
        fh.write("b\n")
    return w


# ------------------------------------------------------------------ #
#  Pure-python image encoders (fixtures need no libraries)            #
# ------------------------------------------------------------------ #
def gradient(w, h):
    """Raw RGB bytes: a smooth gradient, easy to eyeball and to compare."""
    out = bytearray(w * h * 3)
    i = 0
    for y in range(h):
        for x in range(w):
            out[i] = (x * 255) // max(1, w)
            out[i + 1] = (y * 255) // max(1, h)
            out[i + 2] = 120
            i += 3
    return bytes(out)


def write_png(path, w, h, rgb):
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = bytearray()
    for y in range(h):                       # filter byte 0 per scanline
        raw.append(0)
        raw += rgb[y * w * 3:(y + 1) * w * 3]
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)
    return path


def write_bmp(path, w, h, rgb):
    row_pad = (-w * 3) % 4
    rows = bytearray()
    for y in range(h - 1, -1, -1):           # BMP is bottom-up
        for x in range(w):
            i = (y * w + x) * 3
            rows += bytes((rgb[i + 2], rgb[i + 1], rgb[i]))   # BGR
        rows += b"\x00" * row_pad
    size = 54 + len(rows)
    hdr = (b"BM" + struct.pack("<IHHI", size, 0, 0, 54)
           + struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0,
                         len(rows), 2835, 2835, 0, 0))
    with open(path, "wb") as fh:
        fh.write(hdr + bytes(rows))
    return path


def write_tga(path, w, h, rgb):
    hdr = bytes((0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0)) + struct.pack(
        "<HHBB", w, h, 24, 0)
    body = bytearray()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            i = (y * w + x) * 3
            body += bytes((rgb[i + 2], rgb[i + 1], rgb[i]))
    with open(path, "wb") as fh:
        fh.write(hdr + bytes(body))
    return path


def write_ppm(path, w, h, rgb):
    with open(path, "wb") as fh:
        fh.write(b"P6\n%d %d\n255\n" % (w, h) + rgb)
    return path


# ------------------------------------------------------------------ #
#  Encoded blobs for formats we cannot write by hand                  #
# ------------------------------------------------------------------ #
JPEG_64x48 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8S"
    "EhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJCIeJBweHx7/2wBDAQUFBQcGBw4ICA4eFBEU"
    "Hh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh7/wAAR"
    "CAAwAEADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAA"
    "AgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
    "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWG"
    "h4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl"
    "5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYk"
    "NOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
    "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk"
    "5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD5fgsfatCCx9q2ILH/AGa0ILHpxX6HVxp5"
    "mAzDbUxoLHpxV+Cx9q2YLH/Zq/BY+1edVxp9pgMw21MeCx9qvwWPTitiCx9q0ILH/ZrzquNP"
    "s8BmG2pjQWPtV+Cx6cVswWPTir8Fj/s15tXGn2eAzDbU88gsfar8Fj/s1swWP+zV+Cx6cVvV"
    "xp/FmAzDbUx4LHpxV+Cx9q2YLH/Zq/BY+1edVxp9ngMw21MaCx6cVoQWPTitiCx/2a0ILH2r"
    "zquNPtMBmG2pjQWPtV+Cx6cVswWPtV+Cx/2a82rjT7PAZhtqeeQWPtV+Cx9q2YLH/Zq/BY9O"
    "K3q40/izAZhtqY8Fj04q/BY+1bMFj/s1fgsenFedVxp9ngMw21MaCx6cVoQWPtWxBY/7NX4L"
    "H2rzquNPtMBmG2pjwWPtV+Cx6cVswWP+zV+Cx9q82rjT7PAZhtqf/9k="
)

GIF_64x48 = (
    "R0lGODdhQAAwAIcAAPP0ePPpeOHxePPfeOHfeM/0eL/0eMnpeM/feL/fePPPePPEeOHMeOu8"
    "eM/PeL/PeMnEeMm8eK/0eK/peJ3xeI30eH/0eIfpeK/feJ3feI3feH/feK/PeK/EeJ3MeKe8"
    "eI3PeH/PeIfEeIe8ePOvePOkeOGsePOaeOGaeM+veL+veMmkeM+aeL+aePOKeOGKeOt9eM+K"
    "eL+KeMl9eK+veK+keJ2seI2veH+veIekeK+aeJ2aeI2aeH+aeK+KeJ2KeKd9eI2KeH+KeId9"
    "eG/0eG/peF3xeE30eD/0eEfpeG/feF3feE3feD/feC/0eB/0eCnpeBH0eAP0eAvpeC/feB/f"
    "eBHfeAPfeG/PeG/EeF3MeGe8eE3PeD/PeEfEeEe8eC/PeB/PeCnEeCm8eBHPeAPPeAvEeAu8"
    "eG+veG+keF2seE2veD+veEekeG+aeF2aeE2aeD+aeG+KeF2KeGd9eE2KeD+KeEd9eC+veB+v"
    "eCmkeBGveAOveAukeC+aeB+aeBGaeAOaeC+KeB+KeCl9eBGKeAOKeAt9ePNvePNkeOFsePNa"
    "eOFaeM9veL9veMlkeM9aeL9aePNKeOFKeOs9eM9KeL9KeMk9eK9veK9keJ1seI1veH9veIdk"
    "eK9aeJ1aeI1aeH9aeK9KeJ1KeKc9eI1KeH9KeIc9ePMvePMleOEteOsdeM8veL8veMkleMkd"
    "ePMPeOEPeOsDeM8PeL8PeMkDeK8veK8leJ0teKcdeI0veH8veIcleIcdeK8PeJ0PeKcDeI0P"
    "eH8PeIcDeG9veG9keF1seE1veD9veEdkeG9aeF1aeE1aeD9aeG9KeF1KeGc9eE1KeD9KeEc9"
    "eC9veB9veClkeBFveANveAtkeC9aeB9aeBFaeANaeC9KeB9KeCk9eBFKeANKeAs9eG8veG8l"
    "eF0teGcdeE0veD8veEcleEcdeG8PeF0PeGcDeE0PeD8PeEcDeC8veB8veCkleCkdeBEveAMv"
    "eAsleAsdeC8PeB8PeCkDeBEPeAMPeAsDeCwAAAAAQAAwAEAI/wD/CRz4j5/BgwbjKVwYr527"
    "hxAfDptIcdgvYBgzYqzFsSPHWLJCigx5ryQ+eyjnqaRHT57LdDDVoZtprqY5cjhx7trJS5dP"
    "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"
)

WEBP_16x12 = (
    "UklGRkwAAABXRUJQVlA4IEAAAACwAQCdASoQAAwAAoBCJbACdAEOtW9oAP75Un1YnAJxc9bd"
    "ukR36yBmQh4tZzmZp9XWS41/qiuNf/309n7PyAAA"
)

TIFF_16x12 = (
    "SUkqAAgAAAAKAAABBAABAAAAEAAAAAEBBAABAAAADAAAAAIBAwADAAAAhgAAAAMBAwABAAAA"
    "AQAAAAYBAwABAAAAAgAAABEBBAABAAAAjAAAABUBAwABAAAAAwAAABYBBAABAAAADAAAABcB"
    "BAABAAAAQAIAABwBAwABAAAAAQAAAAAAAAAIAAgACAAAAHgPAHgfAHgvAHg/AHhPAHhfAHhv"
    "AHh/AHiPAHifAHivAHi/AHjPAHjfAHjvAHgAFXgPFXgfFXgvFXg/FXhPFXhfFXhvFXh/FXiP"
    "FXifFXivFXi/FXjPFXjfFXjvFXgAKngPKngfKngvKng/KnhPKnhfKnhvKnh/KniPKnifKniv"
    "Kni/KnjPKnjfKnjvKngAP3gPP3gfP3gvP3g/P3hPP3hfP3hvP3h/P3iPP3ifP3ivP3i/P3jP"
    "P3jfP3jvP3gAVXgPVXgfVXgvVXg/VXhPVXhfVXhvVXh/VXiPVXifVXivVXi/VXjPVXjfVXjv"
    "VXgAangPangfangvang/anhPanhfanhvanh/aniPanifanivani/anjPanjfanjvangAf3gP"
    "f3gff3gvf3g/f3hPf3hff3hvf3h/f3iPf3iff3ivf3i/f3jPf3jff3jvf3gAlHgPlHgflHgv"
    "lHg/lHhPlHhflHhvlHh/lHiPlHiflHivlHi/lHjPlHjflHjvlHgAqngPqngfqngvqng/qnhP"
    "qnhfqnhvqnh/qniPqnifqnivqni/qnjPqnjfqnjvqngAv3gPv3gfv3gvv3g/v3hPv3hfv3hv"
    "v3h/v3iPv3ifv3ivv3i/v3jPv3jfv3jvv3gA1HgP1Hgf1Hgv1Hg/1HhP1Hhf1Hhv1Hh/1HiP"
    "1Hif1Hiv1Hi/1HjP1Hjf1Hjv1HgA6XgP6Xgf6Xgv6Xg/6XhP6Xhf6Xhv6Xh/6XiP6Xif6Xiv"
    "6Xi/6XjP6Xjf6Xjv6Xg="
)

JPEG420_64x48 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQY"
    "GBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYa"
    "KCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAAR"
    "CAAwAEADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAA"
    "AgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
    "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWG"
    "h4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl"
    "5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYk"
    "NOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
    "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk"
    "5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD56itParsVp7VqRWntV2K09q+wqYk4sLjD"
    "KitParsVp7VqxWntV2K09q454k+kwuMMqK09quxWntWpFae1XYrT2riniT6XC4wyorT2q7Fa"
    "e1asNp7VditPauOpiT6TC4w4eK09quRWntWrFae1XIbT2rWeJP5pwuMMuG06cVditPatSK09"
    "quxWntXHUxJ9JhcYZcNp7VcitPatWK09quxWntXFUxJ9LhcYZUVp7VditPatSK09quxWntXH"
    "PEn0uFxhw8Vp7VditPatSK09quxWntWtTEn80YXGGXFae1XIrT2rVitParsVp7VxTxJ9LhcY"
    "ZUVp04q7Fae1akVp7VditPauOeJPpMLjDLitParkVp7VqxWntV2K09q46mJPpcLjD//Z"
)


def write_blob(path, b64):
    with open(path, "wb") as fh:
        fh.write(base64.b64decode("".join(b64.split())))
    return path


def make_image_workspace(w):
    """Every image fixture, built without any third-party package."""
    os.makedirs(w, exist_ok=True)
    rgb = gradient(140, 90)
    write_png(os.path.join(w, "a.png"), 140, 90, rgb)
    write_bmp(os.path.join(w, "a.bmp"), 140, 90, rgb)
    write_tga(os.path.join(w, "a.tga"), 140, 90, rgb)
    write_ppm(os.path.join(w, "a.ppm"), 140, 90, rgb)
    write_blob(os.path.join(w, "a.jpg"), JPEG_64x48)
    write_blob(os.path.join(w, "a420.jpg"), JPEG420_64x48)
    write_blob(os.path.join(w, "a.gif"), GIF_64x48)
    write_blob(os.path.join(w, "a.webp"), WEBP_16x12)
    write_blob(os.path.join(w, "a.tiff"), TIFF_16x12)
    return w


def make_pdf(path, pages, compress=True):
    objs = {}
    n = len(pages)
    kids = " ".join(f"{4 + i * 2} 0 R" for i in range(n))
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode()
    objs[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    for i, txt in enumerate(pages):
        pid, cid = 4 + i * 2, 5 + i * 2
        objs[pid] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 300] "
                     f"/Resources << /Font << /F1 3 0 R >> >> "
                     f"/Contents {cid} 0 R >>").encode()
        body = f"BT /F1 24 Tf 40 200 Td ({txt}) Tj ET\n".encode()
        if compress:
            c = zlib.compress(body)
            objs[cid] = (b"<< /Length " + str(len(c)).encode() +
                         b" /Filter /FlateDecode >>\nstream\n" + c +
                         b"\nendstream")
        else:
            objs[cid] = (b"<< /Length " + str(len(body)).encode() +
                         b" >>\nstream\n" + body + b"\nendstream")
    info = 4 + n * 2
    objs[info] = b"<< /Title (Media Test) >>"
    out = bytearray(b"%PDF-1.4\n")
    offs = {}
    for num in sorted(objs):
        offs[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
    xref = len(out)
    top = max(objs) + 1
    out += f"xref\n0 {top}\n".encode() + b"0000000000 65535 f \n"
    for num in range(1, top):
        out += f"{offs.get(num, 0):010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {top} /Root 1 0 R /Info {info} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    open(path, "wb").write(bytes(out))
