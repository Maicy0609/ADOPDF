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

## 当前状态

- 设计已冻结（2026-11-12）。
- S1/S2 最小 PDF 已生成并通过沙箱静态校验；**Chrome/PDFium 实测未完成，S1/S2 未通过**。
- 正式生成器未开始。详细事实见根目录 `STATUS.md` 与 `docs/SPIKES.md`。
- 下一步：用户在 Chrome 回填 S1 吞吐与 S2 Type3 结果，再定 `--fps` / 字体后端。

## 目录规划

```
ADOPDF/
├── docs/
├── pdfc.py                 # Python 编译器前端（唯一入口）
├── tools/pdf/
│   ├── native/             # C++ 生成器（链接 ADOCAO core）
│   ├── third_party/        # vendored glm / rapidjson（header-only）
│   └── spike/              # S1/S2 最小 PDF
└── tests/                  # Python 单测 + 生成冒烟
```
