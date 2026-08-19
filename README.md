# SRT 白板动画 Skill

将 SRT、旁白或脚本转换为按叙事顺序绘制的白板手绘动画。项目保留原有 **分区遮罩编排 + 流式笔迹绘制** 的核心，同时在本 fork 中补上了更适合生产使用的时序规范化、9:16/16:9 profile、音轨合成、跨平台字体和基础校验。

> 本仓库 fork 自 `geeklee/srt-whiteboard-animation`，继续遵循 MIT License。底层 stream renderer 仍保持兼容，新能力主要集中在编排、配置、校验与合成层，便于后续继续同步上游。

## 效果示例

**场景：猴子山抢香蕉** —— 随着字幕的叙事顺序，依次绘制假山与小猴、抢香蕉的大猴，以及围观小朋友。

![猴子山抢香蕉：SRT 白板动画演示](examples/scene-01-monkey-mountain-stream.gif)

原始线稿：[查看 PNG](examples/scene-01-monkey-mountain.png)。

## 本 fork 的主要升级

- `sequence` 作为唯一绘制顺序来源；渲染前自动重建串行 `startMs`
- 新增 `scripts/annotation_tools.py`：时序归一化 + annotation 校验
- 新增 `scripts/render_short_video.py`：生产级统一渲染入口
- 新增 `profiles/vertical-short-video.json`：9:16 / 1080×1920
- 新增 `profiles/landscape-standard.json`：16:9 / 1920×1080
- 新增 `scripts/mux_audio.py`：旁白/原声合成到最终 MP4
- `prepare_env.py` 增加 `imageio-ffmpeg`，没有系统 ffmpeg 也能取得可用 ffmpeg 二进制
- `render_annotation_preview.py` 改为跨 Windows/macOS/Linux 的中文字体探测
- 新增 `requirements.txt`
- 新增基础单元测试与 GitHub Actions CI
- Skill 工作流支持 `interactive` 与 `autopilot`，不再把逐步确认写死

## 核心架构

这套 Skill 分成三层：

```text
SRT / 旁白 / 脚本
        ↓
叙事分镜 + annotation.json
        ↓
sequence → 时间轴归一化 → 校验
        ↓
mask 编排 + stream 笔迹 renderer
        ↓
H.264 MP4
        ↓
可选旁白/原声音轨 mux
```

其中：

- SRT 决定“说什么、什么时候说”
- `annotation.json` 决定“哪个元素对应哪个叙事事件”
- `sequence` 决定“画什么先、画什么后”
- `startMs` 是执行时间轴，由生产流程自动生成

## 为什么要修 sequence / startMs

原版预览台拖动模块顺序时会更新 `sequence`，但底层渲染器实际按 `reveal.startMs` 排序，因此存在两个顺序来源。

本 fork 不直接重写底层 77KB stream renderer，而是在生产入口前做规范化：

```text
sequence
  ↓
保留 durationMs
  ↓
自动重建 startMs
  ↓
得到无重叠串行时间轴
  ↓
交给原 renderer
```

这样既修复了真实成片顺序，又尽量减少对底层算法的侵入。

## 安装

推荐：

```bash
python scripts/prepare_env.py
```

也可以标准安装：

```bash
pip install -r requirements.txt
```

运行时依赖：

- opencv-python
- numpy
- av
- Pillow
- imageio-ffmpeg

## 9:16 竖版渲染

源图和 `annotation.canvas` 应为同一 9:16 像素尺寸，例如 1080×1920：

```bash
python scripts/render_short_video.py \
  scene.png \
  scene.annotation.json \
  scene.mp4 \
  --profile vertical-short-video
```

竖版 profile 默认：

- 1080×1920 目标比例
- 30 FPS
- 长边 1920
- `skeleton` 笔迹
- `contour-wipe` 上色
- 统一纸张色 `#F5EBD7`

渲染器保持输入图片比例，不会强行拉伸。如果需要严格限制比例，可加：

```bash
--strict-aspect
```

## 16:9 横版渲染

```bash
python scripts/render_short_video.py \
  scene.png \
  scene.annotation.json \
  scene.mp4 \
  --profile landscape-standard
```

## 合成旁白 / 原声

直接在最终渲染时传音频：

```bash
python scripts/render_short_video.py \
  scene.png \
  scene.annotation.json \
  scene-final.mp4 \
  --profile vertical-short-video \
  --audio narration.mp3
```

