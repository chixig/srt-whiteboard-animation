# SRT Whiteboard Animation · Production Fork

把 **SRT / 旁白 / 脚本** 转成按叙事顺序绘制的白板手绘视频。

本仓库 fork 自 `geeklee/srt-whiteboard-animation`，保留上游最有价值的 **分区遮罩 + stream 连续笔迹渲染器**，并把它升级成更适合短视频和 Agent 自动化的生产工作流。

## 这版解决了什么

上游核心 renderer 很有价值，但生产使用存在几个明显缺口：

- `sequence` 与 `startMs` 可能冲突，拖动顺序不等于最终绘制顺序；
- 默认工作流偏 16:9，短视频 9:16 需要额外改造；
- SRT 分幕只按时长，不看标点、停顿和叙事转折；
- 浏览器预览是矩形代理，而且旧预览台存在排序与时间轴双真相；
- 单幕渲染后没有完整的旁白/原声音频合成；
- 多幕需要手工逐条运行；
- Windows 中文字体路径被硬编码；
- 缺少基础校验、测试和 CI。

本 fork 的原则是：**尽量不重写底层 stream renderer，把生产能力放到编排、配置、校验和合成层。**

---

## 架构

```text
SRT / 脚本 / 旁白
        │
        ▼
parse_srt.py
语义边界建议
(时长 + 标点 + 停顿 + 转折)
        │
        ▼
分镜 / 生图
        │
        ▼
annotation.json
sequence = 唯一绘制顺序
        │
        ├── preview-v2.html  可视化调整并自动重排时间轴
        │
        ▼
annotation_tools.py
校验 + timeline normalize
        │
        ▼
render_short_video.py
profile + stream renderer
        │
        ▼
单幕 MP4
        │
        ├── render_project.py  多幕批量渲染
        ▼
merge_scenes.py
        │
        ▼
mux_audio.py
旁白 / 原声音频
        │
        ▼
最终 MP4
```

### 三层职责

1. **字幕层**：决定什么时候说什么。
2. **annotation 编排层**：决定哪个视觉元素对应哪个叙事事件、什么顺序出现。
3. **stream renderer**：决定笔尖如何真实落墨、添彩和移动。

`annotation.json` 是整个系统最重要的中间表示，可以看作轻量级 Video DSL。

---

## 第一原则：sequence 是唯一顺序

新版默认：

```text
sequence
   ↓
自动重建 startMs
   ↓
底层 renderer
```

不再允许 `sequence=1`、但 `startMs` 却排在后面的双重真相。

生产入口 `render_short_video.py` 会在渲染前自动：

1. 按 `sequence` 排序；
2. 根据每个元素的 `durationMs`、gap、lead-in 重建 `startMs`；
3. 校验 annotation；
4. 再交给原 stream renderer。

如果必须兼容旧数据，可以使用：

```bash
--timeline-mode startMs --no-retime
```

---

## SRT 语义分幕

默认不再只是“30 秒到了就切”。

```bash
python scripts/parse_srt.py narration.srt \
  --mode semantic \
  --target-sec 30 \
  --min-sec 25 \
  --max-sec 35
```

`semantic` 是**离线确定性启发式算法**，综合：

- 与目标时长的距离；
- 句号、问号、感叹号、分号等句末信号；
- 字幕之间的静默停顿；
- “但是 / 后来 / 因此 / 最终 / 与此同时”等转折或阶段词。

每个场景会多输出：

```json
"boundaryReason": "sentence-end+transition:后来"
```

注意：这不是 LLM 级语义理解。Agent 仍可以在此基础上进一步调整叙事边界，但代码本身已经比纯时长切段自然得多。

保留旧模式：

```bash
--mode duration
```

---

## 9:16 / 16:9 Profile

内置：

```text
profiles/vertical-short-video.json   9:16 / 1080×1920
profiles/landscape-standard.json     16:9 / 1920×1080
```

默认生产入口使用竖版：

```bash
python scripts/render_short_video.py \
  scene-01.png \
  scene-01.annotation.json \
  scene-01.mp4 \
  --profile vertical-short-video
```

横版：

```bash
--profile landscape-standard
```

profile 集中管理：

- canvas / aspect ratio
- fps
- cap_long_edge
- hand size
- background color
- ink path
- color fill
- timeline gap / lead-in / gaze

---

## Preview V2

推荐使用：

```text
assets/preview-v2.html
```

在 Chrome / Edge 中打开，然后选择包含：

```text
scene-01.png
scene-01.annotation.json
scene-02.png
scene-02.annotation.json
...
```

的目录。

### V2 与旧版最关键的不同

**拖动模块顺序后立即：**

```text
array order
→ sequence 重新编号
→ startMs 自动重建
→ sceneDurationMs 更新
→ 时间轴立即同步
→ 代理预览立即同步
```

