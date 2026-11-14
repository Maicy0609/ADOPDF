# Spike 计划与结果

> 目的：在写正式生成器之前，用最小 PDF 验证两个不可推断的假设：
> **PDFium 的行字段更新吞吐**、**Type3 字符格是否可用**。
> S1/S2 不通过，不进入正式实现。

## 环境说明

- 当前沙箱有：`python3`、`g++`、`pdfinfo`、`pdftoppm`、`node`。
- 当前沙箱**没有 Chrome/Chromium**，PDF 内 JS 的真实运行必须由用户在 Chrome 桌面版打开。
- 沙箱能做的：生成 PDF、`pdfinfo` 检查页数/尺寸、`pdftoppm` 渲染首帧（不含 JS）、
  `node` 跑纯 JS 解码/栅格化单测。
- **不得**把“沙箱里 pdfinfo 通过”当成“PDFium 里 JS 通过”。
- 2026-11-13 复跑在本机 Windows 上完成，该机**没有 Poppler**：结构校验改为直接读 PDF 字节
  （`/FT /Tx` 计数、`MediaBox`、`%PDF` 头、`%%EOF`），六份产物的字节数与 2026-11-12 完全一致。

## 结论速览

| Spike | 状态 | 关键数字 |
|---|---|---|
| S1 行字段吞吐 | **通过** | 160×90 Courier 49.8 fps（20.08 ms/帧，setter 7.59 ms） |
| S2 Type3 字符格 | **通过（渲染）** | Type3 在 PDFium 表单 AP 中正常出字，10 级密度可辨；但吞吐只 14.7 fps |
| 默认值（S1/S2 推导） | 已定 | `--fps 30`、字体后端 Courier（见 `DECISIONS.md` D10） |

## 2026-11-12：S1/S2 已生成（静态校验通过）

生成命令：

```
python3 tools/pdf/spike/gen_spikes.py --out build/spike
```

产物（`build/spike/`，不提交）：

| 文件 | 大小 | 说明 |
|---|---|---|
| `s1_courier_160x90.pdf` | 36,250 B | 90 行 + HUD；Courier |
| `s1_type3_160x90.pdf` | 38,917 B | 90 行 + HUD；Type3 |
| `s1_courier_240x135.pdf` | 65,450 B | 135 行 + HUD；Courier |
| `s1_courier_320x180.pdf` | 99,326 B | 180 行 + HUD；Courier |
| `s2_type3.pdf` | 34,186 B | 80 行 + HUD；Type3 |
| `s2_courier.pdf` | 31,577 B | 80 行 + HUD；Courier |

静态校验（沙箱内）：

- `pdfinfo`：全部 1 页，1280×768 pt，PDF 1.7。
- 字段数：S1 = 91/136/181 个 `/FT /Tx`（行 + HUD）+ 1 个 `/FT /Btn`；
  S2 = 81 个 `/FT /Tx`（80 行 + HUD）。
- `pdffonts s2_type3.pdf`：`Block` 是 **Type 3 / embedded**；Courier/Helvetica 是 Type 1。
- `pdftoppm`：全部能出图；S2 的页面文本样本与字段值都能被 Poppler 渲染
  （Type3 样张非黑像素 14,802；Courier 3,321；字段面板 119,403 / 26,584）。
- S1 的 JS 已从 PDF 流里解出并用 `node --check` 验证语法；`/OpenAction` 指向 JS 流。
- 沙箱内**不能**验证 PDFium 的字段吞吐；该项由 2026-11-13 的 Chrome 实测补上（见 S1 结论）。

Chrome 打开方式与记录：

1. 打开 `build/spike/s1_courier_160x90.pdf`，点 `Start`（或等 1 秒自动开始）。
   约 120 帧后 HUD 显示 `avg=…ms fps=… setter=…ms`，把这三个数填进下面的表。
