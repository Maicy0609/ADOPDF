# 架构与实现契约

## 1. 总管线

```
level.adofai
  │
  ├─ chart2pdf（C++，g++ 编译，链接 ADOCAO core）
  │    LevelData → Timeline → TileAnimation → CameraTimeline
  │    逐帧 t_k：pivotStarAt → CameraDirector::drive → 相机
  │    可见砖 → TileShape::buildShape/expand/indexTable → 屏幕三角形
  │    拖尾/星球/图标 → 屏幕图元
  │    ├─ --render frames  : C++ 栅格化成 160×90 字符网格 → 行 RLE
  │    └─ --render runtime : 形状表 + 每帧砖实例/图元
  │    → scene.bin
  │
  ├─ pdfc.py（Python，标准库）
  │    读 scene.bin → base64/varint → PDF JS
  │    写单页：90 行字段 + HUD + 按钮 + Type3/Courier + Flate
  │
  └─ Chrome PDFium
       /OpenAction → 解码 → Start → app.setTimeOut 自调度
       k = floor((now-epoch)*fps/1000)
       frames  : RLE → 行字符串 → field.value
       runtime : 形状表 + 实例 → 三角形栅格化 → 行字符串 → field.value
```

## 2. C++ 生成器

### 2.1 链接闭包

只链接 ADOCAO `core` 的纯逻辑：

`LevelData`、`Timeline`、`PositionSolver`、`TileAnimation`、`TileXform`、
`CameraTimeline`、`CameraDirector`、`Easing`、`Logger`、`MappedFile`、
`ByteSource`、`JsonCleaner`、`JsonScan`、`AngleStore`、`FloorWindow`、
`Scheduler`、`Env`、`CountLimits`、`Progress`、`LevelPath`。

再加 `render/TileShape.cpp`、`render/TileGeometryReference.cpp`、`render/TileGeometry.hpp`。

**不链接**：GL、GLFW、ImGui、miniaudio、stb_vorbis、archive 的 zstd/lzma。
`ByteSource` 的 `ArchiveBackend` 保持空；压缩容器返回明确错误。

### 2.2 帧循环（顺序不能换）

```
t = -preRoll
resetDrive()
for k in 0..N-1:
    t = t_start + k / fps
    pivot, hold = PositionSolver::pivotStarAt(t, anim)
    bpm = tileBPMs[clamp(findTileIndex(t), 0, n-2)]
    pitch = max(0.1, settings.pitch/100)
    cameraDirector.setHoldOffset(hold)
    cameraDirector.drive(t, 1/fps, bpm, pitch, pivotX, pivotY, tileIdx)
    camX/Y = cameraDirector.x()/y()
    rot = cameraDirector.rotation()
    adoZoom = cameraDirector.zoom() * zoomScale
    planets = PositionSolver::planetsAt(t, anim)
    trails = sampleTrail(t, ...)
    visible = CullIndex / 可见砖
```

- `t_start = -preRoll`；`t_end = totalDuration()`。
- `frameCount = floor((t_end - t_start) * fps) + 1`，上限 `--max-frames`。
- 第一帧 `drive` 会走 `seek`（`m_driveActive=false`），与原版首帧一致。
- 不调用 `PlaybackClock`；时间直接由 `t_k` 给出，避免音频/墙钟影响。
- `zoomScale` 只乘在 `CameraDirector::zoom()` 上；位置/旋转不变。

### 2.3 砖几何

每块可见砖：

1. `TileShape::keyForTile(level, i, sa, ea, mid)`。
2. `key = (quantize(sa), quantize(ea), mid)`；`buildShape(sa, ea, mid, TILE_WIDTH, TILE_LENGTH, false)`。
3. `TileShape::expand(shape, expanded)` → 局部顶点 + `type`（0 描边 / 1 填充）。
4. `TileShape::indexTable()` → 三角形。
5. 变换（照 `tile.vert`）：
   - MoveTrack：`rot/scaleX/scaleY/move`（绕局部原点）。
   - 世界位置：`tilePositionAt(i) + move`。
   - 相机：`screen = project(world, cam, rot, adoZoom)`。
