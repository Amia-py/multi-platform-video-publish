# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Amia-py
"""B 站投稿（Playwright + 本机 Chrome 持久化 profile）。

用法：
  python publish_bilibili.py login [job.json]   # 打开登录页，等扫码
  python publish_bilibili.py form  [job.json]   # 只上传 + 落盘页面结构，不改任何字段
  python publish_bilibili.py fill  [job.json]   # 上传 + 填表，停在发布按钮前

job.json 结构见同目录 job.example.json。
"""
import os, sys, time, json

from playwright.sync_api import sync_playwright

WORK = os.path.dirname(os.path.abspath(__file__))
PLAT = "bilibili"
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
_pf = CFG.get("profile", "bili_profile")
PROFILE = _pf if os.path.isabs(_pf) else os.path.join(STATE_ROOT, _pf)
SHOTS = os.path.join(STATE_ROOT, "shots", PLAT)
VIDEO = _resolve(CFG["video"])
COVER = _resolve(CFG.get("cover"))
UPLOAD_URL = "https://member.bilibili.com/platform/upload/video/frame"
LOGIN_URL = "https://passport.bilibili.com/login"

TITLE = CFG["title"]
DESC = CFG["desc"]
TAGS_PREF = CFG.get("tags", [])
PARTITION = tuple(CFG.get("partition", ["\u6e38\u620f"]))
KEEP_OPEN = OPT.get("keep_open_sec", 3000)

os.makedirs(SHOTS, exist_ok=True)
os.makedirs(PROFILE, exist_ok=True)


def logged_in(ctx):
    return "SESSDATA" in {c["name"] for c in ctx.cookies()}


