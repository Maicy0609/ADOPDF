# 编译、测试与验收

> 遵循 `docs/CODING.md`：**严格编译 + 全量冒烟**两项都是强制门槛。
> 环境限制导致无法执行时，必须报告阻塞原因与实际结果，不得虚报。

## 1. 严格编译

### C++ 生成器

```
g++ -std=c++20 -O2 -Wall -Wextra -Werror \
    -isystem tools/pdf/third_party/glm \
    -isystem tools/pdf/third_party/rapidjson \
    ... (core 闭包 + TileShape/TileGeometryReference + main)
```

- 项目自有代码不得关 `-Werror`；第三方头文件走 `-isystem`。
- 若 ADOCAO core 在 g++ 13 下有既有警告，先记录并最小化修正；不得用 `-w` 掩盖。
- `--render frames` 与 `--render runtime` 两个后端都必须编进同一二进制（运行时选择）。

### Python

```
python3 -m py_compile pdfc.py tools/pdf/spike/*.py tests/*.py
```

- 只用标准库；不引入 pip 依赖。
- `zlib`/`struct`/`base64`/`json`/`subprocess`/`tempfile` 是允许的。

## 2. 单元测试

### Python（`tests/`）

- `test_varint.py`：zigzag/varint 往返。
- `test_rle.py`：行 RLE 编解码，含空行/满行。
- `test_pdf_writer.py`：对象表/xref 偏移、页数、MediaBox、字段数量。
- `test_scene.py`：scene.bin 头/帧索引边界；截断必须报错。

### JS（`node`）

- `test_decode.js`：base64 → 字节 → 帧索引/行 RLE 的纯函数。
- `test_raster.js`：runtime 模式的三角形/圆/线栅格化，给定输入比对字符网格。
- 这些函数必须从 PDF JS 模板里抽出（同一份源码，避免两份实现）。

### C++

- `test_frame_time.cpp`（可选）：断言 `t_k` 单调、首尾覆盖 `[-preRoll, totalDuration]`。
- 不重复实现相机/行星数学；只测生成器的时间轴与边界。

## 3. 生成冒烟

fixture（来自 `/workspace/ADOCAO/tests/charts/`）：

- `angles360.adofai`（形状/角度覆盖）
- `camera_basic.adofai`（运镜）
- `diag_midspin.adofai`（中旋）
- `shapes_exhaustive.adofai`（砖形）
- `neon_alpha.adofai`（描边/透明度，灰度下也应可生成）

命令：

```
python3 pdfc.py /workspace/ADOCAO/tests/charts/angles360.adofai -o /tmp/angles360.pdf
pdfinfo /tmp/angles360.pdf
pdftoppm -f 1 -l 1 -png -r 72 /tmp/angles360.pdf /tmp/angles360
```

检查：

- 页数 = 1；MediaBox = 1280×768。
- `pdfinfo` 无错误；`pdftoppm` 能出图（首帧静态，不含 JS）。
- 字段数 = 90 + 1 + 3；AcroForm 存在。
- 两种模式都生成一份。

## 4. 人工验收（Chrome PDFium）

沙箱没有 Chrome，以下必须在用户桌面执行并记录：

1. 打开 PDF；是否出现 `Start`。
2. 点击后是否开始播放；画面是否为灰度砖形。
3. HUD 是否显示时间/砖号/BPM/相机/进度。
4. 按钮是否工作（Play/Pause/Restart）。
5. 记录实际 fps（S1 的 HUD 或肉眼/录屏）。
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
