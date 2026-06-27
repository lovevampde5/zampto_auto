import os, re, logging, random, json, time, requests
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

TG_BOT_TOKEN   = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID     = os.environ.get("TG_CHAT_ID", "")

BASE_URL    = "https://dash.zampto.net"
SCREENSHOT_DIR = Path("./screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

# ---------- 推送函数（不变） ----------
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
            url,
            data=payload,
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

# ---------- 工具函数（不变） ----------
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
                if (/\\.zampto\\.net/.test(el.textContent)) {
                    el.textContent = '***';
                }
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

# ---------- ★★★ 改进的 Cloudflare Turnstile 处理（支持 blob URL） ----------
def handle_cf_turnstile(page, timeout=60) -> bool:
    log.info("⏳ 处理 Cloudflare Turnstile 验证（增强版）...")
    # 使用 JavaScript 检测任何包含 turnstile 或 challenges.cloudflare.com 的 iframe（包括 blob:）
    cf_detected = page.evaluate("""() => {
        var iframes = document.querySelectorAll('iframe');
        for (var f of iframes) {
            var src = f.src || '';
            if (src.includes('challenges.cloudflare.com') || src.includes('turnstile')) {
                return true;
            }
        }
        // 也可能存在 div#turnstile-wrapper 等
        if (document.querySelector('#turnstile-wrapper, .turnstile-container, [data-sitekey]')) {
            return true;
        }
        return false;
    }""")
    if not cf_detected:
        log.info("✅ 未检测到 Cloudflare Turnstile，跳过")
        return True

    log.info("🔄 检测到 Turnstile，尝试处理...")
    # 尝试点击复选框（通用方法）
    for attempt in range(3):
        # 尝试通过 frame_locator 定位所有 iframe
        try:
            frames = page.frames
            for f in frames:
                if 'challenges.cloudflare.com' in f.url or 'turnstile' in f.url:
                    # 在 frame 中查找复选框
                    checkbox = f.locator('[role="checkbox"], .challenge, .checkbox, input[type="checkbox"]').first
                    if checkbox.count():
                        checkbox.click(timeout=3000)
                        log.info(f"  点击了 frame 中的复选框 (尝试 {attempt+1})")
                        time.sleep(2)
                        break
        except:
            pass
        # 如果上述不行，尝试点击页面中可能存在的 iframe 本身
        try:
            iframe = page.locator('iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"]').first
            if iframe.count():
                iframe.click(force=True)
                log.info(f"  点击 iframe 本身 (尝试 {attempt+1})")
                time.sleep(2)
        except:
            pass
        # 等待 iframe 消失（验证通过）
        deadline = time.time() + timeout
        while time.time() < deadline:
            still_exists = page.evaluate("""() => {
                var iframes = document.querySelectorAll('iframe');
                for (var f of iframes) {
                    var src = f.src || '';
                    if (src.includes('challenges.cloudflare.com') || src.includes('turnstile')) {
                        return true;
                    }
                }
                return false;
            }""")
            if not still_exists:
                log.info(f"✅ Turnstile 验证通过 (尝试 {attempt+1})")
                return True
            time.sleep(1)
        log.warning(f"  尝试 {attempt+1} 后 Turnstile 仍未消失，重试...")

    # 最终尝试：刷新页面（有时验证会重置）
    log.warning("⚠️ Turnstile 未通过，刷新页面重试...")
    page.reload()
    time.sleep(5)
    # 递归调用一次，但限制避免死循环
    return handle_cf_turnstile(page, timeout=30)

# ---------- 处理 Google reCAPTCHA（不变） ----------
def handle_google_recaptcha(page):
    try:
        recaptcha_iframe = page.locator('iframe[src*="recaptcha/api2/aframe"]')
        if recaptcha_iframe.count() == 0:
            return
        log.info("⚠️ 检测到 Google reCAPTCHA，尝试点击复选框...")
        try:
            frame = page.frame_locator('iframe[src*="recaptcha/api2/aframe"]')
            checkbox = frame.locator('.recaptcha-checkbox-border, .recaptcha-checkbox-checkmark, #recaptcha-anchor')
            if checkbox.count():
                checkbox.click(timeout=5000)
                log.info("  已点击 reCAPTCHA 复选框")
                time.sleep(5)
                return
        except Exception as e:
            log.warning(f"  reCAPTCHA 点击失败: {e}")
        try:
            recaptcha_iframe.click(force=True)
            log.info("  点击了 reCAPTCHA iframe（force）")
            time.sleep(5)
        except:
            pass
        try:
            page.evaluate("""() => {
                var iframe = document.querySelector('iframe[src*="recaptcha/api2/aframe"]');
                if (iframe) {
                    try {
                        var doc = iframe.contentDocument || iframe.contentWindow.document;
                        var checkbox = doc.querySelector('.recaptcha-checkbox-border');
                        if (checkbox) checkbox.click();
                    } catch(e) {
                        iframe.click();
                    }
                }
            }""")
            log.info("  使用 JS 尝试点击 reCAPTCHA")
            time.sleep(5)
        except:
            pass
    except Exception as e:
        log.warning(f"处理 reCAPTCHA 异常: {e}")

# ---------- 登录（不变） ----------
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

# ---------- 获取服务器信息（不变） ----------
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

# ---------- 启动服务器（不变） ----------
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

# ---------- ★★★ 终极续期：网络诊断 + 暴力尝试（改进） ----------
def renew_server(page, server_id: str, expiry_before: str) -> bool:
    """
    改进策略：
    1. 监听网络并捕获续期相关请求（含 blob 等）。
    2. 点击 Renew Server 按钮。
    3. 处理 Cloudflare Turnstile（增强版）。
    4. 模态框出现后，明确点击确认按钮（支持多种文本）。
    5. 若失败，尝试直接重放捕获的续期请求。
    6. 最终检查 expiry 变化。
    """
    server_url = f"{BASE_URL}/server?id={server_id}"
    all_requests = []
    all_responses = []
    captured_renew_reqs = []  # 用于存储疑似续期的请求

    def log_req(request):
        log.info(f"📤 REQ: {request.method} {request.url}")
        all_requests.append((request.method, request.url))
        # 如果请求包含 renew/extend/refresh，记录下来
        if any(kw in request.url.lower() for kw in ["renew", "extend", "refresh"]):
            post_data = None
            try:
                post_data = request.post_data
            except:
                pass
            captured_renew_reqs.append({
                "method": request.method,
                "url": request.url,
                "post_data": post_data,
                "headers": dict(request.headers)
            })
        if request.method == "POST":
            try:
                post_data = request.post_data
                if post_data:
                    log.info(f"    POST数据: {post_data[:200]}")
            except:
                pass

    def log_resp(response):
        log.info(f"📥 RESP: {response.status} {response.url}")
        all_responses.append((response.status, response.url))
        try:
            if "application/json" in response.headers.get("content-type", ""):
                body = response.json()
                log.info(f"    响应JSON: {json.dumps(body, ensure_ascii=False)[:200]}")
        except:
            pass

    page.on("request", log_req)
    page.on("response", log_resp)

    # 辅助函数：获取当前 expiry
    def get_current_expiry():
        try:
            # 重新加载页面
            page.goto(server_url, timeout=20000, wait_until="domcontentloaded")
            time.sleep(3)
            dismiss_all_popups(page)
            info = page.evaluate("""() => {
                var body = document.body.innerText || '';
                var m = body.match(/Expiry[^:]*:\\s*([^\\n]+)/i);
                return m ? m[1].trim() : null;
            }""")
            return info
        except:
            return None

    # 辅助函数：点击模态框确认按钮
    def click_modal_confirm():
        # 等待模态框出现
        try:
            page.wait_for_selector('#renewModal, [role="dialog"], .modal:not([style*="display: none"])', timeout=10000)
            log.info("✅ 模态框已出现")
        except:
            log.warning("未检测到模态框")
            return False
        time.sleep(1)
        # 尝试多种方式点击确认
        success = page.evaluate("""() => {
            var modal = document.getElementById('renewModal') ||
                        document.querySelector('[role="dialog"]') ||
                        document.querySelector('.modal:not([style*="display: none"])');
            var searchIn = modal || document;
            var confirmTexts = ['Confirm', 'Yes', 'OK', 'Ok', 'Submit', 'Renew', 'Renew Server', 'Extend', 'Continue', 'Proceed', '确认', '确定', '续期'];
            var btns = Array.from(searchIn.querySelectorAll('button, a, input[type="submit"], input[type="button"]'));
            for (var t of confirmTexts) {
                for (var b of btns) {
                    var txt = (b.innerText || b.textContent || b.value || '').trim();
                    if (txt === t || txt.toLowerCase() === t.toLowerCase()) {
                        if (b.offsetParent !== null && !b.disabled) {
                            b.scrollIntoView({block: 'center'});
                            b.focus();
                            b.click();
                            return 'exact:' + t;
                        }
                    }
                }
            }
            // 模糊匹配
            for (var b of btns) {
                var txt = (b.innerText || b.textContent || b.value || '').trim().toLowerCase();
                if ((txt.includes('confirm') || txt.includes('renew') || txt.includes('extend') || txt.includes('proceed') || txt.includes('确定') || txt.includes('续期'))
                    && b.offsetParent !== null && !b.disabled) {
                    b.scrollIntoView({block: 'center'});
                    b.focus();
                    b.click();
                    return 'fuzzy:' + txt;
                }
            }
            // 备用：.btn-primary 或 .btn-success
            var primary = searchIn.querySelector('button.btn-primary, button.btn-success, button[class*="primary"], button[class*="success"]');
            if (primary && primary.offsetParent !== null && !primary.disabled) {
                primary.scrollIntoView({block: 'center'});
                primary.click();
                return 'primary';
            }
            return null;
        }""")
        if success:
            log.info(f"  ✅ 已点击模态框确认按钮: {success}")
            return True
        else:
            # 回退：按 Enter
            try:
                page.keyboard.press("Enter")
                log.info("  回退：按 Enter 确认")
                return True
            except:
                return False

    # ---------- 开始续期尝试 ----------
    for attempt in range(1, 4):  # 最多尝试3次
        log.info(f"🔄 续期尝试 {attempt}/3")
        # 导航到服务器详情页
        try:
            page.goto(server_url, timeout=30000, wait_until="domcontentloaded")
        except:
            continue
        time.sleep(3)
        dismiss_all_popups(page)
        take_screenshot(page, f"renew_before_click_{attempt}")

        # 1. 点击 Renew Server 按钮
        clicked = False
        try:
            # 使用多种选择器
            btn_selectors = [
                'a:has-text("Renew Server")',
                'button:has-text("Renew Server")',
                'a:has-text("Renew")',
                'button:has-text("Renew")',
                'a:has-text("Extend")',
                'button:has-text("Extend")',
                '[role="button"]:has-text("Renew")',
                '.btn-renew',
                '.renew-btn',
                'a[href*="renew"]',
            ]
            for sel in btn_selectors:
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible():
                        btn.scroll_into_view_if_needed()
                        btn.click(force=True, timeout=5000)
                        log.info(f"✅ 点击按钮成功 (选择器: {sel})")
                        clicked = True
                        break
                except:
                    continue
            if not clicked:
                # 备用：JS 点击
                clicked = page.evaluate("""() => {
                    var keywords = ['Renew Server', 'Renew', 'Extend', 'Renouveler', 'Verlängern', 'Renovar'];
                    var els = Array.from(document.querySelectorAll('a, button, input[type="button"], input[type="submit"], [role="button"]'));
                    for (var kw of keywords) {
                        for (var el of els) {
                            var txt = (el.innerText || el.textContent || el.value || '').trim();
                            if (txt === kw || txt.toLowerCase() === kw.toLowerCase()) {
                                if (el.offsetParent !== null && !el.disabled) {
                                    el.scrollIntoView({block: 'center'});
                                    el.focus();
                                    el.click();
                                    return kw;
                                }
                            }
                        }
                    }
                    return null;
                }""")
                if clicked:
                    log.info(f"✅ JS 点击按钮成功: {clicked}")
                else:
                    log.warning(f"第 {attempt} 次：未找到续期按钮")
                    take_screenshot(page, f"renew_no_btn_{attempt}")
                    continue
        except Exception as e:
            log.warning(f"点击按钮异常: {e}")
            continue

        # 2. 处理 Cloudflare Turnstile
        cf_ok = handle_cf_turnstile(page, timeout=60)
        log.info(f"  CF Turnstile 处理结果: {cf_ok}")

        # 3. 处理 Google reCAPTCHA（如果有）
        handle_google_recaptcha(page)

        # 4. 处理模态框（如果出现）
        time.sleep(2)
        modal_confirmed = False
        # 检查模态框是否存在
        modal_exists = page.evaluate("""() => {
            return !!(document.getElementById('renewModal') || document.querySelector('[role="dialog"]') || document.querySelector('.modal:not([style*="display: none"])'));
        }""")
        if modal_exists:
            log.info("检测到模态框，尝试确认...")
            modal_confirmed = click_modal_confirm()
            take_screenshot(page, f"renew_modal_after_confirm_{attempt}")
        else:
            log.info("未检测到模态框，可能直接触发续期")

        # 5. 等待网络请求（捕获续期请求）
        log.info("等待 15 秒捕获网络请求...")
        time.sleep(15)

        # 6. 尝试重放捕获的续期请求
        if captured_renew_reqs:
            log.info(f"🎯 捕获到 {len(captured_renew_reqs)} 个续期请求，尝试重放...")
            # 获取 cookies 和 tokens
            cookies = page.context.cookies()
            session = requests.Session()
            for cookie in cookies:
                session.cookies.set(cookie['name'], cookie['value'])
            # 提取 CSRF token
            csrf = page.evaluate("""() => {
                var m = document.querySelector('meta[name="csrf-token"]');
                if (m) return m.content;
                var inp = document.querySelector('input[name="_token"], input[name="csrf"]');
                if (inp) return inp.value;
                return null;
            }""")
            headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
            if csrf:
                headers["X-CSRF-Token"] = csrf
                headers["CSRF-Token"] = csrf

            for idx, req in enumerate(captured_renew_reqs):
                try:
                    method = req['method']
                    url = req['url']
                    post_data = req.get('post_data')
                    if method == "GET":
                        resp = session.get(url, headers=headers, timeout=15)
                    elif method in ("POST", "PUT", "PATCH"):
                        if post_data:
                            resp = session.request(method, url, data=post_data, headers=headers, timeout=15)
                        else:
                            # 尝试常见 body
                            body = {"serverId": server_id, "id": server_id, "server_id": server_id}
                            resp = session.request(method, url, json=body, headers=headers, timeout=15)
                    else:
                        continue
                    log.info(f"    重放响应: {resp.status_code} {resp.text[:200]}")
                    if resp.status_code in (200, 201, 204):
                        time.sleep(5)
                        new_expiry = get_current_expiry()
                        if parse_expiry_minutes(new_expiry) > parse_expiry_minutes(expiry_before):
                            log.info(f"✅ 重放请求 {idx+1} 成功续期，expiry 变为 {new_expiry}")
                            page.remove_listener("request", log_req)
                            page.remove_listener("response", log_resp)
                            return True
                except Exception as e:
                    log.warning(f"    重放异常: {e}")

        # 7. 检查 expiry 是否已增加（可能已经成功）
        new_expiry = get_current_expiry()
        if parse_expiry_minutes(new_expiry) > parse_expiry_minutes(expiry_before):
            log.info(f"✅ 续期成功，expiry 变为 {new_expiry}")
            page.remove_listener("request", log_req)
            page.remove_listener("response", log_resp)
            return True

        # 8. 如果未成功，尝试直接 API 调用（不依赖捕获）
        log.info("尝试直接调用续期 API...")
        cookies = page.context.cookies()
        session = requests.Session()
        for cookie in cookies:
            session.cookies.set(cookie['name'], cookie['value'])
        csrf = page.evaluate("""() => {
            var m = document.querySelector('meta[name="csrf-token"]');
            if (m) return m.content;
            var inp = document.querySelector('input[name="_token"], input[name="csrf"]');
            if (inp) return inp.value;
            return null;
        }""")
        headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
        if csrf:
            headers["X-CSRF-Token"] = csrf
            headers["CSRF-Token"] = csrf

        api_paths = [
            f"{BASE_URL}/api/server/renew",
            f"{BASE_URL}/api/v1/server/renew",
            f"{BASE_URL}/api/v2/server/renew",
            f"{BASE_URL}/api/server/extend",
            f"{BASE_URL}/api/servers/renew",
            f"{BASE_URL}/api/servers/{server_id}/renew",
            f"{BASE_URL}/server/renew",
            f"{BASE_URL}/server/extend",
            f"{BASE_URL}/server/refresh",
        ]
        body_variants = [
            {"serverId": server_id},
            {"id": server_id},
            {"server_id": server_id},
            {"serverId": server_id, "action": "renew"},
            {"id": server_id, "action": "renew"},
            {"server": server_id, "action": "extend"},
        ]
        for path in api_paths:
            for body in body_variants:
                try:
                    resp = session.post(path, json=body, headers=headers, timeout=15)
                    log.info(f"  POST {path} -> {resp.status_code} {resp.text[:200]}")
                    if resp.status_code in (200, 201, 204):
                        time.sleep(5)
                        new_expiry = get_current_expiry()
                        if parse_expiry_minutes(new_expiry) > parse_expiry_minutes(expiry_before):
                            log.info(f"✅ 直接 API 调用成功: {path}, expiry 变为 {new_expiry}")
                            page.remove_listener("request", log_req)
                            page.remove_listener("response", log_resp)
                            return True
                except Exception as e:
                    log.warning(f"  API 调用异常: {e}")

        # 如果仍未成功，继续下一次尝试
        log.warning(f"第 {attempt} 次续期尝试失败")
        take_screenshot(page, f"renew_fail_{attempt}")
        # 刷新页面重置状态
        try:
            page.reload()
            time.sleep(3)
        except:
            pass

    # 所有尝试失败
    log.error("❌ 所有续期方法均失败。")
    log.info("===== 诊断报告：捕获的网络请求 =====")
    for meth, url in all_requests:
        log.info(f"  {meth} {url}")
    log.info("===== 诊断报告：捕获的网络响应 =====")
    for status, url in all_responses:
        log.info(f"  {status} {url}")
    log.info("=====================================")
    log.info("提示：请检查上述请求中是否包含续期API，若存在则需调整匹配规则。")
    page.remove_listener("request", log_req)
    page.remove_listener("response", log_resp)
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

        info = get_server_info(page, SERVER_ID)
        status     = info.get("status", "Unknown")
        expiry     = info.get("expiry", "未知")
        last_renew = info.get("lastRenewed", "未知")

        log.info(f"服务器状态: {status} | 到期: {expiry}")

        if SKIP_RENEW:
            log.info("⏭️ SKIP_RENEW=true，跳过续期步骤")
            renewed = False
        else:
            renewed = renew_server(page, SERVER_ID, expiry_before=expiry)

        new_expiry = expiry
        if renewed:
            time.sleep(3)
            info2 = get_server_info(page, SERVER_ID)
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
