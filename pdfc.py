#!/usr/bin/env python3
"""pdfc.py —— ADOPDF 编译入口（ADR: docs/ARCHITECTURE.md §3）。

    python3 pdfc.py level.adofai -o out.pdf [选项]

职责：
  1. 校验输入（只收明文 .adofai）；
  2. 首次运行按源文件哈希编译 tools/pdf/native/chart2pdf，之后复用；
  3. 运行它拿到 scene.bin；
  4. 把 scene 写进单页 PDF：90 行字符字段 + HUD + 3 个按钮 + PDF JS。

只用标准库。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

ROOT = os.path.dirname(os.path.abspath(__file__))
NATIVE_DIR = os.path.join(ROOT, "tools", "pdf", "native")
THIRD_PARTY = os.path.join(ROOT, "tools", "pdf", "third_party")
BUILD_DIR = os.path.join(ROOT, "build")
ADOCAO_ROOT = os.environ.get("ADOCAO_ROOT", os.path.join(os.path.dirname(ROOT), "ADOCAO"))

RAMP = " .:-=+*#%@"
DIGIT_RAMP = "0123456789"  # Type3 后端用：编码必须是连续码 48..57（S1 验证过的组合）
# 页面：上方 24pt 边距 + 1280x720 字符屏（严格 16:9）+ 60pt 控制栏
PAGE_W, PAGE_H = 1280, 816
SCREEN_Y, SCREEN_H = 72, 720
RAIL_Y0, RAIL_Y1 = 12, 52
RAIL_LINE_Y = 62

SCENE_MAGIC = b"ADPF"
SCENE_VERSION = 2
SCENE_HEADER_SIZE = 45  # 见 tools/pdf/native/scene_format.h

# chart2pdf 需要链接的 ADOCAO core 闭包（与 docs/ARCHITECTURE.md §2.1 对应；
# 实际仓库里没有 CameraDirector/CameraTimeline，相机在 chart2pdf 内按 GameWindow 的
# 行为实现，见 docs/DECISIONS.md D11）
ADOCAO_SOURCES = [
    "core/level/LevelData.cpp",
    "core/level/FloorWindow.cpp",
    "core/level/ByteSource.cpp",
    "core/level/LevelPath.cpp",
    "core/level/JsonCleaner.cpp",
    "core/level/TileColor.cpp",
    "core/util/Logger.cpp",
    "core/util/Progress.cpp",
    "core/util/Scheduler.cpp",
    "core/util/Easing.cpp",
    "core/util/MappedFile.cpp",
    "core/timeline/Timeline.cpp",
    "core/timeline/Keyframes.cpp",
    "core/timeline/TileAnimation.cpp",
    "core/timeline/PositionSolver.cpp",
    "core/camera/CameraTimeline.cpp",
    "core/camera/CameraDirector.cpp",
    "render/TileGeometryReference.cpp",
]

# 只对 ADOCAO 的既有代码放宽这几条（它们不是本项目代码）；chart2pdf 本身仍走 -Werror。
ADOCAO_SUPPRESS = [
    "-Wno-unused-parameter",
    "-Wno-unused-variable",
    "-Wno-misleading-indentation",
    "-Wno-array-bounds",        # GCC 16 -O2 在 std::sort 内联里报的假阳性（int[8] 下标）
]


class BuildError(RuntimeError):
    pass


# ---------------------------------------------------------------- scene.bin


def parse_scene(path: str) -> dict:
    """读 scene.bin 的头 + 偏移表。帧体按需解码（见 decode_frame）。"""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < SCENE_HEADER_SIZE:
        raise ValueError("scene.bin 太短")
    if data[:4] != SCENE_MAGIC:
        raise ValueError(f"scene.bin magic 不对: {data[:4]!r}")
    (version, mode, w, h, fps, frame_count) = struct.unpack_from("<HBHHHI", data, 4)
    if version != SCENE_VERSION:
        raise ValueError(f"scene.bin 版本不支持: {version}")
    (t_start, t_end) = struct.unpack_from("<dd", data, 17)
    (zoom_scale, tile_count, base_bpm) = struct.unpack_from("<fIf", data, 33)
    off_end = SCENE_HEADER_SIZE + 4 * frame_count
    if len(data) < off_end:
        raise ValueError("scene.bin 偏移表被截断")
    offsets = list(struct.unpack_from(f"<{frame_count}I", data, SCENE_HEADER_SIZE))
    return {
        "mode": mode,
        "width": w,
        "height": h,
        "fps": fps,
        "frame_count": frame_count,
        "t_start": t_start,
        "t_end": t_end,
        "zoom_scale": zoom_scale,
        "tile_count": tile_count,
        "base_bpm": base_bpm,
        "offsets": offsets,
        "data_start": off_end,
        "raw": data,
    }


def decode_frame(scene: dict, k: int) -> dict:
    """解一帧，返回 {t, tile, bpm, cam, zoom, hud, rows}。rows 是 90 个 level 列表。"""
    raw = scene["raw"]
    off = scene["data_start"] + scene["offsets"][k]
    (t, tile, bpm, cam_x, cam_y, zoom) = struct.unpack_from("<fHffff", raw, off + 0)
    hud_len = raw[off + 22]
    hud = raw[off + 23:off + 23 + hud_len].decode("ascii", "replace")
    p = off + 23 + hud_len
    h = scene["height"]
    rows = []
    for _ in range(h):
        runs = raw[p] | (raw[p + 1] << 8)
        p += 2
        row = []
        for _ in range(runs):
            level, count = raw[p], raw[p + 1]
            p += 2
            row.extend([level] * count)
        rows.append(row)
    return {"t": t, "tile": tile, "bpm": bpm, "cam": (cam_x, cam_y),
            "zoom": zoom, "hud": hud, "rows": rows}


def rle_encode_row(levels) -> bytes:
    """行 -> (level,count) 对；供单测与外部工具复用。"""
    out = bytearray()
    i = 0
    n = len(levels)
    while i < n:
        lv = levels[i]
        j = 1
        while i + j < n and levels[i + j] == lv and j < 255:
            j += 1
        out += bytes((lv, j))
        i += j
    return bytes(out)


def rle_decode_row(buf: bytes):
    out = []
    for i in range(0, len(buf), 2):
        out.extend([buf[i]] * buf[i + 1])
    return out


# ---------------------------------------------------------------- 编译 chart2pdf


def _sources_fingerprint() -> str:
    h = hashlib.sha256()
    files = [os.path.join(NATIVE_DIR, "chart2pdf.cpp"),
             os.path.join(NATIVE_DIR, "scene_format.h")]
    files += [os.path.join(ADOCAO_ROOT, s) for s in ADOCAO_SOURCES]
    for f in files:
        h.update(os.path.basename(f).encode())
        try:
            with open(f, "rb") as fh:
                h.update(fh.read())
        except OSError as e:
            raise BuildError(f"缺少源文件: {f} ({e})")
    return h.hexdigest()[:16]


def _exe_path() -> str:
    return os.path.join(BUILD_DIR, "chart2pdf.exe" if os.name == "nt" else "chart2pdf")


def _compile() -> str:
    if not os.path.isdir(ADOCAO_ROOT):
        raise BuildError(f"找不到 ADOCAO 源码目录: {ADOCAO_ROOT}（可用 ADOCAO_ROOT 覆盖）")
    os.makedirs(BUILD_DIR, exist_ok=True)
    exe = _exe_path()
    stamp = exe + ".stamp"
    fp = _sources_fingerprint()
    try:
        with open(stamp, "r", encoding="ascii") as f:
            if f.read().strip() == fp and os.path.exists(exe):
                return exe
    except OSError:
        pass

    cxx = os.environ.get("CXX") or shutil.which("g++")
    if not cxx:
        raise BuildError("找不到 g++（设置 CXX 或把 gcc 加进 PATH）")

    inc = ["-I" + ADOCAO_ROOT,
           "-isystem", os.path.join(THIRD_PARTY, "glm"),
           "-isystem", os.path.join(THIRD_PARTY, "rapidjson")]
    base = [cxx, "-std=c++20", "-O2"]

    objs = []
    # 1) 本项目代码：严格模式
    obj = os.path.join(BUILD_DIR, "chart2pdf.o")
    cmd = base + ["-Wall", "-Wextra", "-Werror", "-c",
                  os.path.join(NATIVE_DIR, "chart2pdf.cpp"), "-o", obj] + inc
    _run(cmd, "编译 chart2pdf.cpp")
    objs.append(obj)

    # 2) ADOCAO core：放宽它自己的既有警告（见 docs/TESTING.md §1）
    for src in ADOCAO_SOURCES:
        o = os.path.join(BUILD_DIR, os.path.basename(src) + ".o")
        cmd = (base + ["-Wall", "-Wextra"] + ADOCAO_SUPPRESS + ["-c",
               os.path.join(ADOCAO_ROOT, src), "-o", o] + inc)
        _run(cmd, f"编译 {src}")
        objs.append(o)

    _run([cxx] + objs + ["-o", exe], "链接 chart2pdf")
    with open(stamp, "w", encoding="ascii") as f:
        f.write(fp)
    return exe


def _run(cmd, what: str) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        msg = (r.stdout or "") + (r.stderr or "")
        raise BuildError(f"{what} 失败:\n{msg.strip()[:4000]}")


def build_scene(level_path: str, fps: int, zoom_scale: float, max_seconds: float,
                max_frames: int, out_dir: str, trace_csv: str | None = None,
                dump_frame: int | None = None, grid: str = "160x90") -> tuple[str, str]:
    exe = _compile()
    scene_path = os.path.join(out_dir, "scene.bin")
    cmd = [exe, level_path, scene_path, "--fps", str(fps),
           "--zoom-scale", f"{zoom_scale:g}",
           "--max-seconds", f"{max_seconds:g}",
           "--max-frames", str(max_frames),
           "--grid", grid]
    if trace_csv:
        cmd += ["--trace-csv", trace_csv]
    if dump_frame is not None:
        cmd += ["--dump-grid", str(dump_frame)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise BuildError((r.stderr or r.stdout or "chart2pdf 失败").strip())
    return scene_path, (r.stdout or "")


# ---------------------------------------------------------------- PDF 写出


def esc(s: str) -> str:
    return (s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
             .replace("\r", "\\r").replace("\n", "\\n"))


def num(x) -> str:
    if isinstance(x, int):
        return str(x)
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


class PDF:
    def __init__(self) -> None:
        self._objs: list[bytes | None] = [None]

    def reserve(self) -> int:
        self._objs.append(None)
        return len(self._objs) - 1

    def set(self, ref: int, body: bytes) -> None:
        if ref <= 0 or ref >= len(self._objs):
            raise ValueError(f"bad object ref {ref}")
        if self._objs[ref] is not None:
            raise ValueError(f"object {ref} already set")
        self._objs[ref] = body

    def add(self, body: bytes) -> int:
        ref = self.reserve()
        self.set(ref, body)
        return ref

    def add_stream(self, data: bytes, extra: str = "", compress: bool = False) -> int:
        if compress:
            data = zlib.compress(data, 6)
            extra += " /Filter /FlateDecode"
        body = f"<< /Length {len(data)}{extra} >>\nstream\n".encode() + data + b"\nendstream"
        return self.add(body)

    def build(self, root: int) -> bytes:
        out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0] * len(self._objs)
        for i in range(1, len(self._objs)):
            body = self._objs[i]
            if body is None:
                raise ValueError(f"object {i} was never set")
            offsets[i] = len(out)
            out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(self._objs)}\n".encode()
        out += b"0000000000 65535 f \n"
        for i in range(1, len(self._objs)):
            out += f"{offsets[i]:010d} 00000 n \n".encode()
        out += (f"trailer\n<< /Size {len(self._objs)} /Root {root} 0 R >>\n"
                f"startxref\n{xref}\n%%EOF\n").encode()
        return bytes(out)


def base_font(pdf: PDF, name: str) -> int:
    return pdf.add(
        f"<< /Type /Font /Subtype /Type1 /BaseFont /{name} "
        f"/Encoding /WinAnsiEncoding >>".encode()
    )


def type3_ramp_font(pdf: PDF) -> int:
    """10 个字形（密度 0..9）：1em 字格内从底部长 L/9 的白实心矩形。

    编码必须用**连续字符码 48–57**，且 /Widths 正好 10 个 —— S1 里验证过的那套。
    早先版本把 RAMP 的散码（32,46,58,…）塞进 Differences，却只给 10 个 Widths，
    而 FirstChar..LastChar 有 33 个码位，属规范违规：PDFium 直接放弃 Type3、
    退回替代字体按 0.6em 排版，画面被压到 60% 宽并变回字母。
    """
    glyphs = []
    for level in range(10):
        h = level / 9.0
        body = "1 0 0 0 1 1 d1"
        if level:
            body += f"\n0 0 1 {num(h)} re f"
        glyphs.append(pdf.add_stream(body.encode()))
    charprocs = " ".join(f"/g{i} {r} 0 R" for i, r in enumerate(glyphs))
    diffs = " ".join(f"/g{i}" for i in range(10))
    body = (
        f"<< /Type /Font /Subtype /Type3 /Name /Ramp "
        f"/FontBBox [0 0 1 1] /FontMatrix [1 0 0 1 0 0] "
        f"/CharProcs << {charprocs} >> "
        f"/Encoding << /Type /Encoding /Differences [48 {diffs}] >> "
        f"/FirstChar 48 /LastChar 57 "
        f"/Widths [1 1 1 1 1 1 1 1 1 1] /Resources << >> >>"
    )
    return pdf.add(body.encode())


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


# ---------------------------------------------------------------- 运行时 JS


JS_TEMPLATE = r"""
var D = this;
var FPS=__FPS__, PFPS=__PLAY_FPS__, W=__W__, H=__H__, N=__N__;
var HDR=45, DATA_START=__DATA_START__;
var RAMP="__RAMP__";
var F=[], LAST=[], CH=[], U8=null, OFF=null, idx=-1, epochMs=0, timer=0, playing=false;

