// chart2pdf —— ADOFAI 谱面 -> 字符网格 -> scene.bin
//
// 数学全部来自 ADOB-C/ADOCAO：LevelData / Timeline / TileAnimation / TileXform /
// PositionSolver / CameraTimeline / CameraDirector，砖形来自 render/TileGeometry.hpp
// 的 CPU 参考实现（createTileMesh / createMidSpinMesh）。本文件只负责：
// 逐帧驱动相机、裁剪、屏幕变换、栅格化、RLE。契约见 docs/ARCHITECTURE.md §2。

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <functional>
#include <map>
#include <string>
#include <tuple>
#include <unordered_map>
#include <vector>

#include "core/camera/CameraDirector.hpp"
#include "core/camera/CameraTimeline.hpp"
#include "core/level/LevelData.hpp"
#include "core/timeline/PositionSolver.hpp"
#include "core/timeline/TileAnimation.hpp"
#include "core/timeline/TileXform.hpp"
#include "core/timeline/Timeline.hpp"
#include "render/TileGeometry.hpp"
#include "scene_format.h"

namespace {

using namespace adofai;

constexpr const char* kRamp = " .:-=+*#%@";  // 10 级，与 docs/SPEC.md §5 一致

constexpr int kLvFill    = 4;
constexpr int kLvStroke  = 8;
constexpr int kLvTwirl   = 9;
constexpr int kLvSpeed   = 6;
constexpr int kLvPivot   = 9;
constexpr int kLvMoving  = 6;
constexpr int kLvTrailPv = 3;
constexpr int kLvTrailMv = 2;

constexpr double kPlanetRadius = 0.25;
constexpr double kIconRadius   = 0.11;   // assets/shaders/tile.frag 的 kIconRadius
constexpr float kTrailDuration   = 0.4f;
constexpr float kTrailSampleRate = 200.0f;

// Camera::setAdoZoom 的换算：halfH = 6 / (m_zoom/100)，m_zoom = (120000/5.47) / adoZoom
// => halfH = 5.47 * adoZoom / 200。adoZoom 越大看得越远（ADOFAI 口径）。
constexpr double kHalfHPerAdoZoom = 5.47 / 200.0;

struct Options {
    std::string levelPath;
    std::string outPath;
    std::string traceCsv;
    int  fps        = 30;
    float zoomScale = 1.0f;
    int  width      = 266;
    int  height     = 90;
    double maxSeconds = 300.0;
    int  maxFrames  = 24000;
    bool noHud      = false;
    int  dumpGrid   = -1;
    bool quiet      = false;
};

struct Grid {
    int w = 266, h = 90;
    std::vector<uint8_t> cells;

    Grid(int w_, int h_) : w(w_), h(h_), cells((size_t)w_ * h_, 0) {}
    void clear() { std::fill(cells.begin(), cells.end(), (uint8_t)0); }
    void put(int x, int y, int level) {
        if (x < 0 || y < 0 || x >= w || y >= h) return;
        cells[(size_t)y * w + x] = (uint8_t)level;
    }
};

struct CachedGeo {
    std::vector<float> xy;
    std::vector<uint8_t> type;
    std::vector<unsigned> idx;
    double minX = 0, minY = 0, maxX = 0, maxY = 0;
};

using GeoKey = std::tuple<int, int, bool>;
std::map<GeoKey, CachedGeo> g_geoCache;

const CachedGeo& geoFor(float startAngle, float endAngle, bool mid) {
    GeoKey key((int)std::round(startAngle * 100.0f), (int)std::round(endAngle * 100.0f), mid);
    auto it = g_geoCache.find(key);
    if (it != g_geoCache.end()) return it->second;

    Scratch sc;   // 新仓库的 Scratch 由调用方持有（旧的全局 g_sc 已删）
    if (mid) createMidSpinMesh(endAngle, sc);
    else     createTileMesh(startAngle, endAngle, sc);

    CachedGeo geo;
    size_t vc = sc.verts.size() / 3;
    geo.xy.resize(vc * 2);
    geo.type.resize(vc);
    for (size_t i = 0; i < vc; i++) {
        geo.xy[i * 2 + 0] = sc.verts[i * 3 + 0];
        geo.xy[i * 2 + 1] = sc.verts[i * 3 + 1];
        geo.type[i] = sc.types[i] < 0.5f ? 0 : 1;
    }
    geo.idx.assign(sc.indices.begin(), sc.indices.end());
    double mnX = 1e30, mnY = 1e30, mxX = -1e30, mxY = -1e30;
    for (size_t i = 0; i < vc; i++) {
        mnX = std::min(mnX, (double)geo.xy[i * 2 + 0]);
        mxX = std::max(mxX, (double)geo.xy[i * 2 + 0]);
        mnY = std::min(mnY, (double)geo.xy[i * 2 + 1]);
        mxY = std::max(mxY, (double)geo.xy[i * 2 + 1]);
    }
    geo.minX = mnX; geo.minY = mnY; geo.maxX = mxX; geo.maxY = mxY;
    return g_geoCache.emplace(key, std::move(geo)).first->second;
}

// ---------------------------------------------------------------- 相机

struct CameraView {
    double camX = 0, camY = 0;
    double rotRad = 0.0;
    double cosR = 1.0, sinR = 0.0;
    double halfH = 6.0, halfW = 6.0;
    int w = 266, h = 90;

