# 当前状态（2026-11-13）

**S1/S2 已通过；frames 模式的正式生成器已打通端到端；Chrome 人工验收未做。**

## 已完成

- 设计文档冻结；S1/S2 spike 与 Chrome 实测（见 `docs/SPIKES.md`）。
- 默认值：`--fps 30`、字形后端 Courier、页面 1280×816、网格 266×90、`--zoom-scale 1.0`（D10/D11/D12/D13）。
- **`frames` 正式生成器**（`tools/pdf/native/chart2pdf.cpp` + `scene_format.h`）
  - 基线仓库换成 **ADOB-C/ADOCAO**（2026-11-07），链接 18 个 TU（含 CameraDirector /
    CameraTimeline / TileAnimation / TileGeometryReference），不碰 GL/音频/窗口；
  - **运镜是真的**：`CameraDirector::drive` + `pivotStarAt` + `setHoldOffset`，逐帧顺序与
    `app/GameWindow.cpp` 一致；旋转进投影（`ortho · R(-θ)`），zoom 走 `setAdoZoom` 口径；
  - 灰格 266×90（`--rows` 可调）、10 级 ramp、砖按楼层倒序、先描边后填充；
  - 砖的空间索引（1.0 单位桶）——60 万砖的压力谱 6209 帧只需 2.6 s；
  - `--dump-grid K` / `--trace-csv` 两个调试出口。
- **`pdfc.py` 入口**：CLI 校验 → 源码哈希编译缓存 → 跑 chart2pdf → 写单页 PDF
  （90 行字段 + HUD + 3 按钮 + Courier/Type3 + Flate JS）。
- 单测 14/14：RLE 边界、scene 头/帧往返/截断、PDF 结构、**PDF 里那份 JS 交给 node
  执行后与 Python 解码逐字符一致**。
- 端到端产物：
  - `tests/fixtures/mini.adofai`（24 砖）→ 473 帧 / 90 KB；
  - `$ADOCAO_ROOT/ci/level/level.adofai`（60 万砖，31 条运镜事件）→ 6209 帧 / 2.12 MiB / t=[-2.07, 204.88]；
  - `tests/charts/camera_basic.adofai` → rot 0→90°、adoZoom 100→200，运镜已生效。
- 首份真实 PDF 反馈后按 `DECISIONS.md` D12/D13 改版：页面 1280×816（24 上边距 + 720 屏幕 + 60 控制栏）、
  网格默认 266×90（`--rows N` 可调）、`--play-fps` 支持 0.5 倍速录制；字形后端 Courier。

## 未完成 / 未验证

- **Chrome/PDFium 人工验收未做**：播放、按钮、HUD、跳帧、首帧延迟都没在真实 PDFium 里跑过。
  19 MB 的 JS 源（base64 载荷）在 PDFium 里的解码耗时是当前最大未知，S3 的 300 ms 预算可能不够。
- `runtime` 模式未实现（`--render runtime` 明确报错）。
- S3（体积/初始化）、S5（端到端对比）未做正式记录。
- 无音频、无颜色、无 MoveTrack（与 SPEC 的非目标一致）。

## 下一步

1. 在 Chrome 打开 `build/mini.pdf` / `build/ci.pdf`，回填 `docs/TESTING.md §4` 的人工验收项。
2. 按实测决定是否需要给载荷换编码（当前是 base64 + Flate on JS stream）。
3. 实现 `runtime` 模式，再跑 S3/S5 比较两种模式。