def dump(page, tag):
    page.screenshot(path=os.path.join(SHOTS, f"{tag}.png"), full_page=False)
    html = page.content()
    with open(os.path.join(SHOTS, f"{tag}.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  [{tag}] url={page.url} html={len(html)}B")


def open_ctx(p):
    return p.chromium.launch_persistent_context(
        PROFILE, channel="chrome", headless=False, no_viewport=True,
        args=["--disable-blink-features=AutomationControlled",
              "--start-maximized", "--no-first-run", "--no-default-browser-check"],
    )


def dismiss_modals(page, tag=""):
    """关掉通知授权弹窗 / 引导弹窗。"""
    for _ in range(6):
        hit = False
        for txt in ("知道了", "我知道了", "关闭", "以后再说", "暂不开启"):
            try:
                loc = page.locator(f"button:has-text('{txt}'), .bcc-button:has-text('{txt}')")
                for i in range(min(loc.count(), 3)):
                    el = loc.nth(i)
                    if el.is_visible():
                        el.click(timeout=2500); hit = True
                        print(f"    关闭弹窗: {txt} {tag}")
                        time.sleep(1.2)
            except Exception:
                pass
        if not hit:
            break
    # 关掉遮罩
    try:
        page.evaluate("""() => {
          document.querySelectorAll('.bcc-dialog__wrapper,.bcc-modal,.vp-nd-f').forEach(e=>{
            const m=e.closest('.bcc-dialog__wrapper,.bcc-modal')||e;
            if (m && m.style) m.style.display='none';
          });
        }""")
    except Exception:
        pass


def upload_video(page):
    print("  上传视频中（76MB）...")
    page.locator("input[type=file]").first.set_input_files(VIDEO)
    time.sleep(6)
    dismiss_modals(page, "(上传后)")
    # 等上传完成：B 站上传完会显示「上传完成」或进度条消失
    for i in range(72):
        time.sleep(5)
        try:
            done = page.evaluate("""() => {
              const t = document.body.innerText || '';
              if (/上传完成|上传成功/.test(t)) return 'done';
              if (/上传失败|上传错误/.test(t)) return 'fail';
              return 'ing';
            }""")
        except Exception:
            done = "ing"
        if done != "ing":
            print(f"  上传状态: {done}（{(i+1)*5}s）")
            break
    else:
        print("  上传状态: 超时未确认（继续）")
    dismiss_modals(page, "(完成后)")
    time.sleep(3)


def fill_desc(page):
    """往 Quill 富文本简介里逐行写入。"""
    eds = page.locator("div[contenteditable='true']")
    for i in range(eds.count()):
        el = eds.nth(i)
        try:
            if not el.is_visible():
                continue
            el.click()
            time.sleep(0.4)
            for line in DESC.split("\n"):
                if line:
                    page.keyboard.insert_text(line)
                page.keyboard.press("Enter")
            got = el.inner_text().strip()
            print(f"  简介写入第 {i} 个编辑器，长度 {len(got)}")
            return got
        except Exception as e:
            print("  editor", i, "失败", str(e)[:120])
    print("  !! 简介未写入")
    return ""


def fill_tags(page):
    """保留页面预填标签，补足到 10 个。"""
    existing = page.eval_on_selector_all(
        ".tag-pre-wrp .label-item-v2-content", "els => els.map(e => e.innerText.trim())")
    print("  预填标签:", existing)
    slots = max(0, 10 - len(existing))
    tg = page.locator("input[placeholder*='标签']").first
    added = []

    def chips():
        return page.eval_on_selector_all(
            ".tag-pre-wrp .label-item-v2-content", "els => els.map(e => e.innerText.trim())")

    for t in TAGS_PREF:
        if len(added) >= slots:
            break
        if t in existing or t in added:
            continue
        for attempt in range(1, 4):
            try:
                tg.scroll_into_view_if_needed()
                tg.click()
                time.sleep(0.4)
                tg.fill(t)
                time.sleep(0.7)
                page.keyboard.press("Enter")
                time.sleep(1.0)
            except Exception as e:
                print(f"    标签 {t} 第{attempt}次异常:", str(e)[:100])
            if t in chips():
                added.append(t)
                break
            print(f"    标签 {t} 第{attempt}次未生效")
            page.keyboard.press("Escape")
            time.sleep(0.5)
        else:
            print(f"    !! 标签 {t} 放弃")
    final = page.eval_on_selector_all(
        ".tag-pre-wrp .label-item-v2-content", "els => els.map(e => e.innerText.trim())")
    print("  最终标签:", final)
    return final


def upload_cover(page):
    try:
        page.locator("text=添加封面").first.click(timeout=8000)
        time.sleep(3.5)
        dump(page, "07_cover_dialog")
        fi = page.locator(".cover-upload input[type=file]").first
        fi.set_input_files(COVER)
        time.sleep(8)
        dump(page, "08_cover_loaded")
        page.locator(".cover-editor-button .button.submit").first.click(timeout=8000)
        time.sleep(4)
        dump(page, "09_cover_done")
        print("  封面已提交")
        return True
    except Exception as e:
        print("  封面失败:", str(e)[:220])
        return False


def _part_value(page):
    try:
        return page.locator(".select-item-cont-inserted").first.inner_text().strip()
    except Exception:
        return ""


def set_partition(page, target=PARTITION):
    """B 站新版分区是「一级平铺列表」（.drop-list-v2-item[title]），无二级。
    target = (一级分区, 可选的二级分区名)。"""
    orig = _part_value(page)
    print("  分区原值:", orig)
    first = target[0]
    try:
        page.locator(".select-controller").first.click()
        time.sleep(2)
        dump(page, "10_part_open")
        items = page.eval_on_selector_all(
            ".drop-list-v2-item", "els => els.map(e => e.getAttribute('title'))")
        print(f"  下拉可选项({len(items)}):", items)
        if first not in items:
            print(f"  !! {first} 不在列表中")
            page.keyboard.press("Escape")
            return orig
        page.locator(f".drop-list-v2-item[title='{first}']").first.click(timeout=6000)
        time.sleep(2)
        now = _part_value(page)
        print(f"  点击 {first} → 分区值 {now}")
        # 若弹出二级列表（老版 UI 才有），再选一次
        if now != first and len(target) > 1:
            items2 = page.eval_on_selector_all(
                ".drop-list-v2-item", "els => els.map(e => e.getAttribute('title'))")
            print("  二级列表:", items2)
            if target[1] in items2:
                page.locator(f".drop-list-v2-item[title='{target[1]}']").first.click(timeout=6000)
                time.sleep(2)
                now = _part_value(page)
                print(f"  点击 {target[1]} → 分区值 {now}")
        dump(page, "10b_part_after")
        return now or orig
    except Exception as e:
        print("  分区切换失败:", str(e)[:200])
        try:
            page.keyboard.press("Escape")
            time.sleep(1)
        except Exception:
            pass
        print("  分区保留:", _part_value(page))
        return _part_value(page)


def publish_state(page):
    """报告「立即投稿」是否可点 + 页面上的校验提示。"""
    st = page.evaluate("""() => {
      const b=[...document.querySelectorAll('.submit-add')].pop();
      const hints=[...document.querySelectorAll('.form-item')].map(f=>{
        const t=(f.innerText||'').replace(/\\s+/g,' ').trim();
        const bad=/请选择|请输入|不能为空|必填/.test(t);
        return bad ? t.slice(0,90) : null;
      }).filter(Boolean);
      return {btn: !!b, cls: b?(b.className||'').toString():'', disabled: b?/disabled/.test((b.className||'').toString()):null, hints};
    }""")
    print("  投稿按钮:", st)
    return st


def probe_elements(page, tag):
    info = page.evaluate("""() => {
      const out = [];
      document.querySelectorAll('input,textarea,[contenteditable="true"],button,div[class*=cover],div[class*=upload]').forEach(el=>{
        const t=(el.innerText||'').trim();
        const ph=el.getAttribute('placeholder')||'';
        const cls=(el.className&&el.className.toString)?el.className.toString().slice(0,100):'';
        out.push({tag:el.tagName, type:el.type||'', ph, txt:t.slice(0,50), cls,
                  ce: el.isContentEditable||false,
                  vis: !!(el.offsetWidth||el.offsetHeight)});
      });
      return out;
    }""")
    with open(os.path.join(SHOTS, f"{tag}_elements.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    print(f"  [{tag}] 元素 {len(info)} 个 → {tag}_elements.json")
    for e in info:
        if e["vis"] and (e["ph"] or e["ce"] or e["tag"] in ("INPUT", "TEXTAREA")):
            print("   ", e)
    return info


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "form"
    with sync_playwright() as p:
        ctx = open_ctx(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if phase == "login":
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            time.sleep(3)
            dump(page, "00_login")
            print("→ 请扫码登录（最多 8 分钟）...")
            dl = time.time() + 480
            ok = False
            while time.time() < dl:
                if logged_in(ctx):
                    ok = True; break
                time.sleep(3)
            print("登录结果:", "成功" if ok else "超时")
            ctx.close()
            sys.exit(0 if ok else 2)

        if not logged_in(ctx):
            print("未登录，先跑 login"); ctx.close(); sys.exit(3)

        if phase == "form":
            page.goto(UPLOAD_URL, wait_until="domcontentloaded")
            time.sleep(8)
            upload_video(page)
            dump(page, "02_form")
            probe_elements(page, "02_form")
            ctx.close()
            return

        if phase == "probe2":
            page.goto(UPLOAD_URL, wait_until="domcontentloaded")
            time.sleep(8)
            upload_video(page)
            # 滚到底部，把下半部分表单露出来
            for _ in range(8):
                page.mouse.wheel(0, 600); time.sleep(0.6)
            time.sleep(2)
            dump(page, "05_lower")
            info = page.evaluate("""() => {
              const out = [];
              document.querySelectorAll('*').forEach(el=>{
                if (el.children.length) return;
                const t=(el.innerText||'').trim();
                if (!t || t.length>26) return;
                if (!(el.offsetWidth||el.offsetHeight)) return;
                const cls=(el.className&&el.className.toString)?el.className.toString().slice(0,90):'';
                out.push({tag:el.tagName, txt:t, cls});
              });
              return out;
            }""")
            with open(os.path.join(SHOTS, "05_texts.json"), "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=1)
            seen = set()
            for e in info:
                k = e["txt"]
                if k in seen: continue
                seen.add(k)
                print("   ", e)
            # 打开封面弹窗
            print("--- 点击 添加封面 ---")
            try:
                page.locator("text=添加封面").first.click(timeout=6000)
                time.sleep(3)
                dump(page, "06_cover_dialog")
                cinfo = page.evaluate("""() => {
                  const out=[];
                  document.querySelectorAll('input,button,div,span').forEach(el=>{
                    const t=(el.innerText||'').trim();
                    if (el.tagName==='INPUT') { out.push({tag:'INPUT',type:el.type,cls:(el.className||'').toString().slice(0,80)}); return; }
                    if (t && t.length<20 && /上传|封面|确定|完成|取消|截取/.test(t) && (el.offsetWidth||el.offsetHeight))
                      out.push({tag:el.tagName, txt:t, cls:(el.className&&el.className.toString)?el.className.toString().slice(0,80):''});
                  });
                  return out;
                }""")
                for e in cinfo[:40]:
                    print("   ", e)
            except Exception as e:
                print("   封面弹窗失败:", str(e)[:200])
            ctx.close()
            return

        if phase == "fill":
            page.goto(UPLOAD_URL, wait_until="domcontentloaded")
            time.sleep(8)
            dismiss_modals(page, "(进入)")
            upload_video(page)
            dump(page, "03_uploaded")

            # ---- 标题 ----
            ti = page.locator("input[placeholder*='标题']").first
            ti.click(); ti.fill(""); ti.type(TITLE, delay=8)
            print("  标题 OK:", ti.input_value())

            # ---- 简介 ----
            fill_desc(page)

            # ---- 标签 ----
            fill_tags(page)

            # ---- 封面 ----
            upload_cover(page)

            # ---- 分区 ----
            set_partition(page)

            dismiss_modals(page, "(填表后)")
            time.sleep(2)

            # 顶部 / 底部各存一张，供审查
            page.evaluate("window.scrollTo(0,0)"); time.sleep(1.5)
            dump(page, "11_final_top")
            page.evaluate("window.scrollTo(0,document.body.scrollHeight)"); time.sleep(1.5)
            dump(page, "12_final_bottom")
            st = publish_state(page)

            with open(os.path.join(SHOTS, "STATUS.txt"), "w", encoding="utf-8") as f:
                f.write("READY_FOR_REVIEW\n" + json.dumps(st, ensure_ascii=False, indent=1))

            print("=" * 60)
            print("READY_FOR_REVIEW —— 已停在「立即投稿」前，未点击发布")
            print("=" * 60)

            # 保持浏览器打开，等用户审查/发布（最多 50 分钟）
            end = time.time() + KEEP_OPEN
            while time.time() < end:
                time.sleep(5)
                try:
                    if "upload/video/frame" not in page.url:
                        print("页面已跳转:", page.url)
                        break
                except Exception:
                    print("页面已关闭")
                    break
            try:
                ctx.close()
            except Exception:
                pass
            return

        print("未知 phase:", phase)
        ctx.close()


if __name__ == "__main__":
    main()
