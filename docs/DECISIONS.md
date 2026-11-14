# 已拍板决策

> 这些是**约束**，不是建议。实现偏离任何一条都必须先在本文改决策并说明原因。

## D1. 目标运行环境

| 项 | 决策 |
|---|---|
| 浏览器 | Chrome 桌面版，**原生 PDFium** |
| PDF.js | **不依赖**；PDFium 的 JS 被禁用或缺 API 时才作为退路 |
| 构建平台 | Linux（当前沙箱）；g++ 13 + Python 3 |
| 运行时数据 | 全部构建期塞进 PDF；无文件、网络、DOM、`dataObjects` |

理由：PDFium 默认执行 PDF JS；`app.setTimeOut/setInterval`、字段 `value`、按钮 `/AA /U` 都可用。
PDF.js 不是权限超集，也不更快。

## D2. 渲染模型

- **单页**，不做翻页。
- 屏幕 = **160×90** 字符网格。
- 运行时动态输出面只有**行文本字段的 `value`**；`Start` 按钮额外用一次 `display`。
- **不使用** `rect` 移动字段、**不使用** `fillColor/textColor/rotation/buttonSetIcon`。
- 灰度 10 级：背景 0，砖填充 4，砖描边 8，twirl 9，SetSpeed 6，枢轴星球 9，移动星球 6，拖尾 3/2。
- 字符格必须接近正方形：Type3 1:1 字体或 Courier + 匹配宽高比的网格都能满足（S2 已验证 8 pt 下均接近正方形）；默认用哪个见 **D10**。

## D3. 两种可选模式（用户二选一）

| | `--render frames`（构建期字符帧） | `--render runtime`（运行时渲染） |
|---|---|---|
| PDF 里放什么 | 每帧 RLE 字符行 | 形状表 + 每帧砖实例/图元 |
| 运行时 JS 做什么 | 解码 RLE → 写字段 | 变换形状表三角形 → 栅格化 → 写字段 |
| 帧率 | 最高 | 较低 |
| PDF 体积 | 较大 | 较小 |
| 数学来源 | 同一份 C++ core | 同一份 C++ core |

两种模式共用：同一帧时间轴、同一 160×90 网格、同一字段/HUD/按钮、同一灰度映射。

## D4. 时间轴与帧率

- bake fps 固定，由 `pdfc.py --fps` 指定。
- 帧 `k` 对应 `t_k = t_start + k / fps`；`t_start = -preRoll`，结束到 `totalDuration`。
- 逐帧顺序 `drive()`，`dt = 1/fps`，**不是**每帧 `seek()`。
- 运行时用墙钟取帧号：`k = floor((now - epochMs) * fps / 1000)`。
- 渲染慢 → 跳帧；渲染快 → 重复帧；**不累积误差**。
- 暂停/继续重置 `epochMs = now - k/fps*1000`。
- 无音频、无 A/V 对拍。

## D5. 相机与缩放

- 位置/旋转/zoom 全部来自 `CameraDirector`，宿主顺序与 `GameWindow` 一致。
- `--zoom-scale F` 是**倍率**：`effectiveAdoZoom = chartAdoZoom * F`，保留谱面 zoom 曲线形状。
- 默认 `F = 1.0`。

## D6. 视觉范围

- 画：真实砖形（`TileShape`）、描边、twirl/SetSpeed 圆点、两条拖尾、星球。
- 不画：颜色事件（`ColorTrack`/`RecolorTrack`/`Volume`）、背景闪屏、装饰物、Hold 带、音频。
- twirl = `@`，SetSpeed = `O`（字符与灰度都不同）。
- 砖形默认 Standard；Gems/Neon 等 trackStyle 几何 v1 不做。

## D7. HUD 与控制

- HUD 保留：时间、砖号/总数、BPM、相机 `x,y,rot,zoom`、进度条。
- 控制：`Start`、`Play/Pause`、`Restart`。
- **没有 ±5s**。

## D8. 输入与错误

- v1 只支持明文 `.adofai`。
- 压缩容器（`.xz/.zst/.adocao`）必须**明确报错**，不静默回退；`ArchiveBackend` 留空。
- Type3 不可用 → 自动回退 Courier，并在日志写明。
- 超长谱面/超大 PDF 必须有上限并报错，不静默截断。

## D9. 工具链

