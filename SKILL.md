---
name: srt-whiteboard-animation
description: 将 SRT、旁白或脚本制作成白板手绘动画。支持语义分幕、9:16/16:9 profile、sequence 驱动时序、Preview V2、annotation 校验、单幕/多幕批量渲染与音频合成。用户要求“字幕做成白板动画”“SRT 生成手绘视频”“知识口播做白板视频”“批量生成白板短视频”时触发。
---

# SRT 白板动画 Production Skill

这个 Skill 的职责是把 **字幕/文案 → 白板动画视频**。底层绘制仍使用 `render_stream_whiteboard.py + stream_render.py`，新版重点强化上层的叙事编排、时序、竖屏、批量和音频。

## 核心原则

### 1. sequence 是唯一绘制顺序

`annotation.json` 中：

```text
sequence = 叙事/绘制顺序真相
startMs = 由 sequence + duration + gap 自动派生
```

不得再同时把 `sequence` 和 `startMs` 当作两套独立顺序。

默认渲染必须走：

```text
scripts/render_short_video.py
```

不要直接把未归一化的 annotation 交给旧 `render_stream_whiteboard.py`。

### 2. annotation 是语义桥，不只是矩形框

每个元素至少包含：

```json
{
  "id": "...",
  "label": "...",
  "sequence": 1,
  "narrativeRole": "场景铺垫/人物出现/冲突/结果...",
  "subtitle": "对应字幕",
  "type": "object",
  "region": {"x": 0, "y": 0, "width": 100, "height": 100},
  "reveal": {
    "startMs": 300,
    "durationMs": 2200,
    "direction": "top_to_bottom",
    "protectedRegions": []
  }
}
```

`region` 与 `protectedRegions` 使用原图整数像素坐标。

### 3. 不重写底层 renderer

除非确实涉及笔迹算法，否则优先把新能力放在：

- `parse_srt.py`
- `annotation_tools.py`
- `preview-v2.html`
- `render_short_video.py`
- `render_project.py`
- profile

这样更容易继续同步上游。

---

# 输入模式

## SRT

优先读取 SRT 原始时间轴。

```bash
python scripts/parse_srt.py input.srt --mode semantic
```

默认：

```text
target = 30s
min = 25s
max = 35s
```

可以按内容节奏调整，不要把 25–35 秒理解为绝对规则。

## 只有脚本

如果没有 SRT：

1. 先按语义段落拆分；
2. 如有 TTS/原声时间轴，再回填具体时长；
3. 没有真实时间轴时，只能做估算，必须明确这是估计值。

## 音频

如果已有整条旁白/原声：

- 有 SRT：SRT 控制编排，音频最终 mux；
- 无 SRT：优先先获得转写/字幕，再进入本 Skill。

---

# SRT 分幕

## 默认 semantic

`parse_srt.py --mode semantic` 使用确定性启发式边界：

- 与目标场景时长的距离；
- 句号、问号、感叹号、分号；
- 字幕间停顿；
- “但是、后来、因此、最终、与此同时”等阶段/转折词。

输出 `boundaryReason` 供 Agent 复核。

注意：这是**语义感知启发式**，不是 LLM 真正理解全文。

Agent 在拿到建议场景后仍要检查：

- 是否在一个事件未结束时切断；
- 是否把因果的前后两句拆开；
- 是否把一个强转折埋在同一幕中；
- 是否因为机械追求 30 秒而破坏叙事。

必要时重新组合 cueRange。

## duration 兼容模式

只有明确需要复现旧行为时才用：

```bash
--mode duration
```

---

# 视觉 Profile

默认优先根据用户的平台与素材比例选择，而不是写死 16:9。

## 竖版短视频

```text
profiles/vertical-short-video.json
1080×1920 / 9:16
```

适合视频号、抖音、Shorts、Reels。

## 横版

```text
profiles/landscape-standard.json
1920×1080 / 16:9
```

适合横屏课程、B 站横版、YouTube 横版。

如果用户没有说明且任务明显属于短视频，默认 `vertical-short-video`。

---

# 统一视觉规范

默认 whiteboard 风格：

- 暖米黄纸张底；
- 深灰手绘线；
- 少量红/橙/蓝强调；
- 简洁、低噪点、大留白；
- 一个场景只表达一个核心意思；
- 主体之间尽量不要无意义重叠；
- 源图避免文字，字幕另行处理。

这只是默认 profile，不是不可修改的艺术风格。用户明确要求宣纸、历史地图、科技蓝图等白板变体时，可以新建 profile，而不是硬塞进默认配置。

---

# annotation 生成

生成 annotation 前必须同时依据：

1. 对应字幕/脚本；
2. 实际生成出来的图片；
3. 图片真实像素尺寸。

不要只根据字幕臆测坐标。

## 排序

按叙事事件排序，例如：

```text
环境/前提
→ 关键人物或物体
→ 动作/变化
→ 冲突
→ 结果/反应
```

