# 编译、测试与验收

> 遵循 `docs/CODING.md`：**严格编译 + 全量冒烟**两项都是强制门槛。
> 环境限制导致无法执行时，必须报告阻塞原因与实际结果，不得虚报。

## 1. 严格编译

### C++ 生成器

`pdfc.py` 首次运行会自动编译（源码哈希缓存），等价于：

```
# 1) 本项目代码：严格模式
g++ -std=c++20 -O2 -Wall -Wextra -Werror -c tools/pdf/native/chart2pdf.cpp \
    -I$ADOCAO_ROOT -isystem tools/pdf/third_party/glm -isystem tools/pdf/third_party/rapidjson

# 2) ADOCAO（ADOB-C/ADOCAO）的 18 个翻译单元：只放宽它自己的既有警告
g++ -std=c++20 -O2 -Wall -Wextra \
    -Wno-unused-parameter -Wno-unused-variable -Wno-misleading-indentation -Wno-array-bounds \
    -c <core/level/*, core/util/*, core/timeline/*, core/camera/*, render/TileGeometryReference.cpp> ...

# 3) 链接 -> build/chart2pdf
```

- 项目自有代码（`tools/pdf/native/*`）**不得**关 `-Werror`；第三方头文件走 `-isystem`。
- ADOCAO 侧只放宽 4 条：unused-parameter / unused-variable / misleading-indentation，
  以及 GCC 16 在 `std::sort` 内联里报的 `-Warray-bounds` 假阳性；全部限定在 ADOCAO 的 TU 上，
  `-w` 与全局关 `-Werror` 都不允许。
- 源文件清单就是 `pdfc.py` 的 `ADOCAO_SOURCES`（与 ADOCAO 的 core/CMakeLists.txt 对齐，去掉
  map/PNG/zlib 与 PlaybackClock）。
- `--render frames` 与 `--render runtime` 同一二进制：**v1 只实现 frames**，`--render runtime` 明确报错。
- `ADOCAO_ROOT` 环境变量可覆盖 ADOCAO 路径（默认 `../ADOCAO`）。

### Python

```
python3 -m py_compile pdfc.py tools/pdf/spike/*.py tests/*.py
```

- 只用标准库；不引入 pip 依赖。
- `zlib`/`struct`/`base64`/`json`/`subprocess`/`tempfile` 是允许的。

## 2. 单元测试

### Python（`tests/`）

现有（14 条，`python3 -m unittest discover -s tests`）：

- `test_minipdf.py`：PDF 写入器（对象表/xref/转义/数值格式化）。
- `test_scene_pdf.py`
  - `TestRle`：行 RLE 往返，含满行、交替、尾部异色、255 上限截断；
  - `TestScene`：合成 scene.bin 的头字段、帧往返、截断与 magic 错误必须报错；
  - `TestPdf`：页数/MediaBox/91 个 `/FT /Tx`/3 个 `/FT /Btn`/Type3 嵌入/`--no-hud`；
  - `TestJsPayload`：把 PDF 里那份 JS 丢给 `node` 执行，逐字符比对 Python 解出的行——
    **同一份数据的两种实现必须一致**（无 `node` 时 skip）。

### JS（`node`）

由 `TestJsPayload` 驱动：不给 PDF 引擎，只给 `getField/app/display` 桩，
验证 base64 解码、偏移表、行 RLE、HUD 取值。PDFium 的真实行为仍走人工验收（§4）。

## 3. 生成冒烟

fixture：

- **基准谱面**：`E:\0\ADOCAO\ci\level\level.adofai`（= `$ADOCAO_ROOT/ci/level/level.adofai`）
  - 60 万砖 / 16.7 MB 谱面；默认参数（`--rows 90 --fps 30 --zoom-scale 1`）下
    6209 帧、`t=[-2.07, 204.88]`、266×90、scene 8.3 MB、PDF 2.12 MiB
    （chart2pdf 6.95 s、全流程 10.1 s）；
  - 高清组合 `--rows 120 --fps 60 --play-fps 30`：12417 帧、355×120；
    `--zoom-scale 1` → PDF 5.80 MiB（chart2pdf 15.2 s、全流程 16.4 s、scene 23.6 MB），
    `--zoom-scale 2` → PDF 4.47 MiB（chart2pdf 30.1 s、scene 20.0 MB）；
  - **以后所有冒烟、体积、性能对比都以这份为基准**，换谱面要同时更新这一节的数字。
- `tests/fixtures/mini.adofai` —— 24 砖 / 120 BPM / zoom 100，仓库自带，用来跑"秒级"快速回归；
  它只保证链路通，不承担体积/性能口径。

命令：

```
python3 pdfc.py tests/fixtures/mini.adofai -o /tmp/mini.pdf                      # 秒级
python3 pdfc.py $ADOCAO_ROOT/ci/level/level.adofai -o /tmp/baseline.pdf          # 基准，约 3 s + PDF 写出
```

检查：

- 页数 = 1；MediaBox = 1280×816；`/FT /Tx` = 91；`/FT /Btn` = 3；AcroForm 存在。
- 首帧非空：`--dump-frame 0` 打出的 90 行里至少有一行不是全空格。
- 有 Poppler 时补 `pdfinfo` / `pdftoppm`；没有时用上面的字节检查，并**明确记录缺失**。
- `frames` 与 `runtime` 各一份 —— v1 只有 `frames`，runtime 显式报错。

## 4. 人工验收（Chrome PDFium）

本机没有可自动化的 PDFium，以下必须在 Chrome 桌面版执行并记录：

1. 打开 PDF；是否出现 `Start`。
2. 点击后是否开始播放；画面是否为灰度砖形。
3. HUD 是否显示时间/砖号/BPM/相机/进度。
4. 按钮是否工作（Play/Pause/Restart）。
5. 记录实际帧率与首帧延迟（大文件的 base64 解码在 JS 侧）。
6. 切到后台 5 秒再回来，画面是否跳到正确时刻（无累积漂移）。
7. `frames` 与 `runtime` 两种模式分别记录。

**未执行 Chrome 验收时，任务状态只能是“部分完成/阻塞”，不能标记完成。**

## 5. 回归清单

每次改动后至少跑：

- [ ] C++ 严格编译
- [ ] Python `py_compile` + 单测
- [ ] 3 份 fixture 生成 + `pdfinfo`
- [ ] `pdftoppm` 首帧
- [ ] 若改了 JS 模板：node 单测
- [ ] 若改了字段/字体：Chrome 人工验收

## 6. 报告口径

- 通过：列出实际执行的命令与结果。
- 阻塞：写明缺什么（如“沙箱无 Chrome，S1 未实测”），不得写“应该可以”。
- 失败：给出最小复现、根因、修复后重跑全量。
