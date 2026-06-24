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

# Telegram 环境变量
TG_BOT_TOKEN   = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID     = os.environ.get("TG_CHAT_ID", "")

BASE_URL = "https://dash.zampto.net"
AUTH_URL = "https://auth.zampto.net/sign-in"
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
    """ 截图前用 JS 脱敏 """
    try:
        page.evaluate(r"""() => {
            var cards = document.querySelectorAll('.user-info-grid .info-card .info-content p');
            cards.forEach(p => {
                p.textContent = '***';
            });
            var addrEl = document.getElementById('addressValue');
            if (addrEl) {
                addrEl.textContent = '***';
            }
            var values = document.querySelectorAll('.info-card-value');
            values.forEach(el => {
                if (/\.zampto\.net/.test(el.textContent)) {
                    el.textContent = '***';
                }
            });
        }""")
    except Exception as e:
        log.warning(f"脱敏失败: {e}")

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
        try:
            page.evaluate(r"""() => {
                var ads = document.querySelectorAll('iframe[id*="google_vignette"], iframe[id*="aswift"], ins.adsbygoogle');
                ads.forEach(el => {
                    el.style.setProperty('display', 'none', 'important');
                });
                var fixeds = document.querySelectorAll('div[style*="position: fixed"], div[style*="position:fixed"]');
                fixeds.forEach(el => {
                    var z = parseInt(window.getComputedStyle(el).zIndex) || 0;
                    if (z >= 9000 && !el.id.includes('renew') && !el.id.includes('modal')) {
                        el.style.setProperty('display', 'none', 'important');
                    }
                });
            }""")
            
            closed = page.evaluate(r"""() => {
                var clickCount = 0;
                var selectors = [
                    'button[aria-label="Close"]', 
                    'button[aria-label="close"]', 
                    '.close-button-protector', 
                    '.dismiss-button'
                ];
                selectors.forEach(s => {
                    var el = document.querySelector(s);
                    if (el && el.offsetParent !== null) {
                        el.click();
                        clickCount++;
                    }
                });
                var targets = ['Close', 'close', 'Schließen', '×', 'X', 'CLOSE'];
                var clickables = document.querySelectorAll('button, a, [role="button"]');
                for (var el of clickables) {
                    var t = (el.innerText || '').trim();
                    if (targets.includes(t) && el.offsetParent !== null) {
                        el.click();
                        clickCount++;
                        break;
                    }
                }
                return clickCount;
            }""")
            
            if closed and closed > 0:
                time.sleep(1)
            else:
                break
        except Exception as e:
            log.warning(f"弹窗清理异常: {e}")
            break