6. 填充三角形先画，描边三角形后画。
7. 图标：twirl → `@`，SetSpeed → `O`，画在砖起点（接缝）处。

**相机投影**（C++ 唯一实现）：

```
halfH = 5.47 * adoZoom / 200
halfW = halfH * (W / H)
dx = x - camX; dy = y - camY
rx =  dx*cosθ + dy*sinθ
ry = -dx*sinθ + dy*cosθ
sx = (rx/halfW * 0.5 + 0.5) * W
sy = (ry/halfH * 0.5 + 0.5) * H
```

`θ` 为 `CameraDirector::rotation()`（度→弧度）。

### 2.4 拖尾 / 星球

- 拖尾：`sampleTrail`，窗口 0.3–0.4 s，采样 60–120 Hz；屏幕折线，灰度 3/2。
- 星球：`planetsAt(t)`，屏幕圆，半径约 0.25 砖；id 0 = 枢轴（9），id 1 = 移动（6），其余 7。
- 绘制顺序：砖 → 拖尾 → 星球。

### 2.5 栅格化契约（两种模式共用）

- 网格 `W×H`；格 `(x,y)` 覆盖 `[x,x+1)×[y,y+1)`，采样点为格中心。
- 三角形：边函数在中心求值；三边同号（含 0）则写入。
- 不做抗锯齿；后画覆盖先画。
- 砖顺序：楼层倒序；砖内填充→描边；图标在描边后；拖尾在砖后；星球最后。
- 灰度级见 `SPEC.md` §5。
- `frames` 模式：C++ 用上述规则生成字符网格。
- `runtime` 模式：JS 用**同一规则**生成字符网格；C++ 只提供形状表和屏幕变换。

### 2.6 scene.bin

固定 little-endian；具体字段在 `tools/pdf/native/scene_format.h` 落地，文档只约束语义：

- Header：magic `ADPF`、version、mode、W/H、fps、frameCount、t_start、t_end、zoomScale。
- `runtime` 形状表：唯一形状数；每形状三角形数；三角形 `(x0,y0,x1,y1,x2,y2,layer)`，局部坐标量化到 1/256 砖。
- 每帧索引：offset 数组。
- 每帧：
  - 元数据：t、tile、bpm、camX/Y、rot、adoZoom（HUD 用）。
  - `frames`：90 行 RLE `(level,count)`。
  - `runtime`：砖实例 `(sx,sy,scaleX,scaleY,rot,shapeId,icon)`；拖尾折线；星球圆。
- 坐标量化到 0.25 格；varint + zigzag。
- 帧数/体积上限在 Python 端再判一次。

### 2.7 timeline.csv（调试）

`k,t,tile,bpm,camX,camY,rot,adoZoom,pivotX,pivotY,redX,redY,blueX,blueY`。
只用于排查，不作为验收门槛。

## 3. Python 前端

### 3.1 职责

- 解析 CLI；校验谱面扩展名/大小。
- 首次运行编译 `chart2pdf`：`g++ -std=c++20 -O2 -Wall -Wextra -Werror`，
  `-isystem third_party/glm`、`-isystem third_party/rapidjson`；缓存按源文件哈希。
- 运行 `chart2pdf`，读 `scene.bin`。
- 生成 PDF：对象表、xref、字段、字体、JS、Flate。
- 输出统计：帧数、PDF 字节数、生成耗时。

### 3.2 PDF 结构