function s_now(){ return (typeof Date.now==="function")?Date.now():new Date().getTime(); }

var B64 = __B64__;

function dec_b64(s){
  var tbl=new Int16Array(256), i, n=s.length, pad=0, out, o=0, a, b, c, d;
  for(i=0;i<256;i++) tbl[i]=-1;
  var A="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  for(i=0;i<64;i++) tbl[A.charCodeAt(i)]=i;
  if(n>0&&s.charCodeAt(n-1)===61) pad++;
  if(n>1&&s.charCodeAt(n-2)===61) pad++;
  out=new Uint8Array((n>>2)*3-pad);
  for(i=0;i<n;i+=4){
    a=tbl[s.charCodeAt(i)];     b=tbl[s.charCodeAt(i+1)];
    c=tbl[s.charCodeAt(i+2)];   d=tbl[s.charCodeAt(i+3)];
    if(c<0)c=0; if(d<0)d=0;
    if(o<out.length) out[o++]=(a<<2)|(b>>4);
    if(o<out.length) out[o++]=((b&15)<<4)|(c>>2);
    if(o<out.length) out[o++]=((c&3)<<6)|d;
  }
  return out;
}

function rd_u16(p){ return U8[p]|(U8[p+1]<<8); }
function init(){
  if(U8) return;
  var r, l, s;
  for(r=0;r<H;r++){
    var nm="r"+(r<10?"00":(r<100?"0":""))+r;
    F[r]=D.getField(nm);
    LAST[r]="";
  }
  for(l=0;l<10;l++){ s=""; for(var x=0;x<W;x++) s+=RAMP.charAt(l); CH[l]=s; }
  U8=dec_b64(B64);
  OFF=new Int32Array(N);
  for(var i=0;i<N;i++){
    var p=HDR+i*4;
    OFF[i]=(U8[p]|(U8[p+1]<<8)|(U8[p+2]<<16)|(U8[p+3]<<24))|0;
  }
}