    // 与 render/Camera 的 proj = ortho * R(-θ) 同构：顶点先按相机反旋转，再正交缩放。
    void project(double x, double y, double& sx, double& sy) const {
        double dx = x - camX, dy = y - camY;
        double rx =  dx * cosR + dy * sinR;
        double ry = -dx * sinR + dy * cosR;
        sx = (rx / halfW * 0.5 + 0.5) * w;
        sy = (1.0 - (ry / halfH * 0.5 + 0.5)) * h;
    }
};

// ---------------------------------------------------------------- 栅格化

inline double edgeFn(double ax, double ay, double bx, double by, double px, double py) {
    return (bx - ax) * (py - ay) - (by - ay) * (px - ax);
}

void drawTriangle(Grid& g, double x0, double y0, double x1, double y1,
                  double x2, double y2, int level) {
    double mnX = std::min(x0, std::min(x1, x2));
    double mxX = std::max(x0, std::max(x1, x2));
    double mnY = std::min(y0, std::min(y1, y2));
    double mxY = std::max(y0, std::max(y1, y2));

    int ix0 = (int)std::floor(mnX), ix1 = (int)std::ceil(mxX);
    int iy0 = (int)std::floor(mnY), iy1 = (int)std::ceil(mxY);
    if (ix1 < 0 || iy1 < 0 || ix0 >= g.w || iy0 >= g.h) return;
    ix0 = std::max(ix0, 0); iy0 = std::max(iy0, 0);
    ix1 = std::min(ix1, g.w - 1); iy1 = std::min(iy1, g.h - 1);

    for (int y = iy0; y <= iy1; y++) {
        double py = y + 0.5;
        for (int x = ix0; x <= ix1; x++) {
            double px = x + 0.5;
            double w0 = edgeFn(x1, y1, x2, y2, px, py);
            double w1 = edgeFn(x2, y2, x0, y0, px, py);
            double w2 = edgeFn(x0, y0, x1, y1, px, py);
            bool pos = (w0 >= 0 && w1 >= 0 && w2 >= 0);
            bool neg = (w0 <= 0 && w1 <= 0 && w2 <= 0);
            if (pos || neg) g.put(x, y, level);
        }
    }
}

void drawDisk(Grid& g, const CameraView& cam, double wx, double wy, double radius, int level) {
    double sx, sy, sx2, sy2;
    cam.project(wx, wy, sx, sy);
    cam.project(wx + radius, wy, sx2, sy2);
    double r = std::fabs(sx2 - sx);
    if (r < 0.35) r = 0.35;
    int x0 = (int)std::floor(sx - r), x1 = (int)std::ceil(sx + r);
    int y0 = (int)std::floor(sy - r), y1 = (int)std::ceil(sy + r);
    for (int y = y0; y <= y1; y++)
        for (int x = x0; x <= x1; x++) {
            double dx = (x + 0.5) - sx, dy = (y + 0.5) - sy;
            if (dx * dx + dy * dy <= r * r) g.put(x, y, level);
        }
}

void drawPolyline(Grid& g, const CameraView& cam, const std::vector<glm::dvec2>& pts, int level) {
    for (size_t i = 1; i < pts.size(); i++) {
        double ax, ay, bx, by;
        cam.project(pts[i - 1].x, pts[i - 1].y, ax, ay);
        cam.project(pts[i].x, pts[i].y, bx, by);
        double dx = bx - ax, dy = by - ay;
        double len = std::sqrt(dx * dx + dy * dy);
        int steps = (int)std::ceil(len * 2.0);
        if (steps < 1) steps = 1;
        if (steps > 4000) steps = 4000;
        for (int s = 0; s <= steps; s++) {
            double t = (double)s / (double)steps;
            g.put((int)std::floor(ax + dx * t), (int)std::floor(ay + dy * t), level);
        }
    }
}

// ---------------------------------------------------------------- 砖索引

constexpr double kBucketSize = 1.0;

struct TileRec {
    double x = 0, y = 0;
    const CachedGeo* geo = nullptr;
};

class TileIndex {
public:
    void build(const LevelData& level, int64_t brickCount) {
        m_tiles.clear();
        m_tiles.resize((size_t)brickCount);
        m_buckets.clear();
        for (int64_t i = 0; i < brickCount; i++) {
            const float sa = (i == 0) ? -180.0f : level.tiles[(size_t)i - 1].direction - 180.0f;
            const float ea = level.tiles[(size_t)i].direction;
            const bool mid = (i < (int64_t)level.angleData.size() &&
                              level.angleData[(size_t)i] == 999.0);
            const CachedGeo& geo = geoFor(sa, ea, mid);

            TileRec& rec = m_tiles[(size_t)i];
            const auto p = level.tilePositionAt(i);
            rec.x = p[0]; rec.y = p[1];
            rec.geo = &geo;

            // 动画会把砖搬走：桶按"静态位置 ± 2 砖"铺，覆盖常规 MoveTrack 幅度
            const int bx0 = cellOf(rec.x + geo.minX - 2.0), bx1 = cellOf(rec.x + geo.maxX + 2.0);
            const int by0 = cellOf(rec.y + geo.minY - 2.0), by1 = cellOf(rec.y + geo.maxY + 2.0);
            for (int by = by0; by <= by1; by++)
                for (int bx = bx0; bx <= bx1; bx++)
                    m_buckets[bucketKey(bx, by)].push_back((int)i);
        }
    }

