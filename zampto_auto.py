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

BASE_URL    = "https://dash.zampto.net"
AUTH_URL    = "https://auth.zampto.net/sign-in"
SERVERS_URL = f"{BASE_URL}/servers"

SCREENSHOT_DIR = Path("./screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

# ---------- 推送工具 ----------
def wxpush(content: str):
    if not WXPUSHER_TOKEN or not WXPUSHER_UID:
        log.warning("✉️ WXPUSHER_TOKEN 或 WXPUSHER_UID 未配置，跳过推送")
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

# ---------- 基础工具函数 ----------
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
        log.warning(f"脱敏 JS 执行失败: {e}")

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
    if not expiry_str: return -1
    total = 0
    m = re.search(r'(\d+)\s*day', expiry_str)
    if m: total += int(m.group(1)) * 24 * 60
    m = re.search(r'(\d+)\s*h', expiry_str)
    if m: total += int(m.group(1)) * 60
    m = re.search(r'(\d+)\s*m', expiry_str)
    if m: total += int(m.group(1))
    return total if total > 0 else -1

def dismiss_all_popups(page):
    for _ in range(4):
        closed_any = False
        hidden = page.evaluate("""() => {
            var count = 0;
            document.querySelectorAll('iframe').forEach(function(f) {
                if ((f.id && (f.id.includes('google_vignette') || f.id.includes('aswift'))) ||
                    (f.name && f.name.includes('google_vignette'))) {
                    f.style.setProperty('display', 'none', 'important');
                    if (f.parentElement) {
                        f.parentElement.style.setProperty('display', 'none', 'important');
                    }
                    count++;
                }
            });
            document.querySelectorAll('ins.adsbygoogle').forEach(function(ins) {
                ins.style.setProperty('display', 'none', 'important');
                count++;
            });
            return count;
        }""")
        if hidden and hidden > 0: closed_any = True

        closed = page.evaluate("""() => {
            var count = 0;
            var closeTexts = ['Close', 'close', 'Schließen', '×', 'X', 'CLOSE'];
            for (var t of closeTexts) {
                var btns = Array.from(document.querySelectorAll('button, a, [role="button"]'));
                for (var b of btns) {
                    if (b.innerText && b.innerText.trim() === t) {
                        var parent = b.closest('[class*="modal"],[class*="popup"],[class*="overlay"],[class*="ad-"],[class*="vignette"]');
                        if (parent && parent.offsetParent !== null) { b.click(); count++; break; }
                    }
                }
            }
            return count;
        }""")
        if closed and closed > 0:
            closed_any = True
            time.sleep(1)

        if not closed_any: break
        time.sleep(0.8)

# ---------- CF Turnstile 等待与穿透点击 (核心重写) ----------
def wait_cf_turnstile(page, timeout=60) -> bool:
    log.info("🛡️ 等待 Cloudflare Turnstile 验证...")
    deadline = time.time() + timeout
    
    while time.time() < deadline:
        try:
            # 使用 Playwright 的 frame_locator 精准穿透跨域 iframe
            cf_frame = page.frame_locator('iframe[src*="challenges.cloudflare.com"]').first
            
            # 定位 Turnstile 复选框 (兼容不同的 class 和 input 结构)
            checkbox = cf_frame.locator('.ctp-checkbox-label, input[type="checkbox"], .cb-c, .mark').first
            
            if checkbox.is_visible(timeout=1500):
                log.info("👀 发现 CF Turnstile 验证框，尝试模拟人类点击...")
                # 增加随机 delay 模拟真实的物理点击耗时，降低被检测为脚本的概率
                checkbox.click(force=True, delay=random.randint(150, 450))
                time.sleep(3) # 给予 CF 执行验证脚本的时间
        except Exception:
            # 如果没找到元素，说明可能还没加载出来，或者已经验证通过消失了，跳过报错继续检测
            pass

        # 判断是否还在验证状态
        is_verifying = page.evaluate("""() => {
            var frames = Array.from(document.querySelectorAll('iframe'));
            var cfFrame = frames.find(f => f.src && f.src.includes('challenges.cloudflare.com'));
            // 如果 CF iframe 存在且未被隐藏，说明还在验证
            if (cfFrame && cfFrame.offsetParent !== null && cfFrame.style.display !== 'none') {
                return true;
            }
            // 兜底文本检测
            var body = document.body.innerText || '';
            return body.includes('正在验证') || body.includes('Verifying') || body.includes('Just a moment...');
        }""")
        
        if not is_verifying:
            log.info("✅ CF Turnstile 验证完成 (或验证框已通过/隐藏)")
            return True
            
        time.sleep(2)

    log.error(f"❌ CF Turnstile 验证超时（{timeout}s），可能被盾彻底拦截")
    return False

# ---------- 登录 ----------
def login(page, max_retries=3) -> bool:
    login_url = "https://auth.zampto.net/sign-in?app_id=YOUR_APP_ID"
    for attempt in range(1, max_retries + 1):
        log.info(f"🔑 尝试登录 {attempt}/{max_retries}")
        try:
            page.goto(login_url, timeout=30000, wait_until="domcontentloaded")
        except:
            pass

        try:
            page.wait_for_selector('input[name="identifier"], input[autocomplete="username email"]', timeout=15000)
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
            log.warning(f"⚠️ 登录尝试 {attempt} 失败: {e}")
            time.sleep(2)
    return False

# ---------- 获取服务器信息 ----------
def get_server_info(page, server_id: str) -> dict:
    server_url = f"{BASE_URL}/server?id={server_id}"
    try:
        page.goto(server_url, timeout=30000, wait_until="domcontentloaded")
    except:
        pass
    time.sleep(3)
    dismiss_all_popups(page)

    info = page.evaluate("""() => {
        var body = document.body.innerText || '';
        var expiryMatch  = body.match(/Expiry[^:]*:\\s*([^\\n]+)/i);
        var renewedMatch = body.match(/last renewed[^:]*:\\s*([^\\n]+)/i);
        return {
            expiry:      expiryMatch  ? expiryMatch[1].trim()  : null,
            lastRenewed: renewedMatch ? renewedMatch[1].trim() : null
        };
    }""")

    console_url = f"{BASE_URL}/server-console?id={server_id}"
    try:
        page.goto(console_url, timeout=30000, wait_until="domcontentloaded")
    except:
        pass
    time.sleep(3)
    
    status_text = page.evaluate("""() => {
        var runEl = document.querySelector('.status-running,.status-stopped,.status-starting');
        if (runEl) return runEl.innerText.trim();
        var body = document.body.innerText || '';
        var sm = body.match(/Running(?:\\s*\\([^)]+\\))?|Stopped|Starting|Stopping/i);
        return sm ? sm[0] : 'Unknown';
    }""")
    info["status"] = status_text or "Unknown"
    return info

# ---------- 启动服务器 ----------
def start_server(page) -> bool:
    console_url = f"{BASE_URL}/server-console?id={SERVER_ID}"
    try:
        page.goto(console_url, timeout=30000)
    except:
        pass
    time.sleep(3)
    dismiss_all_popups(page)

    try:
        start_btn = page.locator('button:has-text("Start")').first
        if start_btn.is_visible(timeout=5000):
            start_btn.click()
            log.info("🚀 已点击 Start 按钮")
    except:
        pass

    for _ in range(30):
        time.sleep(10)
        try:
            page.reload(timeout=20000)
            if "Running" in get_text(page):
                log.info("✅ 服务器已变为 Running")
                return True
        except:
            pass
    return False

# ---------- 续期核心逻辑 ----------
def renew_server(page, server_id: str, expiry_before: str) -> bool:
    minutes_before = parse_expiry_minutes(expiry_before)
    server_url = f"{BASE_URL}/server?id={server_id}"
    
    try:
        page.goto(server_url, timeout=30000, wait_until="domcontentloaded")
    except:
        pass
    time.sleep(3)
    dismiss_all_popups(page)

    try:
        renew_btn = page.locator('a:has-text("Renew Server"), button:has-text("Renew Server")').first
        renew_btn.scroll_into_view_if_needed()
        time.sleep(0.5)
        renew_btn.click(force=True)
        log.info("👆 已点击 Renew Server 按钮，等待弹窗与 CF 拦截...")
    except Exception as e:
        log.warning(f"点击 Renew Server 失败: {e}")
        return False

    time.sleep(2)
    dismiss_all_popups(page)

    # 触发强力的 CF Turnstile 穿透检测
    if not wait_cf_turnstile(page, timeout=60):
        log.warning("⚠️ CF 验证未通过，可能导致续期请求失败")
        # 即使这里提示失败，我们也继续往下走，因为有时面板后台其实已经接收到了请求

    # 检查验证通过后，是否还需要点击弹窗内的二次确认
    try:
        confirm_btn = page.locator('button:has-text("Confirm"), button:has-text("Renew")').nth(1)
        if confirm_btn.is_visible(timeout=3000):
            confirm_btn.click(force=True)
            log.info("🖱️ 点击了弹窗内的二次确认按钮")
            time.sleep(3)
    except:
        pass

    log.info("⏳ 等待后台处理并验证到期时间...")
    
    # 强制加上时间戳防止强缓存，循环检查多次
    for attempt in range(1, 6):
        time.sleep(10)
        try:
            page.goto(f"{BASE_URL}/server?id={server_id}&_t={int(time.time())}", timeout=30000)
            time.sleep(3) 
        except:
            continue

        info_after = page.evaluate("""() => {
            var m = (document.body.innerText || '').match(/Expiry[^:]*:\\s*([^\\n]+)/i);
            return m ? m[1].trim() : null;
        }""") or expiry_before
        
        minutes_after = parse_expiry_minutes(info_after)
        log.info(f"第 {attempt} 次比对：前[{expiry_before}] -> 后[{info_after}]")
        
        if minutes_after > 0 and (minutes_after > minutes_before or minutes_before <= 0):
            log.info(f"✅ 续期成功！时长已增加。")
            return True

    log.warning(f"⚠️ 续期后 expiry 未增加（{expiry_before} → {info_after}）。")
    return False

# ---------- 主流程 ----------
def main():
    from cloakbrowser import launch

    if not SERVER_ID:
        log.error("❌ 未配置 ZAMPTO_SERVER_ID 环境变量")
        return

    # 这里按你原来的代理设置
    PROXY_SERVER = "socks5://127.0.0.1:1080" 

    browser = launch(headless=False, humanize=True, proxy=PROXY_SERVER, geoip=True)
    page = browser.new_page()

    try:
        if not login(page):
            wxpush("❌ Zampto 登录失败")
            return

        info = get_server_info(page, SERVER_ID)
        status = info.get("status", "Unknown")
        expiry = info.get("expiry", "未知")
        
        log.info(f"📊 初始状态: {status} | 初始到期: {expiry}")

        if SKIP_RENEW:
            renewed = False
        else:
            renewed = renew_server(page, SERVER_ID, expiry_before=expiry)

        # 获取最终状态
        info2 = get_server_info(page, SERVER_ID)
        new_expiry = info2.get("expiry") or expiry

        started = False
        if "stopped" in status.lower() or "offline" in status.lower():
            log.info("🔴 服务器处于离线状态，尝试启动...")
            started = start_server(page)
            status = "Running" if started else "Start Failed"

        # 生成报告
        lines = ["🖥️ **Zampto 自动续期日报**"]
        lines.append(f"服务器 ID: `{SERVER_ID}`")
        status_icon = "🟢" if "running" in status.lower() else "🔴"
        lines.append(f"状态: {status_icon} {status}")
        lines.append(f"Expiry: `{new_expiry}`")
        
        if renewed:
            lines.append("  → 已自动续期成功 ✅")
        elif not SKIP_RENEW:
            lines.append("  ⚠️ 续期动作执行完毕，但时间未增加 (请检查是否达上限或CF被拦截)")

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
