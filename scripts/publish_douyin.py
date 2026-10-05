# -*- coding: utf-8 -*-
"""抖音（中国版）创作者中心投稿（Playwright + 本机 Chrome 持久化 profile）。

用法：
  python publish_douyin.py login [job.json]   # 打开登录页，等扫码
  python publish_douyin.py form  [job.json]   # 只上传 + 落盘页面结构，不改任何字段
  python publish_douyin.py fill  [job.json]   # 上传 + 填表，停在发布按钮前

job.json 结构见同目录 job.example.json。
"""
import os, sys, time, json

from playwright.sync_api import sync_playwright

WORK = os.path.dirname(os.path.abspath(__file__))
PLAT = "douyin"
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
_pf = CFG.get("profile", "dy_profile")
PROFILE = _pf if os.path.isabs(_pf) else os.path.join(STATE_ROOT, _pf)
SHOTS = os.path.join(STATE_ROOT, "shots", PLAT)
VIDEO = _resolve(CFG["video"])
COVER = _resolve(CFG.get("cover"))
COVER_V = COVER
HOME = "https://creator.douyin.com/"
UPLOAD = "https://creator.douyin.com/creator-micro/content/upload"

TITLE = CFG["title"]
DESC = CFG["desc"]
TOPICS = CFG.get("topics", [])
MAX_TOPICS = int(CFG.get("max_topics", 5))     # 抖音描述框话题上限（实测 5）
KEEP_OPEN = OPT.get("keep_open_sec", 3000)

os.makedirs(SHOTS, exist_ok=True)
os.makedirs(PROFILE, exist_ok=True)


def logged_in(ctx):
    return any("douyin" in (c.get("domain") or "") and c["name"] in
               ("sessionid", "sessionid_ss", "sid_tt") for c in ctx.cookies())


