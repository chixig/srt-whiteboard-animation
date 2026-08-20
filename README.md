# SRT Whiteboard Animation · Production Fork

把 **SRT / 旁白 / 脚本** 转成按叙事顺序绘制、带字幕与完整音轨的白板手绘视频。

本仓库 fork 自 `geeklee/srt-whiteboard-animation`。上游最有价值的 **mask 分区编排 + stream 连续笔迹 renderer** 继续保留；本 fork 主要在外围增加生产能力，尽量不重写 `stream_render.py`，以便继续同步上游。

## 当前完整链路

```text
SRT / 脚本 / 旁白
        ↓
parse_srt.py --mode semantic
时长 + 标点 + 停顿 + 转折的分幕建议
        ↓
Agent narrative review / storyboard
        ↓
image generation
        ↓
suggest_regions.py
CV proposal: region + maskPolygon
        ↓
字幕 + 图片语义匹配
        ↓
annotation.json
sequence = 唯一绘制顺序
        ↓
preview-v2.html
时序 / region / Polygon 可视化调整
        ↓
annotation + polygon validation
        ↓
render_preview.py
同一 renderer 的真实低清 stream QC
        ↓
render_short_video.py / render_project.py
高清 Polygon-aware 白板渲染
        ↓
assemble_media.py
旁白 + BGM ducking + SFX + 字幕 + 时长校准
        ↓
final MP4
```

## 主要升级

- `sequence` 成为唯一绘制顺序，`startMs` 自动派生；
- 9:16 / 16:9 profile；
- SRT 从纯时长分幕升级为确定性语义感知边界；
- Preview V2 拖动顺序后立即重建时间轴；
- `maskPolygon` / `protectedPolygons` 进入真实 renderer；
- OpenCV 自动给出 region / Polygon proposal，但不冒充语义理解；
- 真实低清 stream preview 与最终 renderer 同源；
- 多场景自然排序、批量渲染、manifest；
- 旁白、BGM 自动 ducking、annotation 驱动 SFX、字幕烧录；
- 最终音视频自动按视频时长 trim/pad，并检查 duration drift；
- 跨平台中文字体、annotation/Polygon 校验、运行时 CI。

---

# 1. sequence 是唯一绘制顺序

```text
sequence
→ duration + gap + lead-in
→ startMs
→ validation
→ renderer
```

推荐入口：

```bash
python scripts/render_short_video.py \
  scene.png scene.annotation.json scene.mp4 \
  --profile vertical-short-video
```

只有兼容旧数据时才考虑：

```bash
--timeline-mode startMs --no-retime
```

---

# 2. SRT 语义分幕

```bash
python scripts/parse_srt.py narration.srt \
  --mode semantic \
  --target-sec 30 \
  --min-sec 25 \
  --max-sec 35
```

`semantic` 是离线确定性启发式，综合：目标时长、句末标点、字幕间停顿、转折/阶段词。输出 `boundaryReason`，供 Agent 继续检查完整事件、因果关系和叙事节奏。

复现旧行为：

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

源图比例不匹配时会警告；`--strict-aspect` 可直接阻止继续渲染。

---

# 4. CV 自动区域 / Polygon Proposal

```bash
python scripts/suggest_regions.py scene.png \
  --output scene.regions.json \
  --annotation-output scene.annotation.json \
  --preview scene-regions-preview.png
```

它通过背景估计、笔迹检测、连通域和 convex hull 给出候选 `region + maskPolygon`。

**它只做视觉 proposal。** 正确流程仍是：

```text
CV proposal
→ Agent 看字幕 + 看图
→ 语义匹配
→ 合并 / 拆分
→ sequence 排序
→ Preview 微调
```

---

# 5. Polygon Annotation

```json
{
  "region": {"x": 120, "y": 200, "width": 500, "height": 700},
  "maskPolygon": [
    {"x": 160, "y": 230},
    {"x": 560, "y": 220},
    {"x": 610, "y": 760},
    {"x": 180, "y": 820}
  ],
  "reveal": {
    "protectedRegions": [],
    "protectedPolygons": []
  }
}
```

真实允许掩码：

```text
当前 maskPolygon（没有则 region）
- 后续元素 maskPolygon（没有则 region）
- protectedRegions
- protectedPolygons
```

旧矩形 annotation 完全兼容。

---

# 6. Preview V2 + 真实低清预览

浏览器编辑：

```text
assets/preview-v2.html
```

支持 sequence、duration、lead-in/gap/gaze、region、字幕、Polygon 顶点增删与拖动。

真正判断笔迹质量：

```bash
python scripts/render_preview.py \
  scene.png scene.annotation.json scene-preview.mp4 \
  --profile vertical-short-video
```

默认 20 fps、长边 540px，调用的是同一套 production renderer。

---

# 7. 单幕最终成片

仅白板动画：

```bash
python scripts/render_short_video.py \
  scene.png scene.annotation.json scene.mp4 \
  --profile vertical-short-video
```

旁白：

```bash
--narration narration.mp3
```

旁白 + BGM 自动 ducking：

```bash
--narration narration.mp3 \
--bgm bgm.mp3 \
--bgm-gain-db -18 \
--duck-ratio 8
```

