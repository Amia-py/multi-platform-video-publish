<!-- 由技能 bilibili-upload-automation 合并而来，供 multi-platform-video-publish 参考 -->

# 用 Playwright 自动化 B 站投稿（Windows，无连接器时）

## 0. 先确认真的没有连接器

先跑 `recommend-connectors` / `search_plugins` 找 B 站投稿类连接器。
没有 → 走本文方案。**不要谎称"B 站不支持 API 上传"**：Web 端投稿接口是存在的，
只是需要登录态；用浏览器自动化最省事，也不必逆向 wbi 签名。

## 1. 登录：不要用本机 Chrome 的 Default profile

实测：本机 Chrome `Default` profile 里只有匿名 bilibili cookie，**没有 `SESSDATA`**。

用**独立持久化 profile**，让用户扫码一次：

```python
ctx = p.chromium.launch_persistent_context(
    PROFILE, channel="chrome", headless=False, no_viewport=True,
    args=["--disable-blink-features=AutomationControlled",
          "--start-maximized", "--no-first-run", "--no-default-browser-check"])

def logged_in(ctx):
    return "SESSDATA" in {c["name"] for c in ctx.cookies()}
```

- 打开 `https://passport.bilibili.com/login`，轮询 `logged_in(ctx)`，给足 8 分钟。
- 第一次跑经常 8 分钟超时（用户没看到窗口）→ **先问一句再重跑**，别默默重试。
- profile 目录不要提交/删除，它是登录态本身。
- `headless=False` 必须；`channel="chrome"` 用本机 Chrome，免下 playwright 浏览器。
- 若 `pip install playwright` 走镜像源报 `from versions: none`，加 `-i https://pypi.org/simple`。

## 2. 投稿页与字段（2026-10 实测）

入口：`https://member.bilibili.com/platform/upload/video/frame`

| 字段 | 选择器 |
|---|---|
| 视频文件 | `input[type=file]`（**取 `.first`**，封面弹窗会再塞进来几个） |
| 标题 | `input[placeholder*='标题']` |
| 简介（Quill） | `div[contenteditable='true']`（可见的那个，class 含 `ql-editor`） |
| 标签 | `input[placeholder*='标签']` |
| 分区 | `.select-controller`（显示值 `.select-item-cont-inserted`） |
| 封面 | 先点 `text=添加封面` |
| 封面文件 | `.cover-upload input[type=file]`（`display:none`，`set_input_files` 照样能用） |
| 封面确认 | `.cover-editor-button .button.submit`（文案「完成」） |
| 存草稿 | `.submit-draft` |
| **立即投稿** | `.submit-add` |

**顺序很重要**：先传视频，再填字段，**最后**才开封面弹窗（否则 `input[type=file]` 会有多个）。

## 3. 分区：新版是「一级平铺列表」，别去找二级

实测 30 项，**全部是一级**：

```
影视 娱乐 音乐 舞蹈 动画 绘画 鬼畜 游戏 资讯 知识 人工智能 科技数码 汽车 时尚美妆
家装房产 户外潮流 健身 体育运动 手工 美食 小剧场 旅游出行 三农 动物 亲子 健康
情感 vlog 生活兴趣 生活经验
```

- DOM：`.drop-list-v2-item[title='游戏']`（`title` 属性就是要选的值）。
- **没有「手机游戏」**。想要"游戏→手机游戏"是旧版 UI 的写法，会 `Timeout`。
- 页面上**没有** `select-option` 之类的二级结构；不要按旧教程写。
- 当前值 `.select-item-cont-inserted` 的文本**每次上传都可能不同**（实测同一份稿子被判过
  `人工智能` 和 `vlog`），所以**必须读出来判断，不能假定默认值**。

正确写法（自校验，失败不硬撑）：

```python
page.locator(".select-controller").first.click(); time.sleep(2)
items = page.eval_on_selector_all(".drop-list-v2-item", "e=>e.map(x=>x.getAttribute('title'))")
if first not in items: page.keyboard.press("Escape"); return orig   # 不在列表就别点
page.locator(f".drop-list-v2-item[title='{first}']").first.click(timeout=6000)
now = page.locator(".select-item-cont-inserted").first.inner_text().strip()
```

