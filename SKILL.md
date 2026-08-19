---
name: srt-whiteboard-animation
description: 将 SRT、旁白或脚本制作成白板手绘动画。支持语义分幕、CV 区域/Polygon 建议、Polygon 遮罩、Preview V2、真实低清 stream 预览、9:16/16:9 profile、sequence 驱动时序、单幕/多幕批量渲染与音频合成。用户要求“字幕做成白板动画”“SRT 生成手绘视频”“知识口播做白板视频”“批量生成白板短视频”时触发。
---

# SRT 白板动画 Production Skill

这个 Skill 负责把 **SRT / 文案 / 旁白 → 白板动画 MP4**。底层笔迹算法继续复用 `render_stream_whiteboard.py + stream_render.py`；生产能力主要放在叙事编排、annotation、Polygon、预览、批量与音频层，避免与上游 renderer 深度分叉。

## 核心原则

### 1. `sequence` 是唯一绘制顺序

```text
sequence = 叙事/绘制顺序真相
startMs  = sequence + duration + gap 的派生值
```

默认生产入口必须自动 normalize，不要让 `sequence` 与 `startMs` 形成两套独立顺序。

### 2. annotation 是语义桥 + 几何桥

每个元素至少要把字幕事件与画面对象对应起来：

```json
{
  "id": "subject-01",
  "label": "关键人物",
  "sequence": 1,
  "narrativeRole": "人物出现",
  "subtitle": "对应字幕文本",
  "type": "object",
  "region": {"x": 120, "y": 200, "width": 500, "height": 700},
  "maskPolygon": [
    {"x": 160, "y": 230},
    {"x": 560, "y": 220},
    {"x": 610, "y": 760},
    {"x": 180, "y": 820}
  ],
  "reveal": {
    "startMs": 300,
    "durationMs": 2200,
    "direction": "top_to_bottom",
    "protectedRegions": [],
    "protectedPolygons": []
  }
}
```

`region` 永远保留，作为兼容边界框和 UI 操作范围；`maskPolygon` 是可选精细形状。没有 Polygon 时按矩形工作。

### 3. 自动识别只做 proposal，不冒充语义理解

`scripts/suggest_regions.py` 使用确定性 CV 找视觉连通区域并建议 `region + maskPolygon`。

它不能判断“哪个对象先出现”“哪个对象对应哪句字幕”。Agent 必须结合字幕和实际图片做：

```text
proposal
→ 语义匹配
→ 合并/拆分
→ sequence 排序
→ Preview 微调
```

### 4. 真实质量判断必须走真实 renderer

Preview V2 的浏览器代理仍是布局/时序工具。最终笔迹质量必须用：

```bash
python scripts/render_preview.py ...
```

生成真实低清 stream MP4 抽检，再决定是否全清渲染。

---

# 推荐生产流水线

```text
SRT / 脚本 / 旁白
↓
parse_srt semantic
↓
Agent narrative review
↓
storyboard
↓
image generation
↓
suggest_regions.py（可选 CV proposal）
↓
Agent vision + subtitle semantic mapping
↓
annotation.json
↓
Preview V2：sequence / timing / region / Polygon
↓
annotation validation
↓
render_preview.py：真实低清 stream 预览
↓
QC
↓
render_short_video.py / render_project.py
↓
audio mux
↓
final QC
```

---

# 输入与语义分幕

## SRT

默认：

```bash
python scripts/parse_srt.py input.srt --mode semantic
```

`semantic` 使用确定性启发式综合：

- 目标场景时长；
- 句号、问号、感叹号、分号；
- 字幕间停顿；
- “但是、后来、因此、最终、与此同时”等转折/阶段词。

输出 `boundaryReason` 供 Agent 复核。它是语义感知启发式，不是 LLM 全文理解。

只有需要复现旧版纯时长行为时使用：

```bash
--mode duration
```

## 只有脚本

没有 SRT 时先按语义段落拆分；如果后续有 TTS/原声音轨，再回填真实时间轴。没有真实时间轴时必须把时长标记为估算。

---

# 视觉 Profile

短视频默认：

```text
profiles/vertical-short-video.json
1080×1920 / 9:16
```

横版：

```text
profiles/landscape-standard.json
1920×1080 / 16:9
```

如果用户没有说明且任务明显属于视频号、抖音、Shorts、Reels，默认竖版。

默认 whiteboard 视觉语言：暖米黄纸张、深灰手绘线、少量红/橙/蓝强调、干净背景、大留白、低复杂度。用户明确要求宣纸、历史地图、科技蓝图等变体时应新建 profile，而不是硬改底层算法。

---

# 自动区域 / Polygon 建议

生成源图后可以先运行：

```bash
python scripts/suggest_regions.py scene.png \
  --output scene.regions.json \
  --annotation-output scene.annotation.json \
  --preview scene-regions-preview.png
```

常用参数：

```text
--merge-gap          控制邻近笔迹是否合并成一个视觉对象
--min-area-ratio     过滤噪点/极小对象
--max-regions        最大建议区域数
--color-threshold    与纸张背景的颜色差阈值
--dark-threshold     深色笔迹阈值
```

输出的 annotation 模板中会写：

```text
narrativeRole = 待 Agent 结合字幕确认
```

必须继续做语义复核，不能直接把 proposal 顺序当叙事顺序。

---

# Polygon Mask 模型

## 当前对象

如果元素有：

```json
"maskPolygon": [{"x": 10, "y": 20}, ...]
```

