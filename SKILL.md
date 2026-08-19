---
name: srt-whiteboard-animation
description: 将 SRT、旁白或脚本制作成白板手绘流式笔迹动画。支持 9:16/16:9 profile、语义分镜、annotation.json 分区编排、sequence 驱动的时序归一化、区域校验、stream 连续笔迹渲染，以及可选旁白/原声音轨合成。用户要求“字幕做白板动画”“SRT 生成手绘视频”“旁白生成白板讲解视频”“竖版白板短视频”时触发。
---

# SRT 白板动画 Skill

这是一个“叙事编排层 + 可编辑标注层 + 确定性本地渲染层”的白板动画工作流。

核心原则：

- SRT / 旁白负责 **说什么、什么时候说**。
- `annotation.json` 负责 **哪个画面元素对应哪个叙事事件**。
- `sequence` 是 **绘制顺序的唯一真相**。
- `startMs` 是由生产流程生成的 **执行时间轴**，不要再让它与 `sequence` 各自独立维护。
- `render_short_video.py` 在真正渲染前会按 `sequence` 自动重建串行 `startMs`，随后调用原有 stream renderer。
- 原有 mask 不变量继续保留：当前元素允许绘制区域 = 当前 `region` - 后续元素区域 - `protectedRegions`。

## 适用输入

可接受：

1. `.srt` 字幕；
2. 已有旁白/原声音频 + SRT；
3. 只有脚本，由宿主 Agent 先生成或取得时间轴；
4. 已有线稿图 + `annotation.json`，直接进入校验/渲染。

本仓库 **不内置图片生成模型**。线稿生成由宿主 Agent 的图片生成能力完成，本 Skill 负责提示词约束、标注、校验和确定性视频渲染。

## 输出规格与 Profile

不要再把 16:9 写死。优先根据用户目标平台选择 profile：

- `profiles/vertical-short-video.json`：9:16，目标画布 1080×1920，短视频默认。
- `profiles/landscape-standard.json`：16:9，目标画布 1920×1080。
- 用户可以复制 JSON 创建自定义 profile。

Profile 可配置：

- 目标画布比例；
- FPS；
- `cap_long_edge`；
- 背景色 `canvas_hex`；
- `grid` / `skeleton` 笔迹；
- `contour-wipe` / `brush` 上色；
- 手部尺寸；
- lead-in、元素间 gap、结尾 gaze。

默认统一纸张色使用 `#F5EBD7`。如用户指定其他视觉主题，以用户要求为准，不要把暖米黄当成不可变规则。

## 执行模式

支持两种模式：

### interactive

用于用户希望逐步审阅时。关键创意节点可停下来确认，例如分镜策略、线稿和最终预览。

### autopilot

当用户明确要求“直接做完”“批量生成”“不要逐步确认”时，一次完成：解析 → 分镜 → 出图 → 标注 → 归一化 → 校验 → 渲染 → 音频合成。不要因为旧版 Skill 的确认关卡而强制中断。

如果用户没有明确偏好，涉及大量图片生成或创意方向时采用 interactive；只有确定性处理时可连续执行。

## 工作流程

### 1. 解析字幕

先运行：

```bash
python scripts/parse_srt.py input.srt
```

`parse_srt.py` 的 25–35 秒分组只是 **候选时间块**，不是最终语义分镜。Agent 必须再结合：

- 完整句结束点；
- 话题切换；
- 因果/转折；
- 人物或场景变化；
- 视觉信息密度；

进行语义微调。时间范围是约束，不应为了凑 30 秒强行切断一句话或一个事件。

### 2. 生成线稿

源图必须与目标 profile 比例一致。默认建议：

- 简洁白板/手绘视觉；
- 主体之间有足够留白；
- 深灰/黑色清晰线条；
- 少量强调色；
- 避免照片级复杂纹理；
- 默认不在源图中生成文字，字幕交给独立字幕层或平台处理；
- 不要让多个未来才出现的主体严重粘连，否则矩形区域和 mask 很难拆分。

如果用户明确要求其他风格，可以调整主题，但仍要保证线条可被阈值/骨架算法识别。

## 3. 建立 annotation.json

标注前同时读取对应字幕和实际图片，不能只根据字幕猜坐标。

推荐字段：

```json
{
  "sceneId": "scene-01",
  "canvas": {"width": 1080, "height": 1920},
  "sceneDurationMs": 12000,
  "elements": [
    {
      "id": "subject-a",
      "label": "主体 A",
      "sequence": 1,
      "narrativeRole": "场景铺垫",
      "subtitle": "对应字幕",
      "type": "subject",
      "region": {"x": 80, "y": 220, "width": 600, "height": 700},
      "reveal": {
        "direction": "top_to_bottom",
        "startMs": 250,
        "durationMs": 2200,
        "maskPaddingPx": 22,
        "protectedRegions": []
      },
      "handPath": {
        "start": [380, 250],
        "end": [380, 880],
        "easing": "easeInOut"
      }
    }
  ]
}
```

### 字段权威关系

- `sequence`：权威绘制顺序，从 1 开始连续。
- `reveal.durationMs`：该元素绘制预算，保留人工/Agent 调整结果。
- `reveal.startMs`：执行字段，可由 `sequence + duration + gap` 自动重建。
- `direction` / `handPath`：主要供矩形代理预览；真实 stream 笔迹由 grid/skeleton 自动计算。
- `protectedRegions`：用于避免后续元素提前泄露。