function draw(k){
  var p=DATA_START+OFF[k], r, i, lv, cnt, s, nr, q, hl;
  p+=22; hl=U8[p]; p+=1;
  var hud="";
  for(i=0;i<hl;i++) hud+=String.fromCharCode(U8[p+i]);
  p+=hl;
  for(r=0;r<H;r++){
    nr=U8[p]|(U8[p+1]<<8); p+=2; s="";
    for(i=0;i<nr;i++){ lv=U8[p]; cnt=U8[p+1]; p+=2; s+=CH[lv].substr(0,cnt); }
    if(s!==LAST[r]){ F[r].value=s; LAST[r]=s; }
  }
  D.getField("hud").value=hud;
  idx=k;
}

function kForNow(){
  var k=Math.floor((s_now()-epochMs)*PFPS/1000);
  return k<0?0:(k>=N?N-1:k);
}

function tick(){
  if(!playing) return;
  var k=kForNow();
  if(k!==idx) draw(k);
  if(k>=N-1){ playing=false; return; }
  timer=app.setTimeOut("tick()", Math.max(1, Math.floor(1000/PFPS)));
}

function start(){
  init();
  if(playing) return;
  epochMs=s_now();
  playing=true;
  if(idx<0){ draw(0); }
  tick();
  try{ D.getField("btn_start").display=((typeof display!=="undefined"&&display.hidden!==undefined)?display.hidden:1); }catch(e){}
}