真实 renderer 会使用 Polygon 作为当前元素允许作画形状；没有则回退 `region`。

## 后续对象保护

允许掩码现在是：

```text
allowed mask
= 当前元素 maskPolygon（没有则 region）
- 所有后续元素 maskPolygon（没有则 region）
- 当前 protectedRegions
- 当前 protectedPolygons
```

这样复杂重叠对象不再只能依赖粗矩形保护。

Polygon 使用原图整数像素坐标；至少 3 个顶点；所有顶点必须在 canvas 内。

---

# Preview V2

默认使用：

```text
assets/preview-v2.html
```

支持：

- 拖动模块列表改变 sequence；
- sequence 改变后立即重建 startMs；
- duration / lead-in / gap / gaze；
- region 移动与精确尺寸；
- label / subtitle / direction；
- `矩形→Polygon`；
- 拖动 Polygon 顶点；
- 双击边附近增加 Polygon 顶点；
- 右键顶点删除（至少保留 3 点）；
- 读取同目录 `<场景名>-preview.mp4` 并直接播放真实 stream 预览。

移动 region 时现有 Polygon 会一起移动；通过右侧宽高缩放 region 时 Polygon 会同比例缩放。

`protectedPolygons` 当前主要通过 annotation / Agent 写入；浏览器编辑器重点负责当前元素 `maskPolygon`。

---

# annotation 校验

生产入口会同时运行：

```text
annotation_tools.validate_annotation
polygon_schema.validate_polygon_fields
```

错误级问题必须修复：

- canvas 无效或与图片尺寸不一致；
- region 越界；
- duration 非法；
- annotation 没有 elements；
- maskPolygon 少于 3 点；
- Polygon 顶点越界；
- protectedPolygons 数据结构无效；
- sceneDurationMs 小于最后绘制结束时间。

warning 需要人工判断：

- sequence 不连续；
- 时间重叠；
- 其它兼容性问题。

---

# 真实低清 Stream 预览

使用与成片同一套 renderer，只降低尺寸和 FPS：

```bash
python scripts/render_preview.py \
  scene.png \
  scene.annotation.json \
  scene-preview.mp4 \
  --profile vertical-short-video
```

默认：

```text
20 fps
长边 540px
```

这是质量检查工具，不是最终交付。重点检查：

- 真实笔迹顺序；
- Polygon 是否裁错主体；
- 后续元素是否提前泄露；
- 手部/笔尖是否大范围离线；
- skeleton/grid 哪个更适合当前画面。

生成 `<场景名>-preview.mp4` 后，Preview V2 可直接加载播放。

---

# 单幕生产渲染

推荐：

```bash
python scripts/render_short_video.py \
  scene.png \
  scene.annotation.json \
  scene.mp4 \
  --profile vertical-short-video
```

默认：

```text
timeline-mode = sequence
renderer = PolygonRegionStreamRenderer
```

因此旧 annotation 仍按矩形工作；新 annotation 有 `maskPolygon` 时自动使用 Polygon。

常用覆盖：

```text
--ink-path grid|skeleton
--color-fill contour-wipe|brush
--fps
--cap-long-edge
--canvas-hex
--target-hand-height
```

只有兼容历史标注时才考虑：

```bash
--timeline-mode startMs --no-retime
```

---

# 多幕项目

目录：

```text
scene-01.png
scene-01.annotation.json
scene-02.png
scene-02.annotation.json
scene-03.png
scene-03.annotation.json
```

批量：

```bash
python scripts/render_project.py \
  ./scenes \
  ./final.mp4 \
  --profile vertical-short-video
```

先看计划：

```bash
--dry-run
```

`render_project.py` 会自然排序、检查 image/annotation 配对、逐幕调用生产 renderer、合并视觉并写 manifest。

---

# 音频

单幕：

```bash
python scripts/render_short_video.py ... --audio narration.mp3
```

多幕整轨：

```bash
python scripts/render_project.py ... --audio narration-full.mp3
```

多幕默认先合并视觉，再 mux 整条音轨，避免旧 PyAV merge fallback 丢音频。

---

# 执行模式

## interactive

高价值单条内容建议在这些节点确认：

1. semantic 分幕 / storyboard；
2. 源图；
3. annotation + Polygon；
4. 真实低清 stream preview；
5. 全清成片。

## autopilot

用户明确要求“直接完成 / 批量生成 / 不用逐步确认”时自动走完整流程，只在缺少必需输入、无法安全推断内容边界或工具真正失败时中断。

---

# 最终 QC

至少检查：

- 开场没有未到时机的对象提前出现；
- sequence 与字幕事件一致；
- Polygon 没有切掉主体关键笔迹；
- complex overlap 中后续对象没有提前泄露；
- 实际 stream 笔迹自然；
- 结尾 gaze 足够；
- 9:16 主体不过度拥挤；
- 音频起止与总时长匹配；
- 多幕无缺幕、重复、乱序。

---

# 环境

```bash
python scripts/prepare_env.py
```

或：

```bash
pip install -r requirements.txt
```

中文预览字体可用：

```text
SRT_WHITEBOARD_FONT=/path/to/font.ttf
```

覆盖。

本仓库应作为更大 Video Agent 中的 **Whiteboard Renderer Skill**：脚本写作、图像生成、TTS、字幕烧录、BGM/SFX、发布平台上传可以由其它 Skill 通过标准输入输出串联，不要强耦合进底层 `stream_render.py`。