## 4. 编辑区域

可继续使用：

```text
assets/preview.html
```

它用于拖动/缩放 `region`、编辑字幕和调整 `sequence`。

重要：旧预览台仍可能保留历史 `startMs`。因此 **从预览台保存后，不直接把 JSON 交给底层 renderer**，必须先做时序归一化。

## 5. 时序归一化与校验

推荐命令：

```bash
python scripts/annotation_tools.py scene.annotation.json \
  --normalize \
  --mode sequence \
  --gap-ms 180 \
  --in-place
```

它会：

- 按 `sequence` 排序；
- 自动重新编号为 1..N；
- 保留每个元素的 `durationMs`；
- 重建不重叠的 `startMs`；
- 预留元素间 gap；
- 保证 `sceneDurationMs` 至少覆盖最后元素和结尾凝视；
- 检查 region / protectedRegions 越界、时长非法、sequence 不连续、时间重叠等问题。

生产渲染器 `render_short_video.py` 已内置这一过程，因此一般不需要手工先改 JSON；单独执行主要用于调试或将规范化结果写回文件。

## 6. 生成区域检查图

```bash
python scripts/render_annotation_preview.py \
  scene.png \
  scene.annotation.json \
  scene-preview.png
```

字体已改为跨平台探测：

- Windows：微软雅黑/黑体；
- macOS：苹方/华文黑体等；
- Linux：Noto CJK/WenQuanYi 等；
- 可通过环境变量 `SRT_WHITEBOARD_FONT=/path/to/font.ttf` 强制指定。

## 7. 生产渲染

优先使用新入口：

### 9:16

```bash
python scripts/render_short_video.py \
  scene.png \
  scene.annotation.json \
  scene.mp4 \
  --profile vertical-short-video
```

### 16:9

```bash
python scripts/render_short_video.py \
  scene.png \
  scene.annotation.json \
  scene.mp4 \
  --profile landscape-standard
```

### 带旁白/原声

```bash
python scripts/render_short_video.py \
  scene.png \
  scene.annotation.json \
  scene-final.mp4 \
  --profile vertical-short-video \
  --audio narration.mp3
```

音频合成优先使用系统 `ffmpeg`；若系统没有，则使用 `imageio-ffmpeg` 自带二进制。`prepare_env.py` 会自动安装该依赖。

如果只需要给已有 MP4 加音轨：

```bash
python scripts/mux_audio.py silent.mp4 narration.mp3 final.mp4
```

## 8. 多幕合并

继续使用：

```bash
python scripts/merge_scenes.py scene-01.mp4 scene-02.mp4 scene-03.mp4 final.mp4
```

如果每幕已经带完整音频，合并前确保编码、帧率与分辨率一致。更推荐整条旁白先切成每幕对应音频，逐幕 mux 后再合并。

## Mask 编排不变量

对当前元素 `E_i`：

```text
allowed(E_i)
= region(E_i)
- union(region(E_j), j > i)
- protectedRegions(E_i)
```

其中 `j > i` 按 **归一化后的 sequence 顺序** 判断。

这保证：

- 后续主体不会提前露出；
- 交叉背景线不会把未来主体带出来；
- 当前元素画完后保留在持久画布上。

矩形 mask 仍是近似方案。对于复杂交叠、人物四肢穿插或不规则物体，未来应升级到 polygon / segmentation mask，而不是无限堆矩形。

## Grid 与 Skeleton

- `grid`：稳健，对文字块、粗线、大面积墨迹容错高。
- `skeleton`：沿细化骨架追踪，更像真实描线；要求源图线稿清晰、对比足够。

9:16 profile 默认 `skeleton`；16:9 profile 默认 `grid`。可以通过 CLI 覆盖。

## 质量检查

渲染前必须检查：

1. 图片像素尺寸与 `canvas` 一致；
2. 所有 `region` 在画布范围内；
3. `sequence` 连续且符合叙事顺序；
4. 归一化后没有时间重叠；
5. `sceneDurationMs` 覆盖最后绘制结束时间；
6. 后绘主体如果与前绘区域交叉，前者区域会从前者 mask 中扣除；
7. 线稿与背景对比足够，低对比灰线可能无法稳定提取；
8. 抽查开场、冲突/重叠区域和结尾完整帧；
9. 若带音频，检查音画总时长和尾部是否被意外截断。

## 环境

首次运行：

```bash
python scripts/prepare_env.py
```

安装：

- opencv-python
- numpy
- av
- Pillow
- imageio-ffmpeg

## 回归测试

```bash
python -m unittest discover -s tests -v
```

当前回归测试至少覆盖：

- `sequence` 成为 canonical order；
- 重排后 `startMs` 自动串行化；
- region 越界校验。

## 推荐目录

```text
project/
  input/
    narration.srt
    narration.mp3
  scenes/
    scene-01.png
    scene-01.annotation.json
    scene-01.mp4
    scene-02.png
    scene-02.annotation.json
    scene-02.mp4
  output/
    final.mp4
```

## 兼容性

原来的 `render_stream_whiteboard.py` 仍保留，不破坏上游兼容性。新生产流程优先调用 `render_short_video.py`。

这样做的原因是：底层 stream renderer 已经有价值且较稳定，升级应尽量集中在编排、配置、校验与合成层，而不是为了增加短视频能力重写底层笔迹算法。
