---
name: multi-platform-video-publish
agent_created: true
description: |
  在没有平台连接器/MCP 的情况下，用 Playwright + 本机 Chrome 持久化 profile
  自动化视频投稿到 B 站 / 抖音（中国版）/ 微信视频号：上传视频、填标题与描述、
  打标签或话题、设置封面、选分区，最后**停在发布按钮前**交给用户。
  一个 job.json 描述一次投稿，三个脚本各自独立可跑，登录态持久化、可并行。
  含各平台实测选择器与硬坑：B 站分区是 30 项一级平铺（无「手机游戏」二级）、
  标签预填 2 个且 fill+Enter 偶发失效必须逐个校验；抖音话题必须点下拉项、
  封面要按「上传封面」叶子节点向上找第 4 个隐藏 input；视频号是 wujie 微前端、
  表单在 iframe 内（page.evaluate 读不到，必须用 locator），描述框是 contenteditable=""。
  触发词：自动投稿、一键投稿、发布到 B站、发抖音、发视频号、多平台分发、
  投稿自动化、视频分发、上传视频到多个平台、publish video to bilibili/douyin/channels。
description_en: |
  Automate video publishing to Bilibili, Douyin (China) and WeChat Channels with Playwright
  driving the local Chrome persistent profile, when no platform connector/MCP exists.
  One job.json describes a job; three standalone scripts; persistent logins; parallel-safe.
  Includes field-tested selectors and hard-won pitfalls for each platform, and always stops
  right before the publish button for human review.
  Triggers: auto publish video, multi-platform distribution, upload to Bilibili/Douyin/WeChat Channels.
---

# 多平台视频投稿自动化（B 站 / 抖音 / 视频号）

## 0. 选型：先 skill，别急着做 MCP

- **能用 skill 就别做 MCP**：这三个平台都**没有官方投稿 Open API** 给个人开发者，
  走 Web 端就必须带登录态、过风控、处理弹窗 —— 这些恰恰是浏览器自动化的强项，
  MCP 化只会把同一套 Playwright 代码包一层，还多一份常驻进程和配置成本。
- 先跑 `recommend-connectors` / `search_plugins` 确认有没有现成连接器。
  没有 → 用本技能。
- **不要谎称"平台不支持上传"**：Web 投稿接口都在，缺的只是登录态。

## 1. 用法

```bash
# 1) 准备任务描述
cp scripts/job.example.json ./job.json && vi ./job.json

# 2) 首次登录（每个平台一次，扫码；登录态存进 profile）
python scripts/publish_bilibili.py login job.json
python scripts/publish_douyin.py   login job.json
python scripts/publish_channels.py login job.json

# 3) 投稿：上传 + 填表，停在发布按钮前
python scripts/publish_bilibili.py fill job.json
python scripts/publish_douyin.py   fill job.json
python scripts/publish_channels.py fill job.json
```

- 依赖：`pip install playwright`（若镜像源报 `from versions: none`，加 `-i https://pypi.org/simple`）。
- **不用** `playwright install` —— 走 `channel="chrome"` 直接用本机 Chrome。
- 运行态产物（profile、截图、HTML 快照）默认落在 `<cwd>/.video-publish/`。
- 三个平台**可以同时跑**：每个平台一个独立 profile，互不抢占
  （**同一个 profile 不能被两个进程同时打开**，这是并行的唯一约束）。

## 2. 三平台对照

| | B 站 | 抖音（中国版） | 微信视频号 |
|---|---|---|---|
| 入口 | `member.bilibili.com/platform/upload/video/frame` | `creator.douyin.com/creator-micro/content/upload` | `channels.weixin.qq.com/platform/post/create` |
| 登录判据 | cookie `SESSDATA` | 域含 `douyin` 的 `sessionid` / `sid_tt` | 域含 `weixin` 的 `sessionid` |
| 标题 | `input[placeholder*='标题']` | `input[placeholder*='作品标题']` | `input[placeholder*='短标题']` |
| 正文 | `div[contenteditable='true']`（`ql-editor`） | `div[contenteditable='true']`（`zone-container`） | **`[contenteditable]`**（值是空串！） |
| 标签/话题 | `input[placeholder*='标签']`，上限 10 | 描述里打 `#` **点下拉项**，**上限 5** | 描述里写 `#话题` 文本 |
| 封面 | `.cover-upload input[type=file]` → `.cover-editor-button .button.submit` | 「上传封面」**第 4 个** hidden input → 「完成」→「暂不设置」 | 「更换封面」 |
| 发布按钮 | `.submit-add` | `.button-dhlUZE.primary-cECiOJ.fixed-J9O8Yw` | `button:has-text('发表')` |
| 特殊 | **分区必选**（新版一级平铺 30 项） | 「自主声明」带 `*` | 「声明原创」（引用类内容别勾） |

## 3. 通用流程

1. `launch_persistent_context(profile, channel="chrome", headless=False, no_viewport=True)`
   + `--disable-blink-features=AutomationControlled`。
2. 未登录 → 打开登录页，轮询 cookie，给足 8–10 分钟（**用户可能没看到窗口，超时先问一句再重跑**）。
3. 打开发布页（**重试 3–4 次**，偶发 `ERR_CONNECTION_RESET`）。
4. 上传视频 → 等上传完成 → 关引导弹窗。
5. 填标题 / 正文 / 标签 / 封面 / 分区。
6. 滚到顶、底各截一张图，读发布按钮 `disabled` 状态与页面校验提示。
7. **不点发布**，打印 `READY_FOR_REVIEW`，保持浏览器打开（脚本尾部空转）。

## 4. 停手规则（重要）

- **绝不代点发布按钮**，也**绝不代选**「创作声明 / 自主声明 / 声明原创」这类
  「添加后不可修改」的合规选项 —— 列出来让用户自己选。
