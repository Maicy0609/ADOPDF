"""scene.bin 读写、行 RLE、PDF 结构与 JS 载荷的一致性测试。

不依赖 chart2pdf：用合成 scene 覆盖编解码边界；node 可用时额外验证 PDF 里
那份 JS 解出来的行与 Python 解码一致（同一份数据的两种实现必须对拍）。
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pdfc  # noqa: E402


def make_scene(frames, w=160, h=90, fps=30):
    """合成一份 frames 模式的 scene.bin 字节流。frames 是 dict 列表。"""
    t_start, t_end = -1.0, 16.0
    blobs = []
    offsets = []
    for fr in frames:
        body = bytearray()
        body += struct.pack("<fHffff", fr["t"], fr["tile"], fr["bpm"],
                            fr["cam"][0], fr["cam"][1], fr["zoom"])
        hud = fr["hud"].encode("ascii")
        body += bytes((len(hud),)) + hud
        for row in fr["rows"]:
            rle = pdfc.rle_encode_row(row)
            body += bytes((len(rle) // 2,)) + rle
        offsets.append(sum(len(b) for b in blobs))
        blobs.append(bytes(body))

    head = bytearray()
    head += pdfc.SCENE_MAGIC
    head += struct.pack("<HBHHHI", pdfc.SCENE_VERSION, 0, w, h, fps, len(frames))
    head += struct.pack("<dd", t_start, t_end)
    head += struct.pack("<fIf", 1.0, 42, 120.0)
    head += struct.pack(f"<{len(offsets)}I", *offsets)
    return bytes(head) + b"".join(blobs)


class TestRle(unittest.TestCase):
    def test_roundtrip_edges(self):
        cases = [
            [0] * 160,                      # 满行单色
            list(range(10)) * 16,           # 交替
            [0] * 159 + [9],                # 尾部异色
            [4] * 255,                      # 单个 run 达上限
            [4] * 256,                      # 触发 255 截断（两个 run）
        ]
        for row in cases:
            enc = pdfc.rle_encode_row(row)
            self.assertEqual(pdfc.rle_decode_row(enc), row, f"len={len(row)}")
            for i in range(0, len(enc), 2):
                self.assertLessEqual(enc[i + 1], 255)

    def test_empty(self):
        self.assertEqual(pdfc.rle_encode_row([]), b"")
        self.assertEqual(pdfc.rle_decode_row(b""), [])


class TestScene(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="adopdf-test-")
        rows = [[(x + y) % 10 for x in range(160)] for y in range(90)]
        self.frames = [
            {"t": -1.0, "tile": 0, "bpm": 120.0, "cam": (0.0, 0.0), "zoom": 100.0,
             "hud": "t=  -1.00s tile=0/42", "rows": rows},
            {"t": 0.0, "tile": 1, "bpm": 180.0, "cam": (1.5, -2.5), "zoom": 300.0,
             "hud": "t=   0.00s tile=1/42", "rows": [list(reversed(r)) for r in rows]},
        ]
        self.path = os.path.join(self.tmp, "scene.bin")
        with open(self.path, "wb") as f:
            f.write(make_scene(self.frames))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_header(self):
        s = pdfc.parse_scene(self.path)
        self.assertEqual(s["mode"], 0)
        self.assertEqual((s["width"], s["height"], s["fps"]), (160, 90, 30))
        self.assertEqual(s["frame_count"], 2)
        self.assertAlmostEqual(s["t_start"], -1.0)
        self.assertAlmostEqual(s["t_end"], 16.0)
        self.assertEqual(s["tile_count"], 42)
        self.assertEqual(s["data_start"], pdfc.SCENE_HEADER_SIZE + 8)
        self.assertEqual(s["offsets"][0], 0)

    def test_frame_roundtrip(self):
        s = pdfc.parse_scene(self.path)
        for k, fr in enumerate(self.frames):
            got = pdfc.decode_frame(s, k)
            self.assertEqual(got["hud"], fr["hud"])
            self.assertEqual(got["rows"], fr["rows"])
            self.assertAlmostEqual(got["t"], fr["t"], places=5)
            self.assertEqual(got["tile"], fr["tile"])
            for row in got["rows"]:
                self.assertEqual(len(row), s["width"])

    def test_truncated_rejected(self):
        with open(self.path, "rb") as f:
            data = f.read()
        bad = os.path.join(self.tmp, "bad.bin")
        with open(bad, "wb") as f:
            f.write(data[: pdfc.SCENE_HEADER_SIZE + 4])  # 偏移表被砍
        with self.assertRaises(ValueError):
            pdfc.parse_scene(bad)

    def test_bad_magic_rejected(self):
        bad = os.path.join(self.tmp, "magic.bin")
        with open(bad, "wb") as f:
            f.write(b"XXXX" + b"\0" * 80)
        with self.assertRaises(ValueError):
            pdfc.parse_scene(bad)


class TestPdf(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="adopdf-pdf-")
        rows = [[y % 10 for _ in range(160)] for y in range(90)]
        frames = [{"t": -1.0, "tile": 0, "bpm": 120.0, "cam": (0.0, 0.0), "zoom": 100.0,
                   "hud": "hud-%d" % k, "rows": rows} for k in range(3)]
        self.scene_path = os.path.join(self.tmp, "scene.bin")
        with open(self.scene_path, "wb") as f:
            f.write(make_scene(frames))
        self.scene = pdfc.parse_scene(self.scene_path)
        self.frames = frames

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, type3=False, no_hud=False):
        out = os.path.join(self.tmp, "out.pdf")
        size, _ = pdfc.write_pdf(self.scene, out, type3, no_hud)
        with open(out, "rb") as f:
            return f.read(), size

    def test_structure(self):
        data, size = self._write()
        self.assertEqual(size, len(data))
        self.assertTrue(data.startswith(b"%PDF-1.7"))
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))
        self.assertEqual(data.count(b"/FT /Tx"), 91)   # 90 行 + HUD
        self.assertEqual(data.count(b"/FT /Btn"), 3)
        self.assertEqual(data.count(b"/MediaBox [0 0 1280 816]"), 1)
        self.assertIn(b"/AcroForm", data)
        self.assertIn(b"/OpenAction", data)

    def test_no_hud_keeps_buttons(self):
        data, _ = self._write(no_hud=True)
        self.assertEqual(data.count(b"/FT /Btn"), 3)
        self.assertNotIn(b"/T (hud)", data.split(b"/Annots [")[-1].split(b"]")[0])

    def test_type3_embedding(self):
        data, _ = self._write(type3=True)
        self.assertIn(b"/Subtype /Type3", data)
        self.assertIn(b"/Ramp 8 Tf", data)
        # 编码必须连续且 Widths 个数 = LastChar-FirstChar+1，否则 PDFium 会丢弃 Type3
        self.assertIn(b"/FirstChar 48 /LastChar 57", data)
        self.assertIn(b"/Widths [1 1 1 1 1 1 1 1 1 1]", data)
        self.assertIn(b"/Differences [48 /g0 /g1", data)


class TestJsPayload(unittest.TestCase):
    """PDF 里的 JS 解出来的行，必须与 Python 解 scene.bin 的结果逐字符一致。"""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("没有 node，跳过 JS 对拍")
        self.tmp = tempfile.mkdtemp(prefix="adopdf-js-")
        rows0 = [[(x * 3 + y) % 10 for x in range(160)] for y in range(90)]
        rows1 = [[(x + y * 7) % 10 for x in range(160)] for y in range(90)]
        self.frames = [
            {"t": -1.0, "tile": 0, "bpm": 120.0, "cam": (0.0, 0.0), "zoom": 100.0,
             "hud": "t=  -1.00s tile=0/8  bpm=120", "rows": rows0},
            {"t": 0.5, "tile": 3, "bpm": 240.0, "cam": (2.0, 3.0), "zoom": 150.0,
             "hud": "t=   0.50s tile=3/8  bpm=240", "rows": rows1},
        ]
        self.scene_path = os.path.join(self.tmp, "scene.bin")
        with open(self.scene_path, "wb") as f:
            f.write(make_scene(self.frames))
        self.scene = pdfc.parse_scene(self.scene_path)

    def tearDown(self):
        if os.path.isdir(self.tmp):
            shutil.rmtree(self.tmp, ignore_errors=True)

    def test_js_matches_python(self):
        with open(self.scene_path, "rb") as f:
            packed = f.read()
        js = pdfc.build_js(self.scene, packed)
        js_path = os.path.join(self.tmp, "scene.js")
        with open(js_path, "w", encoding="utf-8") as f:
            f.write(js)

        runner = os.path.join(self.tmp, "run.js")
        with open(runner, "w", encoding="utf-8") as f:
            f.write(RUNNER % {"js": json.dumps(js_path), "n": len(self.frames)})
        out = subprocess.run(["node", runner], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr[:2000])
        got = json.loads(out.stdout)
        for k, frame in enumerate(got["frames"]):
            exp = pdfc.decode_frame(self.scene, k)
            self.assertEqual(frame["hud"], exp["hud"], f"hud @{k}")
            self.assertEqual(frame["rows"], ["".join(pdfc.RAMP[l] for l in r) for r in exp["rows"]],
                             f"rows @{k}")


RUNNER = r"""
const fs = require('fs');
const src = fs.readFileSync(%(js)s, 'utf8');
const fields = Object.create(null);
const display = { hidden: 1, visible: 0 };
const app = { setTimeOut: () => 0, clearTimeOut: () => {} };
const ctx = {
  getField: (n) => (fields[n] || (fields[n] = { value: '', display: 0 })),
  app, display, Date, Math, console, String,
};
const fn = new Function(src + ';return {draw:draw, rows:function(){var a=[],i;for(i=0;i<F.length;i++)a.push(F[i].value);return a;},hud:function(){return D.getField("hud").value;}};');
const api = fn.call(ctx);
const out = { frames: [] };
for (let k = 0; k < %(n)d; k++) { api.draw(k); out.frames.push({ rows: api.rows(), hud: api.hud() }); }
process.stdout.write(JSON.stringify(out));
"""


if __name__ == "__main__":
    unittest.main(verbosity=2)
