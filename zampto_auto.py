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

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID   = os.environ.get("TG_CHAT_ID", "")

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
                if (/\\.zampto\\.net/.test(el.textContent)) el.textContent = '***';
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

def read_expiry_from_page(page) -> str:
    try:
        result = page.evaluate("""() => {
            var body = document.body.innerText || '';
            var m = body.match(/Expiry[^:\\n]*:\\s*([^\\n]+)/i);
            if (m && m[1].trim()) return m[1].trim();
            m = body.match(/Next Renewal[^:\\n]*:\\s*([^\\n]+)/i);
            if (m && m[1].trim()) return m[1].trim();
            m = body.match(/(\\d+\\s*day[s]?\\s*)?\\d+\\s*h\\s*\\d+\\s*m/i);
            if (m) return m[0].trim();
            return null;
        }""")
        return result
    except:
        return None

# ---------- 弹窗清除（已增加 CF 白名单保护） ----------
def dismiss_all_popups(page):
    for round_idx in range(4):
        closed_any = False

        hidden = page.evaluate("""() => {
            var count = 0;
            document.querySelectorAll('iframe').forEach(function(f) {
                if (f.src && f.src.includes('challenges.cloudflare.com')) return; // 保护 CF
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
                if (ov.querySelector('iframe[src*="challenges.cloudflare.com"]') || ov.classList.contains('cf-turnstile')) return; // 保护 CF
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
                if (ov.querySelector('iframe[src*="challenges.cloudflare.com"]') || ov.classList.contains('cf-turnstile')) continue; // 保护 CF
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

        if not has_popup or not closed_any:
            break
        time.sleep(0.8)

# ---------- 强力清除广告（已增加 CF 白名单保护） ----------
def force_clear_ads(page):
    try:
        removed = page.evaluate("""() => {
            var count = 0;
            var renewModal = document.getElementById('renewModal');

            document.querySelectorAll('*').forEach(function(el) {
                if (renewModal && (el === renewModal || renewModal.contains(el) || el.contains(renewModal))) return;
                if (el.id && (el.id.includes('renew') || el.id.toLowerCase().includes('modal'))) return;
                if (el.className && typeof el.className === 'string' &&
                    (el.className.includes('renew') || el.className.toLowerCase().includes('modal'))) return;
                
                // 核心防护：如果该元素包含 Cloudflare 验证，绝对不能隐藏
                if (el.querySelector('iframe[src*="challenges.cloudflare.com"]') || el.classList.contains('cf-turnstile')) return;

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
    try:
        clicked = page.evaluate("""() => {
            var m = document.getElementById('renewModal');
            if (!m) m = document.body;
            var keywords = ['confirm', 'submit', 'renew', 'ok', '确认', '续期', 'proceed'];
            var excludeKeywords = ['cancel', 'close', 'dismiss', '取消', '关闭'];
            var btns = Array.from(m.querySelectorAll('button, input[type="submit"], a[role="button"]'));
            for (var b of btns) {
                var txt = (b.innerText || b.value || b.textContent || '').trim().toLowerCase();
                if (excludeKeywords.some(k => txt.includes(k))) continue;
                if (keywords.some(k => txt.includes(k))) {
                    if (!b.disabled) {
                        b.click();
                        return txt;
                    }
                }
            }
            var submitBtn = m.querySelector('button[type="submit"], input[type="submit"], button.btn-primary');
            if (submitBtn && submitBtn.offsetParent !== null && !submitBtn.disabled) {
                submitBtn.click();
                return 'primary/submit';
            }
            return null;
        }""")
        if clicked:
            log.info(f"  ✅ 已成功点击续期确认按钮: [{clicked}]")
        else:
            log.info("  ℹ️ 未找到可点击的续期确认按钮（可能已自动提交或未解锁）")
    except Exception as e:
        log.warning(f"  点击续期确认按钮失败: {e}")

# ---------- CF Turnstile 主动安全交互 ----------
def _try_interact_cf_iframe(page):
    """采用 Playwright 原生 Locator 模拟真实点击，杜绝因不安全的全局 JS 事件导致的机器特征风控"""
    try:
        for frame in page.frames:
            if "challenges.cloudflare.com" in (frame.url or ""):
                # 轮询 Turnstile 常见的原生复选框和定位标记
                for selector in ['input[type="checkbox"]', '#challenge-stage_cb', '.cb-i', 'span.mark']:
                    try:
                        cb = frame.locator(selector).first
                        if cb.is_visible(timeout=1000):
                            cb.click()
                            log.info(f"  ✅ 成功通过物理模拟点击了 CF Turnstile 复选框: [{selector}]")
                            return
                    except Exception:
                        pass
    except Exception as e:
        log.info(f"  CF 原生框架交互尝试异常（可能处于托管状态，不影响流转）: {e}")

# ---------- CF Turnstile 等待 ----------
def wait_cf_turnstile(page, timeout=120) -> bool:
    log.info("等待续期弹窗及 Cloudflare Turnstile 验证...")

    modal_wait = 20
    renew_modal_visible = False
    for i in range(modal_wait):
        renew_modal_visible = page.evaluate("""() => {
            var m = document.getElementById('renewModal');
            if (!m) {
                var candidates = Array.from(document.querySelectorAll('[id*="renew"],[class*="renew"]'));
                for (var c of candidates) {
                    if (c.offsetParent !== null || c.getBoundingClientRect().height > 0) return true;
                }
                return false;
            }
            var style = window.getComputedStyle(m);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            return m.offsetParent !== null || m.getBoundingClientRect().height > 0;
        }""")
        if renew_modal_visible:
            log.info(f"  renewModal 已出现（等待了 {i}s）")
            break
        time.sleep(1)

    if not renew_modal_visible:
        log.warning("⚠️ renewModal 未弹出，进行一次安全过滤后继续等待...")
        force_clear_ads(page)
        time.sleep(2)

    # 首次给予自然加载交互
    _try_interact_cf_iframe(page)
    time.sleep(2)

    log.info(f"  等待 CF 验证完成且确认按钮可用（最多 {timeout}s）...")
    deadline = time.time() + timeout
    cf_passed = False
    last_interact = time.time()

    while time.time() < deadline:
        # 每 15 秒在必要时进行一次高仿真辅助点击
        if time.time() - last_interact >= 15:
            _try_interact_cf_iframe(page)
            last_interact = time.time()

        passed = page.evaluate("""() => {
            // 条件A: CF 核心 Token 已生成，最稳健的依据
            var cfInputs = document.querySelectorAll(
                '[name="cf-turnstile-response"], input[name*="turnstile"], input[name*="cf-"]'
            );
            for (var ci of cfInputs) {
                if (ci.value && ci.value.length > 10) return 'token';
            }
            // 条件B: 确认按钮已被激活解锁
            var m = document.getElementById('renewModal') || document.body;
            var btns = Array.from(m.querySelectorAll('button, input[type="submit"]'));
            for (var b of btns) {
                var txt = (b.innerText || b.value || '').toLowerCase();
                if ((txt.includes('renew') || txt.includes('confirm') || txt.includes('submit') || txt.includes('ok')) && !b.disabled) {
                    return 'button_unlocked';
                }
            }
            // 条件C: 验证成功组件标记出现
            var widgets = document.querySelectorAll('.cf-turnstile, [data-cf-turnstile]');
            for (var w of widgets) {
                var wClass = w.className || '';
                if (wClass.includes('success') || wClass.includes('solved')) return 'widget_success';
            }
            return false;
        }""")

        if passed:
            log.info(f"  ✅ CF Turnstile 验证通过（通关条件: {passed}）")
            cf_passed = True
            break
        time.sleep(1.5)

    if not cf_passed:
        log.warning(f"CF Turnstile 验证超时（{timeout}s 内未完成），本次放弃")
        return False

    log.info("✅ CF Turnstile 验证通过 / 确认按钮已解锁")
    time.sleep(1.5)
    _click_confirm_in_modal(page)
    return True

# ---------- 续期后读取expiry（带重试） ----------
def read_expiry_after_renew(page, server_id: str, minutes_before: int) -> tuple:
    for attempt in range(1, 4):
        log.info(f"  续期后读取 expiry（第 {attempt}/3 次）...")
        try:
            page.goto(f"{BASE_URL}/server?id={server_id}", timeout=30000, wait_until="domcontentloaded")
            time.sleep(5)
            dismiss_all_popups(page)
            time.sleep(1)
        except Exception as e:
            log.warning(f"  续期后导航失败: {e}")
            time.sleep(5)
            continue

        info_after = read_expiry_from_page(page)
        log.info(f"  第 {attempt} 次读取 expiry: {info_after}")

        if info_after:
            minutes_after = parse_expiry_minutes(info_after)
            if minutes_after > 0:
                return info_after, minutes_after

        if attempt < 3:
            log.info(f"  expiry 读取失败或为0，10s 后重试...")
            time.sleep(10)

    return None, -1

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
        var expiryMatch  = body.match(/Expiry[^:\\n]*:\\s*([^\\n]+)/i);
        var renewedMatch = body.match(/last renewed[^:\\n]*:\\s*([^\\n]+)/i);
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
    log.info("清洗页面广告干扰...")
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

    MAX_CF_ATTEMPTS = 3
    cf_success = False

    for cf_attempt in range(1, MAX_CF_ATTEMPTS + 1):
        if cf_attempt == 1:
            log.info(f"🔄 第 {cf_attempt}/{MAX_CF_ATTEMPTS} 次尝试点击 Renew Server...")
            if not _click_renew_btn():
                log.warning("点击 Renew Server 按钮失败，放弃续期")
                take_screenshot(page, "05_renew_click_fail")
                return False
            take_screenshot(page, "05_renew_clicked")
        else:
            log.warning(f"CF 验证未通过，8s 后重新点击 Renew Server（第 {cf_attempt}/{MAX_CF_ATTEMPTS} 次）...")
            time.sleep(8)
            try:
                page.goto(f"{BASE_URL}/server?id={server_id}", timeout=30000, wait_until="domcontentloaded")
                time.sleep(3)
            except Exception as e:
                log.warning(f"重新导航失败: {e}")
            
            # 安全调用清理（不会隐藏CF组件）
            force_clear_ads(page)
            time.sleep(2)
            dismiss_all_popups(page)
            time.sleep(1)

            if not _click_renew_btn():
                log.warning(f"第 {cf_attempt} 次点击 Renew Server 失败，继续下一次循环")
                take_screenshot(page, f"06_cf_click_fail_{cf_attempt}")
                continue
            take_screenshot(page, f"06_renew_modal_retry_{cf_attempt}")

        time.sleep(2)
        log.info("安全过滤普通遮罩层，准备加载验证弹窗...")
        force_clear_ads(page)
        time.sleep(1)
        dismiss_all_popups(page)
        time.sleep(1)
        take_screenshot(page, f"06_renew_modal_attempt{cf_attempt}")

        if wait_cf_turnstile(page, timeout=120):
            cf_success = True
            break
        else:
            take_screenshot(page, f"06_cf_timeout_attempt{cf_attempt}")
            log.warning(f"第 {cf_attempt}/{MAX_CF_ATTEMPTS} 次 CF 验证失败")

    if not cf_success:
        log.warning(f"全部 {MAX_CF_ATTEMPTS} 次 CF 验证均失败，续期放弃")
        take_screenshot(page, "06_cf_all_failed")
        return False

    log.info("等待续期生效（30s）...")
    time.sleep(30)
    take_screenshot(page, "07_after_renew")

    info_after, minutes_after = read_expiry_after_renew(page, server_id, minutes_before)
    log.info(f"续期前 expiry: {expiry_before}（{minutes_before}分钟），续期后: {info_after}（{minutes_after}分钟）")

    if minutes_after > 0:
        if minutes_after > minutes_before:
            diff = minutes_after - minutes_before
            log.info(f"✅ 续期成功！expiry: {expiry_before} → {info_after}（时间增加了 {diff} 分钟）")
            return True
        else:
            log.warning(
                f"⚠️ 续期后时间未增加（{expiry_before} → {info_after}），"
                f"续期未生效！可能原因：①CF验证未真正通过 ②网站限制频率"
            )
            return False

    log.warning(f"⚠️ 3次尝试均无法读取续期后 expiry，续期结果未知")
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

        info       = get_server_info(page, SERVER_ID)
        status     = info.get("status", "Unknown")
        expiry     = info.get("expiry", "未知")
        last_renew = info.get("lastRenewed", "未知")

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
