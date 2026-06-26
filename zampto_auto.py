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
        log.warning("WXPUSHER_TOKEN 或 WXPUSHER_UID 未配置，跳过推送")
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
                log.info("WxPusher 推送成功")
            else:
                log.warning(f"WxPusher 推送失败: {result}")
    except Exception as e:
        log.warning(f"WxPusher 推送异常: {e}")

def tgpush(content: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        log.warning("TG_BOT_TOKEN 或 TG_CHAT_ID 未配置，跳过推送")
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
                log.info("Telegram 通知发送成功")
            else:
                log.warning(f"Telegram 推送返回错误: {result}")
    except Exception as e:
        log.warning(f"Telegram 推送异常: {e}")

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
        log.info(f"截图: {path}")
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
    log.info(f"等待端口可连接（最多 {max_wait}s）...")
    elapsed = 0
    while elapsed < max_wait:
        if tcp_check(host, port):
            log.info(f"端口已可连接（等待了 {elapsed}s）")
            return True
        time.sleep(interval)
        elapsed += interval
        log.info(f"  [{elapsed}s] 端口还未开放，继续等待...")
    log.warning(f"端口等待超时（{max_wait}s）")
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

# ---------- 处理验证码 ----------
def handle_cf_turnstile(page, timeout=60) -> bool:
    log.info("处理 Cloudflare Turnstile 验证...")
    cf_iframe_selector = "iframe[src*='challenges.cloudflare.com']"
    start_time = time.time()
    while time.time() - start_time < 30:
        if page.locator(cf_iframe_selector).count() > 0:
            log.info("检测到 Cloudflare iframe")
            break
        time.sleep(0.5)
    else:
        log.warning("未检测到 Cloudflare iframe，跳过")
        return True

    try:
        frame = page.frame_locator(cf_iframe_selector)
        checkbox = frame.locator('[role="checkbox"], .challenge, .checkbox, input[type="checkbox"]').first
        if checkbox.count() > 0:
            checkbox.click(timeout=5000)
            log.info("已点击复选框")
            time.sleep(5)
            if not page.locator(cf_iframe_selector).count():
                return True
    except:
        pass

    try:
        iframe_el = page.locator(cf_iframe_selector).first
        if iframe_el.count():
            iframe_el.click(force=True)
            log.info("点击 iframe 区域")
            time.sleep(5)
            if not page.locator(cf_iframe_selector).count():
                return True
    except:
        pass

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not page.locator(cf_iframe_selector).count():
            return True
        time.sleep(1)

    log.error("CF 验证超时")
    return False

def handle_google_recaptcha(page):
    try:
        recaptcha_iframe = page.locator('iframe[src*="recaptcha/api2/aframe"]')
        if recaptcha_iframe.count() == 0:
            return
        log.info("检测到 Google reCAPTCHA，尝试点击...")
        try:
            frame = page.frame_locator('iframe[src*="recaptcha/api2/aframe"]')
            checkbox = frame.locator('.recaptcha-checkbox-border, .recaptcha-checkbox-checkmark, #recaptcha-anchor')
            if checkbox.count():
                checkbox.click(timeout=5000)
                log.info("已点击 reCAPTCHA")
                time.sleep(5)
                return
        except:
            pass
        try:
            recaptcha_iframe.click(force=True)
            log.info("点击 reCAPTCHA iframe")
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
        except:
            pass
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
        except:
            continue
        human_delay()
        try:
            page.locator('button[name="submit"], button[type="submit"]').first.click()
            log.info("已点击登录按钮（第一步）")
        except:
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
        except:
            continue
        human_delay()
        try:
            page.locator('button[name="submit"], button[type="submit"]').first.click()
            log.info("已点击继续按钮（第二步）")
        except:
            continue
        if wait_for_url_contains(page, "dash.zampto.net", 20):
            log.info("登录成功")
            take_screenshot(page, "01_login_success")
            return True
        time.sleep(3)
        if "dash.zampto.net" in page.url or "zampto.net/server" in page.url:
            log.info("登录成功")
            take_screenshot(page, "01_login_success")
            return True
        log.warning("登录后未跳转")
        take_screenshot(page, f"login_fail_{attempt}")
        time.sleep(2)
    return False

# ---------- 获取服务器信息 ----------
def get_server_info(page, server_id: str) -> dict:
    server_url = f"{BASE_URL}/server?id={server_id}"
    log.info("访问服务器详情页")
    try:
        page.goto(server_url, timeout=30000, wait_until="domcontentloaded")
    except:
        pass
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
    log.info("访问 Console 页读取运行状态")
    try:
        page.goto(console_url, timeout=30000, wait_until="domcontentloaded")
    except:
        pass
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
    log.info(f"服务器信息: expiry={info.get('expiry')}, status={info.get('status')}")
    return info

# ---------- 启动服务器 ----------
def start_server(page) -> bool:
    console_url = f"{BASE_URL}/server-console?id={SERVER_ID}"
    MAX_START_ATTEMPTS = 3
    for attempt in range(1, MAX_START_ATTEMPTS + 1):
        log.info(f"启动尝试 {attempt}/{MAX_START_ATTEMPTS}")
        try:
            page.goto(console_url, timeout=30000, wait_until="domcontentloaded")
        except:
            pass
        time.sleep(3)
        if attempt == 1:
            take_screenshot(page, "03_console_page")
        dismiss_all_popups(page)
        time.sleep(1)
        try:
            start_btn = page.locator('button:has-text("Start")').first
            if start_btn.is_visible(timeout=5000):
                start_btn.click()
                log.info("已点击 Start 按钮")
                time.sleep(5)
                take_screenshot(page, f"04_after_start_attempt{attempt}")
            else:
                body_now = get_text(page)
                if "Running" in body_now:
                    log.info("服务器已在运行，跳过启动")
                    return True
                else:
                    log.warning("Start 按钮不可见，继续等待")
                    continue
        except Exception as e:
            log.warning(f"点击 Start 失败: {e}")
            continue
        log.info("等待服务器变为 Running（最多 5 分钟）...")
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
                    log.info(f"服务器已变为 Running（等待了 {elapsed}s）")
                    take_screenshot(page, f"05_running_confirmed_attempt{attempt}")
                    break
                elif "Starting" in body:
                    log.info(f"  [{elapsed}s] 还在 Starting...")
                elif "Offline" in body or "Stopped" in body:
                    offline_streak += 1
                    if offline_streak >= 3:
                        final_status = "Offline"
                        take_screenshot(page, f"05_start_failed_attempt{attempt}")
                        break
                else:
                    offline_streak = 0
            except:
                pass
        if final_status == "Running":
            # 验证端口
            try:
                addr_raw = page.evaluate("""() => {
                    var body = document.body.innerText || '';
                    var m = body.match(/node\\d+\\.zampto\\.net:\\d+/i);
                    return m ? m[0] : null;
                }""")
                if addr_raw:
                    parts = addr_raw.rsplit(":", 1)
                    if len(parts) == 2:
                        port = int(parts[1])
                        if wait_for_port(parts[0], port, max_wait=60, interval=10):
                            log.info("端口验证通过")
                            return True
            except:
                pass
            return True
        if attempt < MAX_START_ATTEMPTS:
            time.sleep(5)
    return False

# ---------- 续期 ----------
def renew_server(page, server_id: str, expiry_before: str) -> bool:
    server_url = f"{BASE_URL}/server?id={server_id}"
    
    for attempt in range(1, 4):
        log.info(f"续期尝试 {attempt}/3")
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
                log.info("已点击 Renew Server")
            else:
                renew_btn = page.locator('a:has-text("Renew Server"), button:has-text("Renew Server")').first
                if renew_btn.count():
                    renew_btn.scroll_into_view_if_needed()
                    renew_btn.click(force=True)
                    log.info("已点击 Renew Server (locator)")
                else:
                    log.warning("无法定位 Renew Server")
                    continue
        except Exception as e:
            log.warning(f"点击失败: {e}")
            continue

        time.sleep(2)
        handle_google_recaptcha(page)
        handle_cf_turnstile(page, timeout=30)

        # 尝试按 Enter
        try:
            page.keyboard.press("Enter")
            log.info("按 Enter 键")
            time.sleep(2)
        except:
            pass

        # 尝试点击模态框背景
        try:
            page.click("#renewModal", force=True)
            log.info("点击模态框背景")
            time.sleep(2)
        except:
            pass

        log.info("等待续期完成...")
        time.sleep(15)

        # 刷新检查 expiry
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
            log.info(f"续期成功！expiry: {expiry_before} -> {info_after}")
            return True
        else:
            log.warning(f"尝试 {attempt} 后 expiry 未变化")

    # 尝试直接 API
    log.info("尝试直接调用续期 API...")
    try:
        cookies = page.context.cookies()
        session = requests.Session()
        for cookie in cookies:
            session.cookies.set(cookie['name'], cookie['value'])
        headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}

        paths = [
            f"{BASE_URL}/server/renew?id={server_id}",
            f"{BASE_URL}/api/server/renew?id={server_id}",
            f"{BASE_URL}/api/v1/server/renew?id={server_id}",
        ]
        for path in paths:
            try:
                resp = session.get(path, headers=headers, timeout=10)
                if resp.status_code == 200:
                    log.info(f"API 调用成功: {path}")
                    time.sleep(5)
                    page.goto(server_url)
                    time.sleep(3)
                    info_final = page.evaluate("""() => {
                        var body = document.body.innerText || '';
                        var m = body.match(/Expiry[^:]*:\\s*([^\\n]+)/i);
                        return m ? m[1].trim() : null;
                    }""")
                    if parse_expiry_minutes(info_final) > parse_expiry_minutes(expiry_before):
                        log.info("API 续期成功")
                        return True
            except:
                pass
    except Exception as e:
        log.warning(f"API 尝试失败: {e}")

    return False

