# 当前状态（2026-11-12）

**S1/S2 未通过，正式生成器未开始。** 本文只记录事实，不把“已生成 PDF”当成“已完成验收”。

## 已完成

- 设计文档冻结：`docs/SPEC.md`、`docs/DECISIONS.md`、`docs/ARCHITECTURE.md`、
  `docs/SPIKES.md`、`docs/TESTING.md`。
- S1/S2 最小 PDF 生成器：`tools/pdf/spike/gen_spikes.py` + `minipdf.py`。
- 沙箱静态校验：
  - 6 份 PDF 均为 1 页、1280×768 pt、PDF 1.7；
  - 字段数：S1 = 91/136/181 个文本字段 + 1 按钮；S2 = 81 个文本字段；
  - `pdffonts` 确认 Type3 字体 `Block` 已嵌入；
  - `pdftoppm` 能渲染页面文本与字段值；
  - S1 的 JS 通过 `node --check`。
- Python 单测：`tests/test_minipdf.py` 4/4。

## 未完成 / 未验证

- **S1 未通过**：Chrome/PDFium 里的实际字段更新吞吐（`avg/fps/setter`）未实测；
  沙箱没有 Chrome。
- **S2 未通过**：PDFium 的表单 AP 是否接受 Type3 字体未实测；只验证了 Poppler 静态渲染。
- 正式生成器（C++ core → `scene.bin` → Python PDF）未开始。
- `frames` / `runtime` 两种模式、HUD、按钮、时间轴均未实现。
- `pdfc.py` 入口未实现。

## 下一步

1. 用户在 Chrome 打开 `build/spike/*.pdf`，回填 S1 HUD 数字与 S2 Type3 结果到
   `docs/SPIKES.md`。
2. 依据 S1 定 `--fps` 默认值；依据 S2 定 Type3/Courier 默认后端。
3. S1/S2 通过后，再开始正式生成器。