- `pdfc.py` 是唯一入口；首次运行用 g++ 编译 `tools/pdf/native/chart2pdf` 并缓存。
- 只链接 ADOCAO `core` 的纯逻辑闭包 + `render/TileShape.cpp` / `TileGeometryReference.cpp`；不碰 GL/GLFW/音频。
- glm / rapidjson 以 header-only 形式 vendor；用户不需要 CMake/网络/apt。

## D10. 字体后端与 bake fps（2026-11-13 实测结论）

| 项 | 决策 | 依据 |
|---|---|---|
| 默认字体后端 | **Courier**（8 pt，`/Cour`） | Type3 渲染正常（S2 通过），但 160×90 下 14.7 fps、setter 35.52 ms/帧；Courier 49.8 fps、setter 7.59 ms |
| `--type3` | 保留，**仅显式开启** | 需要真正方形字格时用；默认不走 Type3 |
| `--fps` 默认 | **30** | 90 行满更新 20.08 ms/帧；30 fps 预算 33.3 ms（余量 1.6×），60 fps 预算 16.7 ms 不成立 |
| 网格 | v1 固定 160×90 | 135 行 32.0 fps、180 行 22.1 fps，均已无余量；不把高分辨率作为默认 |

- 本决策把 `SPEC.md §4` 的“默认先 Type3，失败回退”改为“默认 Courier”；
  D8 的回退规则降级为 `--type3` 显式开启时的兜底。
- 数据见 `SPIKES.md` 的 S1/S2 结论；未测项（S3 体积、S5 端到端）不改变本决策。

## D11. 以 ADOB-C/ADOCAO 为准（2026-11-13 换仓库）

旧本地仓库是 `Pitaki-Dev/ADOCAO`（最后提交 2026-09-25），**没有** CameraDirector / CameraTimeline /
TileAnimation / TileShape；此前的生成器是按"这台播放器没有运镜"写的，属于对着错误基线实现。
2026-11-13 换成 `https://github.com/ADOB-C/ADOCAO`（最后提交 2026-11-07），旧目录保留在
`E://0//ADOCAO_old`（含 105 MB 的 `level.mp4` 与 395 MB 的 `wonyou/`，未删）。

现在 `chart2pdf` 链接的闭包（`pdfc.py` 的 `ADOCAO_SOURCES`）：LevelData / FloorWindow / ByteSource /
LevelPath / JsonCleaner / TileColor / Logger / Progress / Scheduler / Easing / MappedFile /
Timeline / Keyframes / TileAnimation / PositionSolver / CameraTimeline / CameraDirector /
TileGeometryReference（CPU 几何参考实现）。

**逐帧顺序与 `app/GameWindow.cpp` 完全一致**：

1. `tileIdx = timeline.findTileIndex(t)`，夹到 `[0, tileCount-2]`；
2. `bpm = tileBPMs[tileIdx]`，`pitch = max(0.1, settings.pitch/100)`；
3. `PositionSolver::pivotStarAt(timeline, t, px, py, &anim, &holdSlide)` —— 相机跟的是行星枢轴，
   不是加载期烘好的静态砖位（否则 MoveTrack 搬砖、长按滑动时画面会相对星球漂开）；
4. `director.setHoldOffset(holdSlide)` → `director.drive(t, 1/fps, bpm, pitch, px, py, tileIdx)`；
5. `camX/Y = director.x()/y()`，`rot = rotation()`，`adoZoom = zoom() * zoomScale`；
6. `halfH = 5.47 * adoZoom / 200`（`Camera::setAdoZoom` 的换算），屏幕 = `ortho · R(-θ)`。

砖：`tileXformAt(level, &anim, i, t)` 给出 move/rot/scale/opacity，形状由 `createTileMesh` /
`createMidSpinMesh` 生成（新常量 `TILE_WIDTH=0.2695 / TILE_LENGTH=0.49 / OUTLINE=0.0125`）。

- **`--zoom-scale` 的语义随之改变**：新仓库的 adoZoom 越大看得越远，所以倍率 >1 才是"拉远"。
  默认 1.0 = 忠实还原谱面运镜；想多看砖用 `--zoom-scale 2`。
- 旧实现里的 `--zoom-scale 0.125`（旧口径"越小越远"）已作废。

## D12. 字形后端改 Type3、页面加控制栏、默认拉远（2026-11-13 首份正式 PDF 实测后）