# ---------- 主流程 ----------
def main():
    from cloakbrowser import launch

    if not SERVER_ID:
        log.error("未配置 ZAMPTO_SERVER_ID")
        wxpush("未配置 ZAMPTO_SERVER_ID，任务中止")
        tgpush("未配置 `ZAMPTO_SERVER_ID`，任务中止")
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
            msg = "Zampto 登录失败"
            wxpush(msg)
            tgpush(msg)
            return

        dismiss_all_popups(page)
        info = get_server_info(page, SERVER_ID)
        status = info.get("status", "Unknown")
        expiry = info.get("expiry", "未知")
        last_renew = info.get("lastRenewed", "未知")

        log.info(f"状态: {status} | 到期: {expiry}")

        if SKIP_RENEW:
            log.info("SKIP_RENEW=true，跳过续期")
            renewed = False
        else:
            renewed = renew_server(page, SERVER_ID, expiry)

        new_expiry = expiry
        if renewed:
            time.sleep(3)
            info2 = get_server_info(page, SERVER_ID)
            new_expiry = info2.get("expiry") or expiry
            last_renew = info2.get("lastRenewed") or last_renew

        started = False
        if "stopped" in status.lower() or "offline" in status.lower():
            log.info("服务器已停止，尝试启动...")
            started = start_server(page)
            if started:
                status = "Running"
            else:
                status = "Start Failed"

        lines = ["🖥️ **Zampto 服务器日报**"]
        lines.append(f"服务器 ID: `{SERVER_ID}`")
        lines.append("")
        status_icon = "🟢" if "running" in status.lower() else ("🟡" if "starting" in status.lower() else "🔴")
        lines.append(f"状态: {status_icon} {status}")
        if started:
            lines.append("  → 已启动 ✅")
        elif "failed" in status.lower():
            lines.append("  ⚠️ 启动失败，请手动处理")
        lines.append("")
        lines.append(f"Expiry: `{new_expiry}`")
        if last_renew:
            lines.append(f"Last Renewed: {last_renew}")
        if renewed:
            lines.append("  → 已自动续期成功 ✅")
        else:
            lines.append("  ⚠️ 续期失败，请手动检查")

        msg = "\n".join(lines)
        log.info(f"推送内容:\n{msg}")
        wxpush(msg)
        tgpush(msg)

    except Exception as e:
        log.exception(e)
        take_screenshot(page, "99_error")
        err_msg = f"Zampto 任务异常: {e}"
        wxpush(err_msg)
        tgpush(err_msg)
    finally:
        time.sleep(3)
        browser.close()
        log.info("任务结束")

if __name__ == "__main__":
    main()