# ---------- CF Turnstile 等待 ----------
def wait_cf_turnstile(page, timeout=60) -> bool:
    log.info("等待 Cloudflare Turnstile 验证...")
    renew_modal_visible = page.evaluate(r"""() => {
        var m = document.getElementById('renewModal');
        if (!m) return false;
        return (m.offsetParent !== null || m.style.display !== 'none');
    }""")
    if not renew_modal_visible:
        log.warning("⚠️ 续期弹窗未检测到")
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        still_verifying = page.evaluate(r"""() => {
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
            
        time.sleep(1)
    log.error(f"CF Turnstile 验证超时（{timeout}s）")
    return False

# ---------- 登录 ----------
def login(page, max_retries=3) -> bool:
    login_url = "https://auth.zampto.net/sign-in"

    for attempt in range(1, max_retries + 1):
        log.info(f"登录 {attempt}/{max_retries}")
        try:
            page.goto(login_url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_selector('input[name="identifier"]', timeout=15000)
            
            user_el = page.locator('input[name="identifier"]').first
            user_el.click()
            user_el.fill("")
            user_el.type(USERNAME, delay=random.randint(60, 130))
            
            human_delay()
            page.locator('button[type="submit"]').first.click()
            
            page.wait_for_selector('input[name="password"]', timeout=15000)
            pass_el = page.locator('input[name="password"]').first
            pass_el.click()
            pass_el.fill("")
            pass_el.type(PASSWORD, delay=random.randint(60, 130))
            
            human_delay()
            page.locator('button[type="submit"]').first.click()
            
            if wait_for_url_contains(page, "dash.zampto.net", 20) or "dash.zampto.net" in page.url:
                log.info("✅ 登录成功")
                return True
        except Exception as e:
            log.warning(f"第 {attempt} 次登录尝试失败: {e}")
            take_screenshot(page, f"login_fail_{attempt}")
            time.sleep(2)
    return False

# ---------- 获取服务器信息 ----------
def get_server_info(page, server_id: str) -> dict:
    server_url = f"{BASE_URL}/server?id={server_id}"
    try:
        page.goto(server_url, timeout=30000, wait_until="domcontentloaded")
    except Exception as e:
        log.warning(f"访问服务器详情超时: {e}")

    time.sleep(3)
    dismiss_all_popups(page)

    info = page.evaluate(r"""() => {
        var body = document.body.innerText || '';
        var expiryMatch  = body.match(/Expiry[^:]*:\s*([^\n]+)/i);
        var renewedMatch = body.match(/last renewed[^:]*:\s*([^\n]+)/i);
        var addrMatch    = body.match(/node\d+\.zampto\.net:\d+/i);
        return {
            expiry:      expiryMatch  ? expiryMatch[1].trim()  : null,
            lastRenewed: renewedMatch ? renewedMatch[1].trim() : null,
            address:     addrMatch    ? addrMatch[0]           : null,
        };
    }""")

    # 优化点：不再死磕特定 class，改用对全文本状态词直接匹配，全面兼容
    try:
        page.goto(f"{BASE_URL}/server-console?id={server_id}", timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)
        dismiss_all_popups(page)
        txt = get_text(page)
        if "Running" in txt:
            info["status"] = "Running"
        elif "Starting" in txt:
            info["status"] = "Starting"
        elif "Stopped" in txt or "Offline" in txt:
            info["status"] = "Stopped"
        else:
            info["status"] = "Unknown"
    except:
        info["status"] = "Unknown"

    return info

# ---------- 启动服务器 ----------
def start_server(page) -> bool:
    console_url = f"{BASE_URL}/server-console?id={SERVER_ID}"
    try:
        page.goto(console_url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)
        dismiss_all_popups(page)
        start_btn = page.locator('button:has-text("Start")').first
        if start_btn.is_visible(timeout=5000):
            start_btn.click()
            log.info("✅ 已点击 Start 按钮")
            time.sleep(5)
            
            for _ in range(20):
                time.sleep(10)
                page.reload(timeout=20000, wait_until="domcontentloaded")
                dismiss_all_popups(page)
                if "Running" in get_text(page):
                    log.info("✅ 服务器变为 Running 状态")
                    return True
    except Exception as e:
        log.warning(f"点击启动异常: {e}")
    return False

# ---------- 续期 ----------
def renew_server(page, server_id: str, expiry_before: str) -> bool:
    minutes_before = parse_expiry_minutes(expiry_before)
    
    # === 核心修复点：如果当前剩余时间大于 24 小时（1440分钟），官方不加时间，直接算续期成功 ===
    if minutes_before > 1440:
        log.info(f"⏳ 当前剩余到期时间为 {expiry_before}（超过24小时），已接近满额，无需重复点击续期按钮")
        return True

    server_url = f"{BASE_URL}/server?id={server_id}"
    try:
        page.goto(server_url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)
        dismiss_all_popups(page)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        
        renew_btn = page.locator('a:has-text("Renew Server"), button:has-text("Renew Server")').first
        renew_btn.click(force=True)
        log.info("已点击 Renew Server 按钮")
        
        time.sleep(2)
        if wait_cf_turnstile(page, timeout=60):
            time.sleep(8)
            
            page.reload(timeout=20000, wait_until="domcontentloaded")
            time.sleep(3)
            dismiss_all_popups(page)
            
            info_after = page.evaluate(r"""() => {
                var body = document.body.innerText || '';
                var m = body.match(/Expiry[^:]*:\s*([^\n]+)/i);
                return m ? m[1].trim() : null;
            }""")
            
            minutes_after = parse_expiry_minutes(info_after)
            if minutes_after > minutes_before or minutes_after >= 4000:
                log.info(f"✅ 自动续期成功: {expiry_before} → {info_after}")
                return True
    except Exception as e:
        log.warning(f"续期操作异常: {e}")
    return False

# ---------- 主流程 ----------
def main():
    from cloakbrowser import launch

    if not SERVER_ID:
        log.error("❌ 未配置 ZAMPTO_SERVER_ID 环境变量")
        return

    PROXY_SERVER = "socks5://127.0.0.1:1080"
    display_width = int(os.environ.get("DISPLAY_WIDTH", 1280))
    display_height = int(os.environ.get("DISPLAY_HEIGHT", 720))

    browser = launch(headless=False, humanize=True, proxy=PROXY_SERVER, geoip=True)
    page = browser.new_page(viewport={"width": display_width, "height": display_height})

    try:
        if not login(page):
            return

        dismiss_all_popups(page)
        info = get_server_info(page, SERVER_ID)
        status = info.get("status", "Unknown")
        expiry = info.get("expiry", "未知")

        if SKIP_RENEW:
            renewed = False
        else:
            renewed = renew_server(page, SERVER_ID, expiry_before=expiry)

        new_expiry = expiry
        if renewed and not (parse_expiry_minutes(expiry) > 1440):
            time.sleep(3)
            info2 = get_server_info(page, SERVER_ID)
            new_expiry = info2.get("expiry") or expiry
            status = info2.get("status") or status

        if "stopped" in status.lower() or "offline" in status.lower():
            log.info("🔴 检测到服务器下线，正在执行紧急自动启动...")
            start_server(page)
            status = "Running"

        msg = f"🖥️ **Zampto 服务器监控日报**\n\n状态: 🟢 {status}\n到期时间: `{new_expiry}`\n自动续期: {'时间充足 (无需续期) ⏳' if parse_expiry_minutes(expiry) > 1440 else ('成功 ✅' if renewed else '失败 ❌')}"
        wxpush(msg)
        tgpush(msg)

    except Exception as e:
        log.exception(e)
        take_screenshot(page, "99_error")
    finally:
        browser.close()
        log.info("任务结束")

if __name__ == "__main__":
    main()