默认 `--audio-fit video`：音频不足时尾部补静音，以视频长度为准。

也可以单独给已有 MP4 加音轨：

```bash
python scripts/mux_audio.py silent.mp4 narration.mp3 final.mp4
```

音频合成优先寻找系统 `ffmpeg`；如果不存在，则使用 `imageio-ffmpeg` 提供的二进制。

## annotation 时序归一化

如果需要把规范化结果直接写回 JSON：

```bash
python scripts/annotation_tools.py scene.annotation.json \
  --normalize \
  --mode sequence \
  --gap-ms 180 \
  --in-place
```

主要处理：

- 按 `sequence` 重排 elements
- 自动重新编号为 1..N
- 保留 `durationMs`
- 重建不重叠 `startMs`
- 保证 `sceneDurationMs` 覆盖最后绘制和结尾凝视
- 校验画布、区域、protectedRegions、时长和时间轴

`render_short_video.py` 已经内置这一过程，正常生产时无需先手工执行。

## 标注格式

```json
{
  "sceneId": "scene-01",
  "canvas": {"width": 1080, "height": 1920},
  "sceneDurationMs": 9000,
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

字段关系：

- `sequence`：权威顺序
- `durationMs`：元素绘制预算
- `startMs`：可自动生成的执行字段
- `direction` / `handPath`：主要用于矩形代理预览
- `protectedRegions`：防止后绘元素提前泄露

## Mask 不变量

对元素 `E_i`：

```text
allowed(E_i)
= region(E_i)
- union(region(E_j), j > i)
- protectedRegions(E_i)
```

这里的 `j > i` 使用归一化后的绘制顺序。

## 编辑与检查

浏览器区域编辑器仍位于：

```text
assets/preview.html
```

它可以调整区域、字幕、顺序和时间。

保存后推荐直接走 `render_short_video.py`，由生产入口再次根据 `sequence` 归一化时间轴，避免 UI 中残留的历史 `startMs` 影响最终成片。

区域检查图：

```bash
python scripts/render_annotation_preview.py \
  scene.png scene.annotation.json scene-preview.png
```

中文字体现在会跨平台自动探测，也可以强制指定：

```bash
SRT_WHITEBOARD_FONT=/path/to/font.ttf python scripts/render_annotation_preview.py ...
```

## SRT 分镜

```bash
python scripts/parse_srt.py input.srt --target-sec 30 --min-sec 25 --max-sec 35
```

时间切分只作为候选分镜。实际 Agent 工作流还应结合完整句、话题变化、因果/转折和人物/场景变化做语义微调，避免机械地按 30 秒切断叙事。

## 多幕合并

```bash
python scripts/merge_scenes.py --inputs scene-01.mp4 scene-02.mp4 scene-03.mp4 --output final.mp4
```

## 测试

```bash
python -m unittest discover -s tests -v
```

当前测试覆盖：

- `sequence` 成为 canonical order
- 重排后 `startMs` 自动串行化
- region 越界检测

GitHub Actions 会在 push / PR 时执行脚本语法检查和这些单元测试。

## 仓库结构

```text
srt-whiteboard-animation/
├── SKILL.md
├── README.md
├── requirements.txt
├── profiles/
│   ├── vertical-short-video.json
│   └── landscape-standard.json
├── assets/
│   ├── drawing-hand.png
│   └── preview.html
├── scripts/
│   ├── parse_srt.py
│   ├── annotation_tools.py
│   ├── render_annotation_preview.py
│   ├── render_stream_whiteboard.py
│   ├── render_short_video.py
│   ├── mux_audio.py
│   ├── merge_scenes.py
│   └── prepare_env.py
├── tests/
│   └── test_annotation_tools.py
└── agents/openai.yaml
```

## 兼容性策略

原 `render_stream_whiteboard.py`、`stream_render.py`、`merge_scenes.py` 均保留。

新能力通过包装层组合已有 renderer，而不是直接大面积修改底层算法。这样未来从上游同步 stream/path 算法时，冲突更少。

## 许可证

MIT License，详见 [LICENSE](LICENSE)。

## 上游作者

原项目作者：一个爱养鱼的老登 / AI Builder / 用 AI 团队打造一人公司。

抖音、B站、公众号：江哥是老登啊