function toggle(){
  init();
  if(playing){
    playing=false;
    if(timer) app.clearTimeOut(timer);
    timer=0;
  } else {
    if(idx<0) idx=0;
    epochMs=s_now()-(idx*1000/PFPS);
    playing=true;
    tick();
  }
}

function restart(){
  init();
  playing=false;
  if(timer){ app.clearTimeOut(timer); timer=0; }
  idx=-1;
  for(var r=0;r<H;r++) LAST[r]="__CH_NONE__";
  draw(0);
  epochMs=s_now();
  playing=true;
  tick();
}

init();
draw(0);
"""


def build_js(scene: dict, packed: bytes, ramp: str = RAMP, play_fps: int = 30) -> str:
    b64 = base64.b64encode(packed).decode("ascii")
    chunks = [b64[i:i + 8192] for i in range(0, len(b64), 8192)]
    b64_js = "\n".join(f'"{c}"+' if i + 1 < len(chunks) else f'"{c}"'
                       for i, c in enumerate(chunks))
    return (JS_TEMPLATE
            .replace("__FPS__", str(scene["fps"]))
            .replace("__W__", str(scene["width"]))
            .replace("__H__", str(scene["height"]))
            .replace("__N__", str(scene["frame_count"]))
            .replace("__PLAY_FPS__", str(play_fps))
            .replace("__DATA_START__", str(scene["data_start"]))
            .replace("__RAMP__", ramp)
            .replace("__CH_NONE__", "\\u0001")
            .replace("__B64__", b64_js))


def write_pdf(scene: dict, out_path: str, use_type3: bool, no_hud: bool,
              play_fps: int = 30) -> tuple[int, int]:
    """返回 (PDF 字节数, JS 字节数)。"""
    raw = scene["raw"]
    packed = raw[:SCENE_HEADER_SIZE] + raw[SCENE_HEADER_SIZE:]  # 头 + 偏移 + 帧体
    ramp = DIGIT_RAMP if use_type3 else RAMP
    js = build_js(scene, packed, ramp, play_fps)
    js_bytes = len(js.encode("utf-8"))

    pdf = PDF()
    font_name = "Ramp" if use_type3 else "Cour"
    t3 = type3_ramp_font(pdf) if use_type3 else None
    cour = base_font(pdf, "Courier")
    helv = base_font(pdf, "Helvetica")

    page_ref = pdf.reserve()
    pages_ref = pdf.reserve()

    h = scene["height"]
    cell = SCREEN_H / h
    annots: list[int] = []
    fields: list[int] = []
    for r in range(h):
        y0 = SCREEN_Y + (h - 1 - r) * cell
        ref = text_field(pdf, f"r{r:03d}", [0, y0, PAGE_W, y0 + cell],
                         "", font_name, cell, page_ref)
        annots.append(ref)
        fields.append(ref)

    hud_ref = text_field(pdf, "hud", [24, RAIL_Y0, 692, RAIL_Y1], "", "Helv", 9, page_ref)
    annots.append(hud_ref)
    fields.append(hud_ref)
    if no_hud:
        annots.remove(hud_ref)

    btn_defs = [
        ("btn_start", [704, RAIL_Y0, 828, RAIL_Y1], "Start", "start()"),
        ("btn_pp", [840, RAIL_Y0, 1000, RAIL_Y1], "Play / Pause", "toggle()"),
        ("btn_restart", [1012, RAIL_Y0, 1256, RAIL_Y1], "Restart", "restart()"),
    ]
    for name, rect, cap, fn in btn_defs:
        ref = button(pdf, name, rect, cap, fn, page_ref)
        annots.append(ref)
        fields.append(ref)

    content = [
        f"0 0 0 rg 0 0 {PAGE_W} {PAGE_H} re f",
        f"0.18 0.18 0.18 RG 1 w 0 {RAIL_LINE_Y} m {PAGE_W} {RAIL_LINE_Y} l S",
    ]
    content_ref = pdf.add_stream("\n".join(content).encode(), compress=True)

    fonts = f"/Cour {cour} 0 R /Helv {helv} 0 R"
    if t3 is not None:
        fonts += f" /Ramp {t3} 0 R"
    page = (
        f"<< /Type /Page /Parent {pages_ref} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
        f"/Resources << /Font << {fonts} >> >> /Contents {content_ref} 0 R "
        f"/Annots [{' '.join(f'{r} 0 R' for r in annots)}] >>"
    )
    pdf.set(page_ref, page.encode())
    pdf.set(pages_ref, f"<< /Type /Pages /Kids [{page_ref} 0 R] /Count 1 >>".encode())

    dr = f"/Font << /Cour {cour} 0 R /Helv {helv} 0 R"
    if t3 is not None:
        dr += f" /Ramp {t3} 0 R"
    dr += " >>"
    acro = (
        f"<< /Fields [{' '.join(f'{r} 0 R' for r in fields)}] "
        f"/DR << {dr} >> /NeedAppearances true >>"
    )
    acro_ref = pdf.add(acro.encode())

    js_ref = pdf.add_stream(js.encode("utf-8"), compress=True)
    cat = (
        f"<< /Type /Catalog /Pages {pages_ref} 0 R /AcroForm {acro_ref} 0 R "
        f"/OpenAction << /S /JavaScript /JS {js_ref} 0 R >> >>"
    )
    cat_ref = pdf.add(cat.encode())

    data = pdf.build(cat_ref)
    with open(out_path, "wb") as f:
        f.write(data)
    return len(data), js_bytes


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pdfc.py", description="ADOFAI 谱面 -> 单页 PDF")
    ap.add_argument("level", help="明文 .adofai 谱面")
    ap.add_argument("-o", "--out", required=True, help="输出 PDF")
    ap.add_argument("--render", choices=["frames", "runtime"], default="frames",
                    help="渲染模式（v1 只有 frames）")
    ap.add_argument("--fps", type=int, default=30, help="bake fps（默认 30，见 D10）")
    ap.add_argument("--zoom-scale", type=float, default=1.0,
                    help="相机 adoZoom 的倍率（ADOB-C 口径：越大看得越远；1.0 = 忠实还原谱面运镜）")
    ap.add_argument("--rows", type=int, default=90,
                    help="字符屏行数（60..180）。列数按 8pt 行高下的等宽字体自动配平，"
                         "使一行正好铺满 1280pt（默认 90 行 -> 266 列）")
    ap.add_argument("--grid", default=None,
                    help="显式指定 WxH，覆盖 --rows 推出的列数")
    ap.add_argument("--play-fps", type=int, default=30,
                    help="PDF 实际播放帧率。小于 --fps 即慢放（例如 --fps 60 --play-fps 30 是 0.5 倍速）")
    ap.add_argument("--max-seconds", type=float, default=300.0)
    ap.add_argument("--max-frames", type=int, default=24000)
    ap.add_argument("--no-hud", action="store_true")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--type3", action="store_true",
                     help="Type3 后端：1em 前进量，8x8 格严格方正（密度条，不是字母）")
    grp.add_argument("--courier", action="store_true", help="Courier 后端（默认）")
    ap.add_argument("--trace-csv", default=None, help="输出 timeline.csv（调试）")
    ap.add_argument("--dump-frame", type=int, default=None, metavar="K",
                    help="把第 K 帧的字符网格打到 stdout（调试）")
    ap.add_argument("--keep-scene", action="store_true", help="保留 scene.bin")
    args = ap.parse_args(argv)

    level = args.level
    if not os.path.isfile(level):
        print(f"pdfc: 找不到谱面 {level}", file=sys.stderr)
        return 2
    ext = os.path.splitext(level)[1].lower()
    if ext != ".adofai":
        print("pdfc: 本版本只支持明文 .adofai（压缩容器需要 archive 后端）", file=sys.stderr)
        return 2
    if args.rows < 60 or args.rows > 400:
        print("pdfc: --rows 只接受 60..400", file=sys.stderr)
        return 2
    if args.play_fps < 1 or args.play_fps > args.fps:
        print(f"pdfc: --play-fps 需在 1..{args.fps}（大于等于 --fps 就没有慢放意义）", file=sys.stderr)
        return 2
    # 8pt 行高下 Courier 每字 0.6em：列数取 floor(1280 / (0.6 * 行高))，让一行正好铺满
    if args.grid:
        gw, _, gh = args.grid.partition("x")
        if not (gw.isdigit() and gh.isdigit()):
            print("pdfc: --grid 需要 WxH", file=sys.stderr)
            return 2
        grid = f"{int(gw)}x{int(gh)}"
    else:
        cell_h = SCREEN_H / args.rows
        cols = int(PAGE_W // (0.6 * cell_h))
        grid = f"{cols}x{args.rows}"

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)

    tmp_dir = tempfile.mkdtemp(prefix="adopdf-", dir=BUILD_DIR)
    try:
        try:
            scene_path, dump_out = build_scene(level, args.fps, args.zoom_scale,
                                               args.max_seconds, args.max_frames, tmp_dir,
                                               args.trace_csv, args.dump_frame, grid)
        except BuildError as e:
            print(f"pdfc: {e}", file=sys.stderr)
            return 3

        if dump_out:
            sys.stdout.write(dump_out)

        scene = parse_scene(scene_path)
        if scene["mode"] != 0:
            print("pdfc: scene.bin 不是 frames 模式", file=sys.stderr)
            return 3
        pdf_bytes, js_bytes = write_pdf(scene, args.out, args.type3, args.no_hud, args.play_fps)
    finally:
        if args.keep_scene:
            keep = os.path.join(BUILD_DIR, "scene.bin")
            try:
                shutil.copyfile(os.path.join(tmp_dir, "scene.bin"), keep)
                print(f"pdfc: scene -> {keep}", file=sys.stderr)
            except OSError:
                pass
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"pdfc: {args.out}  frames={scene['frame_count']} fps={scene['fps']} "
          f"pdf={pdf_bytes / 1048576:.2f} MiB js={js_bytes / 1048576:.2f} MiB "
          f"t=[{scene['t_start']:.2f},{scene['t_end']:.2f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
