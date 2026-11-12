#!/usr/bin/env python3
"""Generate the S1/S2 spike PDFs.

S1: H row text fields + a JS benchmark that updates every row's value.
S2: Type3 vs Courier character cells, with a tile-like grayscale pattern.

No third-party deps. Run:
    python3 tools/pdf/spike/gen_spikes.py --out build/spike
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from minipdf import PDF, esc, num  # noqa: E402

PAGE_W, PAGE_H = 1280, 768
SCREEN_Y, SCREEN_H = 48, 720
RAMP = " .:-=+*#%@"          # 10 levels, Courier
DIGITS = "0123456789"         # 10 levels, Type3


# ---------------------------------------------------------------- fonts

def base_font(pdf: PDF, name: str) -> int:
    return pdf.add(
        f"<< /Type /Font /Subtype /Type1 /BaseFont /{name} /Encoding /WinAnsiEncoding >>".encode()
    )


def type3_font(pdf: PDF) -> int:
    """10 glyphs, each a 3x3 grid with 0..9 cells filled."""
    glyph_refs = []
    for level in range(10):
        lines = ["1 0 0 0 1 1 d1"]
        for k in range(level):
            i, j = k % 3, k // 3
            lines.append(
                f"{num(i / 3)} {num(j / 3)} {num(1 / 3)} {num(1 / 3)} re f"
            )
        glyph_refs.append(pdf.add_stream("\n".join(lines).encode()))

    charprocs = " ".join(f"/g{i} {r} 0 R" for i, r in enumerate(glyph_refs))
    diffs = " ".join(f"/g{i}" for i in range(10))
    body = (
        f"<< /Type /Font /Subtype /Type3 /Name /Block "
        f"/FontBBox [0 0 1 1] /FontMatrix [1 0 0 1 0 0] "
        f"/CharProcs << {charprocs} >> "
        f"/Encoding << /Type /Encoding /Differences [48 {diffs}] >> "
        f"/FirstChar 48 /LastChar 57 /Widths [1 1 1 1 1 1 1 1 1 1] "
        f"/Resources << >> >>"
    )
    return pdf.add(body.encode())


# ---------------------------------------------------------------- fields

def text_field(pdf: PDF, name: str, rect, value: str, font: str, size: float,
               page_ref: int) -> int:
    r = " ".join(num(v) for v in rect)
    da = f"/{font} {num(size)} Tf 1 1 1 rg"
    body = (
        f"<< /Type /Annot /Subtype /Widget /FT /Tx /T ({esc(name)}) "
        f"/Rect [{r}] /Ff 1 /DA ({esc(da)}) "
        f"/MK << /BG [0 0 0] /BC [] >> /BS << /W 0 >> "
        f"/P {page_ref} 0 R /V ({esc(value)}) >>"
    )
    return pdf.add(body.encode())


def button(pdf: PDF, name: str, rect, caption: str, js: str, page_ref: int) -> int:
    r = " ".join(num(v) for v in rect)
    body = (
        f"<< /Type /Annot /Subtype /Widget /FT /Btn /T ({esc(name)}) "
        f"/Rect [{r}] /Ff 65536 /DA (/Helv 9 Tf 0 0 0 rg) "
        f"/MK << /CA ({esc(caption)}) /BG [0.2 0.2 0.2] /BC [] >> "
        f"/BS << /W 0 >> /P {page_ref} 0 R "
        f"/AA << /U << /S /JavaScript /JS ({esc(js)}) >> >> >>"
    )
    return pdf.add(body.encode())


# ---------------------------------------------------------------- S1

S1_JS = r"""
var D = this;
var H = __H__, W = __W__, TARGET = 120, FONT = "__FONT__", ALPHA = "__ALPHA__";
var CH = [], F = [], inited = false, started = false, f = 0, t0 = 0, setter = 0;
function s1_now() {
  return (typeof Date.now === "function") ? Date.now() : new Date().getTime();
}
function s1_init() {
  if (inited) return;
  inited = true;
  var r, l, x, s;
  for (r = 0; r < H; r++) {
    var n = "r" + (r < 10 ? "00" : (r < 100 ? "0" : "")) + r;
    F[r] = D.getField(n);
  }
  for (l = 0; l < 10; l++) {
    s = "";
    for (x = 0; x < W; x++) s += ALPHA.charAt(l);
    CH[l] = s;
  }
  D.getField("hud").value = "S1 H=" + H + " " + FONT + " - click Start (auto 1s)";
  app.setTimeOut("s1_start()", 1000);
}
function s1_boot() {
  s1_init();
  s1_start();
}
function s1_start() {
  if (started) return;
  started = true; f = 0; setter = 0; t0 = s1_now();
  app.setTimeOut("s1_tick()", 1);
}
function s1_tick() {
  var a = s1_now();
  for (var r = 0; r < H; r++) F[r].value = CH[(r + f) % 10];
  var b = s1_now();
  setter += (b - a);
  f++;
  if (f >= TARGET) {
    var wall = b - t0;
    var avg = wall / TARGET;
    var fps = TARGET * 1000 / wall;
    D.getField("hud").value = "S1 H=" + H + " " + FONT +
      " avg=" + avg.toFixed(2) + "ms fps=" + fps.toFixed(1) +
      " setter=" + (setter / TARGET).toFixed(2) + "ms";
    return;
  }
  app.setTimeOut("s1_tick()", 1);
}
s1_init();
"""


def build_s1(path: str, H: int, font: str, alphabet: str) -> int:
    W = H * 16 // 9          # keep the 16:9 grid: 90->160, 135->240, 180->320
    pdf = PDF()
    t3 = type3_font(pdf) if font == "Block" else None
    cour = base_font(pdf, "Courier")
    helv = base_font(pdf, "Helvetica")

    page_ref = pdf.reserve()
    pages_ref = pdf.reserve()
    cell = SCREEN_H / H

    annots, fields = [], []
    for r in range(H):
        y0 = SCREEN_Y + (H - 1 - r) * cell
        value = alphabet[r % len(alphabet)] * W
        ref = text_field(pdf, f"r{r:03d}", [0, y0, PAGE_W, y0 + cell],
                         value, font, cell, page_ref)
        annots.append(ref)
        fields.append(ref)

    hud = text_field(pdf, "hud", [8, 8, 1000, 40],
                     f"S1 H={H} {font} ready", "Helv", 9, page_ref)
    annots.append(hud); fields.append(hud)

    btn = button(pdf, "btn_start", [1010, 8, 1180, 40], "Start",
                 "s1_boot()", page_ref)
    annots.append(btn); fields.append(btn)

    content = [
        "0 0 0 rg 0 0 1280 768 re f",
        "0.15 0.15 0.15 RG 1 w 0 48 m 1280 48 l S",
    ]
    content.append(
        f"BT /Helv 9 Tf 1 1 1 rg 1010 52 Td ({esc('S1 ' + str(H) + ' ' + font)}) Tj ET"
    )
    content_ref = pdf.add_stream("\n".join(content).encode(), compress=True)

    fonts = f"/Cour {cour} 0 R /Helv {helv} 0 R"
    if t3 is not None:
        fonts += f" /Block {t3} 0 R"
    page = (
        f"<< /Type /Page /Parent {pages_ref} 0 R /MediaBox [0 0 1280 768] "
        f"/Resources << /Font << {fonts} >> >> /Contents {content_ref} 0 R "
        f"/Annots [{' '.join(f'{r} 0 R' for r in annots)}] >>"
    )
    pdf.set(page_ref, page.encode())
    pdf.set(pages_ref, f"<< /Type /Pages /Kids [{page_ref} 0 R] /Count 1 >>".encode())

    dr = f"/Font << /Cour {cour} 0 R /Helv {helv} 0 R"
    if t3 is not None:
        dr += f" /Block {t3} 0 R"
    dr += " >>"
    acro = (
        f"<< /Fields [{' '.join(f'{r} 0 R' for r in fields)}] "
        f"/DR << {dr} >> /NeedAppearances true >>"
    )
    acro_ref = pdf.add(acro.encode())

    js = (S1_JS.replace("__H__", str(H))
                .replace("__W__", str(W))
                .replace("__FONT__", font)
                .replace("__ALPHA__", alphabet))
    js_ref = pdf.add_stream(js.encode(), compress=True)

    cat = (
        f"<< /Type /Catalog /Pages {pages_ref} 0 R /AcroForm {acro_ref} 0 R "
        f"/OpenAction << /S /JavaScript /JS {js_ref} 0 R >> >>"
    )
    cat_ref = pdf.add(cat.encode())

    data = pdf.build(cat_ref)
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


# ---------------------------------------------------------------- S2

def make_pattern(W: int = 160, H: int = 80):
    g = [[0] * W for _ in range(H)]

    def put(x: int, y: int, level: int) -> None:
        if 0 <= x < W and 0 <= y < H:
            g[y][x] = level

    def disk(cx: int, cy: int, r: int, level: int) -> None:
        for y in range(cy - r, cy + r + 1):
            for x in range(cx - r, cx + r + 1):
                if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= r * r:
                    put(x, y, level)

    def line(x0: int, y0: int, x1: int, y1: int, level: int, r: int) -> None:
        n = max(abs(x1 - x0), abs(y1 - y0), 1)
        for i in range(n + 1):
            x = x0 + (x1 - x0) * i // n
            y = y0 + (y1 - y0) * i // n
            disk(x, y, r, level)

    pts = [(20, 10), (55, 10), (55, 25), (25, 25), (25, 40),
           (70, 40), (70, 55), (35, 55), (35, 70), (80, 70)]

    for a, b in zip(pts, pts[1:]):
        line(a[0], a[1], b[0], b[1], 8, 4)   # outline
    for a, b in zip(pts, pts[1:]):
        line(a[0], a[1], b[0], b[1], 4, 2)   # fill
    for i, (x, y) in enumerate(pts):
        disk(x, y, 1, 9 if i % 2 == 0 else 6)  # twirl / SetSpeed marker

    disk(92, 40, 3, 9)    # pivot planet
    disk(102, 40, 3, 6)   # moving planet
    line(80, 70, 90, 58, 3, 1)
    line(90, 58, 95, 45, 3, 1)
    return g


def build_s2(path: str, font: str) -> int:
    W, H = 160, 80
    alphabet = DIGITS if font == "Block" else RAMP
    rows = ["".join(alphabet[v] for v in row) for row in make_pattern(W, H)]

    pdf = PDF()
    t3 = type3_font(pdf) if font == "Block" else None
    cour = base_font(pdf, "Courier")
    helv = base_font(pdf, "Helvetica")

    page_ref = pdf.reserve()
    pages_ref = pdf.reserve()
    cell = 8

    annots, fields = [], []
    for r, row in enumerate(rows):
        y0 = 48 + (H - 1 - r) * cell
        ref = text_field(pdf, f"r{r:03d}", [0, y0, PAGE_W, y0 + cell],
                         row, font, cell, page_ref)
        annots.append(ref)
        fields.append(ref)

    hud = text_field(pdf, "hud", [8, 8, 1000, 40],
                     f"S2 {font}: top = page text sample, bottom = form fields",
                     "Helv", 9, page_ref)
    annots.append(hud); fields.append(hud)

    fname = "Block" if font == "Block" else "Cour"
    content = [
        "0 0 0 rg 0 0 1280 768 re f",
        "0.15 0.15 0.15 RG 1 w 0 48 m 1280 48 l S",
        f"BT /Helv 9 Tf 1 1 1 rg 10 756 Td ({esc('S2 ' + font + ' - page text sample')}) Tj ET",
    ]
    for i, row in enumerate(rows[8:16]):
        y = 688 + (7 - i) * 8
        content.append(f"BT /{fname} 8 Tf 1 1 1 rg 0 {y} Td ({esc(row)}) Tj ET")
    content_ref = pdf.add_stream("\n".join(content).encode(), compress=True)

    fonts = f"/Cour {cour} 0 R /Helv {helv} 0 R"
    if t3 is not None:
        fonts += f" /Block {t3} 0 R"
    page = (
        f"<< /Type /Page /Parent {pages_ref} 0 R /MediaBox [0 0 1280 768] "
        f"/Resources << /Font << {fonts} >> >> /Contents {content_ref} 0 R "
        f"/Annots [{' '.join(f'{r} 0 R' for r in annots)}] >>"
    )
    pdf.set(page_ref, page.encode())
    pdf.set(pages_ref, f"<< /Type /Pages /Kids [{page_ref} 0 R] /Count 1 >>".encode())

    dr = f"/Font << /Cour {cour} 0 R /Helv {helv} 0 R"
    if t3 is not None:
        dr += f" /Block {t3} 0 R"
    dr += " >>"
    acro = (
        f"<< /Fields [{' '.join(f'{r} 0 R' for r in fields)}] "
        f"/DR << {dr} >> /NeedAppearances true >>"
    )
    acro_ref = pdf.add(acro.encode())

    cat = f"<< /Type /Catalog /Pages {pages_ref} 0 R /AcroForm {acro_ref} 0 R >>"
    cat_ref = pdf.add(cat.encode())

    data = pdf.build(cat_ref)
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/spike")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    jobs = [
        ("s1_courier_160x90.pdf", lambda p: build_s1(p, 90, "Cour", RAMP)),
        ("s1_type3_160x90.pdf", lambda p: build_s1(p, 90, "Block", DIGITS)),
        ("s1_courier_240x135.pdf", lambda p: build_s1(p, 135, "Cour", RAMP)),
        ("s1_courier_320x180.pdf", lambda p: build_s1(p, 180, "Cour", RAMP)),
        ("s2_type3.pdf", lambda p: build_s2(p, "Block")),
        ("s2_courier.pdf", lambda p: build_s2(p, "Cour")),
    ]
    for name, fn in jobs:
        path = os.path.join(args.out, name)
        size = fn(path)
        print(f"{name}\t{size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
