# SRT Whiteboard Animation · Production Fork

把 **SRT / 旁白 / 脚本** 转成按叙事顺序绘制的白板手绘视频。

本仓库 fork 自 `geeklee/srt-whiteboard-animation`，保留上游最有价值的 **分区遮罩 + stream 连续笔迹 renderer**，并在外围补上短视频生产需要的语义分幕、9:16、Polygon 遮罩、真实低清预览、批量渲染、音频合成、校验和 CI。

> 设计目标不是重写上游笔迹算法，而是把它变成一个更稳定、可编排、可批处理的 Whiteboard Video Skill。

## 当前生产链路

```text
SRT / 脚本 / 旁白
        │
        ▼
parse_srt.py --mode semantic
时长 + 标点 + 停顿 + 转折的分幕建议
        │
        ▼
Agent narrative review / storyboard
        │
        ▼
image generation
        │
        ├── suggest_regions.py
        │   CV visual proposals: region + maskPolygon
        ▼
annotation.json
sequence = 唯一绘制顺序
        │
        ▼
preview-v2.html
时序 / region / Polygon 可视化调整
        │
        ▼
annotation + polygon validation
        │
        ├── render_preview.py
        │   同一 renderer 的低清真实 stream 预览
        ▼
render_short_video.py
Polygon-aware production renderer
        │
        ├── render_project.py 多幕批处理
        ▼
merge + audio mux
        │
        ▼
final MP4
```

## 这版解决了什么

- `sequence` 与 `startMs` 不再形成两套绘制顺序；
- 支持 9:16 / 16:9 profile；
- SRT 分幕从纯时长升级为确定性语义感知边界；
- Preview V2 拖动顺序会立刻重建时间轴；
- 支持 `maskPolygon` / `protectedPolygons`，复杂重叠不再只能靠粗矩形；
- 新增 CV 区域/Polygon proposal，但明确不把视觉连通域冒充语义理解；
- 新增真实低清 stream preview，质量判断不再只看矩形代理；
- 支持单幕音频、整条旁白、多幕批量渲染；
- 修复跨平台中文字体；
- 增加 annotation / Polygon 校验、运行时测试和 GitHub Actions。

---

# 1. sequence 是唯一绘制顺序

新版默认模型：

```text
sequence
→ duration + gap + lead-in
→ 自动派生 startMs
→ validation
→ renderer
```

生产入口：

```bash
python scripts/render_short_video.py scene.png scene.annotation.json scene.mp4 \
  --profile vertical-short-video
```

旧 annotation 仍兼容。只有明确需要复现历史 `startMs` 时才使用：

```bash
--timeline-mode startMs --no-retime
```

---

# 2. SRT 语义分幕

默认：

```bash
python scripts/parse_srt.py narration.srt \
  --mode semantic \
  --target-sec 30 \
  --min-sec 25 \
  --max-sec 35
```

`semantic` 是**离线确定性启发式算法**，综合：

- 与目标时长的距离；
- 句号、问号、感叹号、分号；
- 字幕间停顿；
- “但是、后来、因此、最终、与此同时”等转折/阶段词。

输出包含 `boundaryReason`，供 Agent 再检查是否切断了完整事件或因果关系。

兼容旧纯时长逻辑：

```bash
--mode duration
```

---

# 3. 9:16 / 16:9 Profile

短视频默认：

```text
profiles/vertical-short-video.json
1080 × 1920
```

横版：

```text
profiles/landscape-standard.json
1920 × 1080
```

如果源图比例和 profile 不一致，生产入口会警告；可用 `--strict-aspect` 直接阻止错误比例继续渲染。

---

# 4. CV 自动区域 / Polygon Proposal

生成线稿后，可以先让 OpenCV 给出视觉候选：

```bash
python scripts/suggest_regions.py scene.png \
  --output scene.regions.json \
  --annotation-output scene.annotation.json \
  --preview scene-regions-preview.png
```

它会：

1. 从四角估计纸张背景；
2. 找到与背景颜色差异明显或更深的笔迹；
3. 合并邻近笔迹；
4. 做 connected components；
5. 输出候选 `region`；
6. 为候选对象生成 convex-hull / simplified `maskPolygon`。

常用参数：

```text
--merge-gap
--min-area-ratio
--max-regions
--color-threshold
--dark-threshold
```

**重要：它只做视觉 proposal。**

它不知道哪个对象对应哪句字幕，也不知道叙事顺序。正确生产流程是：

```text
CV proposal
→ Agent 看字幕 + 看图
→ 语义匹配
→ 合并 / 拆分
→ sequence 排序
→ Preview 微调
```

自动生成的 annotation 会明确写：

```text
narrativeRole = 待 Agent 结合字幕确认
```

---

# 5. Polygon Annotation

矩形仍然保留：

```json
"region": {"x": 120, "y": 200, "width": 500, "height": 700}
```

需要精细形状时增加：

```json
"maskPolygon": [
  {"x": 160, "y": 230},
  {"x": 560, "y": 220},
  {"x": 610, "y": 760},
  {"x": 180, "y": 820}
]
```

重叠保护可以同时使用：

```json
"reveal": {
  "protectedRegions": [],
  "protectedPolygons": []
}
```

生产 renderer 的允许掩码现在是：

```text
allowed mask
= 当前 maskPolygon（没有则 region）
- 所有后续元素 maskPolygon（没有则 region）
- 当前 protectedRegions
- 当前 protectedPolygons
```

