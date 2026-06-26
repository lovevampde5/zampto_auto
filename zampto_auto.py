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

# ---------- 推送函数 ----------
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

# ---------- 处理 Cloudflare Turnstile ----------
def handle_cf_turnstile(page, timeout=60) -> bool:
    log.info("⏳ 处理 Cloudflare Turnstile 验证（多策略）...")
    cf_iframe_selector = "iframe[src*='challenges.cloudflare.com']"
    start_time = time.time()
    while time.time() - start_time < 30:
        if page.locator(cf_iframe_selector).count() > 0:
            log.info("✅ 检测到 Cloudflare iframe")
            break
        time.sleep(0.5)
    else:
        log.warning("⚠️ 等待 30 秒仍未检测到 Cloudflare iframe，可能无需验证或已自动通过")
        return True

    try:
        log.info("🔄 [策略 A] 尝试通过 frame_locator 点击 Turnstile 复选框...")
        frame = page.frame_locator(cf_iframe_selector)
        checkbox = frame.locator('[role="checkbox"], .challenge, .checkbox, input[type="checkbox"]').first
        if checkbox.count() > 0:
            checkbox.click(timeout=5000)
            log.info("  已点击复选框，等待验证...")
            time.sleep(5)
            if not page.locator(cf_iframe_selector).count():
                log.info("✅ [策略 A] 验证通过")
                return True
        else:
            log.info("  未找到复选框，策略 A 跳过")
    except Exception as e:
        log.info(f"  策略 A 异常: {e}")

    try:
        log.info("🔄 [策略 B] 尝试直接点击 iframe 区域...")
        iframe_el = page.locator(cf_iframe_selector).first
        if iframe_el.count():
            box = iframe_el.bounding_box()
            if box:
                page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
                log.info("  点击 iframe 中心")
                time.sleep(5)
                if not page.locator(cf_iframe_selector).count():
                    log.info("✅ [策略 B] 验证通过")
                    return True
            else:
                iframe_el.click(force=True)
                time.sleep(5)
                if not page.locator(cf_iframe_selector).count():
                    log.info("✅ [策略 B] 验证通过 (force click)")
                    return True
    except Exception as e:
        log.info(f"  策略 B 异常: {e}")

    try:
        log.info("🔄 [策略 C] 使用 JS 点击 iframe 内部元素...")
        page.evaluate(f"""() => {{
            var iframe = document.querySelector('{cf_iframe_selector}');
            if (iframe) {{
                try {{
                    var doc = iframe.contentDocument || iframe.contentWindow.document;
                    var checkbox = doc.querySelector('[role="checkbox"], .challenge, .checkbox, input[type="checkbox"]');
                    if (checkbox) {{
                        checkbox.click();
                        return true;
                    }}
                }} catch(e) {{
                    iframe.click();
                }}
            }}
        }}""")
        time.sleep(5)
        if not page.locator(cf_iframe_selector).count():
            log.info("✅ [策略 C] 验证通过")
            return True
    except Exception as e:
        log.info(f"  策略 C 异常: {e}")

    log.info("⏳ 等待验证自动完成（最长 %ds）..." % timeout)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not page.locator(cf_iframe_selector).count():
            log.info("✅ 验证 iframe 已消失，视为通过")
            return True
        time.sleep(1)

    log.error("❌ 所有策略均失败，验证超时")
    take_screenshot(page, "cf_fail")
    return False

# ---------- 处理 Google reCAPTCHA（增强） ----------
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