**踩坑**：第一版脚本 `text='游戏'` 点完就去等 `text='手机游戏'` → 超时 → 走"回退到原值"分支，
把已经改对的 `游戏` **又改回了 `vlog`**。教训：**验证失败的分支不要盲目回滚**，
先判断"当前值是不是已经是我要的"，是就收工。

## 4. 标签：会预填 2 个，上限 10，必须逐个校验

- 上传后标签框里**已经有 2 个**（实测是「机器人」「人工智能」，B 站按内容预填）。
- 计数提示 `.tag-last-wrp`：「还可以添加 N 个标签」。已有 chip：`.tag-pre-wrp .label-item-v2-content`。
- 上限 **10**：`slots = 10 - len(existing)`，按优先级补足，不要硬塞 10 个新的。
- 输入框 `maxlength=20`。
- **`fill()` + `Enter` 偶发第一项不生效**（实测第一次跑丢了「世界计划」，只进 9 个）。
  必须逐个校验：

```python
for t in wanted:
    for attempt in range(1, 4):
        tg.click(); tg.fill(t); time.sleep(0.7)
        page.keyboard.press("Enter"); time.sleep(1.0)
        if t in chips(): break
        page.keyboard.press("Escape"); time.sleep(0.5)
    else:
        print("放弃", t)
```

## 5. 封面

```python
page.locator("text=添加封面").first.click(timeout=8000); time.sleep(3)
page.locator(".cover-upload input[type=file]").first.set_input_files(COVER); time.sleep(8)
page.locator(".cover-editor-button .button.submit").first.click(timeout=8000); time.sleep(4)
```

- 弹窗里有 4:3 与 16:9 两个画布，传一张图会自动填两边。
- 底部另有一个 `.bcc-dialog__footer`（确定/取消）属于**另一个**提示弹窗，别点错。
- 传完回列表页，`.cover-editor-button` 消失。

## 6. 弹窗与遮罩

上传后会弹「通知授权」等引导框。循环点掉 `知道了/我知道了/关闭/以后再说/暂不开启`，
再用 JS 把 `.bcc-dialog__wrapper` 之类遮罩 `display:none`。
**但要留神**：封面弹窗本身也带 `.bcc-dialog__wrap`，别把正在用的弹窗一起隐藏了。

## 7. 停手点：不要替用户按「立即投稿」

- 用户要"审查后再发"时，填完**只做**：`window.scrollTo` 到顶/到底各截一张图，
  读一下 `.submit-add` 是否 `disabled`、页面有没有 `请选择/请输入/不能为空` 提示，
  然后**保持浏览器打开**（脚本尾部 `while True: sleep`），把截图给用户。
- 想确认"发布按钮真的可点"，就查按钮 class 里有没有 `disabled`，以及
  `.form-item` 里有没有未填的必填项文案——比"看起来是蓝的"可靠。

## 8. 创作声明：**不可代用户决定**

`* 创作声明`，选项：`内容无需标注 / 含AI生成内容 / 含虚构演绎内容 / 内容含营销信息 / 个人观点，仅供参考`。

提示明确写着「添加后**不可再次编辑**」。所以**留空并告知用户**，
不要为了凑"只差一下"就自己选一个。

## 9. 效率

- 76MB 竖屏视频实测上传 5–20s；整个 fill 流程 ~90s。
- 每次重跑都要重新上传（页面状态不跨会话保留）→ **把标题/简介/标签/分区/封面
  写进同一个脚本一次跑完**，不要拆成多轮探测。
- 想探测 DOM，就顺手在流程里 `page.content()` 落盘 + 截图，事后离线解析，
  别为了看结构再传一遍视频。

## 10. 交付时要说清

- 稿件的 **BV 号 / 审核状态**在点「立即投稿」之前**不存在**，不要写成"已发布"。
- 明确区分「表单已填好」与「已投稿」。
