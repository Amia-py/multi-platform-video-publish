# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Amia-py
"""微信视频号助手投稿（Playwright + 本机 Chrome 持久化 profile）。

用法：
  python publish_channels.py login [job.json]   # 打开登录页，等扫码
  python publish_channels.py form  [job.json]   # 只上传 + 落盘页面结构，不改任何字段
  python publish_channels.py fill  [job.json]   # 上传 + 填表，停在发布按钮前

job.json 结构见同目录 job.example.json。
"""
import os, sys, time, json

from playwright.sync_api import sync_playwright

WORK = os.path.dirname(os.path.abspath(__file__))
PLAT = "channels"
JOB_PATH = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else "job.json")
JOB_DIR = os.path.dirname(JOB_PATH)
with open(JOB_PATH, encoding="utf-8") as _f:
    JOB = json.load(_f)
CFG = JOB[PLAT]
OPT = JOB.get("_options", {})


def _resolve(v):
    if not v:
        return None
    return v if os.path.isabs(v) else os.path.abspath(os.path.join(JOB_DIR, v))


STATE_ROOT = _resolve(OPT.get("state_dir", ".video-publish"))
_pf = CFG.get("profile", "sns_profile")
PROFILE = _pf if os.path.isabs(_pf) else os.path.join(STATE_ROOT, _pf)
SHOTS = os.path.join(STATE_ROOT, "shots", PLAT)
VIDEO = _resolve(CFG["video"])
COVER = _resolve(CFG.get("cover"))
COVER_V = COVER
HOME = "https://channels.weixin.qq.com/platform"
CREATE = "https://channels.weixin.qq.com/platform/post/create"

DESC = CFG["desc"]
SHORT_TITLE = CFG.get("short_title", "")
KEEP_OPEN = OPT.get("keep_open_sec", 3000)

os.makedirs(SHOTS, exist_ok=True)
os.makedirs(PROFILE, exist_ok=True)


def logged_in(ctx):
    return any("weixin" in (c.get("domain") or "") and c["name"] in
               ("sessionid", "wxuin", "wxuinv", "wx_uin") for c in ctx.cookies())