真实 PDF 里发现的问题（Chrome/PDFium）：用 Courier 时，160 个字符每字前进量只有 0.6em，
字段却有 1280pt 宽 —— **PDFium 会按字段宽度把整行拉满**，字号被放大到约 13.3pt，
而行距只有 8pt，于是行与行互相压住，画面糊成一片，看着完全不像 16:9。

| 项 | 决策 | 依据 |
|---|---|---|
| 默认字形后端 | **Courier**（`--type3` 实验项） | 首版 Courier 在 Chrome 里观感正常；Type3 只有 1em 前进量才能让 8×8 格严格方正，但见下方编码坑 |
| Type3 编码 | **连续码 48–57 + 10 个 `/Widths`** | 早先把 RAMP 的散码（32,46,58,…）写进 `Differences` 却只给 10 个 `Widths`，而 `FirstChar..LastChar` 有 33 个码位：PDFium 直接丢弃 Type3、退回替代字体按 0.6em 排，画面被压到 60% 宽并变回字母 |
| Type3 字形形状 | 每级 1 个矩形（从底部填 `level/9` 高度） | S1 的 3×3 点阵最坏 9 个矩形，setter 35.5 ms；单矩形是绘制开销下限 |
| 页面尺寸 | **1280×816**：24pt 上边距 + 1280×720 字符屏 + 60pt 控制栏 | 屏幕区严格 16:9，控制栏独立成条，不再和屏幕挤在同一块里 |
| 控制栏 | HUD 左、Start / Play-Pause / Restart 右，高 40pt，`y=12..52`，`y=62` 画分隔线 | 三个按钮有自己的栏位，不压住画面 |
| `--zoom-scale` 默认 | **0.25**（视野里多看到四倍的砖） | 用户反馈 300 zoom 的谱面看得太近；D5 的"倍率"语义不变 |

- 本决策**取代 D10 的字体部分**（D10 的 `--fps 30` 仍然有效）。
- Type3 在 160×90 下仍只有 S1 的 14.7 fps 证据（9 矩形口径），换单矩形后需在 Chrome 复测；
  **复测通过前不作默认**。
- 等宽 TTF（如 Sarasa Mono，0.5em 前进量）在 8×8 格里无法直接用：要么留半个格子的空隙，
  要么被 PDFium 拉满后行重叠。要用真实字形只能走"Type3 CharProc 里嵌 TTF"的路子，v1 不做。

## D13. 网格分辨率与播放速率（2026-11-13）

`--rows N`（60..180，默认 90）：行高 = 720/N，列数自动取 `floor(1280 / (0.6 × 行高))`，
让 8pt 系等宽字体正好铺满整行。`--grid WxH` 可显式覆盖。

| 行数 | 格子 | 列数 | 每帧字符 | 备注 |
|---|---|---|---|---|
| 90 | 8 pt | 266 | 23,940 | 默认 |
| 120 | 6 pt | 355 | 42,600 | 细节约 1.8×，基准谱 60 fps 下 7.79 MiB |
| 135 | 5.33 pt | 400 | 54,000 | 接近 setter 上限，未实测帧率 |
| 180 | 4 pt | 533 | 95,940 | 只作理论值，不建议 |

`--play-fps M`（默认 30）：PDF 里 JS 的推进速率与 `--fps`（bake）解耦。
`--fps 60 --play-fps 30` 即 **0.5 倍速播放**，录制后 2× 剪辑得到 60 fps。

- 每帧字符数直接决定 setter 开销（≈0.5 µs/字符）：90 行约 12 ms、120 行约 21 ms、135 行约 27 ms，
  再加 ~12.5 ms 的字段重绘。30 Hz 更新下 120 行已接近上限，135 行只在 15–20 Hz 下可行。
- 因此"高分辨率"与"高刷新率"是互斥的：先按 `--play-fps` 定更新率，再定 `--rows`。
- `--max-frames` 默认放宽到 24000（容纳 300 s × 60 fps 的一半以上）。
- Type3 已证伪：PDFium 的表单 AP **不使用 Type3 字形**，只沿用它的 `/Widths`、用替代字体绘制字符，
  所以 `--type3` 出来是一屏数字。该后端仅保留作记录，不作候选。

## 待 spike 决定

| 项 | 由谁定 | 状态 |
|---|---|---|
| Type3 还是 Courier | S2 | **已定**：Courier 默认，见 D10 |
| bake fps 默认值 | S1 | **已定**：30，见 D10 |
| `runtime` 模式是否保留为默认之一 | S5 | 待 S5（两模式都实现，默认由数据决定） |
