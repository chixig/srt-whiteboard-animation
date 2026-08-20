---
name: srt-whiteboard-animation
description: 将 SRT、旁白或脚本制作成可批量生产的白板手绘视频。支持语义分幕、CV region/Polygon proposal、Polygon 遮罩、Preview V2、真实低清 stream 预览、9:16/16:9 profile、sequence 驱动时序、旁白/BGM ducking、annotation SFX、字幕烧录、单幕/多幕批量渲染和最终时长校准。用户要求“字幕做成白板动画”“SRT 生成手绘视频”“知识口播做白板视频”“批量生成白板短视频”时触发。
---

# SRT 白板动画 Production Skill

这个 Skill 负责把 **SRT / 文案 / 旁白 → 最终白板动画 MP4**。

底层笔迹继续复用 `render_stream_whiteboard.py + stream_render.py`。除非确实涉及 grid/skeleton/hand path/contour-wipe 算法，不要把新能力直接塞进 `stream_render.py`；优先放在编排、annotation、preview、production wrapper 和 final assembly 层。

## 一、核心数据原则

### 1. `sequence` 是唯一绘制顺序

```text
sequence = 叙事/绘制顺序真相
startMs  = sequence + duration + gap 的派生值
```

默认生产流程必须 normalize：

```text
sequence
→ startMs
→ validation
→ renderer
```

不要让 `sequence` 和 `startMs` 成为两套独立顺序。

### 2. annotation 是语义桥 + 几何桥 + 可选音效事件桥

元素示例：

```json
{
  "id": "subject-01",
  "label": "关键人物",
  "sequence": 1,
  "narrativeRole": "人物出现",
  "subtitle": "对应字幕",
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
  },
  "sfx": [
    {"file": "sfx/marker.wav", "offsetMs": 80, "gainDb": -6}
  ]
}
```

`region` 始终保留；`maskPolygon` 可选。没有 Polygon 时自动回退矩形。

---

# 二、推荐完整生产流水线

```text
SRT / 脚本 / 旁白
↓
parse_srt.py --mode semantic
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
annotation + polygon validation
↓
render_preview.py：真实低清 stream QC
↓
render_short_video.py / render_project.py
↓
assemble_media.py
旁白 + BGM ducking + SFX + 字幕 + duration fit
↓
final QC
```

如果用户明确要求“直接完成 / 批量生成 / 不用逐步确认”，按 autopilot 执行完整链路；只有缺少必需输入、内容边界无法安全推断或工具真正失败时才中断。

---

# 三、SRT 语义分幕

默认：

```bash
python scripts/parse_srt.py input.srt --mode semantic
```

`semantic` 使用确定性启发式：

- 目标时长；
- 句末标点；
- 字幕间停顿；
- 转折/阶段词。

输出 `boundaryReason` 供 Agent 复核。

它不是 LLM 全文理解。Agent 必须检查：

- 是否切断完整事件；
- 是否拆开强因果；
- 是否把明显转折埋在同一幕；
- 是否机械追求 30 秒破坏叙事。

兼容旧模式：

```bash
--mode duration
```

---

# 四、视觉 Profile

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

视频号、抖音、Shorts、Reels 默认竖版，除非用户明确要求横屏。

默认 whiteboard 视觉语言：暖米黄纸、深灰线稿、少量红/橙/蓝强调、低复杂度、大留白、对象之间避免无意义重叠。

---

# 五、CV 区域 / Polygon Proposal

源图生成后可运行：

```bash
python scripts/suggest_regions.py scene.png \
  --output scene.regions.json \
  --annotation-output scene.annotation.json \
  --preview scene-regions-preview.png
```

它只负责确定性 CV proposal：背景估计、笔迹检测、连通域、候选 region 和 convex-hull `maskPolygon`。

**禁止把 proposal 当成语义识别结果。**

正确流程：

```text
proposal
→ Agent 看字幕 + 看图
→ 语义匹配
→ 合并/拆分
→ sequence 排序
→ Preview 微调
```

---

# 六、Polygon Mask

真实 renderer 的允许掩码：

```text
allowed mask
= 当前 maskPolygon（没有则 region）
- 所有后续元素 maskPolygon（没有则 region）
- 当前 protectedRegions
- 当前 protectedPolygons
```

Polygon：

- 使用原图整数像素坐标；
- 至少 3 个顶点；
- 所有顶点必须在 canvas 内。

生产入口会运行：

```text
annotation_tools.validate_annotation
polygon_schema.validate_polygon_fields
```

---

# 七、Preview V2 与真实预览

浏览器编辑器：

```text
assets/preview-v2.html
```

支持：

- sequence 拖拽；
- 自动重建 startMs / sceneDurationMs；
- duration / lead-in / gap / gaze；
- region；
- label / subtitle / direction；
- 矩形转 Polygon；
- Polygon 顶点拖动、增加、删除；
- 同目录真实 `<scene>-preview.mp4` 播放。

浏览器仍是快速代理。真实笔迹 QC 必须用：

```bash
python scripts/render_preview.py \
  scene.png scene.annotation.json scene-preview.mp4 \
  --profile vertical-short-video
```

重点检查：实际绘制顺序、Polygon 裁切、future element 泄露、hand/ink 贴合、grid/skeleton 选择。

---

