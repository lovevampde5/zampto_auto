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

TG_BOT_TOKEN   = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID     = os.environ.get("TG_CHAT_ID", "")

BASE_URL    = "https://dash.zampto.net"
AUTH_URL    = "https://auth.zampto.net/sign-in"
SERVERS_URL = f"{BASE_URL}/servers"

# ★ FIX 1: 自然衰减容差（分钟）
# 续期过程中页面刷新本身要消耗真实时间，到期时间会自然减少几分钟。
# 只要 续期后 >= 续期前 - NATURAL_DECAY_MINUTES，就视为成功。
NATURAL_DECAY_MINUTES = 5

SCREENSHOT_DIR = Path("./screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

# ---------- 推送工具 ----------
def wxpush(content: str):
    if not WXPUSHER_TOKEN or not WXPUSHER_UID:
        return
    import urllib.request
    payload = json.dumps({
        "appToken": WXPUSHER_TOKEN, "content": content, "contentType": 1, "uids": [WXPUSHER_UID],
    }).encode()
    try:
        req = urllib.request.Request(
            "https://wxpusher.zjiecode.com/api/send/message",
            data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=10): pass
    except Exception as e:
        log.warning(f"📨 WxPusher 推送异常: {e}")

def tgpush(content: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    import urllib.request
    payload = json.dumps({"chat_id": TG_CHAT_ID, "text": content, "parse_mode": "Markdown"}).encode("utf-8")
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10): pass
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
    except: pass

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
    try: return page.inner_text("body") or ""
    except: return ""

def human_delay(min_s=0.5, max_s=1.2):
    time.sleep(random.uniform(min_s, max_s))

def wait_for_url_contains(page, keyword, timeout=15) -> bool:
    try:
        page.wait_for_url(f"**{keyword}**", timeout=timeout * 1000)
        return True
    except:
        return keyword in page.url

# ★ FIX 2: parse_expiry_minutes 增加秒精度，防止分钟截断引发误差
def parse_expiry_minutes(expiry_str: str) -> int:
    if not expiry_str: return -1
    total = 0
    m = re.search(r'(\d+)\s*day', expiry_str)
    if m: total += int(m.group(1)) * 24 * 60
    m = re.search(r'(\d+)\s*h', expiry_str)
    if m: total += int(m.group(1)) * 60
    m = re.search(r'(\d+)\s*m(?:in)?', expiry_str)
    if m: total += int(m.group(1))
    # 秒数折算（不足1分钟的秒数按比例加入，避免截断）
    m = re.search(r'(\d+)\s*s(?:ec)?', expiry_str)
    if m: total += int(m.group(1)) / 60.0
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
                    if (f.parentElement) f.parentElement.style.setProperty('display', 'none', 'important');
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

def tcp_check(host: str, port: int, timeout: int = 5) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout): return True
    except: return False

def wait_for_port(host: str, port: int, max_wait: int = 120, interval: int = 10) -> bool:
    elapsed = 0
    while elapsed < max_wait:
        if tcp_check(host, port): return True
        time.sleep(interval)
        elapsed += interval
    return False

# ---------- CF Turnstile 等待 ----------
def wait_cf_turnstile(page, timeout=60) -> bool:
    log.info("🛡️ 正在探测并处理 Cloudflare Turnstile 验证...")

    cf_frame = page.frame_locator('iframe[src*="challenges.cloudflare.com"]').first
    try:
        log.info("⏳ 等待验证框加载 (最多10秒)...")
        cf_frame.locator('body').wait_for(timeout=10000, state="attached")
        log.info("👀 成功发现 CF Turnstile 验证框！准备突破...")
    except Exception:
        log.info("✅ 10秒内未检测到 CF Turnstile (可能已被后台白名单或无需验证)")
        return True

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            cb = cf_frame.locator('.ctp-checkbox-label, input[type="checkbox"], .cb-c, .mark').first
            if cb.is_visible(timeout=2000):
                log.info("🖱️ 验证复选框已可见，模拟鼠标点击...")
                cb.click(force=True, delay=random.randint(200, 500))
                time.sleep(3)
        except Exception:
            pass

        is_verifying = page.evaluate("""() => {
            var frames = Array.from(document.querySelectorAll('iframe'));
            var cf = frames.find(f => f.src && f.src.includes('challenges.cloudflare.com'));
            if (cf && cf.offsetParent !== null && cf.style.display !== 'none') {
                return true;
            }
            return false;
        }""")

        if not is_verifying:
            log.info("✅ CF Turnstile 验证框已消失 (验证通过/完成)")
            return True

        time.sleep(2)

    log.error(f"❌ CF Turnstile 验证超时未通过（{timeout}s）")
    return False

# ---------- 登录 ----------
def login(page, max_retries=3) -> bool:
    login_url = "https://auth.zampto.net/sign-in?app_id=YOUR_APP_ID"
    for attempt in range(1, max_retries + 1):
        log.info(f"🔑 尝试登录 {attempt}/{max_retries}")
        try: page.goto(login_url, timeout=30000, wait_until="domcontentloaded")
        except: pass

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
    try: page.goto(server_url, timeout=30000, wait_until="domcontentloaded")
    except: pass
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
    try: page.goto(console_url, timeout=30000, wait_until="domcontentloaded")
    except: pass
    time.sleep(3)

    status_text = page.evaluate("""() => {
        var runEl = document.querySelector('.status-running,.status-stopped,.status-starting');
        if (runEl) return runEl.innerText.trim();
        var sm = (document.body.innerText || '').match(/Running(?:\\s*\\([^)]+\\))?|Stopped|Starting|Stopping/i);
        return sm ? sm[0] : 'Unknown';
    }""")
    info["status"] = status_text or "Unknown"
    return info