不要因为一个对象在画面左侧就默认先画。

## 遮罩不变量

对元素 i：

```text
allowed mask
= 当前 region
- 所有后续元素 region
- 当前 protectedRegions
```

这个规则用于防止后续元素提前漏出。

复杂重叠场景如果矩形不够，应优先简化生成图构图；polygon/segmentation mask 属于后续高级能力，不要伪装成已经支持。

---

# Preview

## 默认使用 Preview V2

```text
assets/preview-v2.html
```

V2 的数据模型：

```text
拖动元素顺序
→ 数组顺序改变
→ sequence = 1..N
→ startMs 立即重建
→ sceneDurationMs 立即更新
→ 时间轴和代理预览同步
```

开始时间是派生值，不作为独立手工顺序来源。

可以调整：

- 顺序；
- duration；
- lead-in；
- gap；
- gaze；
- region；
- subtitle；
- label；
- direction。

复杂 `protectedRegions` 暂时可以用旧 `assets/preview.html` 或直接修改 JSON。

Preview 仍然是矩形代理，不等于真实 stream 笔迹。最终质量仍要用实际 renderer 抽帧检查。

---

# annotation 校验

渲染前必须执行校验。

生产入口会自动校验，也可以独立运行：

```bash
python scripts/annotation_tools.py scene.annotation.json \
  --image-width 1080 --image-height 1920
```

错误级问题必须修复后才能继续：

- canvas 无效；
- region 越界；
- duration 非法；
- annotation 没有 elements；
- 关键结构缺失。

warning 需要人工判断：

- sequence 不连续；
- startMs 重叠；
- sceneDurationMs 太短。

在 sequence 模式下，startMs 重叠通常可由 normalize 自动修复。

---

# 单幕渲染

推荐：

```bash
python scripts/render_short_video.py \
  scene.png \
  scene.annotation.json \
  scene.mp4 \
  --profile vertical-short-video
```

可覆盖：

```text
--ink-path grid|skeleton
--color-fill contour-wipe|brush
--fps
--cap-long-edge
--canvas-hex
--target-hand-height
```

默认 `timeline-mode=sequence`。

只有为了兼容历史标注才使用：

```bash
--timeline-mode startMs --no-retime
```

---

# 音频

单幕：

```bash
python scripts/render_short_video.py ... --audio narration.mp3
```

独立 mux：

```bash
python scripts/mux_audio.py video.mp4 narration.mp3 final.mp4
```

系统 ffmpeg 优先；没有时尝试 `imageio-ffmpeg`。

---

# 多幕项目

目录示例：

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

带整条旁白：

```bash
--audio narration-full.mp3
```

`render_project.py` 会：

1. 自然排序场景；
2. 检查同名 image/annotation 配对；
3. 每幕调用 `render_short_video.py`；
4. `merge_scenes.py` 合并视觉；
5. 最终再 mux 整条音轨；
6. 写出 manifest。

为什么音轨放在最后：旧 `merge_scenes.py` 的 PyAV fallback 只保证视频，因此先合并视觉再加整轨音频更稳定。

想先检查计划：

```bash
--dry-run
```

---

# 执行模式

## interactive

适合探索和高价值内容：

1. 分幕策略后确认；
2. 图片后确认；
3. annotation/Preview 后确认；
4. 成片后确认。

## autopilot

当用户明确要求“直接完成”“批量生成”“不用逐步问我”时：

- 不要每一步停下来；
- 自动走完整流程；
- 只在缺少必需输入、存在无法安全猜测的内容边界、或工具真正失败时中断；
- 最终报告生成了什么、哪些是自动估算、哪些需要人工抽检。

---

# Agent 推荐编排

```text
input
↓
parse_srt semantic
↓
Agent narrative review
↓
storyboard
↓
image generation
↓
vision-based annotation
↓
Preview V2 / validation
↓
render_project
↓
QC
↓
final video
```

本仓库应被视为更大 Video Agent 中的 **Whiteboard Renderer Skill**。

选题、脚本写作、图像生成、TTS、发布平台上传等能力可以由其他 Skill 负责，通过标准输入输出串联，不要强耦合进底层 renderer。

---

# 质量检查

最终至少检查：

- 开场：没有未到时机的对象提前漏出；
- 中段：重叠元素 protectedRegions 是否正确；
- 顺序：实际绘制顺序与字幕事件一致；
- 笔迹：手部/笔尖没有大范围脱离线条；
- 结尾：完整画面有足够 gaze；
- 竖屏：主体没有因为 9:16 过度挤压；
- 音频：开头、结尾和总时长匹配；
- 多幕：场景顺序正确，没有缺幕/重复幕。

---

# 环境

```bash
python scripts/prepare_env.py
```

或：

```bash
pip install -r requirements.txt
```

跨平台中文预览字体可通过：

```text
SRT_WHITEBOARD_FONT=/path/to/font.ttf
```

覆盖。
