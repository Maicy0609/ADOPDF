# ADOPDF 文档索引

把 ADOFAI `.adofai` 谱面编译成**单页 PDF**，在 Chrome 原生 PDFium 里播放。
画面是 160×90 灰度字符网格；轨道/星球/相机的数学来自 ADOCAO 的 C++ core。

## 事实来源顺序

1. `docs/CODING.md` —— 开发纪律与完成标准，**最高优先级**。
2. `docs/DECISIONS.md` —— 已拍板的决策，不允许在实现里悄悄偏离。
3. `docs/SPEC.md` —— 对外行为、参数、非目标。
4. `docs/ARCHITECTURE.md` —— 构建期 / PDF / 运行期的实现契约。
5. `docs/SPIKES.md` —— 先于正式实现的验证项与通过标准。
6. `docs/TESTING.md` —— 编译、冒烟、人工验收与报告口径。

## 参考材料（非约束）

- `docs/OPTIMIZATION-NOTES.md` —— 外部优化建议摘录；仅参考，冲突时以冻结文档为准。

## 当前状态

- 设计已冻结（2026-11-12）。
- S1/S2 已通过 Chrome 实测（2026-11-13）：160×90 Courier 49.8 fps；Type3 渲染可用但慢 3.4×。
- 默认值已定：`--fps 30`、字体后端 Courier（D10）。
- 正式生成器未开始。详细事实见根目录 `STATUS.md` 与 `docs/SPIKES.md`。
- 下一步：实现 `chart2pdf` + `pdfc.py`（先 `frames` 模式），再跑 S3/S5。

## 目录规划

```
ADOPDF/
├── docs/
├── pdfc.py                 # Python 编译器前端（唯一入口）
├── tools/pdf/
│   ├── native/             # chart2pdf（C++，链接 ADOCAO core）+ scene_format.h
│   ├── third_party/        # vendored glm / rapidjson（header-only）
│   └── spike/              # S1/S2 最小 PDF
└── tests/
    ├── fixtures/           # mini.adofai（快速冒烟）
    └── *.py               # Python 单测（含 JS 载荷对拍）
```