    void gather(double cx, double cy, double halfW, double halfH, std::vector<int>& out) const {
        out.clear();
        const double reach = std::sqrt(halfW * halfW + halfH * halfH) + 2.0;
        int bx0 = cellOf(cx - reach), bx1 = cellOf(cx + reach);
        int by0 = cellOf(cy - reach), by1 = cellOf(cy + reach);
        if ((long long)(bx1 - bx0 + 1) * (by1 - by0 + 1) > 200000) return;
        for (int by = by0; by <= by1; by++)
            for (int bx = bx0; bx <= bx1; bx++) {
                auto it = m_buckets.find(bucketKey(bx, by));
                if (it == m_buckets.end()) continue;
                for (int ti : it->second) out.push_back(ti);
            }
        std::sort(out.begin(), out.end(), std::greater<int>());
        out.erase(std::unique(out.begin(), out.end()), out.end());
    }

    const TileRec& at(int i) const { return m_tiles[(size_t)i]; }

private:
    static int cellOf(double v) { return (int)std::floor(v / kBucketSize); }
    static uint64_t bucketKey(int bx, int by) {
        return ((uint64_t)(uint32_t)bx << 32) | (uint64_t)(uint32_t)by;
    }

    std::vector<TileRec> m_tiles;
    std::unordered_map<uint64_t, std::vector<int>> m_buckets;
};

void drawTile(Grid& g, const CameraView& cam, const CachedGeo& geo, const TileXform& xf,
              double wx, double wy) {
    const size_t vc = geo.xy.size() / 2;
    thread_local std::vector<double> sx, sy;
    sx.resize(vc); sy.resize(vc);

    const double cs = std::cos(xf.rot), sn = std::sin(xf.rot);
    for (size_t i = 0; i < vc; i++) {
        double lx = (double)geo.xy[i * 2] * xf.scaleX;
        double ly = (double)geo.xy[i * 2 + 1] * xf.scaleY;
        double rx = lx * cs - ly * sn + wx;
        double ry = lx * sn + ly * cs + wy;
        cam.project(rx, ry, sx[i], sy[i]);
    }
    for (size_t i = 0; i + 2 < geo.idx.size(); i += 3) {
        unsigned a = geo.idx[i], b = geo.idx[i + 1], c = geo.idx[i + 2];
        if (a >= vc || b >= vc || c >= vc) continue;
        int level = geo.type[a] ? kLvFill : kLvStroke;
        drawTriangle(g, sx[a], sy[a], sx[b], sy[b], sx[c], sy[c], level);
    }
}

// ---------------------------------------------------------------- 输出

struct RowRle { std::vector<uint8_t> pairs; };

void rleRows(const Grid& g, std::vector<RowRle>& out) {
    out.resize((size_t)g.h);
    for (int y = 0; y < g.h; y++) {
        RowRle& r = out[(size_t)y];
        r.pairs.clear();
        const uint8_t* row = &g.cells[(size_t)y * g.w];
        int x = 0;
        while (x < g.w) {
            uint8_t lv = row[x];
            int n = 1;
            while (x + n < g.w && row[x + n] == lv && n < 255) n++;
            r.pairs.push_back(lv);
            r.pairs.push_back((uint8_t)n);
            x += n;
        }
    }
}

std::string formatHud(double t, int64_t tile, int64_t tileCount, double bpm,
                      const CameraView& cam, double zoom, double rot, int k, int frames) {
    char buf[256];
    int filled = (frames > 1) ? (int)std::floor((double)k / (double)(frames - 1) * 12.0 + 0.5) : 12;
    if (filled < 0) filled = 0;
    if (filled > 12) filled = 12;
    std::string bar;
    for (int i = 0; i < 12; i++) bar += (i < filled) ? '#' : '-';
    std::snprintf(buf, sizeof(buf),
                  "t=%7.2fs  tile=%lld/%lld  bpm=%4.0f  cam=%.2f,%.2f  rot=%5.1f  z=%.1f  [%s]",
                  t, (long long)tile, (long long)tileCount, bpm,
                  cam.camX, cam.camY, rot, zoom, bar.c_str());
    return std::string(buf);
}

bool parseArgs(int argc, char** argv, Options& opt, std::string& err) {
    std::vector<std::string> positional;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        auto nextNum = [&](double& dst) {
            if (i + 1 >= argc) { err = "missing value for " + a; return false; }
            dst = std::atof(argv[++i]);
            return true;
        };
        double v = 0.0;
        if (a == "--fps") { if (!nextNum(v)) return false; opt.fps = (int)v; }
        else if (a == "--zoom-scale") { if (!nextNum(v)) return false; opt.zoomScale = (float)v; }
        else if (a == "--max-seconds") { if (!nextNum(v)) return false; opt.maxSeconds = v; }
        else if (a == "--max-frames") { if (!nextNum(v)) return false; opt.maxFrames = (int)v; }
        else if (a == "--dump-grid") { if (!nextNum(v)) return false; opt.dumpGrid = (int)v; }
        else if (a == "--no-hud") { opt.noHud = true; }
        else if (a == "--quiet") { opt.quiet = true; }
        else if (a == "--trace-csv") {
            if (i + 1 >= argc) { err = "missing value for --trace-csv"; return false; }
            opt.traceCsv = argv[++i];
        } else if (a == "--grid") {
            if (i + 1 >= argc) { err = "missing value for --grid"; return false; }
            int w = 0, h = 0;
            if (std::sscanf(argv[++i], "%dx%d", &w, &h) != 2 || w <= 0 || h <= 0) {
                err = "bad --grid value"; return false;
            }
            opt.width = w; opt.height = h;
        } else if (a == "--render") {
            if (i + 1 >= argc) { err = "missing value for --render"; return false; }
            std::string m = argv[++i];
            if (m != "frames") { err = "v1 只实现 --render frames"; return false; }
        } else if (!a.empty() && a[0] == '-') {
            err = "unknown option: " + a; return false;
        } else {
            positional.push_back(a);
        }
    }
    if (positional.size() != 2) { err = "usage: chart2pdf <level.adofai> <scene.bin> [options]"; return false; }
    opt.levelPath = positional[0];
    opt.outPath   = positional[1];
    if (opt.fps < 1 || opt.fps > 120) { err = "--fps out of range (1..120)"; return false; }
    if (opt.height < 60 || opt.height > 180 || opt.width < 80 || opt.width > 600) {
        err = "行数 60..180、宽度 80..600（默认 266x90，见 D13）";
        return false;
    }
    return true;
}

}  // namespace

