#pragma once

// scene.bin 的落盘格式。字段语义见 docs/ARCHITECTURE.md §2.6；
// 本文件是可编译的落地点（文档只约束语义，这里约束字节）。
//
// 全部小端。结构：
//   "ADPF" u16 version u8 mode u16 W u16 H u16 fps u32 frameCount
//   f64 tStart f64 tEnd f32 zoomScale u32 tileCount f32 baseBpm
//   u32 offsets[frameCount]         // 相对 frameDataStart 的字节偏移
//   frame blobs...
//
// frames 模式的每帧 blob：
//   f32 t  u16 tile  f32 bpm  f32 camX  f32 camY  f32 zoom
//   u8 hudLen  char hud[hudLen]
//   H × { u16 runs, runs × (u8 level, u8 count) }

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace adpdf {

constexpr uint16_t kVersion = 2;   // v2: 行 RLE 的 run 数改成 u16（高分辨率下一行可超 255 段）
constexpr char kMagic[4] = {'A', 'D', 'P', 'F'};

enum Mode : uint8_t {
    kModeFrames  = 0,  // 构建期字符帧
    kModeRuntime = 1,  // 形状表 + 每帧实例（v1 未实现）
};

struct Header {
    uint8_t  mode       = kModeFrames;
    uint16_t width      = 160;
    uint16_t height     = 90;
    uint16_t fps        = 30;
    uint32_t frameCount = 0;
    double   tStart     = 0.0;
    double   tEnd       = 0.0;
    float    zoomScale  = 1.0f;
    uint32_t tileCount  = 0;
    float    baseBpm    = 0.0f;
};

// 小端写入器。scene.bin 只在同机生成同机读取，但仍显式按字节写，避免对齐差异。
class Writer {
public:
    explicit Writer(std::vector<uint8_t>& out) : m_out(out) {}

    void u8(uint8_t v)  { m_out.push_back(v); }
    void u16(uint16_t v) { u8((uint8_t)(v & 0xFF)); u8((uint8_t)(v >> 8)); }
    void u32(uint32_t v) {
        u8((uint8_t)(v & 0xFF)); u8((uint8_t)((v >> 8) & 0xFF));
        u8((uint8_t)((v >> 16) & 0xFF)); u8((uint8_t)((v >> 24) & 0xFF));
    }
    void f32(float v) {
        uint32_t bits = 0;
        std::memcpy(&bits, &v, 4);
        u32(bits);
    }
    void f64(double v) {
        uint64_t bits = 0;
        std::memcpy(&bits, &v, 8);
        u32((uint32_t)(bits & 0xFFFFFFFFu));
        u32((uint32_t)(bits >> 32));
    }
    void bytes(const void* p, size_t n) {
        const uint8_t* b = (const uint8_t*)p;
        m_out.insert(m_out.end(), b, b + n);
    }

private:
    std::vector<uint8_t>& m_out;
};

inline void putHeader(Writer& w, const Header& h) {
    w.bytes(kMagic, 4);
    w.u16(kVersion);
    w.u8(h.mode);
    w.u16(h.width);
    w.u16(h.height);
    w.u16(h.fps);
    w.u32(h.frameCount);
    w.f64(h.tStart);
    w.f64(h.tEnd);
    w.f32(h.zoomScale);
    w.u32(h.tileCount);
    w.f32(h.baseBpm);
}

inline bool writeFile(const std::string& path, const std::vector<uint8_t>& data, std::string& err) {
    FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) { err = "cannot open output for writing: " + path; return false; }
    size_t n = std::fwrite(data.data(), 1, data.size(), f);
    std::fclose(f);
    if (n != data.size()) { err = "short write: " + path; return false; }
    return true;
}

}  // namespace adpdf