def dump(page, tag):
    try:
        page.screenshot(path=os.path.join(SHOTS, f"wx_{tag}.png"), full_page=False)
        html = page.content()
        with open(os.path.join(SHOTS, f"wx_{tag}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  [wx_{tag}] url={page.url} html={len(html)}B")
    except Exception as e:
        print("  dump 失败:", str(e)[:120])


def open_ctx(p):
    return p.chromium.launch_persistent_context(
        PROFILE, channel="chrome", headless=False, no_viewport=True,
        args=["--disable-blink-features=AutomationControlled",
              "--start-maximized", "--no-first-run", "--no-default-browser-check"],
    )


def dismiss(page):
    for _ in range(5):
        hit = False
        for txt in ("我知道了", "知道了", "以后再说", "暂不", "关闭"):
            try:
                loc = page.locator(f"button:has-text('{txt}')")
                for i in range(min(loc.count(), 3)):
                    el = loc.nth(i)
                    if el.is_visible():
                        el.click(timeout=2000); hit = True
                        print("    关闭弹窗:", txt)
                        time.sleep(1.0)
            except Exception:
                pass
        if not hit:
            break


def probe(page, tag):
    info = page.evaluate("""() => {
      const out = [];
      document.querySelectorAll('input,textarea,[contenteditable="true"],button,span,div').forEach(el=>{
        const t=(el.innerText||'').trim();
        if (!(el.offsetWidth||el.offsetHeight)) return;
        const ph=el.getAttribute('placeholder')||'';
        const ce=el.isContentEditable||false;
        const cls=(el.className&&el.className.toString)?el.className.toString().slice(0,80):'';
        const tag=el.tagName;
        const keep = (tag==='INPUT'||tag==='TEXTAREA'||ce||ph) || (t && t.length<20);
        if (!keep) return;
        out.push({tag, type:el.type||'', ph, ce, txt:t.slice(0,40), cls});
      });
      return out;
    }""")
    with open(os.path.join(SHOTS, f"wx_{tag}_elements.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    seen = set()
    for e in info:
        k = (e["tag"], e["ph"], e["txt"], e["cls"][:24])
        if k in seen:
            continue
        seen.add(k)
        if e["tag"] in ("INPUT", "TEXTAREA") or e["ce"] or e["ph"]:
            print("   ", e)
    return info


def upload_video(page):
    inputs = page.evaluate("""() => [...document.querySelectorAll('input[type=file]')].map((el,i)=>({
        i, accept:(el.accept||'').slice(0,60), cls:(el.className||'').toString().slice(0,50),
        vis: !!(el.offsetWidth||el.offsetHeight), parent:(el.parentElement.className||'').toString().slice(0,60)
    }))""")
    print("  页面 file input:", inputs)
    # 选 accept 含 video 的那个，没有就用第一个
    idx = 0
    for e in inputs:
        if "video" in e["accept"]:
            idx = e["i"]
            break
    if inputs:
        print(f"  使用第 {idx} 个 input 上传视频（78MB）...")
        page.locator("input[type=file]").nth(idx).set_input_files(VIDEO)
    else:
        # 页面初始没有 file input：点上传区，用文件选择器兜住
        print("  页面无 file input，改用文件选择器...")
        done = False
        for txt in ("上传视频", "添加视频", "点击上传", "上传", "拖拽"):
            try:
                with page.expect_file_chooser(timeout=6000) as fc:
                    page.locator(f"text={txt}").first.click(timeout=5000)
                fc.value.set_files(VIDEO)
                print(f"  通过「{txt}」触发上传成功")
                done = True
                break
            except Exception as e:
                print(f"    「{txt}」不行: {str(e)[:70]}")
        if not done:
            dump(page, "upload_fail")
            print("  !! 无法触发上传，退出")
            return False
    time.sleep(8)
    dismiss(page)
    # 重要：视频号助手是 wujie 微前端，表单/缩略图都渲染在 <iframe name="content"> 内，
    # page.evaluate 只在主 frame 执行，读不到 iframe 文本 —— 之前用 innerText 判定
    # 导致「上传早已完成却一直报 ing」空转 20 分钟。
    # Playwright 的 locator 会跨 frame（且穿透 shadow DOM）搜索，必须用它判定。
    for i in range(60):
        time.sleep(5)
        try:
            if page.locator("text=上传失败").count() or page.locator("text=解析失败").count():
                st = "fail"
            elif page.locator("text=删除").count():
                st = "done"          # 缩略图区的「删除」按钮出现 = 上传完成
            elif page.locator("text=更换封面").count():
                st = "done"
            else:
                st = "ing"
        except Exception:
            st = "ing"
        if i % 4 == 0:
            print(f"  [{(i+1)*5}s] {st}")
            try:
                page.screenshot(path=os.path.join(SHOTS, f"wx_up_{i}.png"))
            except Exception:
                pass
        if st in ("done", "fail"):
            print(f"  上传状态: {st}（{(i+1)*5}s）")
            break
    else:
        print("  上传状态: 超时未确认（继续）")
    if st == "done":
        # 「删除」按钮只说明本地已选中文件，不代表服务端接收完毕 —— 再等一段时间
        print("  等待服务端接收完成（45s）...")
        for k in range(9):
            time.sleep(5)
            try:
                if page.locator("text=上传失败").count() or page.locator("text=解析失败").count():
                    print("  !! 出现上传失败提示")
                    break
            except Exception:
                pass
        print("  服务端等待结束")
    dismiss(page)
    time.sleep(3)


def probe_frames(page):
    try:
        for f in page.frames:
            print("   frame:", f.url[:110])
    except Exception as e:
        print("   probe_frames 失败:", str(e)[:80])


def locator_probe(page):
    """用 Playwright locator 探测（可穿透 iframe + open shadow DOM）；
    视频号表单在 wujie 微前端 iframe 里，frame.evaluate 的 querySelectorAll 读不到 shadow 内的元素。"""
    for s in ["[contenteditable]", "[contenteditable='true']", "textarea",
              "[data-placeholder]", "[class*=editor]", "[class*=desc]",
              "[class*=input]", "[class*=text]"]:
        try:
            loc = page.locator(s)
            c = loc.count()
            if c == 0:
                print(f"    {s}: 0")
                continue
            print(f"    {s}: {c}")
            for i in range(min(c, 4)):
                el = loc.nth(i)
                try:
                    d = el.evaluate("""e => e.tagName + '|ce=' + e.getAttribute('contenteditable')
                        + '|ph=' + (e.getAttribute('placeholder')||e.getAttribute('data-placeholder')||'')
                        + '|cls=' + ((e.className||'')+'').slice(0,70)""")
                    print("        ", d)
                except Exception as e2:
                    print("         (读取失败)", str(e2)[:60])
        except Exception as e:
            print(f"    {s} 探测失败 {str(e)[:50]}")


def fill_desc(page):
    loc = page.locator("[contenteditable]")
    n = loc.count()
    print("  [contenteditable] 数量:", n)
    if n == 0:
        print("  !! 未找到可编辑区，落盘 locator 探测：")
        locator_probe(page)
        return
    target = None
    for i in range(n):
        el = loc.nth(i)
        try:
            ce = el.get_attribute("contenteditable")
            vis = el.is_visible()
            print(f"    [{i}] ce={ce!r} vis={vis} cls={el.get_attribute('class')!r}")
            if vis and target is None and ce not in ("false",):
                target = el
        except Exception as e:
            print(f"    [{i}] 读取失败 {str(e)[:60]}")
    if target is None:
        print("  !! 没找到可见的描述编辑器")
        locator_probe(page)
        return
    print("  使用找到的描述编辑器")
    target.click()
    time.sleep(0.6)
    for line in DESC.split("\n"):
        if line:
            page.keyboard.insert_text(line)
        page.keyboard.press("Enter")
    time.sleep(1)
    try:
        got = target.inner_text().strip()
        print(f"  描述写入长度 {len(got)}，前 60 字：{got[:60]!r}")
        print(f"  描述结尾 40 字：{got[-40:]!r}")
    except Exception as e:
        print("  读取描述失败:", str(e)[:80])


def fill_short_title(page):
    for ph in ("概括", "短标题", "标题"):
        try:
            loc = page.locator(f"input[placeholder*='{ph}']").first
            if loc.count():
                loc.click()
                loc.fill(SHORT_TITLE)
                print("  短标题 OK:", loc.input_value())
                return
        except Exception:
            continue
    print("  !! 没找到短标题输入框")


def set_cover(page):
    if not os.path.exists(COVER_V):
        print("  跳过封面（竖版封面不存在）")
        return
    for txt in ("更换封面", "编辑封面", "设置封面", "选择封面"):
        try:
            loc = page.locator(f"text={txt}").first
            if loc.count() and loc.is_visible():
                loc.click(timeout=5000)
                print(f"  点了「{txt}」")
                time.sleep(3)
                dump(page, "cover_dialog")
                fi = page.locator("input[type=file]").last
                fi.set_input_files(COVER_V)
                time.sleep(5)
                dump(page, "cover_uploaded")
                for ok in ("确定", "完成", "保存"):
                    b = page.locator(f"button:has-text('{ok}')").last
                    if b.count() and b.is_visible():
                        b.click(timeout=4000)
                        print(f"  封面弹窗点了「{ok}」")
                        time.sleep(3)
                        break
                return
        except Exception as e:
            print(f"  封面「{txt}」失败:", str(e)[:120])
    print("  未找到封面入口")


def check_original(page):
    """确保「声明原创」没有被勾上（本片是引用评论，不能声明原创）。"""
    st = page.evaluate("""() => {
      const out=[];
      document.querySelectorAll('label,span,div').forEach(el=>{
        const t=(el.innerText||'').trim();
        if (t==='声明原创' || t==='原创声明') {
          const box=el.closest('label')||el.parentElement;
          const inp=box? box.querySelector('input[type=checkbox]') : null;
          out.push({txt:t, checked: inp? inp.checked : null});
        }
      });
      return out;
    }""")
    print("  原创声明状态:", st)
    return st


def publish_state(page):
    try:
        for name in ("发表", "发布"):
            btn = page.get_by_role("button", name=name)
            c = btn.count()
            print(f"  「{name}」按钮数量: {c}")
            for i in range(min(c, 3)):
                try:
                    print("    ", repr(btn.nth(i).inner_text()[:20]),
                          "visible=", btn.nth(i).is_visible(),
                          "enabled=", btn.nth(i).is_enabled())
                except Exception:
                    pass
    except Exception as e:
        print("  发表按钮探测失败:", str(e)[:100])


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "fill"
    with sync_playwright() as p:
        ctx = open_ctx(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if phase == "login":
            page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            dump(page, "login")
            print("→ 请用微信扫码登录（最多 10 分钟）")
            dl = time.time() + 600
            ok = False
            while time.time() < dl:
                if logged_in(ctx):
                    ok = True; break
                time.sleep(4)
            print("登录结果:", "成功" if ok else "超时")
            ctx.close()
            sys.exit(0 if ok else 2)

        if not logged_in(ctx):
            print("未登录，先跑 login"); ctx.close(); sys.exit(3)

        ok = False
        for attempt in range(1, 5):
            try:
                page.goto(CREATE, wait_until="domcontentloaded", timeout=60000)
                ok = True
                break
            except Exception as e:
                print(f"  打开发布页第 {attempt} 次失败: {str(e)[:90]}")
                time.sleep(6)
        if not ok:
            print("  发布页打不开，退出"); ctx.close(); sys.exit(4)
        time.sleep(10)
        dismiss(page)
        dump(page, "00_initial")
        probe(page, "00_initial")
        if upload_video(page) is False:
            _wait(page, ctx); return
        dump(page, "01_uploaded")
        probe_frames(page)
        probe(page, "01_uploaded")

        if phase == "form":
            print("→ 仅上传 + 结构落盘，未改字段")
            print("READY_FOR_REVIEW")
            _wait(page, ctx)
            return

        fill_desc(page)
        fill_short_title(page)
        # 封面 / 位置 / 合集 / 声明原创 由用户自行处理（本轮只填标题+内容）
        check_original(page)
        dismiss(page)
        time.sleep(2)
        page.evaluate("window.scrollTo(0,0)"); time.sleep(1.5)
        dump(page, "02_filled_top")
        page.evaluate("window.scrollTo(0,document.body.scrollHeight)"); time.sleep(1.5)
        dump(page, "03_filled_bottom")
        publish_state(page)
        print("=" * 60)
        print("READY_FOR_REVIEW —— 已停在「发表」前，未点击发表")
        print("=" * 60)
        _wait(page, ctx)


def _wait(page, ctx):
    end = time.time() + KEEP_OPEN
    while time.time() < end:
        time.sleep(5)
        try:
            if "post/create" not in page.url:
                print("页面已跳转:", page.url)
                break
        except Exception:
            print("页面已关闭")
            break
    try:
        ctx.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
