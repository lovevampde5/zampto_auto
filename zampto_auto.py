import os, re, logging, random, json, time
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

USERNAME       = os.environ["ZAMPTO_USERNAME"]
PASSWORD       = os.environ["ZAMPTO_PASSWORD"]
SERVER_ID      = os.environ.get("ZAMPTO_SERVER_ID", "")
WXPUSHER_TOKEN = os.environ.get("WXPUSHER_TOKEN", "")
WXPUSHER_UID   = os.environ.get("WXPUSHER_UID", "")
SKIP_RENEW     = os.environ.get("SKIP_RENEW", "false").lower() == "true"
TG_BOT_TOKEN   = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID     = os.environ.get("TG_CHAT_ID", "")

BASE_URL = "https://dash.zampto.net"

# 续期成功后应增加的最小分钟数（24h = 1440m，保守取1200m）
RENEW_MIN_INCREASE_MINUTES = 1200

SCREENSHOT_DIR = Path("./screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)


# ───────────────────────── 推送 ─────────────────────────

def wxpush(content: str):
    if not WXPUSHER_TOKEN or not WXPUSHER_UID:
        return
    import urllib.request
    payload = json.dumps({
        "appToken": WXPUSHER_TOKEN, "content": content,
        "contentType": 1, "uids": [WXPUSHER_UID],
    }).encode()
    try:
        req = urllib.request.Request(
            "https://wxpusher.zjiecode.com/api/send/message",
            data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10): pass
    except Exception as e:
        log.warning(f"WxPusher 异常: {e}")

def tgpush(content: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    import urllib.request
    payload = json.dumps({
        "chat_id": TG_CHAT_ID, "text": content, "parse_mode": "Markdown"
    }).encode("utf-8")
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10): pass
    except Exception as e:
        log.warning(f"Telegram 异常: {e}")


# ───────────────────────── 工具 ─────────────────────────

def take_screenshot(page, name):
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = str(SCREENSHOT_DIR / f"{ts}_{name}.png")
        page.screenshot(path=path, full_page=False)
        log.info(f"📸 截图: {path}")
    except Exception as e:
        log.warning(f"截图失败: {e}")

def get_text(page) -> str:
    try: return page.inner_text("body") or ""
    except: return ""

def parse_expiry_minutes(expiry_str: str) -> float:
    """解析到期剩余时间字符串，返回总分钟数（浮点），-1 表示解析失败"""
    if not expiry_str:
        return -1
    total = 0.0
    m = re.search(r'(\d+)\s*day', expiry_str, re.I)
    if m: total += int(m.group(1)) * 1440
    m = re.search(r'(\d+)\s*h', expiry_str, re.I)
    if m: total += int(m.group(1)) * 60
    m = re.search(r'(\d+)\s*m(?:in)?(?!\s*s)', expiry_str, re.I)
    if m: total += int(m.group(1))
    m = re.search(r'(\d+)\s*s(?:ec)?', expiry_str, re.I)
    if m: total += int(m.group(1)) / 60.0
    return total if total > 0 else -1

def wait_for_url_contains(page, keyword, timeout=15) -> bool:
    try:
        page.wait_for_url(f"**{keyword}**", timeout=timeout * 1000)
        return True
    except:
        return keyword in page.url

def dismiss_ads(page):
    """只清理广告/遮罩，不碰弹窗内的功能按钮"""
    try:
        page.evaluate("""() => {
            document.querySelectorAll('iframe').forEach(function(f) {
                if ((f.id && (f.id.includes('google_vignette') || f.id.includes('aswift'))) ||
                    (f.name && f.name.includes('google_vignette'))) {
                    f.style.setProperty('display','none','important');
                    if (f.parentElement) f.parentElement.style.setProperty('display','none','important');
                }
            });
            document.querySelectorAll('ins.adsbygoogle').forEach(function(ins){
                ins.style.setProperty('display','none','important');
            });
        }""")
    except: pass


# ───────────────── CF Turnstile 验证（彻底重写）─────────────────

def wait_cf_turnstile(page, timeout=90) -> bool:
    """
    等待并处理 Cloudflare Turnstile 验证。
    策略：
      1. 先等 iframe 出现（最多15秒）
      2. 若出现，持续点击复选框直到 iframe 消失或 token 写入
      3. 每次点击后截图便于调试
    返回 True 表示验证通过或无需验证。
    """
    log.info("🛡️ 检查 Cloudflare Turnstile 验证...")

    # 先等一下让弹窗完全加载
    time.sleep(2)

    cf_selector = 'iframe[src*="challenges.cloudflare.com"]'

    # 检查 iframe 是否存在
    try:
        page.wait_for_selector(cf_selector, timeout=15000, state="attached")
        log.info("👀 发现 CF Turnstile iframe，开始处理...")
    except Exception:
        log.info("✅ 无 CF Turnstile iframe，跳过验证")
        return True

    deadline = time.time() + timeout
    attempt = 0

    while time.time() < deadline:
        attempt += 1

        # 检查 iframe 是否还在页面上且可见
        iframe_visible = page.evaluate("""() => {
            var f = document.querySelector('iframe[src*="challenges.cloudflare.com"]');
            if (!f) return false;
            var r = f.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && f.offsetParent !== null;
        }""")

        if not iframe_visible:
            log.info("✅ CF Turnstile iframe 已消失，验证完成")
            return True

        log.info(f"🔄 CF验证第{attempt}次尝试...")

        # 方法1：通过 frame_locator 点击复选框
        try:
            cf_frame = page.frame_locator(cf_selector).first
            # 尝试多个可能的复选框选择器
            for sel in [
                'input[type="checkbox"]',
                '.ctp-checkbox-label',
                '.cb-c',
                '.mark',
                '[id*="checkbox"]',
                'label',
            ]:
                try:
                    el = cf_frame.locator(sel).first
                    if el.is_visible(timeout=1500):
                        # 模拟人类：先移到元素上，停顿，再点击
                        el.hover()
                        time.sleep(random.uniform(0.3, 0.8))
                        el.click(force=True, delay=random.randint(100, 300))
                        log.info(f"🖱️ 已点击 CF 复选框: {sel}")
                        take_screenshot(page, f"cf_clicked_{attempt}")
                        time.sleep(4)  # 给CF算力验证充分时间
                        break
                except Exception:
                    continue
        except Exception as e:
            log.debug(f"frame_locator 方式失败: {e}")

        # 方法2：通过 JS 直接操作所有 frames 内的复选框（备用）
        try:
            clicked = page.evaluate("""() => {
                var count = 0;
                for (var frame of document.querySelectorAll('iframe')) {
                    try {
                        var doc = frame.contentDocument || frame.contentWindow.document;
                        if (!doc) continue;
                        var cbs = doc.querySelectorAll('input[type="checkbox"], .ctp-checkbox-label, .cb-c, .mark');
                        cbs.forEach(function(cb) {
                            if (cb.offsetParent !== null) {
                                cb.click();
                                count++;
                            }
                        });
                    } catch(e) {}
                }
                return count;
            }""")
            if clicked:
                log.info(f"🖱️ JS备用方式点击了 {clicked} 个 CF 元素")
                time.sleep(4)
        except Exception:
            pass

        # 再次检查是否已完成
        token_found = page.evaluate("""() => {
            var inputs = document.querySelectorAll(
                'input[name="cf-turnstile-response"], input[name="g-recaptcha-response"]'
            );
            for (var inp of inputs) {
                if (inp.value && inp.value.length > 10) return true;
            }
            return false;
        }""")
        if token_found:
            log.info("✅ 检测到 CF token 已写入，验证通过")
            return True

        time.sleep(3)

    log.error(f"❌ CF Turnstile 超时（{timeout}s），截图留证")
    take_screenshot(page, "cf_timeout")
    return False


# ───────────────────────── 登录 ─────────────────────────

def login(page, max_retries=3) -> bool:
    login_url = "https://auth.zampto.net/sign-in?app_id=YOUR_APP_ID"
    for attempt in range(1, max_retries + 1):
        log.info(f"🔑 尝试登录 {attempt}/{max_retries}")
        try:
            page.goto(login_url, timeout=30000, wait_until="domcontentloaded")
        except: pass

        try:
            page.wait_for_selector(
                'input[name="identifier"], input[autocomplete="username email"]',
                timeout=15000)
            user_el = page.locator('input[name="identifier"]').first
            user_el.fill("")
            user_el.type(USERNAME, delay=random.randint(60, 130))
            page.locator('button[name="submit"], button[type="submit"]').first.click()

            page.wait_for_selector('input[name="password"]', timeout=15000)
            pass_el = page.locator('input[name="password"]').first
            pass_el.fill("")
            pass_el.type(PASSWORD, delay=random.randint(60, 130))
            page.locator('button[name="submit"], button[type="submit"]').first.click()

            if wait_for_url_contains(page, "dash.zampto.net", 20):
                log.info("✅ 登录成功")
                return True
        except Exception as e:
            log.warning(f"登录 {attempt} 失败: {e}")
            time.sleep(2)
    return False


# ───────────────────────── 获取服务器信息 ─────────────────────────

def get_server_info(page, server_id: str) -> dict:
    try:
        page.goto(f"{BASE_URL}/server?id={server_id}", timeout=30000,
                  wait_until="domcontentloaded")
    except: pass
    time.sleep(3)
    dismiss_ads(page)

    info = page.evaluate("""() => {
        var body = document.body.innerText || '';
        var em = body.match(/Expiry[^:]*:\\s*([^\\n]+)/i);
        var rm = body.match(/last renewed[^:]*:\\s*([^\\n]+)/i);
        return {
            expiry:      em ? em[1].trim() : null,
            lastRenewed: rm ? rm[1].trim() : null
        };
    }""")

    try:
        page.goto(f"{BASE_URL}/server-console?id={server_id}", timeout=30000,
                  wait_until="domcontentloaded")
    except: pass
    time.sleep(3)

    status_text = page.evaluate("""() => {
        var el = document.querySelector('.status-running,.status-stopped,.status-starting');
        if (el) return el.innerText.trim();
        var m = (document.body.innerText||'').match(
            /Running(?:\\s*\\([^)]+\\))?|Stopped|Starting|Stopping/i);
        return m ? m[0] : 'Unknown';
    }""")
    info["status"] = status_text or "Unknown"
    return info


# ───────────────────────── 续期核心（完全重写）─────────────────────────

def renew_server(page, server_id: str, expiry_before: str) -> bool:
    minutes_before = parse_expiry_minutes(expiry_before)
    log.info(f"续期前剩余：{expiry_before} ({minutes_before:.1f}m)")

    # ── 步骤1：进入服务器详情页 ──
    server_url = f"{BASE_URL}/server?id={server_id}"
    try:
        page.goto(server_url, timeout=30000, wait_until="domcontentloaded")
    except: pass
    time.sleep(3)
    dismiss_ads(page)
    take_screenshot(page, "before_renew_click")

    # ── 步骤2：点击 Renew Server 按钮 ──
    try:
        renew_btn = page.locator(
            'a:has-text("Renew Server"), button:has-text("Renew Server")'
        ).first
        renew_btn.wait_for(timeout=10000, state="visible")
        renew_btn.scroll_into_view_if_needed()
        time.sleep(0.8)
        renew_btn.click(force=True)
        log.info("👆 已点击 Renew Server，等待弹窗...")
    except Exception as e:
        log.warning(f"❌ 点击 Renew Server 失败: {e}")
        take_screenshot(page, "renew_btn_fail")
        return False

    # ── 步骤3：等待弹窗出现（关键！原代码没等弹窗）──
    # 等待模态框/对话框出现
    dialog_appeared = False
    for sel in [
        '[role="dialog"]',
        '.modal', '.dialog', '.popup',
        '[class*="modal"]', '[class*="dialog"]',
        'div:has(> button:has-text("Confirm"))',
        'div:has(> button:has-text("Renew"))',
    ]:
        try:
            page.wait_for_selector(sel, timeout=8000, state="visible")
            log.info(f"✅ 弹窗已出现: {sel}")
            dialog_appeared = True
            break
        except Exception:
            continue

    if not dialog_appeared:
        log.warning("⚠️ 未检测到弹窗，尝试截图查看当前页面状态")
        take_screenshot(page, "no_dialog_found")
        # 继续流程，可能弹窗样式不同

    take_screenshot(page, "after_renew_click")

    # ── 步骤4：处理 CF Turnstile（弹窗内或页面级）──
    cf_passed = wait_cf_turnstile(page, timeout=90)
    if not cf_passed:
        log.warning("⚠️ CF验证未确认通过，但继续尝试点击确认按钮")
        take_screenshot(page, "cf_failed")

    # ── 步骤5：点击弹窗内的确认/续期按钮（强化版）──
    confirm_clicked = False

    # 等弹窗内按钮出现
    for sel in [
        'button:has-text("Confirm")',
        'button:has-text("Renew")',
        'button:has-text("Yes")',
        'button:has-text("OK")',
        'button:has-text("确认")',
        'button:has-text("续期")',
        '[role="dialog"] button',
        '.modal button',
    ]:
        try:
            btns = page.locator(sel).all()
            for btn in btns:
                if btn.is_visible(timeout=2000):
                    txt = btn.inner_text().strip()
                    # 排除 Cancel / Close 按钮
                    if any(x in txt.lower() for x in ['cancel', 'close', '取消', '关闭']):
                        continue
                    btn.scroll_into_view_if_needed()
                    time.sleep(0.5)
                    btn.click(force=True)
                    log.info(f"🖱️ 已点击确认按钮: [{txt}]")
                    confirm_clicked = True
                    take_screenshot(page, "after_confirm_click")
                    time.sleep(2)
                    break
            if confirm_clicked:
                break
        except Exception as e:
            log.debug(f"选择器 {sel} 未命中: {e}")

    if not confirm_clicked:
        log.warning("⚠️ 未能点击到确认按钮，截图留证")
        take_screenshot(page, "no_confirm_btn")

    # ── 步骤6：等待后台处理（给足时间）──
    log.info("⏳ 等待后台处理续期请求（15秒）...")
    time.sleep(15)

    # ── 步骤7：轮询验证续期结果（严格判断：必须增加>=1200分钟）──
    log.info(f"🔍 开始验证续期结果（需增加≥{RENEW_MIN_INCREASE_MINUTES}m）...")
    info_after_str = expiry_before

    for attempt in range(1, 8):
        try:
            page.goto(
                f"{BASE_URL}/server?id={server_id}&_t={int(time.time())}",
                timeout=30000, wait_until="domcontentloaded"
            )
            time.sleep(4)
        except:
            time.sleep(10)
            continue

        info_after_str = page.evaluate("""() => {
            var m = (document.body.innerText || '').match(/Expiry[^:]*:\\s*([^\\n]+)/i);
            return m ? m[1].trim() : null;
        }""") or expiry_before

        minutes_after = parse_expiry_minutes(info_after_str)
        increase = minutes_after - minutes_before

        log.info(
            f"第{attempt}次校验 | 前: {expiry_before}({minutes_before:.0f}m) "
            f"→ 后: {info_after_str}({minutes_after:.0f}m) | 增量: {increase:.0f}m"
        )

        if minutes_after > 0 and increase >= RENEW_MIN_INCREASE_MINUTES:
            log.info(f"✅ 续期成功！时长增加了 {increase:.0f} 分钟")
            take_screenshot(page, "renew_success")
            return True

        # 若未变化，等10秒再试
        if attempt < 7:
            time.sleep(10)

    log.warning(
        f"❌ 续期失败：期望增加≥{RENEW_MIN_INCREASE_MINUTES}m，"
        f"实际: {expiry_before} → {info_after_str}"
    )
    take_screenshot(page, "renew_failed")
    return False


# ───────────────────────── 启动服务器 ─────────────────────────

def start_server(page) -> bool:
    try:
        page.goto(f"{BASE_URL}/server-console?id={SERVER_ID}", timeout=30000)
    except: pass
    time.sleep(3)
    dismiss_ads(page)

    try:
        start_btn = page.locator('button:has-text("Start")').first
        if start_btn.is_visible(timeout=5000):
            start_btn.click()
            log.info("🚀 已点击 Start 按钮")
    except: pass

    for _ in range(30):
        time.sleep(10)
        try:
            page.reload(timeout=20000)
            if "Running" in get_text(page):
                log.info("✅ 服务器已变为 Running")
                return True
        except: pass
    return False


# ───────────────────────── 主流程 ─────────────────────────

def main():
    from cloakbrowser import launch

    if not SERVER_ID:
        log.error("❌ 未配置 ZAMPTO_SERVER_ID")
        return

    PROXY_SERVER = "socks5://127.0.0.1:1080"
    browser = launch(headless=False, humanize=True, proxy=PROXY_SERVER, geoip=True)
    page = browser.new_page()

    try:
        if not login(page):
            msg = "❌ Zampto 登录失败"
            wxpush(msg); tgpush(msg)
            return

        info = get_server_info(page, SERVER_ID)
        status = info.get("status", "Unknown")
        expiry = info.get("expiry", "未知")
        log.info(f"📊 初始状态: {status} | 初始到期: {expiry}")

        renewed = False
        if not SKIP_RENEW:
            renewed = renew_server(page, SERVER_ID, expiry_before=expiry)

        info2 = get_server_info(page, SERVER_ID)
        new_expiry = info2.get("expiry") or expiry

        started = False
        if "stopped" in status.lower() or "offline" in status.lower():
            log.info("🔴 服务器离线，尝试启动...")
            started = start_server(page)
            status = "Running" if started else "Start Failed"

        lines = [
            "🖥️ **Zampto 自动续期日报**",
            f"服务器 ID: `{SERVER_ID}`",
            f"状态: {'🟢' if 'running' in status.lower() else '🔴'} {status}",
            f"Expiry: `{new_expiry}`",
        ]
        if renewed:
            lines.append("续期: ✅ 成功")
        elif not SKIP_RENEW:
            lines.append("续期: ❌ 失败（请查看截图日志）")

        msg = "\n".join(lines)
        wxpush(msg)
        tgpush(msg)

    except Exception as e:
        log.exception(e)
        wxpush(f"❌ 任务异常: {e}")
    finally:
        browser.close()


if __name__ == "__main__":
    main()