int main(int argc, char** argv) {
    Options opt;
    std::string err;
    if (!parseArgs(argc, argv, opt, err)) {
        std::fprintf(stderr, "chart2pdf: %s\n", err.c_str());
        return 2;
    }

    LevelData level;
    if (!level.loadFromFile(opt.levelPath)) {
        std::fprintf(stderr, "chart2pdf: 无法解析谱面 %s\n", opt.levelPath.c_str());
        return 3;
    }
    if (level.tileCount() < 2) {
        std::fprintf(stderr, "chart2pdf: 谱面无砖（tiles=%lld）\n", (long long)level.tileCount());
        return 3;
    }

    Timeline timeline;
    timeline.build(level);

    TileAnimation anim;
    anim.build(level, timeline);

    CameraTimeline camTimeline;
    camTimeline.build(level, timeline.tileStartTimes(), timeline.tileBPMs());

    CameraDirector director;
    {
        std::array<double, 2> p0 = level.tilePositionAt(0);
        const float bpm0 = timeline.tileBPMs().empty() ? 100.0f : timeline.tileBPMs()[0];
        director.reset(level.settings, camTimeline.keys(), p0[0], p0[1], bpm0);
        director.resetDrive();
    }

    const double tStart = -(double)timeline.preRoll();
    const double tEnd   = timeline.totalDuration();
    if (tEnd - tStart > opt.maxSeconds) {
        std::fprintf(stderr, "chart2pdf: 谱面时长 %.2fs 超过上限 %.0fs（--max-seconds）\n",
                     tEnd - tStart, opt.maxSeconds);
        return 4;
    }
    const int frameCount = (int)std::floor((tEnd - tStart) * opt.fps) + 1;
    if (frameCount > opt.maxFrames) {
        std::fprintf(stderr, "chart2pdf: 帧数 %d 超过上限 %d（--max-frames）\n",
                     frameCount, opt.maxFrames);
        return 4;
    }

    const int64_t tileCount = level.tileCount();
    const int64_t brickCount = tileCount - 1;
    const double pitch = std::max(0.1, (double)level.settings.pitch / 100.0);
    const double dt = 1.0 / (double)opt.fps;

    Grid grid(opt.width, opt.height);
    std::vector<RowRle> rows;
    std::vector<int> visible;
    TileIndex index;
    index.build(level, brickCount);

    std::vector<uint8_t> blob;
    adpdf::Writer w(blob);
    std::vector<uint32_t> offsets;
    offsets.reserve((size_t)frameCount);

    FILE* csv = nullptr;
    if (!opt.traceCsv.empty()) {
        csv = std::fopen(opt.traceCsv.c_str(), "wb");
        if (!csv) {
            std::fprintf(stderr, "chart2pdf: 无法写 --trace-csv %s\n", opt.traceCsv.c_str());
            return 4;
        }
        std::fprintf(csv, "k,t,tile,bpm,camX,camY,rot,adoZoom,redX,redY,blueX,blueY\n");
    }

    for (int k = 0; k < frameCount; k++) {
        const double t = tStart + (double)k / (double)opt.fps;

        int64_t tileIdx = timeline.findTileIndex(t);
        if (tileIdx < 0) tileIdx = 0;
        if (tileIdx > tileCount - 2) tileIdx = tileCount - 2;

        const auto& bpms = timeline.tileBPMs();
        const float bpm = (tileIdx < (int64_t)bpms.size()) ? bpms[(size_t)tileIdx] : 100.0f;

        // 相机跟的是行星枢轴（不是静态砖位），与 GameWindow 一致
        const auto p = level.tilePositionAt(tileIdx);
        double px = p[0], py = p[1];
        glm::dvec2 holdSlide(0.0);
        PositionSolver::pivotStarAt(timeline, t, px, py, &anim, &holdSlide);

        director.setHoldOffset(holdSlide.x, holdSlide.y);
        director.drive(t, dt, bpm, pitch, px, py, tileIdx);

        CameraView cam;
        cam.camX = director.x();
        cam.camY = director.y();
        cam.rotRad = director.rotation() * 3.14159265358979323846 / 180.0;
        cam.cosR = std::cos(cam.rotRad);
        cam.sinR = std::sin(cam.rotRad);
        const double adoZoom = director.zoom() * (double)opt.zoomScale;
        cam.halfH = kHalfHPerAdoZoom * adoZoom;
        cam.halfW = cam.halfH * ((double)grid.w / (double)grid.h);
        cam.w = grid.w;
        cam.h = grid.h;

        glm::dvec2 red(0.0), blue(0.0);
        PositionSolver::positionAt(timeline, t, red, blue, &anim);

        grid.clear();
        index.gather(cam.camX, cam.camY, cam.halfW, cam.halfH, visible);

        // 1) 砖：楼层倒序，先描边后填充，逐砖叠 MoveTrack/AnimateTrack 的活变换
        for (int ti : visible) {
            const TileXform xf = tileXformAt(level, &anim, ti, t);
            if (xf.opacity <= 0.02) continue;
            const TileRec& rec = index.at(ti);
            drawTile(grid, cam, *rec.geo, xf, rec.x + xf.moveX, rec.y + xf.moveY);
        }

        // 2) 事件圆点：twirl / SetSpeed（与 tile.frag 的 bit0/bit1/bit2 同义）
        for (int ti : visible) {
            const TileXform xf = tileXformAt(level, &anim, ti, t);
            if (xf.opacity <= 0.02) continue;
            const TileRec& rec = index.at(ti);
            const double wx = rec.x + xf.moveX, wy = rec.y + xf.moveY;
            const bool twirl = (ti < (int)level.tileHasTwirl.size() && level.tileHasTwirl[(size_t)ti]);
            if (twirl) drawDisk(grid, cam, wx, wy, kIconRadius, kLvTwirl);
            const bool speed = (ti < (int)level.tileHasSetSpeed.size() &&
                                level.tileHasSetSpeed[(size_t)ti]);
            if (speed && ti > 0 && ti < (int)level.tileBPMs.size()) {
                const float ratio = level.tileBPMs[(size_t)ti] / level.tileBPMs[(size_t)ti - 1];
                if (ratio > 1.05f || ratio < 0.95f)
                    drawDisk(grid, cam, wx, wy, kIconRadius, kLvSpeed);
            }
        }

        // 3) 拖尾  4) 星球
        std::vector<glm::dvec2> redPts, bluePts;
        PositionSolver::sampleTrail(timeline, t, kTrailDuration, kTrailSampleRate,
                                    red, blue, redPts, bluePts, &anim);
        const bool redIsPivot = (tileIdx % 2 == 0);
        if (redIsPivot) {
            drawPolyline(grid, cam, redPts, kLvTrailPv);
            drawPolyline(grid, cam, bluePts, kLvTrailMv);
        } else {
            drawPolyline(grid, cam, bluePts, kLvTrailPv);
            drawPolyline(grid, cam, redPts, kLvTrailMv);
        }
        drawDisk(grid, cam, red.x, red.y, kPlanetRadius, redIsPivot ? kLvPivot : kLvMoving);
        drawDisk(grid, cam, blue.x, blue.y, kPlanetRadius, redIsPivot ? kLvMoving : kLvPivot);

        if (opt.dumpGrid == k) {
            std::printf("frame %d  t=%.3f  tile=%lld/%lld  adoZoom=%.1f  rot=%.1f  cam=(%.3f,%.3f)\n",
                        k, t, (long long)tileIdx, (long long)brickCount, adoZoom,
                        director.rotation(), cam.camX, cam.camY);
            for (int y = 0; y < grid.h; y++) {
                std::string line;
                line.reserve((size_t)grid.w);
                for (int x = 0; x < grid.w; x++)
                    line += kRamp[grid.cells[(size_t)y * grid.w + (size_t)x]];
                std::printf("%s\n", line.c_str());
            }
        }

        rleRows(grid, rows);
        const std::string hud = opt.noHud
            ? std::string()
            : formatHud(t, tileIdx, brickCount, bpm, cam, adoZoom, director.rotation(), k, frameCount);

        size_t frameStart = blob.size();
        w.f32((float)t);
        w.u16((uint16_t)std::clamp<int64_t>(tileIdx, 0, 65535));
        w.f32(bpm);
        w.f32((float)cam.camX);
        w.f32((float)cam.camY);
        w.f32((float)adoZoom);
        size_t hudLen = std::min<size_t>(hud.size(), 255);
        w.u8((uint8_t)hudLen);
        w.bytes(hud.data(), hudLen);
        for (int y = 0; y < grid.h; y++) {
            const RowRle& rr = rows[(size_t)y];
            size_t runs = rr.pairs.size() / 2;
            if (runs > 255) { std::fprintf(stderr, "chart2pdf: 行 RLE run 数 > 255\n"); return 5; }
            w.u8((uint8_t)runs);
            w.bytes(rr.pairs.data(), rr.pairs.size());
        }
        offsets.push_back((uint32_t)frameStart);

        if (csv) {
            std::fprintf(csv, "%d,%.4f,%lld,%.1f,%.5f,%.5f,%.3f,%.2f,%.5f,%.5f,%.5f,%.5f\n",
                         k, t, (long long)tileIdx, bpm, cam.camX, cam.camY,
                         director.rotation(), adoZoom, red.x, red.y, blue.x, blue.y);
        }
    }
    if (csv) std::fclose(csv);

    adpdf::Header hdr;
    hdr.mode = adpdf::kModeFrames;
    hdr.width = (uint16_t)grid.w;
    hdr.height = (uint16_t)grid.h;
    hdr.fps = (uint16_t)opt.fps;
    hdr.frameCount = (uint32_t)frameCount;
    hdr.tStart = tStart;
    hdr.tEnd = tEnd;
    hdr.zoomScale = opt.zoomScale;
    hdr.tileCount = (uint32_t)std::min<int64_t>(brickCount, 0xFFFFFFFF);
    hdr.baseBpm = level.settings.bpm;

    std::vector<uint8_t> out;
    out.reserve(blob.size() + offsets.size() * 4 + 64);
    adpdf::Writer ow(out);
    adpdf::putHeader(ow, hdr);
    for (uint32_t off : offsets) ow.u32(off);
    ow.bytes(blob.data(), blob.size());

    if (!adpdf::writeFile(opt.outPath, out, err)) {
        std::fprintf(stderr, "chart2pdf: %s\n", err.c_str());
        return 6;
    }

    if (!opt.quiet) {
        std::fprintf(stderr,
                     "chart2pdf: frames=%d fps=%d grid=%dx%d tiles=%lld shapes=%zu "
                     "camEvents=%zu animTiles=%zu t=[%.3f,%.3f] bytes=%zu\n",
                     frameCount, opt.fps, grid.w, grid.h, (long long)brickCount,
                     g_geoCache.size(), camTimeline.keys().size(), anim.animatedTiles(),
                     tStart, tEnd, out.size());
    }
    return 0;
}