烧录字幕：

```bash
--subtitles narration.srt \
--subtitle-font "Noto Sans CJK SC"
```

完整示例：

```bash
python scripts/render_short_video.py \
  scene.png scene.annotation.json scene-final.mp4 \
  --profile vertical-short-video \
  --narration narration.mp3 \
  --bgm bgm.mp3 \
  --subtitles narration.srt \
  --subtitle-font "Noto Sans CJK SC"
```

`--audio` 仍作为 `--narration` 的兼容别名。

---

# 8. Annotation 驱动 SFX

场景级：

```json
{
  "sfx": [
    {"file": "sfx/scene-open.wav", "startMs": 300, "gainDb": -6}
  ]
}
```

元素级：

```json
{
  "id": "impact",
  "reveal": {"startMs": 2200, "durationMs": 1500},
  "sfx": [
    {"file": "sfx/hit.wav", "offsetMs": 120, "gainDb": -4}
  ]
}
```

元素 SFX 的全局时间锚点：

```text
scene global offset
+ normalized reveal.startMs
+ sfx.offsetMs
```

多幕项目会在每幕真实渲染完成后探测实际 MP4 时长，再累计下一幕的 global offset，减少跨幕编码时长误差。

也可额外传入全局 SFX plan：

```json
{
  "events": [
    {"file": "sfx/whoosh.wav", "startMs": 5300, "gainDb": -8}
  ]
}
```

```bash
--sfx-plan project.sfx.json
```

---

# 9. BGM Ducking

`audio_mix.py` 不是简单把 BGM 永久压低，而是：

```text
narration
   ├─→ final mix
   └─→ sidechain control
             ↓
looped BGM → sidechaincompress → ducked BGM
```

默认：

```text
BGM gain = -18 dB
duck ratio = 8
attack = 20 ms
release = 300 ms
```

旁白停止后，BGM 会按 release 恢复，不需要手工做音量关键帧。

---

# 10. 字幕烧录

字幕链路：

```text
SRT
→ subtitle_ass.py
→ ASS style
→ burn_subtitles.py / libass
→ H.264 MP4
```

ASS 尺寸会依据实际视频分辨率生成。可以调整字体、字号和底部安全边距。

要求 ffmpeg 含 `ass` filter；如果没有，会明确报错而不是输出“看起来成功但没有字幕”的视频。

---

# 11. 最终音视频装配与时长校准

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
→ narration/BGM/SFX mix
→ apad + atrim 到视频长度
→ mux
→ subtitle burn-in
→ probe final duration
→ drift validation
```

默认允许最大时长漂移：

```text
250 ms
```

超过阈值直接报错。可用 `--max-drift-ms` 调整。

---

# 12. 多幕批量生产

```bash
python scripts/render_project.py ./scenes ./final.mp4 \
  --profile vertical-short-video \
  --narration narration-full.mp3 \
  --bgm bgm.mp3 \
  --subtitles narration-full.srt
```

`render_project.py` 会：

1. 自然排序 scene；
2. 校验 image/annotation 配对；
3. 逐幕调用 production renderer；
4. 探测每幕真实输出时长；
5. 汇总 annotation SFX 到全局时间轴；
6. 合并视觉；
7. 调用 `assemble_media.py` 混音、字幕和时长校准；
8. 写 manifest。

只看计划：

```bash
--dry-run
```

---

# 13. 工程边界

本 fork 仍尽量不修改 `stream_render.py`。新增能力主要位于：

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
media_utils.py
audio_mix.py
sfx_plan.py
subtitle_ass.py
burn_subtitles.py
assemble_media.py
```

这样上游继续优化 skeleton、grid、hand path、contour wipe 时，仍更容易同步。

---

# 14. 测试与 CI

GitHub Actions 会安装真实 ffmpeg，并验证：

- `sidechaincompress` filter；
- `ass` / libass filter；
- 所有升级脚本 `py_compile`；
- 完整 unittest。

运行时测试覆盖：

- sequence/timeline；
- semantic SRT grouping；
- Polygon schema/raster mask；
- CV proposal；
- annotation SFX offset；
- BGM ducking + SFX 混音；
- ASS 字幕烧录；
- 最终 media assembly 的音轨存在性和 duration drift。

---

# 安装

```bash
python scripts/prepare_env.py
```

或：

```bash
pip install -r requirements.txt
```

字幕烧录建议安装带 libass 的系统 ffmpeg。`imageio-ffmpeg` 可作为一般 ffmpeg fallback，但不保证包含 libass。

跨平台中文预览字体可覆盖：

```text
SRT_WHITEBOARD_FONT=/path/to/font.ttf
```

## 当前边界

- CV proposal 仍是确定性连通域启发式，不是通用实例分割模型；
- `protectedPolygons` 主要由 Agent/JSON 写入，Preview V2 重点编辑当前元素 `maskPolygon`；
- semantic scene planning 仍需要 Agent 做完整叙事复核；
- BGM/SFX 素材选择本身不由 renderer 自动生成；
- 图像生成、TTS、发布平台上传应由更大的 Video Agent 或其它 Skill 负责。

## License

MIT。上游作者与许可证信息保留，详见 [LICENSE](LICENSE)。