因此完全不写 Polygon 的旧项目行为不变；有 Polygon 时才启用精细裁切。

---

# 6. Preview V2

打开：

```text
assets/preview-v2.html
```

建议用 Chrome / Edge，因为保存依赖 File System Access API。

支持：

- 模块拖拽排序；
- 自动重建 `sequence / startMs / sceneDurationMs`；
- duration / lead-in / gap / gaze；
- region 移动与精确尺寸；
- label / subtitle / reveal direction；
- `矩形 → Polygon`；
- 拖动 Polygon 顶点；
- 双击边附近增加顶点；
- 右键顶点删除；
- region 移动时 Polygon 同步移动；
- region 缩放时 Polygon 同比例缩放；
- 直接播放同目录 `<scene>-preview.mp4` 的真实 stream 预览。

浏览器时间轴仍然是快速代理；真正判断笔迹质量，请继续使用下一步。

---

# 7. 真实低清 Stream Preview

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
长边 540 px
```

它不是另一套模拟算法，而是调用**同一个 production renderer**，只降低分辨率和 FPS，因此非常适合检查：

- 实际绘制顺序；
- Polygon 是否切掉关键笔迹；
- future element 是否提前泄露；
- grid / skeleton 哪个更自然；
- 手部与笔迹的贴合程度。

生成 `<scene>-preview.mp4` 后，Preview V2 可以直接播放。

---

# 8. Annotation / Polygon 校验

基础 annotation 工具：

```bash
python scripts/annotation_tools.py scene.annotation.json --normalize
```

生产入口还会额外调用 Polygon validator，检查：

- canvas 是否有效；
- region 是否越界；
- duration 是否非法；
- sequence 是否连续；
- 时间轴是否重叠；
- `maskPolygon` 是否至少 3 个点；
- Polygon 顶点是否在 canvas 范围内；
- `protectedPolygons` 是否为正确数组结构；
- `sceneDurationMs` 是否覆盖最终绘制时间。

---

# 9. 单幕渲染

```bash
python scripts/render_short_video.py \
  scene.png \
  scene.annotation.json \
  scene.mp4 \
  --profile vertical-short-video
```

默认使用 `PolygonRegionStreamRenderer`：

- 有 Polygon → Polygon mask；
- 没 Polygon → 原矩形 region；
- 底层 ink/grid/skeleton/contour-wipe 算法继续复用上游。

常用覆盖：

```text
--ink-path grid|skeleton
--color-fill contour-wipe|brush
--fps
--cap-long-edge
--canvas-hex
--target-hand-height
```

带旁白：

```bash
python scripts/render_short_video.py ... --audio narration.mp3
```

---

# 10. 多幕批量生产

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
python scripts/render_project.py ./scenes ./final.mp4 \
  --profile vertical-short-video
```

带整条旁白：

```bash
python scripts/render_project.py ./scenes ./final.mp4 \
  --profile vertical-short-video \
  --audio narration-full.mp3
```

只看计划、不渲染：

```bash
--dry-run
```

批处理会自然排序、检查 image/annotation 配对、逐幕渲染、合并视觉、最终 mux 整条音轨并写出 manifest。

---

# 11. 为什么不直接重写 stream_render.py

这是本 fork 最重要的工程决策之一。

`stream_render.py` 仍是上游的核心笔迹算法，当前升级尽可能通过外围模块完成：

```text
parse_srt.py
suggest_regions.py
annotation_tools.py
polygon_schema.py
polygon_renderer.py
preview-v2.html
render_preview.py
render_short_video.py
render_project.py
mux_audio.py
profiles/
```

好处是：上游以后继续优化 skeleton、grid、hand path、contour wipe 时，这个 fork 仍然比较容易同步，而不是一次改造后彻底失去 upstream compatibility。

---

# 12. 测试与 CI

GitHub Actions 会：

1. 安装 `numpy + opencv-python-headless`；
2. `py_compile` 所有升级脚本；
3. 运行完整 unittest。

当前测试覆盖：

- sequence timeline normalize；
- annotation 边界校验；
- semantic SRT grouping；
- 多幕场景发现 / 自然排序；
- Polygon schema；
- Polygon mask 的真实数组裁切；
- protectedPolygon subtraction；
- CV proposal 对多个独立对象的识别。

---

# 安装

```bash
python scripts/prepare_env.py
```

或：

```bash
pip install -r requirements.txt
```

跨平台中文预览字体可覆盖：

```text
SRT_WHITEBOARD_FONT=/path/to/font.ttf
```

---

# 当前边界

这版已经支持 Polygon，但仍有几个明确边界：

- `maskPolygon` 在 Preview V2 中可视化编辑；`protectedPolygons` 主要由 Agent / JSON 写入，尚未做完整可视化编辑器；
- CV proposal 是启发式连通域，不是通用实例分割模型，复杂重叠图仍可能过度合并或拆分；
- 浏览器代理不是逐笔 renderer，本地 `render_preview.py` 才是最终笔迹 QC；
- 还没有内置字幕烧录、BGM ducking、SFX 事件轨；
- 图像生成、TTS、发布平台上传仍应由更大的 Video Agent / 其它 Skill 负责。

## License

MIT。上游作者与许可证信息保留，详见 [LICENSE](LICENSE)。
