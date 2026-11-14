# ADOPDF

把 ADOFAI 谱面（`.adofai`）编译成**单页 PDF**，在 Chrome 原生 PDFium 里播放。
PDF 内嵌一份按谱面时间轴烘焙好的灰度字符动画：轨道、星球、相机的位置/角度/缩放
全部来自 [ADOB-C/ADOCAO](https://github.com/ADOB-C/ADOCAO) 的 C++ core，不是另一套近似实现。

- 画面：默认 266×90 灰度字符网格（10 级 ramp），`--rows` 可调
- 播放：PDF JS 用墙钟取帧号，支持播放/暂停/重开；有 HUD；无音频、无颜色
- 输入：v1 只接受明文 `.adofai`；压缩容器明确报错

## 工作原理

```
level.adofai
   │
   ├─ chart2pdf（C++20，首次运行时由 pdfc.py 用 g++ 编译并缓存）
   │    LevelData → Timeline → TileAnimation → CameraTimeline
   │    逐帧：pivotStarAt → CameraDirector::drive → 相机 → 可见砖
   │    C++ 栅格化成 W×H 字符网格，行内 RLE
   │    → scene.bin（v2）
   │
   ├─ pdfc.py（Python，仅标准库）
   │    读 scene.bin → base64 载荷 → 写单页 PDF：
   │    H 个只读行字段 + HUD + 3 个按钮 + Flate 压缩的 PDF JS
   │
   └─ Chrome PDFium
        /OpenAction → 解码偏移表 → Start → app.setTimeOut 自调度
        k = floor((now - epoch) * playFps / 1000)
        RLE → 行字符串 → field.value
```

构建期做完全部谱面数学与栅格化；运行时 JS 只做 base64 解码、RLE 展开和字段赋值。

## 环境要求

| 依赖 | 说明 |
|---|---|
| Linux | 当前开发/验证平台 |
| g++ | 支持 C++20（`-std=c++20 -O2 -Wall -Wextra -Werror`） |
| Python 3 | 只用标准库，无 pip 依赖 |
| ADOCAO 源码 | 默认 `../ADOCAO`，可用环境变量 `ADOCAO_ROOT` 覆盖 |
| node（可选） | 仅 `TestJsPayload` 用它执行 PDF 里那份 JS 做对拍；没有时该测试 skip |
| Chrome 桌面版 | 人工验收 PDFium 播放行为，无法自动化 |

`tools/pdf/third_party/` 已 vendor `glm` 与 `rapidjson`（header-only），不需要 CMake、网络或 apt。

## 快速开始

```bash
cd ADOPDF

# 24 砖的小谱面，秒级出结果
python3 pdfc.py tests/fixtures/mini.adofai -o build/mini.pdf

# 基准谱面（60 万砖；需要 ADOCAO 仓库里的 ci/level/level.adofai）
python3 pdfc.py "$ADOCAO_ROOT/ci/level/level.adofai" -o build/baseline.pdf
```

首次运行会编译 `tools/pdf/native/chart2pdf`（约 18 个 ADOCAO 翻译单元），产物和源码哈希戳
放在 `build/`；源码不变时后续直接复用。用 Chrome 打开生成的 PDF，点 `Start` 播放。

## 命令行参数

```
python3 pdfc.py <level.adofai> -o <out.pdf> [选项]
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--fps N` | `30` | 烘焙帧率；帧 `k` 对应 `t_start + k/fps` |
| `--play-fps M` | `30` | PDF 里的实际播放帧率；小于 `--fps` 即慢放（`--fps 60 --play-fps 30` = 0.5×） |
| `--zoom-scale F` | `1.0` | 相机 adoZoom 的倍率；ADOB-C 口径下越大看得越远，`2` 可多看砖 |
| `--rows N` | `90` | 字符屏行数（60..400）。列数按 `floor(1280 / (0.6 × 行高))` 自动配平：90 行 → 266 列 |
| `--grid WxH` | 自动 | 显式指定网格，覆盖 `--rows` 推出的列数 |
| `--max-seconds S` | `300` | 谱面时长上限，超过报错，不静默截断 |
| `--max-frames N` | `24000` | 帧数上限，超过报错 |
| `--no-hud` | 关 | 不生成 HUD 字段（按钮仍保留） |
| `--type3` | 关 | Type3 字形后端（实验项）；默认 Courier |
| `--courier` | 开 | Courier 字形后端 |
| `--trace-csv PATH` | 关 | 输出逐帧时间线 CSV（调试） |
| `--dump-frame K` | 关 | 把第 K 帧的字符网格打到 stdout（调试） |
| `--keep-scene` | 关 | 把中间产物 `scene.bin` 复制到 `build/` |
| `--render frames\|runtime` | `frames` | v1 只实现 `frames`；`runtime` 仍为预留参数，实际不生效 |

`--play-fps` 必须满足 `1 ≤ M ≤ fps`。列数上限由 chart2pdf 的 `--grid` 校验约束为 80..2000，
行数 60..400。

## 输出 PDF

| 部分 | 内容 |
|---|---|
| 页面 | `1280×816 pt`：24 pt 上边距 + 1280×720 字符屏 + 60 pt 控制栏，`y=62` 处画分隔线 |
| 屏幕 | 90 个只读单行文本字段（`r000`..`r089`），每个字段占一行 |
| HUD | 1 个 Helvetica 9 pt 字段：时间、砖号/总数、BPM、相机 x/y、rot、zoom、进度条 |
| 控制 | `Start`、`Play / Pause`、`Restart` 三个按钮，点击触发 `/AA /U` 里的 JS |
| 数据 | `scene.bin` 以 base64 字符串嵌进 JS 流，JS 流本身走 Flate；无外部资源 |

字体默认 Courier（每字 0.6 em，列数按此配平）。`--type3` 是保留的实验后端：
PDFium 的表单外观流不一定使用 Type3 字形，可能退回替代字体，因此不作默认。

## 目录结构

```
ADOPDF/
├── docs/                       # 规格、架构、决策、测试与 spike 记录
├── pdfc.py                     # 唯一入口：编译缓存 + scene.bin → PDF
├── tools/pdf/
│   ├── native/
│   │   ├── chart2pdf.cpp       # C++ 生成器：谱面 → 相机/几何 → 字符帧
│   │   └── scene_format.h      # scene.bin v2 的字节格式
│   ├── third_party/            # vendored glm / rapidjson
│   └── spike/                  # S1/S2 最小 PDF 验证脚本
├── tests/
│   ├── fixtures/mini.adofai    # 快速冒烟谱面（24 砖）
│   ├── test_minipdf.py         # PDF 写入器单测
│   └── test_scene_pdf.py       # scene 编解码 / PDF 结构 / JS 载荷对拍
├── build/                      # 编译产物与临时文件（gitignore）
└── STATUS.md                   # 当前进展与未验证项
```

`scene.bin` v2 的关键点：小端；头 45 字节；帧偏移表后跟帧体；每行 RLE 的 run 数用 **u16**
（高分辨率下一行可能超过 255 段），run 内计数仍是 u8。

## 测试与验收

```bash
# Python 语法检查
python3 -m py_compile pdfc.py tools/pdf/spike/*.py tests/*.py

# 全部单测（14 条）
python3 -m unittest discover -s tests -v
```

- 单测覆盖：行 RLE 边界、scene 头/帧往返/截断/magic 校验、PDF 页数与字段/按钮数量、
  Type3 嵌入、`--no-hud` 行为；有 node 时还会把 PDF 里那份 JS 真跑一遍，
  与 Python 解码结果逐字符比对。
- 生成冒烟：`mini.adofai` 负责链路通；体积/性能口径以 ADOCAO 的
  `ci/level/level.adofai`（60 万砖）为基准，数字记录在 `docs/TESTING.md §3`。
- **Chrome/PDFium 人工验收尚未执行**：播放、按钮、HUD、跳帧、首帧延迟都需要在真实
  Chrome 里确认；大文件 base64 解码耗时是当前最大未知项。

严格编译（项目自有代码 `-Werror`，ADOCAO 既有代码只放宽 4 条警告）的完整命令见
`docs/TESTING.md §1`。

## 当前状态与限制

- `frames` 模式已端到端打通：C++ 生成器 + `pdfc.py` + 单页 PDF + JS 播放器。
- 运镜真实生效：`CameraDirector::drive` + `pivotStarAt` + `setHoldOffset`，逐帧顺序对齐
  ADOCAO 的 `app/GameWindow.cpp`；旋转进投影，zoom 走 `setAdoZoom` 口径。
- 基准产物（60 万砖、默认参数）：6209 帧、PDF 约 2.12 MiB、`t=[-2.07, 204.88]`。
- `runtime` 模式未实现；`--render runtime` 不产生运行时渲染。
- 无音频、无颜色、无 MoveTrack 之外的额外视觉元素；不画 Gems/Neon、Hold 带、背景闪屏。
- Chrome 人工验收未做，因此不能视为“已在目标环境验证”。

## 文档索引

事实来源按优先级排列：

1. `docs/CODING.md` —— 开发纪律与完成标准，**最高优先级**
2. `docs/DECISIONS.md` —— 已拍板决策，实现不得悄悄偏离
3. `docs/SPEC.md` —— 对外行为、参数、非目标
4. `docs/ARCHITECTURE.md` —— 构建期 / PDF / 运行期实现契约
5. `docs/SPIKES.md` —— 先于正式实现的验证项与通过标准
6. `docs/TESTING.md` —— 编译、冒烟、人工验收与报告口径

参考材料（非约束）：`docs/OPTIMIZATION-NOTES.md`（外部优化建议摘录，冲突时以冻结文档为准）。
当前进展与未验证项：`STATUS.md`。