- 稿件的 BV 号 / 作品 ID 在点发布前**不存在**，汇报时不要说"已发布"，
  要区分「表单已填好」和「已投稿」。
- 浏览器窗口保持打开；**关掉窗口 = 本次上传作废**（页面状态不跨会话保留）。
  脚本空转默认 50 分钟后自动关闭，汇报时要提醒用户尽快操作。

## 5. 各平台硬坑（详见 `references/bilibili.md`、`references/douyin-channels.md`）

**B 站**
- 新版分区是 **30 项一级平铺列表**（`.drop-list-v2-item[title]`），**没有「手机游戏」这种二级**。
- 标签框会**预填 2 个**，上限 10；`fill()+Enter` **偶发第一项不生效** → 必须逐个读 chip 校验并重试。
- 验证失败的分支**不要盲目回滚**（曾把已改对的「游戏」又改回「vlog」）。

**抖音**
- **话题上限 5 个（硬限制，实测）**：第 6 个起，输入 `#` 后联想面板给的候选点了也不会变成话题，
  而且**会把第 5 个话题顶掉**。脚本按 `max_topics`（默认 5）只取前 N 个，多的直接不尝试。
  症状极有规律：前 5 个必成功、第 6 个起必失败 —— 看到这个模式就别再调选择器了，是产品限制。
- 话题必须从下拉里点，三步缺一不可：
  1. **`#` 要用 `keyboard.type("#")`** 发真实 keydown。`insert_text` 走 CDP `Input.insertText`，
     不产生键盘事件，**联想面板根本不会弹**（症状：候选永远是左侧导航「首页/内容管理/数据中心」）。
  2. **`#` 之后停一下再 `insert_text(话题名)`**。若把 `#` 和中文一起逐字 `type`，
     面板弹出时编辑器重渲染会**吃掉话题名首字**（实测得到 `#身智能` / `#全护栏` / `#术分析`）。
  3. 候选**别按类名猜**（`li` 会命中左侧导航）。找「可见叶子节点里含目标词」的、打上
     `data-*` 标记后用 `locator` 点击；按屏幕坐标点会因面板重排而落空。
- **点击 ≠ 成功**：只有真话题 chip 才被 `\xa0` 包裹。必须校验
  `"\xa0#" + 话题 + "\xa0" in 编辑器文本`，否则会出现「日志说成功、实际是纯文本」的假成功。
- **失败回退前必须先 `target.click()` 把焦点点回编辑器** —— 点击候选后联想面板会抢走焦点，
  此时 `Control+End` / `Backspace` 作用在别处，**会把前面已插好的话题 chip 删掉**。
- 封面：从叶子节点「上传封面」向上找 5 层、谁的兄弟里有 file input 就是它（实测**第 4 个**）。
  盲取第一个会"提交成功但缩略图是黑的"。
- 点「完成」后会弹**「设置横封面获更多流量」推销弹窗** → 点**「暂不设置」**。
- 等待循环的 URL 白名单要含 `content/post/video`，否则会被误判"页面已跳转"提前退出。

**视频号**
- 页面是 **wujie 微前端**，真实表单在 iframe `channels.weixin.qq.com/micro/content/post/create` 里。
  `page.evaluate` 只在主 frame 执行、**读不到 iframe 内容** → 任何基于 `innerText` 的判据恒为假
  （曾因此白等 20 分钟）。**必须用 Playwright `locator`**（跨 frame + 穿透 open shadow DOM）。
- 描述框是 **`contenteditable=""`（空值）**，选择器要写 `[contenteditable]`，
  写 `[contenteditable='true']` 会 count=0。
- 上传触发：页面初始**无 file input**，「上传视频 / 添加视频 / 点击上传」都点不到，
  **只有 `text=上传` 能点**，配 `expect_file_chooser`。
- 上传前页面**就有**「视频描述 / 短标题 / 位置」表单 → 不能用它们当"上传完成"判据；
  真正的信号是左侧缩略图区的**「删除」按钮**出现（但那也只是本地已选中，
  判定 done 后再等 45s 并轮询失败提示）。

## 6. 效率

| 项 | 实测 |
|---|---|
| 78MB 竖屏视频上传 | B 站 5–20s；抖音 15–20s；视频号 ~10s（缩略图出现） |
| 单平台 fill 全流程 | 约 90s |
| 重跑成本 | **每次重跑都要重新上传**（页面状态不跨会话保留） |

→ 所以**把探测、填表、截图写进同一次运行**，不要为了看 DOM 结构反复重传。
想离线分析：`page.content()` 只拿主 frame，**iframe 里的要 `frame.content()` 单独落盘**。

## 7. 排错清单

| 症状 | 原因 |
|---|---|
| 登录页扫码后仍判未登录 | cookie 判据的域/名字写错；打印 `ctx.cookies()` 看实际值 |
| 一直卡在"上传中" | 判据读的是主 frame，实际内容在 iframe（视频号）→ 改用 locator |
| 找不到描述框 | 选择器写成 `[contenteditable='true']`，实际值是空串 |
| 分区选完又变回去 | 走了"回退到原值"分支 → 先判断当前值是否已经是目标值 |
| 封面缩略图是黑的 | 取错了 hidden input → 按「上传封面」节点向上定位 |
| 提交后立刻退出 | 等待循环的 URL 白名单太窄，把正常跳转当成"已离开" |
| 两个平台互相抢浏览器 | 用了同一个 profile → 每平台独立 profile |

## 8. 复用既有登录态

若之前已登录过，job.json 里把 `profile` 写成**绝对路径**即可复用，不必重新扫码：

```json
{ "bilibili": { "profile": "D:/proj/work/bili_profile" } }
```