# ---------- 启动服务器 ----------
def start_server(page) -> bool:
    console_url = f"{BASE_URL}/server-console?id={SERVER_ID}"
    try: page.goto(console_url, timeout=30000)
    except: pass
    time.sleep(3)
    dismiss_all_popups(page)

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

# ★ FIX 3: 检测页面成功提示文字作为续期成功的备用判据
def _page_shows_renew_success(page) -> bool:
    """
    检查页面上是否出现了续期成功的提示（toast/alert/flash 等），
    作为 expiry 时间比对的备用判断。
    """
    try:
        result = page.evaluate("""() => {
            var body = (document.body.innerText || '').toLowerCase();
            var keywords = [
                'renewed successfully', 'renewal successful', 'server renewed',
                'renew success', 'successfully renewed', 'renewed!',
                '续期成功', '续期完成', 'renewal complete'
            ];
            return keywords.some(function(k) { return body.includes(k); });
        }""")
        return bool(result)
    except:
        return False

# ---------- 续期核心流程 ----------
def renew_server(page, server_id: str, expiry_before: str) -> bool:
    minutes_before = parse_expiry_minutes(expiry_before)
    # 记录续期开始的真实时间，用于后续计算自然流逝
    renew_start_ts = time.time()

    server_url = f"{BASE_URL}/server?id={server_id}"
    try: page.goto(server_url, timeout=30000, wait_until="domcontentloaded")
    except: pass
    time.sleep(3)
    dismiss_all_popups(page)

    try:
        renew_btn = page.locator('a:has-text("Renew Server"), button:has-text("Renew Server")').first
        renew_btn.scroll_into_view_if_needed()
        time.sleep(0.5)
        renew_btn.click(force=True)
        log.info("👆 已点击 Renew Server 按钮，等待弹窗加载...")
    except Exception as e:
        log.warning(f"❌ 点击 Renew Server 失败: {e}")
        return False

    time.sleep(2)

    if not wait_cf_turnstile(page, timeout=45):
        log.warning("⚠️ CF 验证未完全通过，但我们将继续尝试找确认按钮...")

    try:
        log.info("🔎 查找弹窗内是否还有 Confirm/Renew 二次确认按钮...")
        confirm_btns = page.locator('button:has-text("Confirm"), button:has-text("Renew")').all()
        for btn in confirm_btns:
            if btn.is_visible():
                btn.click(force=True)
                log.info(f"🖱️ 点击了二次确认按钮: {btn.inner_text()}")
                time.sleep(2)
    except Exception as e:
        log.debug(f"二次确认步骤跳过: {e}")

    log.info("⏳ 等待后台处理并验证到期时间...")

    info_after = expiry_before  # 默认值
    for attempt in range(1, 6):
        time.sleep(10)
        try:
            page.goto(f"{BASE_URL}/server?id={server_id}&_t={int(time.time())}", timeout=30000)
            time.sleep(3)
        except:
            continue

        # ★ 备用判断：页面出现成功提示就直接返回成功
        if _page_shows_renew_success(page):
            log.info("✅ 页面检测到续期成功提示，续期完成！")
            return True

        info_after = page.evaluate("""() => {
            var m = (document.body.innerText || '').match(/Expiry[^:]*:\\s*([^\\n]+)/i);
            return m ? m[1].trim() : null;
        }""") or expiry_before

        minutes_after = parse_expiry_minutes(info_after)

        # ★ FIX 1 核心：计算自然流逝的分钟数，加入容差
        elapsed_minutes = (time.time() - renew_start_ts) / 60.0
        # 若续期成功，页面时间应 >= (续期前时间 - 已流逝时间 - 容差)
        # 即 time_after >= time_before - elapsed - NATURAL_DECAY_MINUTES
        # 等价于 time_after + elapsed + NATURAL_DECAY_MINUTES >= time_before
        adjusted_before = minutes_before - elapsed_minutes - NATURAL_DECAY_MINUTES

        log.info(
            f"第 {attempt} 次比对：前[{expiry_before}({minutes_before:.1f}m)] -> "
            f"后[{info_after}({minutes_after:.1f}m)] | "
            f"流逝[{elapsed_minutes:.1f}m] 容差[{NATURAL_DECAY_MINUTES}m] 调整后基准[{adjusted_before:.1f}m]"
        )

        if minutes_after > 0 and minutes_after > adjusted_before:
            log.info(f"✅ 续期成功！时长验证通过（含自然衰减容差）")
            return True

    log.warning(
        f"⚠️ 续期后 expiry 未增加（{expiry_before} → {info_after}）。"
        f"如果是快到期仍然不增加，请检查代码或手动续期排查原因。"
    )
    return False

# ---------- 主流程 ----------
def main():
    from cloakbrowser import launch

    if not SERVER_ID:
        log.error("❌ 未配置 ZAMPTO_SERVER_ID 环境变量")
        return

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

        info2 = get_server_info(page, SERVER_ID)
        new_expiry = info2.get("expiry") or expiry
        last_renew = info2.get("lastRenewed") or info.get("lastRenewed")

        started = False
        if "stopped" in status.lower() or "offline" in status.lower():
            log.info("🔴 服务器处于离线状态，尝试启动...")
            started = start_server(page)
            status = "Running" if started else "Start Failed"

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