- Catalog → Pages → 单 Page。
- Page `/MediaBox [0 0 1280 768]`；内容流画黑底和分隔线。
- `/Annots`：90 个行字段 + HUD + 3 个按钮。
- `/AcroForm /Fields` 同上；`/DR /Font` 放 Type3 或 Courier。
- `/OpenAction` JS 初始化；按钮 `/AA /U`。
- 行字段：
  - `/FT /Tx`、`/Ff 1`（只读）、`/BS /W 0`、`/MK /BG [0 0 0]`。
  - `/DA (/Block 8 Tf 1 1 1 rg)`（Type3）或 `/Cour 8 Tf ...`（Courier）。
  - `Rect [0, y, 1280, y+8]`。
- Type3 字体：10 个字形（密度 0–9），`FontMatrix [1 0 0 1 0 0]`，`Widths` 全 1。
- HUD：Helvetica 9pt 白色。
- 按钮：pushbutton，静态 caption，`/AA /U << /S /JavaScript /JS (...) >>`。
- JS 流用 `/Filter /FlateDecode`。

## 4. 运行时 JS

### 4.1 公共

```
var D = this;
var FPS, W, H, N, T0;
var epochMs = 0, idx = -1, playing = false, timer = null;

function kForNow() {
  var k = Math.floor((Date.now() - epochMs) * FPS / 1000);
  return k < 0 ? 0 : (k >= N ? N - 1 : k);
}
```

- 自调度 `app.setTimeOut("tick()", delay)`，不用 `setInterval`。
- `delay` 至少 1 ms；建议 `1000/FPS`，慢帧时跳帧。
- `tick()`：若 `k !== idx`，`draw(k)`；到末尾停止；否则继续调度。
- 暂停/继续/重开按 `SPEC.md` §6。

### 4.2 frames 模式

```
draw(k):
  for r in 0..H-1:
    s = ""
    for each (level,count) in RLE[row]:
      s += RAMP[level].substring(0, count)   // 预生成 CH[n] 更省
    F[r].value = s
  HUD.value = format(k)
```

- 预生成 `CH[10][W+1]`：`CH[level]` 是长度为 W 的该字符重复串；取 `substring(0,count)`。
- 只在行字符串与上一帧不同时写 `value`。

### 4.3 runtime 模式

```
draw(k):
  grid = Uint8Array(W*H)
  for each tile instance:
    for each triangle in shapeTable[shapeId]:
      p = transform(triangle, sx, sy, scaleX, scaleY, rot)
      rasterizeTriangle(grid, p, level)
  draw trails / planets
  grid -> row strings -> field.value
```

- 三角形变换：`p = R(rot) * (local * (scaleX,scaleY)) + (sx,sy)`。
- 栅格化规则与 C++ 完全一致（§2.5）。
- 形状表只读，启动时解码一次；每帧只解码实例/图元。

### 4.4 HUD

- 预格式化每帧 HUD 字符串放在元数据里；JS 直接写 HUD 字段。
- 或 JS 用 `t/tile/bpm/cam/zoom` 格式化；二者选一，v1 用预格式化，避免运行时精度争议。
- 进度条：`[####----]`，按 `k/(N-1)` 生成。

## 5. 错误处理

| 情况 | 行为 |
|---|---|
| 非 `.adofai` / 压缩容器 | Python 报错；C++ `ByteSource` 空后端明确失败 |
| 谱面无砖 / 解析失败 | 报错，不生成空 PDF |
| 超过 `--max-seconds` / `--max-frames` | 报错，不静默截断 |
| Type3 不可用 | 回退 Courier，日志写明 |
| PDF 写入失败 | 非零退出，保留临时文件路径供排查 |
| 运行时 JS 异常 | `console.println` + HUD 显示错误；不静默黑屏 |

## 6. 不变量

1. 运行时绝不重算谱面数学；所有位置/角度/时间来自 C++。
2. 帧 `k` 的画面只由 `t_k` 决定；与墙钟、音频、上一帧无关。
3. 两种模式共享同一 `t_k`、同一网格、同一灰度、同一 HUD。
4. 运行时不改颜色/不移动字段/不换图标。
5. 生成器不链接 GL/音频/窗口库。
