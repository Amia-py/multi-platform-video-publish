<!-- 由技能 douyin-wechat-channels-upload 合并而来，供 multi-platform-video-publish 参考 -->

# 抖音 / 微信视频号 投稿自动化（Windows，无连接器时）

> B 站投稿见另一个技能 `bilibili-upload-automation`。

## 0. 通用骨架

```python
ctx = p.chromium.launch_persistent_context(
    PROFILE, channel="chrome", headless=False, no_viewport=True,
    args=["--disable-blink-features=AutomationControlled",
          "--start-maximized", "--no-first-run", "--no-default-browser-check"])
```

- **同一 profile 不能被两个进程同时打开** → 要并行跑多个平台，**每个平台一个独立 profile**。
- 登录：打开各自首页，轮询 cookie 判定；抖音看 `sessionid`（域含 `douyin`），视频号看
  `sessionid`（域含 `weixin`）。可在一个窗口开两个标签一次扫码。
- 脚本尾部 `while True: sleep` 保持浏览器打开，把状态交给用户 —— 关掉窗口 = 上传作废。

---

## 1. 抖音创作者中心

入口：`https://creator.douyin.com/creator-micro/content/upload`
发布页会跳到 `.../content/publish` 或 `.../content/post/video`。

| 字段 | 选择器 |
|---|---|
| 视频文件 | `input[type=file]`（第一个） |
| 作品标题 | `input[placeholder*='作品标题']` |
| 作品描述 | `div[contenteditable='true']`（`zone-container editor-kit-container`，内含 `.ace-line`） |
| 封面入口 | `text=选择封面` |
| 发布 | `.button-dhlUZE.primary-cECiOJ.fixed-J9O8Yw`（文案「发布」） |
| 暂存离开 | 按钮文案「暂存离开」 |

### 坑 1：话题必须从下拉里点，纯文本 `#tag` 不生效

在描述框里 `insert_text("#世界计划")` 只会留下**纯文本**，发布后不是可点击话题。
必须输入 `#` 后等下拉出现，再点候选：

```python
page.keyboard.insert_text("#" + t)
time.sleep(1.8)
opts = page.evaluate("""() => {...}""")   # 找 [role=option] / li / 下拉容器里的项
hit = next((o for o in opts if o.startswith(t) or t in o[:len(t)+6]), None)
if hit:
    page.locator(f"text={hit}").first.click(timeout=4000)
else:
    for _ in range(len(t) + 1):           # 没命中就退格删掉，别污染描述
        page.keyboard.press("Backspace")
```

- **选择器不要写太泛**：用 `[class*=dropdown] li` 这类会匹配到**左侧导航**（实测候选返回
  `['首页','内容管理','数据中心']`），必须限定在真正的下拉容器里。
- 下拉容器的类名要在发布页 HTML 里现查，别猜。

### 坑 2：封面

`text=选择封面` 打开弹窗后，「上传封面」是个 `div`，**被压住，`click()` 会超时**。
直接定位隐藏 input：

```python
idx = page.evaluate("""() => {
  const lab=[...document.querySelectorAll('*')].find(e=>e.children.length===0 &&
            (e.innerText||'').trim()==='上传封面');
  if(!lab) return -1;
  const all=[...document.querySelectorAll('input[type=file]')];
  let node=lab;
  for(let k=0;k<5 && node++){
    const sib=node.nextElementSibling;
    if(sib){ const inp=sib.querySelector('input[type=file]'); if(inp) return all.indexOf(inp); }
    node=node.parentElement;
  }
  return -1;
}""")
page.locator("input[type=file]").nth(idx).set_input_files(COVER_V)
```

- **不要盲取第一个 hidden input** —— 弹窗里还有「生成参考图」等其它 input，
  取错会出现"提交成功但缩略图是黑的"。实测正解是**第 4 个**。
- 点「完成」后会弹**「设置横封面获更多流量」推销弹窗** → 点 **「暂不设置」**。
- 竖封面（3:4）设好后，**横封面（4:3）由抖音自动生成**，不用单独传。

### 坑 3：两个小雷

- 打开发布页偶发 `net::ERR_CONNECTION_RESET` → `page.goto` **重试 4 次**。
- 等待循环里若用 URL 判断"是否已跳走"，**白名单要含 `content/post/video`**，
  否则刚上传完页面自己跳一次就被误判成"页面已跳转"直接退出。
- 「自主声明」带 `*`，`Locator.click` 可能超时 → 先 `scroll_into_view_if_needed()`，
  再 `click(force=True)` 兜底。**选项内容需用户确认，不要代选。**

---

## 2. 微信视频号助手（channels.weixin.qq.com）

入口：`https://channels.weixin.qq.com/platform/post/create`

### 坑 1（最容易白跑）：页面是 wujie 微前端，表单在 iframe 里

```html
<iframe src="https://channels.weixin.qq.com/empty.html" name="content" data-wujie-flag="">
```