def dump(page, tag):
    try:
        page.screenshot(path=os.path.join(SHOTS, f"dy_{tag}.png"), full_page=False)
        html = page.content()
        with open(os.path.join(SHOTS, f"dy_{tag}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  [dy_{tag}] url={page.url} html={len(html)}B")
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
        for txt in ("我知道了", "知道了", "以后再说", "暂不", "关闭", "取消"):
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
    with open(os.path.join(SHOTS, f"dy_{tag}_elements.json"), "w", encoding="utf-8") as f:
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
    print("  上传视频中（78MB）...")
    fi = page.locator("input[type=file]").first
    fi.set_input_files(VIDEO)
    time.sleep(8)
    dismiss(page)
    for i in range(90):
        time.sleep(5)
        try:
            st = page.evaluate("""() => {
              const t = document.body.innerText || '';
              if (/上传成功|发布成功|重新上传|上传完成/.test(t)) return 'done';
              if (/上传失败|上传出错|解析失败/.test(t)) return 'fail';
              return 'ing';
            }""")
        except Exception:
            st = "ing"
        if st != "ing":
            print(f"  上传状态: {st}（{(i+1)*5}s）")
            break
    else:
        print("  上传状态: 超时未确认（继续）")
    dismiss(page)
    time.sleep(3)


def fill_desc(page):
    """抖音描述是 contenteditable，话题要在输入 # 后从下拉里选。"""
    eds = page.locator("div[contenteditable='true']")
    n = eds.count()
    print("  contenteditable 数量:", n)
    target = None
    for i in range(n):
        el = eds.nth(i)
        try:
            if el.is_visible():
                target = el
                print(f"  使用第 {i} 个 contenteditable")
                break
        except Exception:
            pass
    if target is None:
        print("  !! 没找到描述编辑器")
        return
    target.click()
    time.sleep(0.5)
    for line in DESC.split("\n"):
        if line:
            page.keyboard.insert_text(line)
        page.keyboard.press("Enter")
    time.sleep(1.5)

    # 话题：输入 #名称 后必须从下拉里「点」中，光按 Enter 会退化成纯文本并粘连。
    # 关键 1：用 keyboard.type 而不是 insert_text —— insert_text 走 CDP Input.insertText，
    #         不产生 keydown/keypress，靠键盘事件触发的联想面板根本不会弹（实测候选永远是左侧导航）。
    #         中文部分 Playwright 会自动退化为 insertText，但 '#' 是 ASCII，会发出真实 keydown。
    # 关键 2：候选不要按类名猜（`li` 会命中左侧导航），直接找「可见叶子节点里含目标词」的，
    #         按屏幕坐标点；并排除描述编辑器自身（正文里可能已有同名词）。
    ok_topics, bad_topics = [], []
    abort = False
    # 实测：抖音描述框**最多只能挂 5 个话题**。第 6 个开始，输入 # 后联想面板给的候选
    # 点了也不会变成话题（退化成纯文本）；更糟的是它会把第 5 个话题顶掉。
    # 所以按顺序只取前 5 个，多余的直接不尝试。
    wanted = TOPICS[:MAX_TOPICS]
    if len(TOPICS) > MAX_TOPICS:
        print(f"  !! 抖音上限 {MAX_TOPICS} 个话题，忽略: {TOPICS[MAX_TOPICS:]}")
    for t in wanted:
        hit_ok = False
        for attempt in range(1, 3):          # 面板搜索是异步的，偶发不更新 → 重试一次
            try:
                # 每次插入前把光标按回末尾，否则会插到中间，话题顺序会乱、字符会交错
                target.click()
                page.keyboard.press("Control+End")
                time.sleep(0.3)
                before = len(target.inner_text())
                # '#' 必须用 keyboard.type 发出真实 keydown（insert_text 不产生键盘事件，联想面板不会弹）；
                # 话题名改用 insert_text 一次性插入 —— 若和 '#' 一起逐字 type，面板弹出时编辑器会
                # 重渲染 DOM，话题名的首字会被吃掉（实测出现 #身智能 / #全护栏 / #术分析）。
                page.keyboard.type("#", delay=60)
                time.sleep(1.2)
                page.keyboard.insert_text(t)
                cand = []
                for _ in range(5):               # 轮询等面板刷新
                    time.sleep(0.8)
                    cand = page.evaluate("""(kw) => {
                      // 每次先清掉上一轮打的标记，避免点到残留元素
                      document.querySelectorAll('[data-vp-cand]').forEach(e=>e.removeAttribute('data-vp-cand'));
                      const out=[];
                      document.querySelectorAll('*').forEach(el=>{
                        if (el.children.length) return;                  // 只取叶子节点
                        if (!(el.offsetWidth||el.offsetHeight)) return;
                        if (el.closest('.zone-container')) return;       // 排除描述编辑器内部
                        const s=(el.innerText||'').trim();
                        if (!s || s.length>60 || s.indexOf(kw)===-1) return;
                        const r=el.getBoundingClientRect();
                        if (r.width<=0 || r.height<=0) return;
                        el.setAttribute('data-vp-cand', '1');            // 打标记，交给 locator 点
                        out.push({t:s.slice(0,40), x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)});
                      });
                      return out.slice(0,8);
                    }""", t)
                    if cand:
                        break
                if cand:
                    # 用 locator 点而不是按坐标点：面板可能在查询与点击之间重排，
                    # 坐标点击会落空（实测"点了候选但没变成话题"）。
                    try:
                        page.locator('[data-vp-cand="1"]').first.click(timeout=4000)
                    except Exception:
                        page.mouse.click(cand[0]["x"], cand[0]["y"])
                    time.sleep(1.5)
                    # 点中候选 ≠ 变成了话题 —— 只有 chip 才会被 nbsp 包裹。
                    # 不校验的话会出现「日志说成功、实际是纯文本 #xxx」的假成功。
                    if ("\xa0#" + t + "\xa0") in target.inner_text():
                        ok_topics.append(t)
                        print(f"    话题 {t} → 已插入（第 {attempt} 次）")
                        hit_ok = True
                        break
                    print(f"    话题 {t} 点了候选但未成话题，回退重试")
                # 失败回退：必须先把焦点点回编辑器 —— 点击候选后联想面板会抢走焦点，
                # 此时 Control+End / Backspace 作用在别处，会把前面已插好的话题 chip 删掉
                # （实测：失败的"大模型""安全护栏"各带走了一个已成功的 chip）。
                target.click()
                time.sleep(0.3)
                page.keyboard.press("Control+End")
                time.sleep(0.3)
                for _ in range(3):           # 反复校验，退到确实回到 before 长度为止
                    now = len(target.inner_text())
                    if now <= before:
                        break
                    for _ in range(now - before + 1):
                        page.keyboard.press("Backspace")
                    time.sleep(0.4)
                if len(target.inner_text()) > before:
                    print(f"    !! 话题 {t} 回退不干净，中止后续话题以免继续污染正文")
                    bad_topics.append(t)
                    hit_ok = True            # 已记账，别再重复 append
                    abort = True
                    break
            except Exception as e:
                print(f"    话题 {t} 第{attempt}次异常:", str(e)[:80])
        if not hit_ok:
            bad_topics.append(t)
        if abort:
            break
    print(f"  话题成功 {len(ok_topics)}: {ok_topics}")
    if bad_topics:
        print(f"  话题失败: {bad_topics}")
    got = target.inner_text().strip()
    print(f"  描述写入长度 {len(got)}，结尾 60 字：{got[-60:]!r}")


def fill_title(page):
    try:
        ti = page.locator("input[placeholder*='作品标题']").first
        if ti.count():
            ti.click()
            ti.fill("")
            ti.type(TITLE, delay=10)
            print("  作品标题 OK:", ti.input_value())
        else:
            print("  未找到作品标题输入框")
    except Exception as e:
        print("  作品标题失败:", str(e)[:120])


def set_cover(page):
    """打开封面弹窗 -> 上传竖封面 -> 点完成。"""
    if not os.path.exists(COVER_V):
        print("  跳过封面（竖版封面不存在）")
        return
    opened = False
    for txt in ("选择封面", "设置封面", "编辑封面", "更换封面"):
        try:
            loc = page.locator(f"text={txt}").first
            if loc.count() and loc.is_visible():
                loc.click(timeout=5000)
                print(f"  点了「{txt}」")
                time.sleep(3)
                dump(page, "cover_dialog")
                opened = True
                break
        except Exception:
            continue
    if not opened:
        print("  未找到封面入口")
        return
    # 「上传封面」那个 div 被别的层压住，click 会超时；
    # 也不能盲取第一个 hidden input（弹窗里还有「生成参考图」等好几个）。
    # 从「上传封面」这个叶子节点往上找，谁的下一个兄弟里有 file input，就是它。
    idx = page.evaluate("""() => {
      const lab=[...document.querySelectorAll('*')].find(e=>e.children.length===0 &&
                (e.innerText||'').trim()==='上传封面');
      if(!lab) return -1;
      const all=[...document.querySelectorAll('input[type=file]')];
      let node=lab;
      for(let k=0;k<5 && node;k++){
        const sib=node.nextElementSibling;
        if(sib){
          const inp=sib.querySelector('input[type=file]');
          if(inp) return all.indexOf(inp);
        }
        node=node.parentElement;
      }
      return -1;
    }""")
    print("  竖封面上传 input 序号:", idx)
    done = False
    if idx is not None and idx >= 0:
        try:
            page.locator("input[type=file]").nth(idx).set_input_files(COVER_V)
            print(f"  竖封面已提交（第 {idx} 个 input）")
            done = True
        except Exception as e:
            print("  指定 input 失败:", str(e)[:120])
    if not done:
        try:
            with page.expect_file_chooser(timeout=15000) as fc:
                page.locator("text=上传封面").first.click(force=True)
            fc.value.set_files(COVER_V)
            print("  竖封面已提交（file chooser）")
            done = True
        except Exception as e:
            print("  上传封面失败:", str(e)[:160])
            return
    time.sleep(8)
    dump(page, "cover_uploaded")
    cov = page.evaluate("""() => [...document.querySelectorAll('img')]
        .filter(i=>/blob:|data:image/.test(i.src) && i.offsetWidth>60)
        .map(i=>({w:i.offsetWidth,h:i.offsetHeight,src:i.src.slice(0,40)}))""")
    print("  弹窗内图片元素:", cov[:6])
    # 点「完成」
    for sel in ("button:has-text('完成')", ".semi-button-primary:has-text('完成')"):
        try:
            b = page.locator(sel).last
            if b.count() and b.is_visible():
                b.click(timeout=6000)
                print("  封面弹窗点了「完成」")
                time.sleep(4)
                break
        except Exception:
            continue
    # 抖音会追一个「设置横封面获更多流量」的推销弹窗 —— 选「暂不设置」
    time.sleep(2)
    for txt in ("暂不设置", "暂不"):
        try:
            b = page.locator(f"button:has-text('{txt}')").last
            if b.count() and b.is_visible():
                b.click(timeout=4000)
                print(f"  横封面推销弹窗点了「{txt}」")
                time.sleep(3)
                break
        except Exception:
            continue
    dump(page, "cover_done")


def check_declaration(page):
    """把「自主声明」可选项列出来（不代用户选）。"""
    try:
        cur = page.evaluate("""() => {
          const out=[];
          document.querySelectorAll('*').forEach(el=>{
            const t=(el.innerText||'').trim();
            if (t && t.length<40 && /请选择自主声明|自主声明/.test(t) && (el.offsetWidth||el.offsetHeight))
              out.push(t);
          });
          return [...new Set(out)];
        }""")
        print("  自主声明区域文本:", cur[:5])
        for txt in ("请选择自主声明", "自主声明"):
            loc = page.locator(f"text={txt}").first
            if loc.count():
                try:
                    loc.scroll_into_view_if_needed(timeout=4000)
                    time.sleep(0.8)
                    loc.click(timeout=4000)
                except Exception:
                    loc.click(force=True, timeout=4000)
                time.sleep(2)
                opts = page.evaluate("""() => {
                  const out=[];
                  document.querySelectorAll('[role=option],li,div').forEach(el=>{
                    const t=(el.innerText||'').trim();
                    if (!t || t.length>20) return;
                    if (!(el.offsetWidth||el.offsetHeight)) return;
                    const r=el.getAttribute('role')||'';
                    const c=(el.className||'').toString();
                    if (r==='option' || /option|item/i.test(c)) out.push(t);
                  });
                  return [...new Set(out)].slice(0,20);
                }""")
                print("  自主声明选项:", opts)
                page.keyboard.press("Escape")
                time.sleep(1)
                break
    except Exception as e:
        print("  自主声明探测失败:", str(e)[:120])


def publish_state(page):
    st = page.evaluate("""() => {
      const btns=[...document.querySelectorAll('button')].filter(b=>b.offsetWidth);
      const find=(kw)=>btns.filter(b=>((b.innerText||'').trim())===kw).map(b=>({t:(b.innerText||'').trim(),
        cls:(b.className||'').toString().slice(0,70), dis:b.disabled||/disabled/.test((b.className||'').toString())}));
      return {publish: find('发布'), draft: find('存草稿').concat(find('保存草稿')),
              all:[...new Set(btns.map(b=>(b.innerText||'').trim()).filter(x=>x&&x.length<8))]};
    }""")
    print("  按钮:", st)
    return st


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "form"
    with sync_playwright() as p:
        ctx = open_ctx(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if phase == "login":
            page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            dump(page, "login")
            print("→ 请用抖音App扫码登录（最多 10 分钟）")
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
                page.goto(UPLOAD, wait_until="domcontentloaded", timeout=60000)
                ok = True
                break
            except Exception as e:
                print(f"  打开投稿页第 {attempt} 次失败: {str(e)[:90]}")
                time.sleep(6)
        if not ok:
            print("  投稿页打不开，退出"); ctx.close(); sys.exit(4)
        time.sleep(8)
        dismiss(page)
        upload_video(page)
        dump(page, "01_uploaded")
        probe(page, "01_uploaded")

        if phase == "form":
            print("→ 仅上传 + 结构落盘，未改字段")
            print("READY_FOR_REVIEW")
            _wait_forever(page, ctx)
            return

        fill_title(page)
        fill_desc(page)
        set_cover(page)
        dismiss(page)
        time.sleep(2)
        page.evaluate("window.scrollTo(0,0)"); time.sleep(1.5)
        dump(page, "02_filled_top")
        page.evaluate("window.scrollTo(0,document.body.scrollHeight)"); time.sleep(1.5)
        dump(page, "03_filled_bottom")
        check_declaration(page)
        publish_state(page)
        print("=" * 60)
        print("READY_FOR_REVIEW —— 已停在「发布」前，未点击发布")
        print("=" * 60)
        _wait_forever(page, ctx)


def _wait_forever(page, ctx):
    """停在投稿页等用户审查。只有跳到别的页面（说明用户点了发布）才退出。"""
    KEEP = ("content/upload", "content/publish", "content/post/video")
    end = time.time() + KEEP_OPEN
    while time.time() < end:
        time.sleep(5)
        try:
            if not any(k in page.url for k in KEEP):
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
