import os, re, logging, random, json, time
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ---------- 环境变量 ----------
USERNAME  = os.environ["ZAMPTO_USERNAME"]
PASSWORD  = os.environ["ZAMPTO_PASSWORD"]
SERVER_ID = os.environ.get("ZAMPTO_SERVER_ID", "")

WXPUSHER_TOKEN = os.environ.get("WXPUSHER_TOKEN", "")
WXPUSHER_UID   = os.environ.get("WXPUSHER_UID", "")
SKIP_RENEW     = os.environ.get("SKIP_RENEW", "false").lower() == "true"

# Telegram 通知
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID   = os.environ.get("TG_CHAT_ID", "")

# 续期冷却阈值（分钟）：expiry 剩余超过此值，说明刚续期过，本次跳过
RENEW_COOLDOWN_MINUTES = int(os.environ.get("RENEW_COOLDOWN_MINUTES", "1380"))

BASE_URL    = "https://dash.zampto.net"
AUTH_URL    = "https://auth.zampto.net/sign-in"
SERVERS_URL = f"{BASE_URL}/servers"

SCREENSHOT_DIR = Path("./screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

# ---------- WxPusher ----------
def wxpush(content: str):
    if not WXPUSHER_TOKEN or not WXPUSHER_UID:
        log.warning("📨 WXPUSHER_TOKEN 或 WXPUSHER_UID 未配置，跳过推送")
        return
    import urllib.request
    payload = json.dumps({
        "appToken": WXPUSHER_TOKEN,
        "content":  content,
        "contentType": 1,
        "uids": [WXPUSHER_UID],
    }).encode()
    try:
        req = urllib.request.Request(
            "https://wxpusher.zjiecode.com/api/send/message",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("success"):
                log.info("📨 WxPusher 推送成功")
            else:
                log.warning(f"📨 WxPusher 推送失败: {result}")
    except Exception as e:
        log.warning(f"📨 WxPusher 推送异常: {e}")

# ---------- Telegram ----------
def tgpush(content: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        log.warning("🚀 TG_BOT_TOKEN 或 TG_CHAT_ID 未配置，跳过 Telegram 推送")
        return
    import urllib.request
    payload = json.dumps({
        "chat_id": TG_CHAT_ID,
        "text": content,
        "parse_mode": "Markdown"
    }).encode("utf-8")
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                log.info("🚀 Telegram 通知发送成功！")
            else:
                log.warning(f"❌ Telegram 推送返回错误: {result}")
    except Exception as e:
        log.warning(f"❌ Telegram 推送异常: {e}")

# ---------- 工具函数 ----------
def redact_sensitive_info(page):
    try:
        page.evaluate("""() => {
            var cards = document.querySelectorAll('.user-info-grid .info-card .info-content');
            cards.forEach(function(card) {
                var p = card.querySelector('p');
                if (p) p.textContent = '***';
                var pStyle = card.querySelector('p[style]');
                if (pStyle) pStyle.textContent = '***';
            });
            var addrEl = document.getElementById('addressValue');
            if (addrEl) addrEl.textContent = '***';
            document.querySelectorAll('.info-card-value').forEach(function(el) {
                if (/\.zampto\.net/.test(el.textContent)) el.textContent = '***';
            });
        }""")
    except Exception as e:
        log.warning(f"脱敏 JS 执行失败（不影响截图）: {e}")

def take_screenshot(page, name):
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = str(SCREENSHOT_DIR / f"{ts}_{name}.png")
        redact_sensitive_info(page)
        page.screenshot(path=path, full_page=False)
        log.info(f"📸 截图: {path}")
    except Exception as e:
        log.warning(f"截图失败: {e}")

def get_text(page) -> str:
    try:
        return page.inner_text("body") or ""
    except:
        return ""

def human_delay(min_s=0.5, max_s=1.2):
    time.sleep(random.uniform(min_s, max_s))

def tcp_check(host: str, port: int, timeout: int = 5) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False

def wait_for_port(host: str, port: int, max_wait: int = 120, interval: int = 10) -> bool:
    log.info(f"🔌 等待端口可连接（最多 {max_wait}s）...")
    elapsed = 0
    while elapsed < max_wait:
        if tcp_check(host, port):
            log.info(f"✅ 端口已可连接（等待了 {elapsed}s）")
            return True
        time.sleep(interval)
        elapsed += interval
        log.info(f"  [{elapsed}s] 端口还未开放，继续等待...")
    log.warning(f"⚠️ 端口等待超时（{max_wait}s）")
    return False

def wait_for_url_contains(page, keyword, timeout=15) -> bool:
    try:
        page.wait_for_url(f"**{keyword}**", timeout=timeout * 1000)
        return True
    except:
        return keyword in page.url

def parse_expiry_minutes(expiry_str: str) -> int:
    """将 expiry 字符串（如 '1 day 23h 44m'）转为分钟数"""
    if not expiry_str:
        return -1
    total = 0
    m = re.search(r'(\d+)\s*day', expiry_str)
    if m:
        total += int(m.group(1)) * 24 * 60
    m = re.search(r'(\d+)\s*h', expiry_str)
    if m:
        total += int(m.group(1)) * 60
    m = re.search(r'(\d+)\s*m', expiry_str)
    if m:
        total += int(m.group(1))
    return total if total > 0 else -1

# ---------- 弹窗清除 ----------
def dismiss_all_popups(page):
    for round_idx in range(4):
        closed_any = False

        hidden = page.evaluate("""() => {
            var count = 0;
            document.querySelectorAll('iframe').forEach(function(f) {
                if ((f.id && (f.id.includes('google_vignette') || f.id.includes('aswift'))) ||
                    (f.name && f.name.includes('google_vignette'))) {
                    f.style.setProperty('display', 'none', 'important');
                    if (f.parentElement) {
                        f.parentElement.style.setProperty('display', 'none', 'important');
                        if (f.parentElement.parentElement) {
                            f.parentElement.parentElement.style.setProperty('display', 'none', 'important');
                        }
                    }
                    count++;
                }
            });
            document.querySelectorAll('div[style*="position: fixed"], div[style*="position:fixed"]').forEach(function(ov) {
                if (!ov.offsetParent && ov.style.display === 'none') return;
                var z = parseInt(window.getComputedStyle(ov).zIndex) || 0;
                if (z >= 9000 && !ov.id.includes('renew') && !ov.id.includes('modal')) {
                    ov.style.setProperty('display', 'none', 'important');
                    count++;
                }
            });
            document.querySelectorAll('ins.adsbygoogle').forEach(function(ins) {
                ins.style.setProperty('display', 'none', 'important');
                count++;
            });
            return count;
        }""")
        if hidden and hidden > 0:
            log.info(f"  [轮{round_idx+1}] JS 隐藏 {hidden} 个广告/遮罩元素")
            closed_any = True

        closed = page.evaluate("""() => {
            var count = 0;
            var closeTexts = ['Close', 'close', 'Schließen', '×', 'X', 'CLOSE'];
            for (var t of closeTexts) {
                var btns = Array.from(document.querySelectorAll('button, a, [role="button"]'));
                for (var b of btns) {
                    if (b.innerText && b.innerText.trim() === t) {
                        var parent = b.closest('[class*="modal"],[class*="popup"],[class*="overlay"],[class*="dialog"],[class*="ad-"],[class*="vignette"]');
                        if (parent && parent.offsetParent !== null) { b.click(); count++; break; }
                    }
                }
            }
            var ariaClose = document.querySelector(
                'button[aria-label="Close"], button[aria-label="close"], ' +
                '[aria-label="Dismiss"], button[aria-label="CLOSE"]'
            );
            if (ariaClose && ariaClose.offsetParent !== null) { ariaClose.click(); count++; }
            var gdprTexts = ['Nicht einwilligen', 'Decline', 'Reject', 'Do not consent'];
            for (var gt of gdprTexts) {
                var gb = Array.from(document.querySelectorAll('button')).find(b => b.innerText.trim() === gt);
                if (gb && gb.offsetParent !== null) { gb.click(); count++; break; }
            }
            var cpClose = document.querySelector(
                '.close-button-protector, .dismiss-button, .dismiss-button-protector, ' +
                '[class*="continue-prompt"] button, [class*="close-button-protector"]'
            );
            if (cpClose && cpClose.offsetParent !== null) { cpClose.click(); count++; }
            var overlays = Array.from(document.querySelectorAll('div[style*="position: fixed"], div[style*="position:fixed"]'));
            for (var ov of overlays) {
                if (ov.offsetParent === null) continue;
                if (ov.id && (ov.id.includes('renew') || ov.id.includes('modal'))) continue;
                var closeBtn = ov.querySelector('button[class*="close"], button[aria-label*="lose"], a[class*="close"]');
                if (closeBtn && closeBtn.offsetParent !== null) { closeBtn.click(); count++; break; }
            }
            return count;
        }""")

        if closed and closed > 0:
            log.info(f"  [轮{round_idx+1}] 已点击关闭 {closed} 个弹窗")
            closed_any = True
            time.sleep(1)

        has_popup = page.evaluate("""() => {
            var selectors = [
                '[class*="modal"]:not([id*="renew"]):not([style*="display: none"])',
                '[class*="popup"]:not([style*="display: none"])',
                '[class*="vignette"]:not([style*="display: none"])',
            ];
            for (var s of selectors) {
                var el = document.querySelector(s);
                if (el && el.offsetParent !== null) return true;
            }
            var iframes = document.querySelectorAll('iframe');
            for (var f of iframes) {
                if ((f.id && f.id.includes('google_vignette')) && f.style.display !== 'none') return true;
            }
            return false;
        }""")

        if not has_popup:
            break
        if not closed_any:
            break
        time.sleep(0.8)

# ---------- 强力清除广告（续期前专用） ----------
def force_clear_ads(page):
    """
    比 dismiss_all_popups 更激进的广告清除，专用于点击 Renew Server 前后。
    修复要点：
    1. 保护 renewModal 及其所有子元素（含 Turnstile iframe）不被隐藏
    2. iframe 过滤改用白名单逻辑，仅隐藏明确的广告 iframe
    3. z-index 阈值提高到 9999，避免误杀普通 modal
    """
    try:
        removed = page.evaluate("""() => {
            var count = 0;
            var renewModal = document.getElementById('renewModal');

            document.querySelectorAll('*').forEach(function(el) {
                if (renewModal && (el === renewModal || renewModal.contains(el) || el.contains(renewModal))) return;
                if (el.id && (el.id.includes('renew') || el.id.toLowerCase().includes('modal'))) return;
                if (el.className && typeof el.className === 'string' &&
                    (el.className.includes('renew') || el.className.toLowerCase().includes('modal'))) return;
                var style = window.getComputedStyle(el);
                var z = parseInt(style.zIndex) || 0;
                var pos = style.position;
                if ((pos === 'fixed' || pos === 'absolute') && z >= 9999) {
                    if (el.innerText && (el.innerText.includes('Renew') || el.innerText.includes('renew'))) return;
                    el.style.setProperty('display', 'none', 'important');
                    count++;
                }
            });

            document.querySelectorAll('iframe').forEach(function(f) {
                if (f.src && f.src.includes('challenges.cloudflare.com')) return;
                if (renewModal && renewModal.contains(f)) return;
                var isAd = (
                    (f.id && (f.id.includes('google_vignette') || f.id.includes('aswift') || f.id.includes('google_ads'))) ||
                    (f.name && f.name.includes('google_vignette')) ||
                    (f.src && (
                        f.src.includes('googlesyndication') ||
                        f.src.includes('doubleclick') ||
                        f.src.includes('googleadservices') ||
                        f.src.includes('adservice.google')
                    ))
                );
                if (isAd) {
                    f.style.setProperty('display', 'none', 'important');
                    count++;
                }
            });

            document.querySelectorAll('ins.adsbygoogle, [id*="aswift"], [id*="google_ads"]').forEach(function(el) {
                if (renewModal && renewModal.contains(el)) return;
                el.style.setProperty('display', 'none', 'important');
                count++;
            });
            return count;
        }""")
        if removed:
            log.info(f"  强力清除广告: 隐藏了 {removed} 个元素")
    except Exception as e:
        log.warning(f"强力清除广告失败: {e}")

# ---------- CF验证后点击确认按钮 ----------
def _click_confirm_in_modal(page):
    """
    CF Turnstile 验证完成后，modal 内通常会出现一个可点击的"Confirm/Submit/Renew"按钮。
    必须点击它才能真正提交续期请求，否则只是通过了验证但没有实际续期。
    """
    try:
        clicked = page.evaluate("""() => {
            var m = document.getElementById('renewModal');
            if (!m) return null;
            var keywords = ['confirm', 'submit', 'renew', 'ok', '确认', '续期', 'proceed'];
            var excludeKeywords = ['cancel', 'close', 'dismiss', '取消', '关闭'];
            var btns = Array.from(m.querySelectorAll('button, input[type="submit"], a[role="button"]'));
            for (var b of btns) {
                var txt = (b.innerText || b.value || b.textContent || '').trim().toLowerCase();
                if (excludeKeywords.some(k => txt.includes(k))) continue;
                if (keywords.some(k => txt.includes(k))) {
                    b.click();
                    return txt;
                }
            }
            var submitBtn = m.querySelector('button[type="submit"], input[type="submit"]');
            if (submitBtn && submitBtn.offsetParent !== null) {
                submitBtn.click();
                return 'type=submit';
            }
            var allBtns = Array.from(m.querySelectorAll('button')).filter(b => {
                var txt = (b.innerText || '').trim().toLowerCase();
                return !excludeKeywords.some(k => txt.includes(k)) && b.offsetParent !== null;
            });
            if (allBtns.length === 1) {
                allBtns[0].click();
                return 'only-btn:' + allBtns[0].innerText.trim();
            }
            return null;
        }""")
        if clicked:
            log.info(f"  ✅ 已点击续期确认按钮: [{clicked}]")
        else:
            log.info("  ℹ️ 未找到续期确认按钮（可能CF验证完成即自动提交）")
    except Exception as e:
        log.warning(f"  点击续期确认按钮失败: {e}")

# ---------- CF Turnstile 等待 ----------
def wait_cf_turnstile(page, timeout=90) -> bool:
    """
    等待 Cloudflare Turnstile 验证完成。
    修复要点：
    1. renewModal 不可见时，先等待几秒再检查（广告可能在加载）
    2. 先等 CF iframe 出现，再等其消失，避免"未出现就误判完成"
    3. 区分"被广告遮挡"和"网站拒绝弹出（冷却期）"两种情况
    4. Turnstile iframe 初始 src 为空，改用多种方式检测
    """
    log.info("等待 Cloudflare Turnstile 验证...")

    modal_wait = 10
    renew_modal_visible = False
    for i in range(modal_wait):
        renew_modal_visible = page.evaluate("""() => {
            var m = document.getElementById('renewModal');
            if (!m) return false;
            var style = window.getComputedStyle(m);
            if (style.display === 'none') return false;
            if (style.visibility === 'hidden') return false;
            if (parseFloat(style.opacity) === 0) return false;
            if (m.classList && m.classList.contains('modal') && !m.classList.contains('show') && style.display === 'none') return false;
            var rect = m.getBoundingClientRect();
            return rect.height > 0 || m.offsetParent !== null || m.querySelector('*') !== null;
        }""")
        if renew_modal_visible:
            log.info(f"  renewModal 已出现（等待了 {i}s）")
            break
        if i == 0:
            log.info(f"  等待 renewModal 出现（最多 {modal_wait}s）...")
        time.sleep(1)

    if not renew_modal_visible:
        modal_in_dom = page.evaluate("""() => {
            return !!document.getElementById('renewModal');
        }""")
        if modal_in_dom:
            log.warning("⚠️ renewModal 存在于 DOM 但不可见，可能被广告覆盖，尝试强力清除...")
            force_clear_ads(page)
            time.sleep(2)
            renew_modal_visible = page.evaluate("""() => {
                var m = document.getElementById('renewModal');
                if (!m) return false;
                var style = window.getComputedStyle(m);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                return m.offsetParent !== null || m.getBoundingClientRect().height > 0;
            }""")
            if not renew_modal_visible:
                log.warning("⚠️ 强力清除后 renewModal 仍不可见，续期弹窗可能被网站拒绝（冷却期）")
                return False
        else:
            log.warning("⚠️ renewModal 不存在于 DOM 中，续期弹窗未弹出（可能处于冷却期或按钮点击失败）")
            return False

    # 第一阶段：等待 CF Turnstile iframe 出现（最多 25 秒）
    cf_appeared = False
    wait_appear = 25
    log.info(f"  等待 CF Turnstile iframe 出现（最多 {wait_appear}s）...")
    for i in range(wait_appear):
        has_cf = page.evaluate("""() => {
            var frames = document.querySelectorAll('iframe');
            for (var f of frames) {
                if (f.src && f.src.includes('challenges.cloudflare.com')) return true;
            }
            var renewModal = document.getElementById('renewModal');
            if (renewModal) {
                var modalFrames = renewModal.querySelectorAll('iframe');
                if (modalFrames.length > 0) return true;
                var turnstileEl = renewModal.querySelector(
                    '.cf-turnstile, [data-sitekey], [data-cf-turnstile], ' +
                    '[id*="turnstile"], [class*="turnstile"]'
                );
                if (turnstileEl) return true;
            }
            var body = document.body.innerText || '';
            return body.includes('正在验证') || body.includes('Verifying') || body.includes('Turnstile');
        }""")
        if has_cf:
            cf_appeared = True
            log.info(f"  CF Turnstile iframe 已出现（等待了 {i}s），等待验证完成...")
            break
        time.sleep(1)

    if not cf_appeared:
        has_submit = page.evaluate("""() => {
            var m = document.getElementById('renewModal');
            if (!m) return false;
            var btns = Array.from(m.querySelectorAll('button, input[type="submit"]'));
            for (var b of btns) {
                var txt = (b.innerText || b.value || '').trim().toLowerCase();
                if (['confirm', 'submit', 'renew', 'ok', '确认', '续期'].some(k => txt.includes(k))) {
                    return true;
                }
            }
            return false;
        }""")
        if has_submit:
            log.info("  CF Turnstile 未出现，但弹窗内有提交按钮，尝试直接提交...")
            page.evaluate("""() => {
                var m = document.getElementById('renewModal');
                if (!m) return;
                var btns = Array.from(m.querySelectorAll('button, input[type="submit"]'));
                for (var b of btns) {
                    var txt = (b.innerText || b.value || '').trim().toLowerCase();
                    if (['confirm', 'submit', 'renew', 'ok', '确认', '续期'].some(k => txt.includes(k))) {
                        b.click();
                        return;
                    }
                }
            }""")
            time.sleep(3)
            return True
        log.warning("⚠️ CF Turnstile iframe 未在 25s 内出现且无提交按钮，续期弹窗可能加载异常")
        return False

    # 第二阶段：等待 CF iframe 消失（验证完成）
    deadline = time.time() + timeout
    while time.time() < deadline:
        still_verifying = page.evaluate("""() => {
            var frames = document.querySelectorAll('iframe');
            for (var f of frames) {
                if (f.src && f.src.includes('challenges.cloudflare.com')) return true;
            }
            var renewModal = document.getElementById('renewModal');
            if (renewModal) {
                var modalFrames = renewModal.querySelectorAll('iframe');
                if (modalFrames.length > 0) {
                    var hasCfFrame = false;
                    for (var mf of modalFrames) {
                        if (!mf.src || mf.src === '' || mf.src.includes('challenges.cloudflare.com')) {
                            hasCfFrame = true;
                            break;
                        }
                    }
                    return hasCfFrame;
                }
            }
            var body = document.body.innerText || '';
            return body.includes('正在验证') || body.includes('Verifying');
        }""")
        if not still_verifying:
            log.info("✅ CF Turnstile 验证完成")
            time.sleep(1)
            _click_confirm_in_modal(page)
            return True
        elapsed = int(time.time() - (deadline - timeout))
        if elapsed % 5 == 0:
            log.info(f"  CF 验证中... {elapsed}s")
        time.sleep(1)

    log.error(f"CF Turnstile 验证超时（{timeout}s）")
    return False

# ---------- 登录 ----------
def login(page, max_retries=3) -> bool:
    login_url = "https://auth.zampto.net/sign-in?app_id=YOUR_APP_ID"

    for attempt in range(1, max_retries + 1):
        log.info(f"登录 {attempt}/{max_retries}")
        try:
            page.goto(login_url, timeout=30000, wait_until="domcontentloaded")
        except Exception as e:
            log.warning(f"goto 异常: {e}")

        try:
            page.wait_for_selector(
                'input[name="identifier"], input[autocomplete="username email"]',
                timeout=15000
            )
        except:
            log.warning("找不到用户名输入框，重试")
            take_screenshot(page, f"login_no_input_{attempt}")
            time.sleep(2)
            continue

        try:
            user_el = page.locator('input[name="identifier"]').first
            user_el.click()
            user_el.fill("")
            user_el.type(USERNAME, delay=random.randint(60, 130))
            log.info("已填写用户名")
        except Exception as e:
            log.warning(f"填写用户名失败: {e}")
            continue

        human_delay()

        try:
            page.locator('button[name="submit"], button[type="submit"]').first.click()
            log.info("已点击登录按钮（第一步）")
        except Exception as e:
            log.warning(f"点击登录失败: {e}")
            continue

        try:
            page.wait_for_selector(
                'input[name="password"], input[autocomplete="current-password"]',
                timeout=15000
            )
            log.info("已进入密码输入页")
        except:
            log.warning("未出现密码输入框，重试")
            take_screenshot(page, f"login_no_password_{attempt}")
            continue

        try:
            pass_el = page.locator('input[name="password"]').first
            pass_el.click()
            pass_el.fill("")
            pass_el.type(PASSWORD, delay=random.randint(60, 130))
            log.info("已填写密码")
        except Exception as e:
            log.warning(f"填写密码失败: {e}")
            continue

        human_delay()

        try:
            page.locator('button[name="submit"], button[type="submit"]').first.click()
            log.info("已点击继续按钮（第二步）")
        except Exception as e:
            log.warning(f"点击继续失败: {e}")
            continue

        if wait_for_url_contains(page, "dash.zampto.net", 20):
            log.info("✅ 登录成功，已跳转到 dashboard")
            take_screenshot(page, "01_login_success")
            return True

        time.sleep(3)
        if "dash.zampto.net" in page.url or "zampto.net/server" in page.url:
            log.info("✅ 登录成功")
            take_screenshot(page, "01_login_success")
            return True

        log.warning(f"登录后未跳转，请检查账号密码")
        take_screenshot(page, f"login_fail_{attempt}")
        time.sleep(2)

    return False

# ---------- 获取服务器信息 ----------
def get_server_info(page, server_id: str) -> dict:
    server_url = f"{BASE_URL}/server?id={server_id}"
    log.info(f"访问服务器详情页")
    try:
        page.goto(server_url, timeout=30000, wait_until="domcontentloaded")
    except Exception as e:
        log.warning(f"访问服务器详情超时: {e}")

    time.sleep(3)
    take_screenshot(page, "02_server_page")
    dismiss_all_popups(page)
    time.sleep(1)

    info = page.evaluate("""() => {
        var body = document.body.innerText || '';
        var expiryMatch  = body.match(/Expiry[^:]*:\\s*([^\\n]+)/i);
        var renewedMatch = body.match(/last renewed[^:]*:\\s*([^\\n]+)/i);
        var addrMatch    = body.match(/node\\d+\\.zampto\\.net:\\d+/i);
        return {
            expiry:      expiryMatch  ? expiryMatch[1].trim()  : null,
            lastRenewed: renewedMatch ? renewedMatch[1].trim() : null,
            address:     addrMatch    ? addrMatch[0]           : null,
        };
    }""")

    console_url = f"{BASE_URL}/server-console?id={server_id}"
    log.info(f"访问 Console 页读取运行状态")
    try:
        page.goto(console_url, timeout=30000, wait_until="domcontentloaded")
    except Exception as e:
        log.warning(f"访问 Console 页超时: {e}")

    time.sleep(3)
    dismiss_all_popups(page)
    time.sleep(1)

    status_text = page.evaluate("""() => {
        var statusEl = document.getElementById('serverStatus');
        if (statusEl) return statusEl.innerText.trim();
        var runEl = document.querySelector('.status-running,.status-stopped,.status-starting');
        if (runEl) return runEl.innerText.trim();
        var body = document.body.innerText || '';
        var sm = body.match(/Running(?:\\s*\\([^)]+\\))?|Stopped|Starting|Stopping/i);
        return sm ? sm[0] : 'Unknown';
    }""")

    info["status"] = status_text or "Unknown"
    log.info(f"服务器信息: expiry={info.get('expiry')}, status={info.get('status')}, address=<已隐藏>")
    return info

# ---------- 启动服务器 ----------
def start_server(page) -> bool:
    console_url = f"{BASE_URL}/server-console?id={SERVER_ID}"
    MAX_START_ATTEMPTS = 3

    for attempt in range(1, MAX_START_ATTEMPTS + 1):
        log.info(f"直接导航到 Console 页（第 {attempt}/{MAX_START_ATTEMPTS} 次尝试）")
        try:
            page.goto(console_url, timeout=30000, wait_until="domcontentloaded")
        except Exception as e:
            log.warning(f"导航 Console 页超时: {e}")
        time.sleep(3)

        if attempt == 1:
            take_screenshot(page, "03_console_page")

        dismiss_all_popups(page)
        time.sleep(1)

        try:
            start_btn = page.locator('button:has-text("Start")').first
            if start_btn.is_visible(timeout=5000):
                start_btn.click()
                log.info(f"✅ 已点击 Start 按钮（第 {attempt} 次）")
                time.sleep(5)
                take_screenshot(page, f"04_after_start_attempt{attempt}")
            else:
                body_now = get_text(page)
                if "Running" in body_now:
                    log.info("Start 按钮不可见，页面已显示 Running，跳过点击")
                else:
                    log.warning(f"Start 按钮不可见且状态不是 Running，第 {attempt} 次跳过")
                    continue
        except Exception as e:
            log.warning(f"点击 Start 失败（第 {attempt} 次）: {e}")
            continue

        log.info("⏳ 等待服务器变为 Running（最多 5 分钟）...")
        wait_total = 300
        poll_interval = 10
        elapsed = 0
        final_status = "Unknown"
        offline_streak = 0

        while elapsed < wait_total:
            time.sleep(poll_interval)
            elapsed += poll_interval
            try:
                page.reload(timeout=20000, wait_until="domcontentloaded")
                time.sleep(4)
                dismiss_all_popups(page)
                time.sleep(1)
                body = get_text(page)
                if "Running" in body:
                    final_status = "Running"
                    offline_streak = 0
                    log.info(f"✅ 服务器已变为 Running（第 {attempt} 次尝试，等待了 {elapsed}s）")
                    take_screenshot(page, f"05_running_confirmed_attempt{attempt}")
                    break
                elif "Starting" in body:
                    final_status = "Starting"
                    offline_streak = 0
                    log.info(f"  [{elapsed}s] 还在 Starting，继续等待...")
                elif "Offline" in body or "Stopped" in body:
                    offline_streak += 1
                    log.info(f"  [{elapsed}s] 读到 Offline（连续第 {offline_streak} 次），{'继续等待...' if offline_streak < 3 else '确认失败'}")
                    if offline_streak >= 3:
                        final_status = "Offline"
                        take_screenshot(page, f"05_start_failed_attempt{attempt}_{elapsed}s")
                        break
                else:
                    offline_streak = 0
                    log.info(f"  [{elapsed}s] 状态未知，继续等待...")
            except Exception as e:
                log.warning(f"  [{elapsed}s] 刷新页面异常: {e}")
        else:
            log.warning(f"⚠️ 第 {attempt} 次等待超时（{wait_total}s），最后状态: {final_status}")
            take_screenshot(page, f"05_start_timeout_attempt{attempt}")

        if final_status == "Running":
            break

        if attempt < MAX_START_ATTEMPTS:
            log.info(f"⏳ 第 {attempt} 次失败，5s 后重试...")
            time.sleep(5)

    if final_status != "Running":
        return False

    addr_raw = None
    try:
        addr_raw = page.evaluate("""() => {
            var body = document.body.innerText || '';
            var m = body.match(/node\\d+\\.zampto\\.net:\\d+/i);
            return m ? m[0] : null;
        }""")
    except Exception:
        pass

    if addr_raw:
        parts = addr_raw.rsplit(":", 1)
        if len(parts) == 2:
            host, port_str = parts[0], parts[1]
            try:
                port = int(port_str)
                port_ok = wait_for_port(host, port, max_wait=120, interval=10)
                if port_ok:
                    log.info(f"✅ TCP 端口验证通过，服务器真正可连接")
                    take_screenshot(page, "06_port_verified")
                    return True
                else:
                    log.warning(f"⚠️ 端口不可达，尝试 Restart 后再等一轮...")
                    take_screenshot(page, "06_port_unreachable_before_restart")

                    restarted = False
                    try:
                        restart_btn = page.locator('button:has-text("Restart")').first
                        if restart_btn.is_visible(timeout=5000):
                            restart_btn.click()
                            log.info("🔄 已点击 Restart 按钮")
                            time.sleep(5)
                            take_screenshot(page, "07_after_restart")
                            restarted = True
                        else:
                            log.warning("Restart 按钮不可见，跳过")
                    except Exception as e:
                        log.warning(f"点击 Restart 失败: {e}")

                    if not restarted:
                        return False

                    log.info("⏳ Restart 后等待面板变为 Running（最多 5 分钟）...")
                    elapsed2 = 0
                    running_again = False
                    while elapsed2 < 300:
                        time.sleep(10)
                        elapsed2 += 10
                        try:
                            page.reload(timeout=20000, wait_until="domcontentloaded")
                            time.sleep(3)
                            dismiss_all_popups(page)
                            time.sleep(1)
                            body2 = get_text(page)
                            if "Running" in body2:
                                log.info(f"✅ Restart 后面板已变为 Running（等待了 {elapsed2}s）")
                                take_screenshot(page, f"08_restart_running")
                                running_again = True
                                break
                            elif "Starting" in body2:
                                log.info(f"  [{elapsed2}s] 还在 Starting，继续等待...")
                            elif "Offline" in body2 or "Stopped" in body2:
                                log.warning(f"  [{elapsed2}s] Restart 后回到 Offline，放弃")
                                break
                        except Exception as e:
                            log.warning(f"  [{elapsed2}s] 刷新异常: {e}")

                    if not running_again:
                        log.warning("⚠️ Restart 后未能恢复 Running，放弃")
                        take_screenshot(page, "08_restart_failed")
                        return False

                    log.info(f"🔌 Restart 后再次验证端口...")
                    port_ok2 = wait_for_port(host, port, max_wait=120, interval=10)
                    if port_ok2:
                        log.info(f"✅ Restart 后端口验证通过")
                        take_screenshot(page, "09_port_verified_after_restart")
                        return True
                    else:
                        log.warning(f"⚠️ Restart 后端口仍不可达，请手动处理")
                        take_screenshot(page, "09_port_still_unreachable")
                        return False
            except ValueError:
                pass
    else:
        log.warning("⚠️ 未能从页面读取服务器地址，跳过端口验证，以面板状态为准")

    return True

# ---------- 续期 ----------
def renew_server(page, server_id: str, expiry_before: str) -> bool:
    """
    核心修复：
    1. 续期前检测冷却期（expiry 剩余 > RENEW_COOLDOWN_MINUTES 则跳过）
    2. 点击 Renew Server 前后用强力清除广告，确保续期弹窗能弹出
    3. CF 验证完成后主动点击确认按钮
    4. CF 验证失败时自动重试一次
    5. 续期成功判断：时间必须真正增加至少30分钟
    """
    minutes_before = parse_expiry_minutes(expiry_before)
    if minutes_before > RENEW_COOLDOWN_MINUTES:
        log.info(
            f"⏭️ 当前 expiry={expiry_before}（{minutes_before} 分钟），"
            f"超过冷却阈值 {RENEW_COOLDOWN_MINUTES} 分钟，"
            f"说明最近已续期，本次跳过续期（视为成功）"
        )
        return True

    server_url = f"{BASE_URL}/server?id={server_id}"
    log.info(f"准备续期，访问服务器详情页")
    try:
        page.goto(server_url, timeout=30000, wait_until="domcontentloaded")
    except Exception as e:
        log.warning(f"访问续期页超时: {e}")

    time.sleep(3)
    log.info("关闭页面上所有弹窗...")
    dismiss_all_popups(page)
    time.sleep(1)

    def _click_renew_btn() -> bool:
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1)

            clicked = page.evaluate("""() => {
                var els = Array.from(document.querySelectorAll('a, button'));
                for (var el of els) {
                    var txt = (el.innerText || el.textContent || '').trim();
                    if (txt === 'Renew Server' || txt.includes('Renew Server')) {
                        el.scrollIntoView({block: 'center'});
                        if (el.onclick) { el.onclick(new MouseEvent('click')); return 'onclick'; }
                        el.click();
                        return 'click';
                    }
                }
                return null;
            }""")

            if not clicked:
                log.warning("JS 未找到 Renew Server 按钮，尝试 Playwright locator...")
                renew_btn = page.locator('a:has-text("Renew Server"), button:has-text("Renew Server")').first
                renew_btn.scroll_into_view_if_needed()
                time.sleep(0.5)
                renew_btn.click(force=True)
                log.info("已点击 Renew Server 按钮（locator force click）")
            else:
                log.info(f"已点击 Renew Server 按钮（JS {clicked}）")
            return True
        except Exception as e:
            log.warning(f"点击 Renew Server 失败: {e}")
            return False

    # 第一次点击
    if not _click_renew_btn():
        return False
    take_screenshot(page, "05_renew_clicked")

    time.sleep(2)
    log.info("强力清除广告，准备检测续期弹窗...")
    force_clear_ads(page)
    time.sleep(1)
    dismiss_all_popups(page)
    time.sleep(1)
    take_screenshot(page, "06_renew_modal")

    # 第一次 CF 验证
    if not wait_cf_turnstile(page, timeout=90):
        log.warning("CF 验证失败，5s 后重新点击 Renew Server 再试一次...")
        time.sleep(5)
        force_clear_ads(page)
        time.sleep(1)
        dismiss_all_popups(page)
        time.sleep(1)

        if not _click_renew_btn():
            log.warning("第二次点击 Renew Server 也失败，放弃续期")
            take_screenshot(page, "06_cf_timeout")
            return False

        time.sleep(2)
        force_clear_ads(page)
        time.sleep(1)
        dismiss_all_popups(page)
        time.sleep(1)
        take_screenshot(page, "06_renew_modal_retry")

        if not wait_cf_turnstile(page, timeout=90):
            log.warning("重试后 CF 验证仍失败，续期放弃")
            take_screenshot(page, "06_cf_timeout")
            return False

    # CF 验证通过，等待服务器处理
    log.info("CF 验证通过，等待续期生效...")
    time.sleep(15)
    take_screenshot(page, "07_after_renew")

    try:
        page.reload(timeout=20000, wait_until="domcontentloaded")
        time.sleep(5)
        dismiss_all_popups(page)
        time.sleep(1)
    except Exception as e:
        log.warning(f"续期后刷新页面失败: {e}，改用 goto 重新导航...")
        try:
            page.goto(f"{BASE_URL}/server?id={server_id}", timeout=30000, wait_until="domcontentloaded")
            time.sleep(5)
            dismiss_all_popups(page)
            time.sleep(1)
        except Exception as e2:
            log.warning(f"续期后重新导航也失败: {e2}")

    info_after = page.evaluate("""() => {
        var body = document.body.innerText || '';
        var m = body.match(/Expiry[^:]*:\\s*([^\\n]+)/i);
        return m ? m[1].trim() : null;
    }""")
    log.info(f"续期后 expiry（页面直读）: {info_after}")

    minutes_after = parse_expiry_minutes(info_after)
    log.info(f"续期前 expiry 分钟数: {minutes_before}, 续期后: {minutes_after}")

    # 判断续期是否成功：时间必须真正增加至少30分钟
    TIME_DRIFT = 5       # 允许最多5分钟自然流逝
    MIN_INCREASE = 30    # 至少增加30分钟才算续期成功

    if minutes_after > 0:
        net_increase = minutes_after - (minutes_before - TIME_DRIFT)
        if net_increase >= MIN_INCREASE:
            diff = minutes_after - minutes_before
            log.info(f"✅ 续期成功！expiry: {expiry_before} → {info_after}（净增加约 {diff} 分钟）")
            return True
        else:
            log.warning(
                f"⚠️ 续期后时间未真正增加（{expiry_before} → {info_after}，"
                f"净增加={minutes_after - minutes_before} 分钟，需≥{MIN_INCREASE} 分钟）"
                f"，续期未生效！可能原因：①网站限制续期频率 ②确认按钮未成功点击"
            )
            return False

    log.warning(f"⚠️ 无法读取续期后 expiry，续期结果未知")
    return False

# ---------- 主流程 ----------
def main():
    from cloakbrowser import launch

    if not SERVER_ID:
        log.error("❌ 未配置 ZAMPTO_SERVER_ID 环境变量")
        wxpush("❌ 未配置 ZAMPTO_SERVER_ID，任务中止")
        tgpush("❌ 未配置 `ZAMPTO_SERVER_ID`，任务中止")
        return

    PROXY_SERVER = "socks5://127.0.0.1:1080"

    log.info("启动 CloakBrowser...")
    browser = launch(
        headless=False,
        humanize=True,
        proxy=PROXY_SERVER,
        geoip=True,
    )
    page = browser.new_page()

    try:
        if not login(page):
            msg_fail = "❌ Zampto 登录失败，请检查账号密码"
            wxpush(msg_fail)
            tgpush(msg_fail)
            return

        dismiss_all_popups(page)

        info      = get_server_info(page, SERVER_ID)
        status    = info.get("status", "Unknown")
        expiry    = info.get("expiry", "未知")
        last_renew= info.get("lastRenewed", "未知")

        log.info(f"服务器状态: {status} | 到期: {expiry}")

        if SKIP_RENEW:
            log.info("⏭️ SKIP_RENEW=true，跳过续期步骤")
            renewed = False
            renew_skipped_cooldown = False
        else:
            minutes_now = parse_expiry_minutes(expiry)
            renew_skipped_cooldown = (minutes_now > RENEW_COOLDOWN_MINUTES)
            renewed = renew_server(page, SERVER_ID, expiry_before=expiry)

        new_expiry = expiry
        if renewed:
            time.sleep(3)
            info2      = get_server_info(page, SERVER_ID)
            new_expiry = info2.get("expiry") or expiry
            last_renew = info2.get("lastRenewed") or last_renew
            log.info(f"续期后到期信息: {new_expiry}")

        started = False
        if "stopped" in status.lower() or "offline" in status.lower():
            log.info("🔴 服务器已停止，尝试启动...")
            started = start_server(page)
            if started:
                status = "Running"
                log.info("✅ 服务器已确认 Running")
            else:
                status = "Start Failed / Timeout"
                log.warning("⚠️ 服务器启动失败或超时，未能确认 Running")

        lines = ["🚨 **Zampto 紧急启动报告**" if SKIP_RENEW else "🖥️ **Zampto 服务器日报**"]
        lines.append(f"服务器 ID: `{SERVER_ID}`")
        lines.append("")
        status_icon = "🟢" if "running" in status.lower() else ("🟡" if "starting" in status.lower() else "🔴")
        lines.append(f"状态: {status_icon} {status}")
        if started:
            lines.append("  → 已启动，面板 Running + 端口可连接 ✅")
        elif "stopped" in status.lower() or "offline" in status.lower() or "failed" in status.lower():
            lines.append("  ⚠️ 启动失败（含自动 Restart 重试），端口仍不可达，请手动处理")
        lines.append("")
        lines.append(f"Expiry (Next Renewal): `{new_expiry}`")
        if last_renew:
            lines.append(f"Last Renewed: {last_renew}")
        if SKIP_RENEW:
            lines.append("  （续期已跳过，仅紧急启动）")
        elif renew_skipped_cooldown:
            lines.append(f"  ℹ️ expiry 剩余 > {RENEW_COOLDOWN_MINUTES} 分钟，处于续期冷却期，本次跳过续期 ✅")
        elif renewed:
            lines.append("  → 已自动续期成功 ✅")
        else:
            lines.append("  ⚠️ 正常续期未触发或失败，请手动检查")

        msg = "\n".join(lines)
        log.info(f"推送内容:\n{msg}")
        wxpush(msg)
        tgpush(msg)

    except Exception as e:
        log.exception(e)
        take_screenshot(page, "99_error")
        err_msg = f"❌ Zampto 任务异常: {e}"
        wxpush(err_msg)
        tgpush(err_msg)
    finally:
        time.sleep(3)
        browser.close()
        log.info("任务结束")

if __name__ == "__main__":
    main()
