# 原文视觉素材采集协议 v5

只处理当天冻结的原文 URL。自动模式固定使用 Codex 内置浏览器；不连接
Chrome，不登录，不读取 Cookie、Local Storage、Profile、密码或授权头。

## 捕获

1. 复用一个可见的内置浏览器标签页，等待正文、帖子或媒体元素稳定。
2. X 只捕获原帖主体；排除回复、他人转发、引用卡片和推荐流。冻结链接是
   转发或引用帖时，跟随可验证的原帖并记录 canonical URL。
3. 普通网页只捕获正常加载后的首屏，必须可见文章标题；禁止滚动、全文长图
   和拼接。正文存在相关图片时，可额外保存一张原图或图片元素截图。
4. 截图使用无损 PNG、至少 2× device scale；视频保留原始 MP4/MOV/WebM。
   不做本地裁切、缩放或重编码，展示文件逐字节复制原始文件。
5. 排除页面外壳、导航、登录面板、广告、二维码、评论区和推荐流。X 每条
   故事最多一个素材；普通网页最多一个首屏素材和一张正文图片。
6. `capture.json` 记录 `capture_type`、`asset_role`、`viewport`、
   `device_scale_factor`、`crop_box`、`original_dimensions`、
   `evidence_text`、`capture_attempt`、来源 URL 和捕获方式。

```json
{
  "complete": true,
  "asset_count": 1,
  "source_url": "https://example.com/post",
  "capture_method": "iab-element-screenshot",
  "capture_scope": "original_post_only",
  "asset_role": "x_original_post",
  "capture_type": "element_screenshot",
  "viewport": {"width": 1440, "height": 1000},
  "device_scale_factor": 2,
  "crop_box": {"x": 80, "y": 120, "width": 1000, "height": 500},
  "original_dimensions": {"width": 2000, "height": 1000},
  "evidence_text": "截图中可见并与新闻 claim 对应的原文",
  "capture_attempt": 1
}
```

## 本地验收与展示

schema 5 仍以自然尺寸计算展示信息，但不固定截图比例或尺寸。文字型截图
禁止放大：源像素不足时返回 `recapture_required`，自动流程提高分辨率重捕一次；
第二次仍不足则标记 `unavailable` 并回退资讯卡。原始文件保留在 raw 目录；
展示副本逐字节复制，并记录 `presentation_sha256`、`presentation_dimensions`
和 `presentation_format`。

素材必须通过 `evidence_text` 映射到 story claim。v5 允许后置
`visual_asset_id` beats：X 最多一个，普通网页最多两个，先显示资讯卡，再按
beat 顺序在同一 `source-visual-layer` 直接叠放图片或静音视频。素材位于卡片
之上、标题/顶部导航/字幕之下；不隐藏卡片、不按 card IDs 做复杂交叉淡入、
不渲染来源徽章。
