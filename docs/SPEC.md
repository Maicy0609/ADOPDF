# ADOPDF 规格

## 1. 目标

输入一份 ADOFAI `.adofai` 谱面，输出一份**单页 PDF**。用户用 Chrome 原生 PDFium 打开，
PDF 内嵌 JS 按谱面时间轴播放：

- 轨道、星球、相机的位置/角度/时间**与 ADOCAO 的 C++ core 同源**，不是近似重写。
- 画面为 160×90 灰度字符网格（10 级 ramp），低分辨率但实时。
- 支持播放/暂停/重开；有 HUD；无音频；无颜色。

## 2. 输入

```
pdfc.py <level.adofai> -o <out.pdf> [选项]
```

v1 只接受明文 `.adofai`。`.adofai.xz`、`.adofai.zst`、`.ilytx`、`.adocao` 直接报错：
“本版本只支持明文 .adofai（压缩容器需要 archive 后端）”。

## 3. 输出

单页 PDF：

| 部分 | 内容 |
|---|---|
| 页面 | 1280×816 pt；24 pt 上边距 + 1280×720 字符屏（160×90 个 8×8 pt 格）+ 60 pt 控制栏（见 D12） |
| 屏幕 | 90 个只读单行文本字段，每行一个 |
| HUD | 1 个文本字段：时间、砖号/总数、BPM、相机 x/y/rot/zoom、进度条 |
| 控制 | `Start`、`Play/Pause`、`Restart` 三个按钮 |
| JS | `/OpenAction` 初始化；`app.setTimeOut` 自调度；无外部资源 |

## 4. 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--render frames\|runtime` | `frames` | 构建期字符帧 / 运行时渲染，见 D3 |
| `--fps N` | 30（S1 已确认，见 D10） | bake fps；固定时间轴 |
| `--play-fps M` | 30 | PDF 里的播放帧率；小于 `--fps` 即慢放（`--fps 60 --play-fps 30` = 0.5×，见 D13） |
| `--zoom-scale F` | 1.0 | 相机 adoZoom 的倍率；ADOB-C 口径下 >1 = 看得更远（见 D11） |
| `--rows N` | 90 | 字符屏行数（60..180），列数按 8pt 等宽自动配平；90 行 → 266 列（见 D13） |
| `--grid WxH` | 自动 | 显式覆盖列数；默认由 `--rows` 推出 |
| `--max-seconds S` | 300 | 超过则报错，不静默截断 |
| `--max-frames N` | 24000 | 超过则报错 |
| `--no-hud` | 关 | 隐藏 HUD（按钮仍保留） |
| `--type3\|--courier` | `--courier` | 字形后端；Type3 用连续码 48–57（见 D12），编码写错会被 PDFium 丢弃 |
| `--trace-csv` | 关 | 输出 `timeline.csv`（调试用，不是验收门槛） |

## 5. 视觉契约

| 元素 | 灰度级 | 字符 |
|---|---|---|
| 背景 | 0 | 空格 |
| 砖填充 | 4 | `=` |
| 砖描边 | 8 | `#` |
| twirl 圆点 | 9 | `@` |
| SetSpeed 圆点 | 6 | `O` |
| 枢轴星球 | 9 | `@` |
| 移动星球 | 6 | `*` |
| 拖尾（枢轴/移动） | 3 / 2 | `-` / `.` |
| HUD | 独立字段 | 白色 Helvetica |

- 砖形：`TileShape` 的 ARC/BIG/ZERO/MIDSPIN；Standard 宽/长；不画 Gems/Neon。
- 绘制顺序：砖按楼层**倒序**（大 → 小，和原版 `renderOrder=-tileIndex` 一致）；
  每块砖先填充后描边；再拖尾；最后星球。
- 不做抗锯齿；160×90 下用格子边界即可。若要改善曲线，可在 C++ 栅格化时做 2×2 覆盖，
  但两种模式的栅格化规则必须一致。

## 6. 运行时契约

- 只用 `getField(name).value` 更新画面；`Start` 按钮点击后用一次 `display.hidden`。
- 不使用 `fillColor/textColor/rotation/buttonSetIcon/rect`。
- 帧号由墙钟计算，不累加：
  `k = floor((Date.now() - epochMs) * fps / 1000)`。
- 到 `k >= frameCount` 停在最后一帧，并停止计时器。
- 暂停：清定时器；继续：`epochMs = Date.now() - k/fps*1000`。
- 重开：`k=0`，`epochMs = Date.now()`。
- HUD 每帧更新一次（一个字段）。
- 背景/字段颜色全部构建期固定；运行时不改色。

## 7. 非目标

- 颜色、音量砖色、背景闪屏、装饰物、Hold 带、音频。
- PDF.js 专有 API；运行时文件/网络/DOM。
- 编辑、导出图片/视频、交互式拖动相机。
- 逐帧与原版抓帧做像素对拍（只保证时间轴与数学同源）。

## 8. 完成定义（DoD）

1. `g++ -std=c++20 -O2 -Wall -Wextra -Werror` 编译通过（第三方头文件走 `-isystem`）。
2. `python3 -m py_compile` + Python 单测全绿。
3. 生成冒烟：至少 3 份 fixture 谱面生成 PDF，`pdfinfo` 页数/尺寸正确，`pdftoppm` 首帧可渲染。
4. S1/S2 的 Chrome 实测数据归档在 `docs/SPIKES.md`（无 Chrome 的环境必须明确报告未验证）。
5. 两种模式都能生成；至少一种在目标机器上达到可用帧率。
