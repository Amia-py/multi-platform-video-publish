# multi-platform-video-publish

用 Playwright 驱动本机 Chrome，把一条视频自动投稿到 **B 站 / 抖音（中国版）/ 微信视频号** ——
上传视频、填标题与描述、打标签或话题、设置封面、选分区，最后**停在发布按钮前**，交给人来按。

> One `job.json` describes a publish job. Three standalone scripts. Stops right before the
> publish button. Field-tested selectors and pitfalls included.

没有官方投稿 Open API 的三个平台，用浏览器自动化是最直接的路径：登录态持久化、风控与弹窗
都在真实浏览器里自然通过，不需要逆向签名。

---

## 特性

- **一个 job.json 描述一次投稿**：视频、封面、标题、描述、标签/话题、分区，全在配置里。
- **三个脚本互相独立**：单平台调试零依赖，也可以三个平台并行跑（各用各的 profile）。
- **登录态持久化**：扫码一次，之后复用；profile 可指定绝对路径以复用既有登录。
- **永远停在发布前**：不代点发布，也不代选「创作声明 / 自主声明 / 声明原创」这类
  添加后不可修改的合规选项。
- **踩坑都写进注释和文档**：每个选择器、每个 sleep 背后都有一次实测。

## 环境

- Windows（脚本用 `channel="chrome"` 调本机 Chrome，不需要 `playwright install`）
- Python 3.9+
- `pip install playwright`

## 快速开始

```bash
git clone https://github.com/Amia-py/multi-platform-video-publish.git
cd multi-platform-video-publish
pip install playwright

# 1) 准备任务描述
cp scripts/job.example.json ./job.json
#    编辑 job.json：填 video / cover / title / desc / tags|topics / partition

# 2) 首次登录（每个平台一次，扫码；登录态存进 profile）
python scripts/publish_bilibili.py login job.json
python scripts/publish_douyin.py   login job.json
python scripts/publish_channels.py login job.json

# 3) 投稿：上传 + 填表，停在发布按钮前
python scripts/publish_bilibili.py fill job.json
python scripts/publish_douyin.py   fill job.json
python scripts/publish_channels.py fill job.json
```

跑完脚本会打印 `READY_FOR_REVIEW`，并**保持浏览器打开**。检查无误后自己点发布。

> ⚠️ 关掉浏览器窗口 = 本次上传作废（页面状态不跨会话保留）。
> 脚本默认空转 50 分钟后自动关闭，可用 `_options.keep_open_sec` 调整。

## 三平台对照

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

## 各平台硬坑（实测）

### B 站
- 新版分区是 **30 项一级平铺列表**（`.drop-list-v2-item[title]`），**没有「手机游戏」这种二级**。
- 标签框会**预填 2 个**，上限 10；`fill()+Enter` **偶发第一项不生效** → 必须逐个读 chip 校验并重试。
- 验证失败的分支**不要盲目回滚**（曾把已改对的「游戏」又改回「vlog」）。

### 抖音
- **话题上限 5 个（硬限制）**：第 6 个起，输入 `#` 后联想面板给的候选点了也不会变成话题，
  而且**会把第 5 个话题顶掉**。症状极有规律 —— 前 5 个必成功、第 6 个起必失败。
- 话题必须从下拉里点，三步缺一不可：
  1. **`#` 要用 `keyboard.type("#")`** 发真实 keydown。`insert_text` 走 CDP `Input.insertText`，
     不产生键盘事件，**联想面板根本不会弹**（症状：候选永远是左侧导航「首页/内容管理/数据中心」）。
  2. **`#` 之后停一下再 `insert_text(话题名)`**。若把 `#` 和中文一起逐字 `type`，
     面板弹出时编辑器重渲染会**吃掉话题名首字**。
  3. 候选**别按类名猜**（`li` 会命中左侧导航）。找「可见叶子节点里含目标词」的、
     打 `data-*` 标记后用 `locator` 点击。
- **点击 ≠ 成功**：只有真话题 chip 才被 `\xa0` 包裹，必须校验
  `"\xa0#" + 话题 + "\xa0" in 编辑器文本`。
- **失败回退前必须先 `target.click()`** 把焦点点回编辑器，否则 `Backspace` 会删掉前面已插好的 chip。
- 封面：从叶子节点「上传封面」向上找 5 层、谁的兄弟里有 file input 就是它（实测**第 4 个**）。
  盲取第一个会「提交成功但缩略图是黑的」。
- 点「完成」后会弹**「设置横封面获更多流量」推销弹窗** → 点**「暂不设置」**。

### 微信视频号
- 页面是 **wujie 微前端**，真实表单在 iframe
  `channels.weixin.qq.com/micro/content/post/create` 里。
  `page.evaluate` 只在主 frame 执行、**读不到 iframe 内容** → 任何基于 `innerText` 的判据恒为假
  （曾因此白等 20 分钟）。**必须用 Playwright `locator`**（跨 frame + 穿透 open shadow DOM）。
- 描述框是 **`contenteditable=""`（空值）**，选择器要写 `[contenteditable]`，
  写 `[contenteditable='true']` 会 `count() == 0`。
- 上传触发：页面初始**无 file input**，「上传视频 / 添加视频 / 点击上传」都点不到，
  **只有 `text=上传` 能点**，配 `expect_file_chooser`。
- 上传前页面**就有**「视频描述 / 短标题 / 位置」表单 → 不能用它们当「上传完成」判据；
  真正的信号是左侧缩略图区的**「删除」按钮**出现。

更细的选择器与现场记录见 [`references/`](references/)。

## 文件结构

```
SKILL.md                        总览：选型 / 用法 / 三平台对照 / 流程 / 停手规则 / 硬坑 / 排错表
scripts/job.example.json        一次投稿任务的模板
scripts/publish_bilibili.py     B 站
scripts/publish_douyin.py       抖音
scripts/publish_channels.py     微信视频号
references/bilibili.md          B 站现场记录
references/douyin-channels.md   抖音 + 视频号现场记录
```

运行态产物（profile、截图、HTML 快照）默认落在 `<cwd>/.video-publish/`，不会污染仓库目录。

## 排错清单

| 症状 | 原因 |
|---|---|
| 登录页扫码后仍判未登录 | cookie 判据的域/名字写错；打印 `ctx.cookies()` 看实际值 |
| 一直卡在「上传中」 | 判据读的是主 frame，实际内容在 iframe（视频号）→ 改用 locator |
| 找不到描述框 | 选择器写成 `[contenteditable='true']`，实际值是空串 |
| 分区选完又变回去 | 走了「回退到原值」分支 → 先判断当前值是否已经是目标值 |
| 封面缩略图是黑的 | 取错了 hidden input → 按「上传封面」节点向上定位 |
| 提交后立刻退出 | 等待循环的 URL 白名单太窄，把正常跳转当成「已离开」 |
| 两个平台互相抢浏览器 | 用了同一个 profile → 每平台独立 profile |

## 合规提醒

- 请遵守各平台的用户协议与社区规范，不要用于批量刷量、搬运或侵权内容。
- 脚本**不会**替你点发布，也不会替你勾选任何原创 / AI 声明 —— 这些判断留给人。
- 引用他人素材（剧情录屏、封面画面等）时请在描述中注明来源。

## License

MIT