2. 同样跑 `s1_type3_160x90.pdf`、`s1_courier_240x135.pdf`、`s1_courier_320x180.pdf`。
3. 打开 `s2_type3.pdf` / `s2_courier.pdf`：
   - 顶部是页面文本样张（静态），底部是表单字段（AP）；
   - 看 Type3 是否显示为方块、是否有乱码/缺字、8pt 格子是否接近正方形；
   - 如果 Type3 的字段面板是空白/乱码，记录为“Type3 不可用，回退 Courier”。

> S2 的图案只是**字体/AP 测试**，不是最终砖形；最终砖形由 `TileShape` 生成。

## S1：行字段吞吐

### 目标

测 160×90 下，90 个只读单行文本字段每帧全部更新 `value` 的实际吞吐；
同时测 240×135（135 行）与 320×180（180 行）作为对照。

### 最小 PDF

- 单页 1280×768；上方 160×90 字符屏，下方 HUD。
- 屏幕 = H 个字段，每行一个，`/FT /Tx`、只读、无边框、黑底、白色等宽字体。
- JS：
  - `Start` 按钮或 `/OpenAction` 延迟启动。
  - `tick()` 最多执行 `TARGET=120` 帧；每帧给每行写一个变化的 W 字符串
    （W=160/240/320，随 H 保持 16:9）。
  - 用 `Date.now()` 量**两次 tick 之间的墙钟**，累加；HUD 显示
    `frames / elapsed`、`ms/frame`、`fps`。
  - `app.setTimeOut("tick()", 0)`，让回调尽快跑；慢帧时回调间隔会变大。
- 变量：
  - 90 / 135 / 180 行；
  - Courier vs Type3。

### 通过标准

- 160×90 ≥ **20 fps**（理想 ≥30；低于 15 则 bake fps 定在实测值）。
- 更新过程中无字段错位、无整页闪烁、无 JS 异常。
- 记录：`H, 字体, 平均 ms/帧, fps, 备注`。

### 记录表

| 日期 | H | 字体 | ms/帧 | fps | setter | 备注 |
|---|---|---|---|---|---|---|
| 2026-11-13 | 90 | Courier | 20.08 | 49.8 | 7.59 ms | **通过**（≥20，且接近理想 30 的 1.6×） |
| 2026-11-13 | 90 | Type3 | 68.25 | 14.7 | 35.52 ms | **不通过**；setter 单项即超 30 fps 预算 |
| 2026-11-13 | 135 | Courier | 31.24 | 32.0 | 17.33 ms | 对照；30 fps 已无余量 |
| 2026-11-13 | 180 | Courier | 45.22 | 22.1 | 24.93 ms | 对照；160×90 是合适的分辨率上限 |

环境：Windows / Chrome 桌面版，页面缩放 72%，`TARGET=120` 帧，数字取自 HUD 读数。
无字段错位、无整页闪烁、无 JS 异常。

### 结论（2026-11-13）

- **160×90 + Courier 达标**：49.8 fps。`--fps 30` 的预算是 33.3 ms/帧，实测 20.08 ms，余量约 1.6×。
  60 fps 需要 ≤16.7 ms，实测不成立 → **bake fps 默认 30**。
- setter 成本随行数近线性：**0.084 / 0.128 / 0.139 ms/行**（90 / 135 / 180 行）。
  90 行满更新 7.59 ms，单看 setter 上限约 130 fps；**瓶颈在字段更新之外的重绘**（`avg − setter` ≈ 12.5 ms）。
- Type3 在同分辨率下 ms/帧是 Courier 的 **3.4×**、setter 是 **4.7×**（35.52 vs 7.59 ms），
  且 `avg − setter` 从 12.5 ms 涨到 32.7 ms（字形绘制更贵）。30 fps 下不可用。
- 一致性推论：三档行数的 `avg − setter` 同步增长（12.5 / 13.9 / 20.3 ms），说明行数增加同时抬高两段成本，
  因此“提高分辨率换清晰度”在 v1 上没有余量。

## S2：Type3 字符格 / Courier 回退

### 目标