# ---------- ★★★ 终极续期：网络诊断 + 暴力尝试 ----------
def renew_server(page, server_id: str, expiry_before: str) -> bool:
    """
    1. 使用网络监听打印所有请求/响应，便于识别真实API。
    2. 尝试多种触发方式：点击按钮、按Enter、点击模态框背景、调用可能存在的JS函数。
    3. 直接发送猜测的API请求（携带cookie）。
    4. 若全部失败，则返回False并生成诊断报告。
    """
    server_url = f"{BASE_URL}/server?id={server_id}"
    all_requests = []
    all_responses = []

    def log_req(request):
        log.info(f"📤 REQ: {request.method} {request.url}")
        all_requests.append((request.method, request.url))
        # 对于POST，尝试打印body
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
        # 尝试获取响应体（仅当是JSON）
        try:
            if "application/json" in response.headers.get("content-type", ""):
                body = response.json()
                log.info(f"    响应JSON: {json.dumps(body, ensure_ascii=False)[:200]}")
        except:
            pass

    page.on("request", log_req)
    page.on("response", log_resp)

    # ----- 方法1：标准点击 + 重试 -----
    for attempt in range(1, 4):
        log.info(f"🔄 尝试 {attempt}/3")
        try:
            page.goto(server_url, timeout=30000, wait_until="domcontentloaded")
        except:
            continue
        time.sleep(3)
        dismiss_all_popups(page)
        time.sleep(1)

        # 点击 Renew Server
        try:
            btn_clicked = page.evaluate("""() => {
                var els = Array.from(document.querySelectorAll('a, button, input[type="button"], input[type="submit"]'));
                for (var el of els) {
                    var txt = (el.innerText || el.textContent || el.value || '').trim();
                    if (txt === 'Renew Server' || txt.includes('Renew Server')) {
                        el.scrollIntoView({block: 'center'});
                        el.click();
                        return true;
                    }
                }
                return false;
            }""")
            if btn_clicked:
                log.info("✅ 已点击 Renew Server")
            else:
                log.warning("未找到按钮，尝试 locator")
                renew_btn = page.locator('a:has-text("Renew Server"), button:has-text("Renew Server")').first
                if renew_btn.count():
                    renew_btn.scroll_into_view_if_needed()
                    renew_btn.click(force=True)
                    log.info("点击成功 (locator)")
                else:
                    log.warning("无法定位 Renew Server")
                    continue
        except Exception as e:
            log.warning(f"点击失败: {e}")
            continue

        time.sleep(2)
        handle_google_recaptcha(page)
        handle_cf_turnstile(page, timeout=30)

        # 检查模态框
        modal_visible = page.evaluate("""() => {
            var m = document.getElementById('renewModal');
            return m && (m.offsetParent !== null || m.style.display !== 'none');
        }""")
        if modal_visible:
            log.info("模态框已出现")
            # 尝试按Enter或点击背景
            try:
                page.keyboard.press("Enter")
                log.info("按Enter键")
                time.sleep(2)
            except:
                pass
            try:
                page.click("#renewModal", force=True)
                log.info("点击模态框背景")
                time.sleep(2)
            except:
                pass
        else:
            log.info("无模态框，可能已直接触发")

        log.info("等待 15 秒监听网络...")
        time.sleep(15)

        # 刷新检查expiry
        try:
            page.reload()
            time.sleep(3)
        except:
            page.goto(server_url)
            time.sleep(3)
        info_after = page.evaluate("""() => {
            var body = document.body.innerText || '';
            var m = body.match(/Expiry[^:]*:\\s*([^\\n]+)/i);
            return m ? m[1].trim() : null;
        }""")
        if parse_expiry_minutes(info_after) > parse_expiry_minutes(expiry_before):
            log.info(f"✅ 续期成功！expiry 变为 {info_after}")
            page.remove_listener("request", log_req)
            page.remove_listener("response", log_resp)
            return True
        else:
            log.warning(f"尝试 {attempt} 后 expiry 未变化")

    # ----- 方法2：直接API猜测 -----
    log.info("尝试直接调用可能的续期 API...")
    try:
        cookies = page.context.cookies()
        session = requests.Session()
        for cookie in cookies:
            session.cookies.set(cookie['name'], cookie['value'])
        headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}

        # 尝试常见路径
        paths = [
            f"{BASE_URL}/server/renew?id={server_id}",
            f"{BASE_URL}/api/server/renew?id={server_id}",
            f"{BASE_URL}/api/v1/server/renew?id={server_id}",
            f"{BASE_URL}/server/extend?id={server_id}",
            f"{BASE_URL}/api/server/extend?id={server_id}",
        ]
        for path in paths:
            log.info(f"  GET {path}")
            try:
                resp = session.get(path, headers=headers, timeout=10)
                log.info(f"    status={resp.status_code}, body={resp.text[:200]}")
                if resp.status_code == 200 and ("success" in resp.text.lower() or "ok" in resp.text.lower()):
                    # 检查expiry
                    time.sleep(5)
                    page.goto(server_url)
                    time.sleep(3)
                    info_final = page.evaluate("""() => {
                        var body = document.body.innerText || '';
                        var m = body.match(/Expiry[^:]*:\\s*([^\\n]+)/i);
                        return m ? m[1].trim() : null;
                    }""")
                    if parse_expiry_minutes(info_final) > parse_expiry_minutes(expiry_before):
                        log.info("✅ API 调用成功，expiry 增加")
                        page.remove_listener("request", log_req)
                        page.remove_listener("response", log_resp)
                        return True
            except Exception as e:
                log.warning(f"  异常: {e}")

        # 尝试 POST（带JSON）
        post_paths = [
            f"{BASE_URL}/api/server/renew",
            f"{BASE_URL}/api/v1/server/renew",
        ]
        for path in post_paths:
            log.info(f"  POST {path} with {{'serverId': '{server_id}'}}")
            try:
                resp = session.post(path, json={"serverId": server_id}, headers=headers, timeout=10)
                log.info(f"    status={resp.status_code}, body={resp.text[:200]}")
                if resp.status_code == 200:
                    time.sleep(5)
                    page.goto(server_url)
                    time.sleep(3)
                    info_final = page.evaluate("""() => {
                        var body = document.body.innerText || '';
                        var m = body.match(/Expiry[^:]*:\\s*([^\\n]+)/i);
                        return m ? m[1].trim() : null;
                    }""")
                    if parse_expiry_minutes(info_final) > parse_expiry_minutes(expiry_before):
                        log.info("✅ POST API 成功")
                        page.remove_listener("request", log_req)
                        page.remove_listener("response", log_resp)
                        return True
            except Exception as e:
                log.warning(f"  异常: {e}")

    except Exception as e:
        log.warning(f"API 尝试失败: {e}")

    # ----- 方法3：尝试在浏览器控制台直接执行可能存在的续期函数 -----
    log.info("尝试在控制台执行可能存在的续期函数...")
    try:
        result = page.evaluate("""() => {
            if (window.renewServer) { window.renewServer(); return 'window.renewServer'; }
            if (window.extendServer) { window.extendServer(); return 'window.extendServer'; }
            // 尝试查找按钮的onclick
            var btn = document.querySelector('a:has-text("Renew Server"), button:has-text("Renew Server")');
            if (btn && btn.onclick) { btn.onclick(new Event('click')); return 'btn.onclick'; }
            return null;
        }""")
        if result:
            log.info(f"✅ 调用了 {result}，等待10秒检查expiry...")
            time.sleep(10)
            page.reload()
            time.sleep(3)
            info_after = page.evaluate("""() => {
                var body = document.body.innerText || '';
                var m = body.match(/Expiry[^:]*:\\s*([^\\n]+)/i);
                return m ? m[1].trim() : null;
            }""")
            if parse_expiry_minutes(info_after) > parse_expiry_minutes(expiry_before):
                log.info("✅ 控制台调用成功")
                page.remove_listener("request", log_req)
                page.remove_listener("response", log_resp)
                return True
    except Exception as e:
        log.warning(f"控制台调用失败: {e}")

    # ----- 最终失败：输出诊断报告 -----
    log.error("❌ 所有续期方法均失败。请手动检查续期功能。")
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