# 八、单幕生产

基础：

```bash
python scripts/render_short_video.py \
  scene.png scene.annotation.json scene.mp4 \
  --profile vertical-short-video
```

默认 renderer：`PolygonRegionStreamRenderer`。

### 旁白

```bash
--narration narration.mp3
```

`--audio` 是兼容别名。

### BGM + 自动 ducking

```bash
--bgm bgm.mp3 \
--bgm-gain-db -18 \
--duck-ratio 8
```

BGM 会循环到视频长度，并使用 narration 作为 sidechain control。默认 attack 20ms、release 300ms。

### 字幕烧录

```bash
--subtitles narration.srt \
--subtitle-font "Noto Sans CJK SC"
```

字幕流程：

```text
SRT → ASS → libass burn-in
```

如果 ffmpeg 没有 `ass` filter，必须明确报错，不得静默产出无字幕视频。

### Annotation SFX

场景级：

```json
"sfx": [
  {"file": "sfx/open.wav", "startMs": 300, "gainDb": -6}
]
```

元素级：

```json
"sfx": [
  {"file": "sfx/hit.wav", "offsetMs": 100, "gainDb": -4}
]
```

元素 SFX 锚点：

```text
normalized reveal.startMs + offsetMs
```

也可额外传：

```bash
--sfx-plan project.sfx.json
```

---

# 九、最终音频总线

`audio_mix.py` 负责：

```text
narration
   ├─→ final mix
   └─→ sidechain control
             ↓
looped BGM → sidechaincompress → ducked BGM

SFX → adelay(startMs) → final mix
```

所有轨道最终：

```text
apad + atrim 到目标视频长度
→ limiter
→ AAC
```

不要通过“让视频跟着较短音频提前结束”来掩盖时长问题，除非用户明确要求兼容旧 `--audio-fit shortest`。

---

# 十、最终装配与时长校准

独立入口：

```bash
python scripts/assemble_media.py visual.mp4 final.mp4 \
  --narration narration.mp3 \
  --bgm bgm.mp3 \
  --sfx-plan project.sfx.json \
  --subtitles narration.srt
```

装配顺序：

```text
probe visual duration
→ audio mix
→ trim/pad 到视频长度
→ mux
→ subtitle burn-in
→ probe final duration
→ drift validation
```

默认最大允许漂移：

```text
250 ms
```

超过阈值报错。用户可用 `--max-drift-ms` 调整。

---

# 十一、多幕项目

```bash
python scripts/render_project.py ./scenes ./final.mp4 \
  --profile vertical-short-video \
  --narration narration-full.mp3 \
  --bgm bgm.mp3 \
  --subtitles narration-full.srt
```

多幕 SFX 时间轴必须这样计算：

1. 当前 scene 用与 production renderer 一致的 normalize 逻辑；
2. 当前 scene 完成渲染后探测真实 MP4 时长；
3. 下一 scene 的 global offset 累加真实时长；
4. 元素 SFX = scene offset + normalized reveal.startMs + offsetMs。

不要只用计划 `sceneDurationMs` 累加，否则编码后的实际时长差可能在多幕后累积。

`render_project.py` 最终写 manifest，并在需要旁白/BGM/SFX/字幕时统一调用 `assemble_media.py`。

只看计划：

```bash
--dry-run
```

---

# 十二、执行模式

## interactive

高价值内容建议确认节点：

1. semantic 分幕 / storyboard；
2. 源图；
3. annotation + Polygon；
4. 真实低清 stream preview；
5. 最终音视频成片。

## autopilot

用户明确要求直接完成时：

- 自动走完整链路；
- 不要每一步停下来；
- 最终报告哪些是自动估算、哪些是确定性算法、哪些需要人工抽检。

---

# 十三、最终 QC

至少检查：

- sequence 与字幕事件一致；
- Polygon 没切掉主体关键笔迹；
- 后续对象没有提前泄露；
- hand/ink 基本贴合；
- 结尾 gaze 足够；
- 9:16 主体不过度拥挤；
- narration 清晰；
- BGM 在说话时明显 duck、停说后恢复；
- SFX 时间点与元素动作一致；
- 字幕无明显越界/遮挡；
- final duration 与 visual duration 漂移不超过阈值；
- 多幕无缺幕、重复、乱序。

---

# 十四、测试要求

GitHub Actions 应验证：

- ffmpeg 可用；
- `sidechaincompress` filter；
- `ass` / libass filter；
- 所有升级脚本 `py_compile`；
- sequence / semantic grouping / Polygon / CV proposal 测试；
- annotation SFX offset；
- BGM ducking + SFX 真实混音；
- ASS 字幕真实烧录；
- 最终 `assemble_media` 有音轨且 duration drift 合格。

---

# 十五、环境与边界

```bash
python scripts/prepare_env.py
```

或：

```bash
pip install -r requirements.txt
```

字幕烧录最好使用带 libass 的系统 ffmpeg；`imageio-ffmpeg` 可作为一般 fallback，但不保证包含 libass。

当前仍明确不负责：

- 自动生成 BGM/SFX 素材本身；
- 通用实例分割模型；
- TTS 生成；
- 平台发布上传。

这些应由更大的 Video Agent / 其它 Skill 提供，通过标准文件和 JSON 接口串联。
