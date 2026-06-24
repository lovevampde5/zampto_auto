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

# Telegram 新增环境变量
TG_BOT_TOKEN   = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID     = os.environ.get("TG_CHAT_ID", "")

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

# ---------- Telegram Notification ----------
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
    """
    截图前用 JS 将页面上的敏感信息替换为 ***，
    避免账号、邮箱、服务器地址等出现在截图文件中。
    覆盖范围：
      - 首页 info-card 里的 username / user_id / email 文本
      - Console 页的服务器地址（#addressValue）
    """
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

# ---------- CF Turnstile 等待 ----------
def wait_cf_turnstile(page, timeout=90) -> bool:
    """
    等待 Cloudflare Turnstile 验证完成。
    修复逻辑：先等待 CF iframe 出现，再等待其消失，避免 iframe 未出现时误判为验证完成。
    """
    log.info("等待 Cloudflare Turnstile 验证...")

    renew_modal_visible = page.evaluate("""() => {
        var m = document.getElementById('renewModal');
        if (!m) return false;
        return m.offsetParent !== null || m.style.display !== 'none';
    }""")
    if not renew_modal_visible:
        log.warning("⚠️ 续期弹窗未检测到（可能被广告弹窗遮挡或未弹出）")
        return False

    # 第一阶段：等待 CF Turnstile iframe 出现（最多等 20 秒）
    cf_appeared = False
    wait_appear = 20
    log.info(f"  等待 CF Turnstile iframe 出现（最多 {wait_appear}s）...")
    for _ in range(wait_appear):
        has_cf = page.evaluate("""() => {
            var frames = document.querySelectorAll('iframe');
            for (var f of frames) {
                if (f.src && f.src.includes('challenges.cloudflare.com')) return true;
            }
            var body = document.body.innerText || '';
            return body.includes('正在验证') || body.includes('Verifying');
        }""")
        if has_cf:
            cf_appeared = True
            log.info("  CF Turnstile iframe 已出现，等待验证完成...")
            break
        time.sleep(1)

    if not cf_appeared:
        # 检查是否续期弹窗里有"Confirm"/"Submit"按钮，说明验证已自动通过或不需要验证
        has_confirm = page.evaluate("""() => {
            var btns = Array.from(document.querySelectorAll('button'));
            for (var b of btns) {
                var txt = (b.innerText || '').trim().toLowerCase();
                if (txt === 'confirm' || txt === 'submit' || txt === 'renew') return true;
            }
            return false;
        }""")
        if has_confirm:
            log.info("  CF Turnstile 未出现但续期弹窗有确认按钮，尝试点击...")
            page.evaluate("""() => {
                var btns = Array.from(document.querySelectorAll('button'));
                for (var b of btns) {
                    var txt = (b.innerText || '').trim().toLowerCase();
                    if (txt === 'confirm' || txt === 'submit' || txt === 'renew') {
                        b.click();
                        return;
                    }
                }
            }""")
            time.sleep(3)
            return True
        log.warning("⚠️ CF Turnstile iframe 未在 20s 内出现，可能续期弹窗加载失败")
        return False

    # 第二阶段：等待 CF iframe 消失（验证完成）
    deadline = time.time() + timeout
    while time.time() < deadline:
        still_verifying = page.evaluate("""() => {
            var frames = document.querySelectorAll('iframe');
            for (var f of frames) {
                if (f.src && f.src.includes('challenges.cloudflare.com')) return true;
            }
            var body = document.body.innerText || '';
            return body.includes('正在验证') || body.includes('Verifying');
        }""")
        
        if not still_verifying:
            log.info("✅ CF Turnstile 验证完成")
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
                        # ⚙️ 此处已完全修正：连续 3 次（30s）都是 Offline，才真正确认失败
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

        take_screenshot(page, "05_renew_clicked")
    except Exception as e:
        log.warning(f"点击 Renew Server 失败: {e}")
        return False

    time.sleep(2)
    # 多轮清除弹窗，确保续期弹窗不被广告遮挡
    for _ in range(3):
        dismiss_all_popups(page)
        time.sleep(1)
    take_screenshot(page, "06_renew_modal")

    if not wait_cf_turnstile(page, timeout=90):
        # 第一次失败时，尝试重新点击 Renew Server 按钮再试一次
        log.warning("CF 验证失败，尝试重新点击 Renew Server 再试一次...")
        for _ in range(3):
            dismiss_all_popups(page)
            time.sleep(1)
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1)
            retry_clicked = page.evaluate("""() => {
                var els = Array.from(document.querySelectorAll('a, button'));
                for (var el of els) {
                    var txt = (el.innerText || el.textContent || '').trim();
                    if (txt === 'Renew Server' || txt.includes('Renew Server')) {
                        el.scrollIntoView({block: 'center'});
                        el.click();
                        return 'click';
                    }
                }
                return null;
            }""")
            if retry_clicked:
                log.info("重试点击 Renew Server 成功，再次等待 CF Turnstile...")
                time.sleep(2)
                for _ in range(3):
                    dismiss_all_popups(page)
                    time.sleep(1)
                if not wait_cf_turnstile(page, timeout=90):
                    log.warning("重试后 CF 验证仍超时或续期弹窗未出现，续期失败")
                    take_screenshot(page, "06_cf_timeout")
                    return False
            else:
                log.warning("重试时也未找到 Renew Server 按钮，续期失败")
                take_screenshot(page, "06_cf_timeout")
                return False
        except Exception as e:
            log.warning(f"重试点击失败: {e}")
            take_screenshot(page, "06_cf_timeout")
            return False

    # 续期提交后多等一段时间，让服务器处理
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

    minutes_before = parse_expiry_minutes(expiry_before)
    minutes_after  = parse_expiry_minutes(info_after)

    log.info(f"续期前 expiry 分钟数: {minutes_before}, 续期后: {minutes_after}")

    # 修复判断逻辑：
    # 1. 如果续期后时间明显增加（>10分钟），认为成功
    # 2. 如果续期前时间已经很少（<30分钟），续期后只要 >60 分钟也算成功
    # 3. 允许最多 10 分钟的时间流逝误差（即续期后可以比续期前少不超过 10 分钟）
    TIME_DRIFT_TOLERANCE = 10  # 允许的时间流逝误差（分钟）
    RENEW_MIN_THRESHOLD  = 60  # 续期后至少要有这么多分钟才算有效

    if minutes_after > 0:
        increased = minutes_after > (minutes_before - TIME_DRIFT_TOLERANCE)
        long_enough = minutes_after >= RENEW_MIN_THRESHOLD

        if increased and long_enough:
            diff = minutes_after - minutes_before
            if diff > 0:
                log.info(f"✅ 续期成功！expiry: {expiry_before} → {info_after}（增加了 {diff} 分钟）")
            else:
                log.info(f"✅ 续期成功！expiry: {expiry_before} → {info_after}（时间在允许误差内，续期有效）")
            return True

    log.warning(f"⚠️ 续期后 expiry 未增加（{expiry_before} → {info_after}），续期失败！")
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
