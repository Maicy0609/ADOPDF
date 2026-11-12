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
- 字符格必须接近正方形：优先 Type3 1:1 字体；失败则 Courier + 匹配宽高比的网格。

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

## 待 spike 决定

| 项 | 由谁定 |
|---|---|
| Type3 还是 Courier | S2 |
| bake fps 默认值 | S1 实测后 |
| `runtime` 模式是否保留为默认之一 | S5 实测后（两模式都实现，默认由数据决定） |
