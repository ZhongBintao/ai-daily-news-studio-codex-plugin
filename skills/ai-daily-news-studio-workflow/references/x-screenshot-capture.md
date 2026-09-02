# 原文视觉素材采集协议 v5

只处理当天冻结的原文 URL。自动模式固定使用 Codex 内置浏览器；不连接
Chrome，不登录，不读取 Cookie、Local Storage、Profile、密码或授权头。

## 捕获

1. 复用一个可见的内置浏览器标签页，并在打开原文前通过 `viewport` 能力临时设置
   `{"width": 1440, "height": 900}`；等待正文、帖子或媒体元素稳定。
2. 截图完成后立即调用 `viewport.reset()`，不把临时尺寸带到后续浏览器任务。
3. X 只捕获原帖主体；排除回复、他人转发、引用卡片和推荐流。冻结链接是
   转发或引用帖时，跟随可验证的原帖并记录 canonical URL。
4. 普通网页直接截取扩大后的当前响应式视口，视口中应包含站点身份、文章标题和相邻
   首段或主图；禁止全文长图和拼接。正文存在明确相关图片时，可额外保存一张
   图片元素截图；找不到时跳过。
5. 截图记录真实的 viewport override、device scale 和原始像素尺寸；不要求伪造
   2× PNG。视频保留
   原始 MP4/MOV/WebM。不做本地裁切、缩放或重编码，展示文件逐字节复制原始文件。
6. 保留识别站点身份所需的必要结构，排除无关页面外壳、登录面板、广告、二维码、评论区和推荐流。X 每条
   故事最多一个素材；普通网页最多一个首屏素材和一张正文图片。
7. `capture.json` 记录 `capture_type`、`asset_role`、`viewport`、`viewport_override`、
   `device_scale_factor`、`crop_box`、`original_dimensions`、
   `evidence_text`、`capture_attempt`、来源 URL 和捕获方式；网站主内容还记录
   `content_bounds`。

最小截图调用顺序固定为：

```js
const viewport = await iab.capabilities.get("viewport");
await viewport.set({width: 1440, height: 900});
const raw = await tab.screenshot({fullPage: false});
await viewport.reset();
```

```json
{
  "complete": true,
  "asset_count": 1,
  "source_url": "https://example.com/post",
  "capture_method": "iab-expanded-viewport-screenshot",
  "capture_scope": "original_post_only",
  "asset_role": "x_original_post",
  "capture_type": "viewport_screenshot",
  "viewport": {"width": 1440, "height": 900},
  "viewport_override": {"width": 1440, "height": 900},
  "device_scale_factor": 2,
  "crop_box": {"x": 0, "y": 0, "width": 905, "height": 769},
  "original_dimensions": {"width": 905, "height": 769},
  "evidence_text": "截图中可见并与新闻 claim 对应的原文",
  "capture_attempt": 1
}
```

## 本地验收与展示

schema 5 仍以自然尺寸记录展示信息；采集时统一请求 1440×900 的扩大视口，但仍记录
浏览器实际返回的尺寸。扩大视口截图由模板按展示舞台自然放大；不再启动 clip 或分辨率重捕循环。原始文件保留在 raw 目录；
展示副本逐字节复制，并记录 `presentation_sha256`、`presentation_dimensions`
和 `presentation_format`。

素材必须通过 `evidence_text` 映射到 story claim。v5 允许后置
`visual_asset_id` beats：X 最多一个，普通网页最多两个，先显示资讯卡，再按
beat 顺序在同一 `source-visual-layer` 直接叠放图片或静音视频。素材位于卡片和故事标题
之上、顶部导航/字幕之下；不隐藏卡片、不按 card IDs 做复杂交叉淡入、
不渲染来源徽章。