验证 PDFium 的表单 AP 是否接受 `/DA` 里的 **Type3 字体**，并确认字符格接近正方形。

### 最小 PDF

- Type3 字体：10 个字形（level 0–9），每个是不同密度的方块；
  `FontMatrix [1 0 0 1 0 0]`、`FontBBox [0 0 1 1]`、`Widths` 全 1。
- 一个行字段，`value = "0123456789..."`，`/DA (/Block 8 Tf 1 1 1 rg)`。
- 第二个行字段用 Courier 作对照。
- 再画一个“砖形测试图”：一条粗线 + 描边 + 一个圆点，用 ramp 表示，检查可辨认度。

### 通过标准

- Type3 行字段在 PDFium 中显示为**实心/半实心方块**，无乱码、无字体缺失。
- 8pt 字号下格子接近 8×8 pt；砖形不被明显拉伸。
- 不通过 → 自动回退 Courier；记录 Courier 的网格宽高比方案（0.6 比例）。

### 记录表

| 日期 | 字体 | 结果 | 备注 |
|---|---|---|---|
| 2026-11-13 | Type3 | **通过** | `s1_type3_160x90.pdf` 的 91 个 Type3 字段在 PDFium 中正常出字；90 行呈现 10 级不同密度，字格无空心、无乱码、无缺字 |
| 2026-11-13 | Courier | **通过** | `s2_courier.pdf` 的砖形样张（描边 8 / 填充 4）、twirl 与 SetSpeed 圆点、拖尾、枢轴/移动星球均清晰可辨 |

### 结论（2026-11-13）

- **Type3 在表单 AP 里可用**。证据：`s1_type3_160x90.pdf` 每行 `value` 是同一个数字重复 160 次，
  行与行的密度差异只能来自 10 个字形本身的填充差异；Chrome 里逐行呈现 0→9 递增的密度带，
  说明字形、`FontMatrix`、`Widths` 与 `/DA (/Block 8 Tf …)` 都被正确接受。
- 8 pt 字格在当前缩放下接近正方形，`ARCHITECTURE.md §3.2` 的 8×8 pt 布局无需调整；
  Courier 的格子宽度已在 `s2_courier.pdf` 上验证可读，正式实现沿用同一布局。
- **渲染可用 ≠ 吞吐可用**：Type3 在 S1 里只有 14.7 fps（见上）。故 S2 判“通过”只解除“能不能画”的疑问，
  默认后端仍定为 Courier（`DECISIONS.md` D10）。
- 未归档：`s2_type3.pdf` 的整页截图（页面文本样张 + 字段面板）。Type3 的 AP 问题已由
  `s1_type3_160x90.pdf` 覆盖，如需补图不影响结论。

## S3：数据体积与解析

### 目标

- `frames` 模式：160×90、30 fps、3 分钟，RLE + base64 + Flate 后的 PDF 体积。
- `runtime` 模式：形状表 + 每帧实例的 PDF 体积。
- JS 初始化（解码 + 建字段引用）耗时。

### 通过标准

- 3 分钟谱 PDF ≤ 20 MB（frames）；runtime 明显更小。
- 初始化 ≤ 300 ms；无内存异常。
- 超过上限 → 降低 fps 或报错，不静默截断。

## S5：端到端 10 秒片段

### 目标

两种模式各生成一份 10 秒 PDF，比较：

- 实际 fps；
- PDF 体积；
- 砖形/描边/twirl/SetSpeed/拖尾/星球的可辨认度；
- HUD/按钮是否正常；
- 跳帧时时间轴是否正确（例如后台 5 秒回来，画面应对应正确时刻）。

### 通过标准

- 至少一种模式达到可用帧率（frames 优先）。
- 画面与截图风格一致（灰度砖形，不是中心线）。
- 时间轴无累积漂移。

## 已取消

- **S4（与 app 逐帧/音乐对拍）**：用户明确不需要；只保留 `timeline.csv` 供排查，
  不作为验收门槛。