真实表单在 frame **`https://channels.weixin.qq.com/micro/content/post/create`**。

- `page.evaluate("document.body.innerText")` **只在主 frame 执行**，
  读不到 iframe 里的任何文本 → 任何基于 innerText 的判据**恒为假**。
- 症状：视频其实 10 秒就传完了，脚本却一路打印 `ing` 空转到超时（实测白等 20 分钟）。
- **正解：用 Playwright `locator`**（跨 frame + 穿透 open shadow DOM）。

**上传完成判据**（实测可用）：

```python
if page.locator("text=上传失败").count() or page.locator("text=解析失败").count():
    st = "fail"
elif page.locator("text=删除").count():      # 左侧缩略图区的「删除」按钮
    st = "done"
else:
    st = "ing"
```

⚠️ 「删除」出现只代表**本地已选中文件**，不代表服务端接收完 →
判定 done 后再**等 45s** 并轮询失败提示。

### 坑 2：描述框的 contenteditable 是**空字符串**

```html
<div contenteditable="" class="input-editor">   <!-- 注意：不是 "true" -->
```

- 写 `div[contenteditable='true']` 会 `count()==0`，直接判定"没找到编辑器"。
- **正确选择器：`[contenteditable]`**（不带值），再按 `is_visible()` 过滤。
- 短标题：`input[placeholder*='短标题']`（占位文案「填写短标题有机会获得更多流量」）。
- 写入用 `target.click()` + `page.keyboard.insert_text(line)` + `Enter` 逐行。

### 坑 3：触发上传

页面初始**没有** `input[type=file]`。逐个试文案，实测：

| 文案 | 结果 |
|---|---|
| 上传视频 | Timeout |
| 添加视频 | Timeout |
| 点击上传 | Timeout |
| **上传** | ✅ |

```python
with page.expect_file_chooser(timeout=6000) as fc:
    page.locator("text=上传").first.click(timeout=5000)
fc.value.set_files(VIDEO)
```

### 坑 4：上传前页面就有「视频描述 / 短标题 / 位置 …」表单

**不能**用"这些表单出现"当上传完成判据 —— 上传前它们就在（只是左侧是「+」占位框）。
真正的差异是左侧缩略图 + 「删除」按钮出现。

---

## 3. 停手点

两个平台都要：填完 → 截图（顶部 + 底部）→ 读发布按钮是否 `enabled` → **不点发布**，
保持浏览器打开，把待用户确认的项列清楚：

- 抖音：`自主声明`（带 `*`）、话题是否需要重新选、封面横竖两张。
- 视频号：封面、位置、添加到合集、`声明原创`（引用评论类内容**不应勾**）。

## 4. 效率

- 视频号 78MB 实测**约 10s 内**缩略图就出来（别被"上传很慢"误导去加大等待）。
- 抖音 78MB 实测 15–20s。
- **每次重跑都要重新上传** → 把探测、填表、截图写进同一个脚本一次跑完。
- 想离线看 DOM：`page.content()` 只拿主 frame，**iframe 里的要 `frame.content()`** 单独落盘。

---

## 更正与补充（2026-10-05 实测，以此为准）

> 上文「坑 1：话题必须从下拉里点」的做法已被推翻，下面是跑通后的正确姿势。

### 抖音话题：上限 5 个，且必须三步走

1. **上限 5 个（硬限制）**：第 6 个起，输入 `#` 后联想面板给的候选点了也不会变成话题，
   而且**会把第 5 个话题顶掉**。症状极有规律 —— 前 5 个必成功、第 6 个起必失败。
   看到这个模式就不要再调选择器了，是产品限制。脚本用 `max_topics`（默认 5）截断。
2. **`#` 必须用 `keyboard.type("#")`**：`insert_text` 走 CDP `Input.insertText`，不产生键盘事件，
   联想面板根本不会弹（症状：候选永远是左侧导航「首页 / 内容管理 / 数据中心」）。
3. **`#` 之后停一下再 `insert_text(话题名)`**：`#` 和中文一起逐字 `type` 时，
   面板弹出会导致编辑器重渲染，**吃掉话题名首字**（实测得到 `#身智能` / `#全护栏` / `#术分析`）。
4. **候选定位别按类名猜**（`li` 会命中左侧导航）。找「可见叶子节点里含目标词」的，
   打上 `data-*` 标记后用 `locator` 点击 —— 按屏幕坐标点会因面板重排而落空。
5. **点击 ≠ 成功**：只有真 chip 才被 `\xa0` 包裹，必须校验 `"\xa0#话题\xa0" in 编辑器文本`，
   否则会出现「日志说成功、实际是纯文本」的假成功。
6. **失败回退前必须先 `target.click()`** 把焦点点回编辑器 —— 点击候选后联想面板抢走焦点，
   此时 `Control+End` / `Backspace` 作用在别处，**会把前面已插好的话题 chip 删掉**。
7. 每次输入话题前 `Control+End` 把光标按回末尾，否则话题顺序会乱、字符会交错。