所以 V2 不再存在“列表显示一个顺序，最终 renderer 又按另一套 startMs 排序”的问题。

V2 当前适合：

- 拖拽绘制顺序；
- 调整 duration / gap / lead-in / gaze；
- 修改 region 数值；
- 在画布上拖动 region；
- 编辑字幕、名称和 direction；
- 保存时统一写回 sequence/startMs。

复杂 `protectedRegions` 精细编辑仍可暂时使用旧 `assets/preview.html`。

---

## annotation 校验

```bash
python scripts/annotation_tools.py scene.annotation.json \
  --image-width 1080 \
  --image-height 1920
```

检查包括：

- canvas 合法性；
- sequence 是否重复/缺失；
- region 是否越界；
- protectedRegions 是否越界；
- duration 是否有效；
- startMs 是否重叠；
- sceneDurationMs 是否覆盖完整绘制时间。

---

## 单幕生产入口

```bash
python scripts/render_short_video.py \
  scene-01.png \
  scene-01.annotation.json \
  scene-01-final.mp4 \
  --profile vertical-short-video \
  --ink-path grid \
  --color-fill contour-wipe
```

带旁白：

```bash
python scripts/render_short_video.py \
  scene-01.png \
  scene-01.annotation.json \
  scene-01-final.mp4 \
  --audio narration.mp3
```

底层仍调用上游：

```text
render_stream_whiteboard.py
stream_render.py
```

---

## 多幕批量项目

如果目录里已经有多组：

```text
scene-01.png
scene-01.annotation.json
scene-02.png
scene-02.annotation.json
scene-03.png
scene-03.annotation.json
```

直接：

```bash
python scripts/render_project.py \
  ./project-scenes \
  ./output/final.mp4 \
  --profile vertical-short-video \
  --audio narration-full.mp3
```

它会自动：

1. 按文件名自然排序发现场景；
2. 检查 annotation 是否有同名图片；
3. 逐幕调用 `render_short_video.py`；
4. 合并所有幕；
5. 最后把整条旁白 / 原声音轨 mux 到成片；
6. 输出 `final.manifest.json`。

只看执行计划、不真正渲染：

```bash
--dry-run
```

---

## 音频

独立使用：

```bash
python scripts/mux_audio.py video.mp4 narration.mp3 final.mp4
```

优先使用系统 ffmpeg；没有系统 ffmpeg 时，会尝试 `imageio-ffmpeg`。

为了避免 `merge_scenes.py` 的旧视频-only PyAV fallback 丢失音轨，**批量模式默认先合并所有视觉场景，再对最终视频添加整条音频。**

---

## 跨平台字体

`render_annotation_preview.py` 现在会自动探测：

- Windows：微软雅黑 / 黑体
- macOS：苹方 / 黑体
- Linux：Noto CJK / 文泉驿等

也可以强制指定：

```bash
SRT_WHITEBOARD_FONT=/path/to/font.ttf python scripts/render_annotation_preview.py ...
```

---

## 安装

```bash
python scripts/prepare_env.py
```

或：

```bash
pip install -r requirements.txt
```

依赖包括：

- OpenCV
- NumPy
- PyAV
- Pillow
- imageio-ffmpeg

---

## 测试

```bash
python -m unittest discover -s tests -v
```

GitHub Actions 同时会执行核心脚本 `py_compile` 和 unit tests。

---

## 推荐 Agent 工作流

```text
输入 SRT / 文案 / 音频
↓
解析字幕
↓
semantic scene planning
↓
Agent 检查并优化叙事边界
↓
生成每幕视觉策略
↓
生成图片
↓
生成 annotation.json
↓
Preview V2 / 自动校验
↓
render_project.py
↓
最终视频
```

这意味着这个仓库更适合作为一个 **Video Agent 的白板动画执行 Skill**，而不是把所有图生视频、发布和选题能力都硬塞进同一个仓库。

---

## 主要文件

```text
srt-whiteboard-animation/
├── SKILL.md
├── agents/openai.yaml
├── profiles/
│   ├── vertical-short-video.json
│   └── landscape-standard.json
├── assets/
│   ├── preview.html
│   ├── preview-v2.html
│   └── drawing-hand.png
├── scripts/
│   ├── parse_srt.py
│   ├── annotation_tools.py
│   ├── render_annotation_preview.py
│   ├── render_stream_whiteboard.py
│   ├── render_short_video.py
│   ├── render_project.py
│   ├── mux_audio.py
│   ├── merge_scenes.py
│   ├── stream_render.py
│   └── prepare_env.py
├── tests/
└── .github/workflows/tests.yml
```

## License

MIT License。原项目及其版权信息继续保留。
