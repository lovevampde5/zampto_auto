import os
import re
import logging
import random
import json
import time
import socket
import urllib.request
from pathlib import Path
from datetime import datetime

from cloakbrowser import launch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ---------- 环境变量 ----------
USERNAME = os.environ.get("ZAMPTO_USERNAME")
PASSWORD = os.environ.get("ZAMPTO_PASSWORD")
SERVER_ID = os.environ.get("ZAMPTO_SERVER_ID")
WXPUSHER_TOKEN = os.environ.get("WXPUSHER_TOKEN", "")
WXPUSHER_UID = os.environ.get("WXPUSHER_UID", "")
SKIP_RENEW = os.environ.get("SKIP_RENEW", "false").lower() == "true"
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

BASE_URL = "https://dash.zampto.net"
AUTH_URL = "https://auth.zampto.net"
SCREENSHOT_DIR = Path("./screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

# ---------- 推送函数（不变） ----------
def wxpush(content: str):
    if not WXPUSHER_TOKEN or not WXPUSHER_UID:
        log.warning("📨 WxPusher 未配置，跳过推送")
        return
    payload = json.dumps({"appToken": WXPUSHER_TOKEN, "content": content, "contentType": 1, "uids": [WXPUSHER_UID]}).encode()
    try:
        req = urllib.request.Request("https://wxpusher.zjiecode.com/api/send/message", data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            if json.loads(resp.read()).get("success"):
                log.info("📨 WxPusher 推送成功")
    except Exception as e:
        log.warning(f"📨 WxPusher 异常: {e}")

def tgpush(content: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        log.warning("🚀 Telegram 未配置，跳过推送")
        return
    payload = json.dumps({"chat_id": TG_CHAT_ID, "text": content, "parse_mode": "Markdown"}).encode("utf-8")
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            if json.loads(resp.read()).get("ok"):
                log.info("🚀 Telegram 通知成功")
    except Exception as e:
        log.warning(f"🚀 Telegram 异常: {e}")

# ---------- 辅助函数 ----------
def human_delay(min_s=0.3, max_s=0.8):
    time.sleep(random.uniform(min_s, max_s))

def take_screenshot(page, name):
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = str(SCREENSHOT_DIR / f"{ts}_{name}.png")
        page.screenshot(path=path, full_page=False)
        log.info(f"📸 截图: {path}")
    except Exception as e:
        log.warning(f"截图失败: {e}")

def get_text(page) -> str:
    try:
        return page.inner_text("body") or ""
    except:
        return ""

def tcp_check(host: str, port: int, timeout: int = 5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except:
        return False

def wait_for_port(host: str, port: int, max_wait: int = 60, interval: int = 5) -> bool:
    log.info(f"🔌 等待端口 {host}:{port} 可达（最多 {max_wait}s）")
    elapsed = 0
    while elapsed < max_wait:
        if tcp_check(host, port):
            log.info(f"✅ 端口已可达（耗时 {elapsed}s）")
            return True
        time.sleep(interval)
        elapsed += interval
        log.info(f"  [{elapsed}s] 端口未开")
    log.warning(f"⚠️ 端口等待超时")
    return False

def parse_expiry_minutes(expiry_str: str) -> int:
    if not expiry_str:
        return -1
    try:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
            try:
                dt = datetime.strptime(expiry_str.strip(), fmt)
                diff = (dt - datetime.now()).total_seconds() / 60
                return int(diff) if diff > 0 else -1
            except:
                continue
    except:
        pass
    total = 0
    m = re.search(r'(\d+)\s*day', expiry_str, re.I)
    if m:
        total += int(m.group(1)) * 24 * 60
    m = re.search(r'(\d+)\s*h', expiry_str, re.I)
    if m:
        total += int(m.group(1)) * 60
    m = re.search(r'(\d+)\s*m(?:in)?', expiry_str, re.I)
    if m:
        total += int(m.group(1))
    return total if total > 0 else -1

# ---------- 弹窗与验证处理（同前） ----------
def dismiss_all_popups(page):
    for _ in range(5):
        closed_any = False
        hidden = page.evaluate("""() => {
            let count = 0;
            document.querySelectorAll('iframe').forEach(f => {
                if ((f.id && (f.id.includes('google_vignette') || f.id.includes('aswift'))) ||
                    (f.name && f.name.includes('google_vignette'))) {
                    f.style.display = 'none';
                    if (f.parentElement) f.parentElement.style.display = 'none';
                    count++;
                }
            });
            document.querySelectorAll('ins.adsbygoogle').forEach(ins => {
                ins.style.display = 'none'; count++;
            });
            return count;
        }""")
        if hidden:
            log.info(f"  隐藏 {hidden} 个广告元素")
            closed_any = True
        closed = page.evaluate("""() => {
            let count = 0;
            const closeTexts = ['Close', 'close', '×', 'X', 'CLOSE', 'Schließen', 'Dismiss'];
            for (let t of closeTexts) {
                let btns = Array.from(document.querySelectorAll('button, a, [role="button"]'));
                for (let b of btns) {
                    if (b.innerText && b.innerText.trim() === t) {
                        let parent = b.closest('[class*="modal"],[class*="popup"],[class*="overlay"],[class*="dialog"],[class*="ad-"]');
                        if (parent && parent.offsetParent !== null) {
                            b.click(); count++; break;
                        }
                    }
                }
            }
            ['Nicht einwilligen', 'Decline', 'Reject'].forEach(t => {
                let b = Array.from(document.querySelectorAll('button')).find(el => el.innerText.trim() === t);
                if (b && b.offsetParent !== null) { b.click(); count++; }
            });
            document.querySelectorAll('.close-button-protector, .dismiss-button, .dismiss-button-protector').forEach(el => {
                if (el.offsetParent !== null) { el.click(); count++; }
            });
            return count;
        }""")
        if closed:
            log.info(f"  点击关闭 {closed} 个弹窗")
            closed_any = True
            time.sleep(0.8)
        if not closed_any:
            break

def handle_cf_turnstile(page, timeout=45):
    log.info("⏳ 处理 Cloudflare Turnstile...")
    cf_selector = "iframe[src*='challenges.cloudflare.com']"
    for _ in range(8):
        if page.locator(cf_selector).count() > 0:
            break
        time.sleep(0.5)
    else:
        log.info("✅ 未检测到 CF iframe，跳过")
        return True
    log.info("🔄 检测到 CF Turnstile，尝试点击复选框")
    try:
        frame = page.frame_locator(cf_selector)
        checkbox = frame.locator('[role="checkbox"], .challenge, .checkbox, input[type="checkbox"]').first
        if checkbox.count() > 0:
            checkbox.click(timeout=5000)
            for _ in range(20):
                time.sleep(1)
                if page.locator(cf_selector).count() == 0:
                    log.info("✅ CF 验证通过")
                    return True
    except Exception as e:
        log.warning(f"CF 点击失败: {e}")
    try:
        iframe = page.locator(cf_selector).first
        box = iframe.bounding_box()
        if box:
            page.mouse.click(box['x'] + box['width'] * 0.1, box['y'] + box['height'] * 0.1)
            time.sleep(5)
            if page.locator(cf_selector).count() == 0:
                log.info("✅ CF 验证通过（备用点击）")
                return True
    except:
        pass
    log.warning("⚠️ CF 验证未能确认，继续执行")
    return True

def handle_google_recaptcha(page):
    try:
        iframe = page.locator('iframe[src*="recaptcha/api2/aframe"]')
        if iframe.count() == 0:
            return
        log.info("⚠️ 检测到 reCAPTCHA，尝试点击")
        try:
            frame = page.frame_locator('iframe[src*="recaptcha/api2/aframe"]')
            frame.locator('.recaptcha-checkbox-border').click(timeout=5000)
            time.sleep(3)
        except:
            iframe.click(force=True)
            time.sleep(3)
    except Exception as e:
        log.warning(f"reCAPTCHA 处理异常: {e}")

# ================= 重点改进：登录函数 =================
def login(page, max_retries=5):
    """
    使用多种选择器和重试机制登录 Zampto
    """
    log.info("开始登录流程")

    # 定义用户名字段的选择器列表（按优先级排序）
    username_selectors = [
        'input[name="identifier"]',
        'input[autocomplete="username"]',
        'input[autocomplete="email"]',
        'input[type="email"]',
        'input[type="text"][name*="user" i]',
        'input[type="text"][name*="email" i]',
        'input[placeholder*="email" i]',
        'input[placeholder*="用户名" i]',
        'input[placeholder*="账号" i]',
        'input[id*="username" i]',
        'input[id*="email" i]',
        'input[aria-label*="username" i]',
        'input[aria-label*="email" i]',
        'input[aria-label*="用户名" i]',
        'input[aria-label*="账号" i]',
    ]

    password_selectors = [
        'input[name="password"]',
        'input[autocomplete="current-password"]',
        'input[type="password"]',
        'input[placeholder*="password" i]',
        'input[placeholder*="密码" i]',
        'input[id*="password" i]',
        'input[aria-label*="password" i]',
        'input[aria-label*="密码" i]',
    ]

    for attempt in range(1, max_retries + 1):
        log.info(f"登录尝试 {attempt}/{max_retries}")

        # 1. 进入登录页面（先访问 dash，再跳转）
        try:
            page.goto(BASE_URL, timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)
            # 尝试从页面动态获取登录链接
            login_url = page.evaluate("""() => {
                let links = Array.from(document.querySelectorAll('a[href*="auth.zampto.net"]'));
                for (let l of links) {
                    if (l.href && l.href.includes('auth.zampto.net')) return l.href;
                }
                return null;
            }""")
            if not login_url:
                login_url = f"{AUTH_URL}/sign-in"
            log.info(f"使用登录 URL: {login_url}")
            page.goto(login_url, timeout=30000, wait_until="domcontentloaded")
        except Exception as e:
            log.warning(f"导航到登录页失败: {e}")
            continue

        # 等待页面加载完成
        time.sleep(3)
        dismiss_all_popups(page)

        # 2. 查找用户名输入框
        username_input = None
        for sel in username_selectors:
            try:
                # 等待元素出现，最多 5 秒
                page.wait_for_selector(sel, timeout=5000)
                el = page.locator(sel).first
                if el.is_visible():
                    username_input = el
                    log.info(f"找到用户名输入框: {sel}")
                    break
            except:
                continue

        if not username_input:
            # 尝试点击“使用密码登录”或“切换登录方式”按钮
            try:
                switch_btn = page.locator('button:has-text("使用密码登录"), button:has-text("Sign in with password"), a:has-text("密码登录")').first
                if switch_btn.is_visible(timeout=2000):
                    switch_btn.click()
                    log.info("点击了切换登录方式按钮")
                    time.sleep(2)
                    # 再次查找
                    for sel in username_selectors:
                        try:
                            page.wait_for_selector(sel, timeout=3000)
                            el = page.locator(sel).first
                            if el.is_visible():
                                username_input = el
                                log.info(f"切换后找到用户名输入框: {sel}")
                                break
                        except:
                            continue
            except:
                pass

        if not username_input:
            log.warning("未找到用户名输入框，刷新页面重试")
            take_screenshot(page, f"login_no_username_{attempt}")
            time.sleep(2)
            continue

        # 3. 填写用户名
        try:
            username_input.click()
            username_input.fill("")
            username_input.type(USERNAME, delay=random.randint(60, 120))
            log.info("已填写用户名")
        except Exception as e:
            log.warning(f"填写用户名失败: {e}")
            continue

        human_delay()

        # 4. 点击“继续”或“下一步”按钮（可能有的登录流程是两步）
        try:
            submit_btn = page.locator('button[type="submit"], button:has-text("Continue"), button:has-text("下一步"), button:has-text("Next")').first
            if submit_btn.is_visible(timeout=3000):
                submit_btn.click()
                log.info("点击继续按钮（第一步）")
                time.sleep(2)
            else:
                # 有些登录是直接提交
                pass
        except:
            pass

        # 5. 等待密码输入框出现
        password_input = None
        for sel in password_selectors:
            try:
                page.wait_for_selector(sel, timeout=8000)
                el = page.locator(sel).first
                if el.is_visible():
                    password_input = el
                    log.info(f"找到密码输入框: {sel}")
                    break
            except:
                continue

        if not password_input:
            log.warning("未找到密码输入框，可能登录流程不同，尝试直接提交")
            take_screenshot(page, f"login_no_password_{attempt}")
            # 尝试直接点击提交（也许用户名密码在同一页）
            try:
                submit_btn = page.locator('button[type="submit"]').first
                if submit_btn.is_visible(timeout=2000):
                    submit_btn.click()
                    time.sleep(3)
            except:
                pass
            # 检查是否已登录
            if "dash.zampto.net" in page.url or page.locator('[class*="avatar"], [class*="user-menu"]').count() > 0:
                log.info("✅ 登录成功（无密码框但已跳转）")
                take_screenshot(page, "login_success")
                return True
            continue

        # 6. 填写密码
        try:
            password_input.click()
            password_input.fill("")
            password_input.type(PASSWORD, delay=random.randint(60, 120))
            log.info("已填写密码")
        except Exception as e:
            log.warning(f"填写密码失败: {e}")
            continue

        human_delay()

        # 7. 点击登录提交
        try:
            submit_btn = page.locator('button[type="submit"], button:has-text("Sign In"), button:has-text("登录"), button:has-text("Log in")').first
            if submit_btn.is_visible(timeout=3000):
                submit_btn.click()
                log.info("点击登录提交按钮")
            else:
                # 按 Enter 键
                page.keyboard.press("Enter")
                log.info("按 Enter 提交登录")
        except Exception as e:
            log.warning(f"提交登录失败: {e}")
            continue

        # 8. 等待跳转或检测登录成功
        time.sleep(5)
        # 检测是否跳转到 dash 或者有用户菜单
        if page.url.startswith(BASE_URL) or "dash.zampto.net" in page.url:
            log.info("✅ 登录成功（URL已跳转）")
            take_screenshot(page, "login_success")
            return True

        # 检查页面上是否有头像、用户名等元素
        try:
            if page.locator('[class*="avatar"], [class*="user-menu"], [class*="profile"]').count() > 0:
                log.info("✅ 登录成功（找到用户元素）")
                take_screenshot(page, "login_success")
                return True
        except:
            pass

        # 检查是否存在“重试”或错误提示，如果有则重新尝试
        error_text = get_text(page)
        if "invalid" in error_text.lower() or "wrong" in error_text.lower():
            log.warning("登录凭证错误，请检查用户名密码")
            take_screenshot(page, "login_credential_error")
            # 不继续重试，直接返回失败
            return False

        log.warning(f"第 {attempt} 次登录未跳转，继续重试")
        take_screenshot(page, f"login_no_redirect_{attempt}")
        time.sleep(2)

    log.error("❌ 登录失败，所有重试均未成功")
    return False

# ---------- 获取服务器信息（同前） ----------
def get_server_info(page, server_id):
    url = f"{BASE_URL}/server?id={server_id}"
    log.info("获取服务器信息...")
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    time.sleep(3)
    dismiss_all_popups(page)
    take_screenshot(page, "server_info")
    info = page.evaluate("""() => {
        let body = document.body.innerText || '';
        let expiry = body.match(/Expiry[^:]*:\\s*([^\\n]+)/i);
        let last = body.match(/last renewed[^:]*:\\s*([^\\n]+)/i);
        let addr = body.match(/node\\d+\\.zampto\\.net:\\d+/i);
        return {
            expiry: expiry ? expiry[1].trim() : null,
            lastRenewed: last ? last[1].trim() : null,
            address: addr ? addr[0] : null,
        };
    }""")
    console_url = f"{BASE_URL}/server-console?id={server_id}"
    page.goto(console_url, timeout=30000, wait_until="domcontentloaded")
    time.sleep(2)
    dismiss_all_popups(page)
    status = page.evaluate("""() => {
        let el = document.getElementById('serverStatus');
        if (el) return el.innerText.trim();
        let body = document.body.innerText || '';
        let m = body.match(/Running|Stopped|Starting|Offline/i);
        return m ? m[0] : 'Unknown';
    }""")
    info["status"] = status or "Unknown"
    log.info(f"服务器状态: {info['status']}, 到期: {info.get('expiry')}")
    return info

# ---------- 启动服务器（同前） ----------
def start_server(page):
    console_url = f"{BASE_URL}/server-console?id={SERVER_ID}"
    log.info("🔴 服务器未运行，尝试启动...")
    for attempt in range(1, 4):
        page.goto(console_url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(2)
        dismiss_all_popups(page)
        start_btn = page.locator('button:has-text("Start")').first
        if start_btn.is_visible(timeout=3000):
            start_btn.click()
            log.info(f"✅ 点击 Start（尝试 {attempt}）")
            time.sleep(3)
        else:
            if "Running" in get_text(page):
                log.info("服务器已 Running")
                return True
            log.warning("Start 按钮不可见，刷新重试")
            continue
        log.info("⏳ 等待服务器 Running（最多 3 分钟）...")
        for _ in range(18):
            time.sleep(10)
            page.reload(timeout=15000, wait_until="domcontentloaded")
            time.sleep(2)
            dismiss_all_popups(page)
            body = get_text(page)
            if "Running" in body:
                log.info("✅ 服务器已 Running")
                take_screenshot(page, f"started_attempt{attempt}")
                addr = page.evaluate("""() => {
                    let m = document.body.innerText.match(/node\\d+\\.zampto\\.net:\\d+/i);
                    return m ? m[0] : null;
                }""")
                if addr:
                    host, port = addr.rsplit(":", 1)
                    try:
                        port = int(port)
                        if wait_for_port(host, port, max_wait=30, interval=5):
                            log.info("✅ 端口验证通过")
                            return True
                        log.warning("⚠️ 端口不可达，但面板显示 Running，仍视为成功")
                        return True
                    except:
                        pass
                return True
            elif "Starting" in body:
                log.info(f"  [{_*10}s] Starting...")
            elif "Offline" in body or "Stopped" in body:
                log.warning(f"  [{_*10}s] 状态变为 Offline，可能启动失败")
                break
        log.warning(f"第 {attempt} 次启动超时")
    log.error("❌ 启动失败")
    return False

# ---------- 续期（深度改进，同前） ----------
def renew_server(page, server_id, expiry_before):
    log.info("🔄 开始续期流程")

    def force_refresh_info():
        page.goto(f"{BASE_URL}/server?id={server_id}", timeout=30000, wait_until="domcontentloaded")
        time.sleep(2)
        dismiss_all_popups(page)
        page.reload(timeout=20000, wait_until="domcontentloaded")
        time.sleep(2)
        expiry = page.evaluate("""() => {
            let m = document.body.innerText.match(/Expiry[^:]*:\\s*([^\\n]+)/i);
            return m ? m[1].trim() : null;
        }""")
        return expiry

    def check_expiry_increased():
        current = force_refresh_info()
        log.info(f"  当前 expiry: {current} (续期前: {expiry_before})")
        if current is None:
            return False
        if not expiry_before or expiry_before in ("未知", "Unknown", ""):
            return True
        return parse_expiry_minutes(current) > parse_expiry_minutes(expiry_before)

    def build_api_session():
        cookies = page.context.cookies()
        session = requests.Session()
        for c in cookies:
            session.cookies.set(c['name'], c['value'])
        csrf = page.evaluate("""() => {
            let m = document.querySelector('meta[name="csrf-token"]');
            if (m) return m.content;
            let inp = document.querySelector('input[name="_token"], input[name="csrf"]');
            return inp ? inp.value : null;
        }""")
        auth_token = page.evaluate("""() => {
            try {
                return localStorage.getItem('token') || localStorage.getItem('auth_token') ||
                       localStorage.getItem('access_token') || sessionStorage.getItem('token') || null;
            } catch(e) { return null; }
        }""")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{BASE_URL}/server?id={server_id}",
            "Origin": BASE_URL,
        }
        if csrf:
            headers["X-CSRF-Token"] = csrf
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        return session, headers

    def try_api_renew(session, headers, url, method="GET", data=None):
        try:
            if method.upper() == "GET":
                resp = session.get(url, headers=headers, timeout=10)
            else:
                resp = session.request(method, url, json=data, headers=headers, timeout=10)
            log.info(f"  API {method} {url} => {resp.status_code}")
            if resp.status_code in (200, 201, 204):
                time.sleep(3)
                if check_expiry_increased():
                    return True
            return False
        except Exception as e:
            log.warning(f"  API 调用异常: {e}")
            return False

    captured_renew_requests = []
    def intercept_request(request):
        url = request.url
        method = request.method
        if any(kw in url.lower() for kw in ["renew", "extend", "refresh", "subscription"]):
            log.info(f"🎯 捕获到疑似续期请求: {method} {url}")
            post_data = None
            try:
                post_data = request.post_data
            except:
                pass
            captured_renew_requests.append({
                "method": method,
                "url": url,
                "post_data": post_data,
                "headers": dict(request.headers),
            })
    page.on("request", intercept_request)

    log.info("【策略1】点击 Renew Server 按钮")
    server_url = f"{BASE_URL}/server?id={server_id}"
    for attempt in range(1, 5):
        log.info(f"  尝试 {attempt}/4")
        page.goto(server_url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(2)
        dismiss_all_popups(page)
        take_screenshot(page, f"renew_attempt_{attempt}")

        btn_clicked = False
        selectors = [
            'a:has-text("Renew Server")',
            'button:has-text("Renew Server")',
            'a:has-text("Renew")',
            'button:has-text("Renew")',
            'a:has-text("Extend")',
            'button:has-text("Extend")',
            'a[href*="renew"]',
            'button[data-action="renew"]',
            '[class*="renew"] a',
            '[class*="renew"] button',
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if el.count() and el.is_visible(timeout=1000):
                    el.scroll_into_view_if_needed()
                    el.click(force=True)
                    log.info(f"  通过选择器 {sel} 点击成功")
                    btn_clicked = True
                    break
            except:
                pass

        if not btn_clicked:
            btn_clicked = page.evaluate("""() => {
                let keywords = ['Renew Server', 'Renew', 'Extend', 'Renouveler', 'Verlängern'];
                let els = Array.from(document.querySelectorAll('a, button, [role="button"]'));
                for (let kw of keywords) {
                    for (let el of els) {
                        let txt = (el.innerText || el.textContent || '').trim();
                        if (txt === kw || txt.toLowerCase() === kw.toLowerCase()) {
                            if (el.offsetParent !== null && !el.disabled) {
                                el.scrollIntoView({block: 'center'});
                                el.click();
                                return true;
                            }
                        }
                    }
                }
                for (let el of els) {
                    let txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                    if ((txt.includes('renew') || txt.includes('extend')) && el.offsetParent !== null && !el.disabled) {
                        el.scrollIntoView({block: 'center'});
                        el.click();
                        return true;
                    }
                }
                return false;
            }""")
            if btn_clicked:
                log.info("  JS 点击按钮成功")

        if not btn_clicked:
            log.warning("  未找到续期按钮")
            continue

        handle_google_recaptcha(page)
        handle_cf_turnstile(page, timeout=30)
        time.sleep(2)

        modal_confirmed = False
        for _ in range(6):
            modal_exists = page.evaluate("""() => {
                let m = document.getElementById('renewModal') ||
                        document.querySelector('[role="dialog"]') ||
                        document.querySelector('[class*="modal"]:not([style*="display: none"])');
                return m && (m.offsetParent !== null || (m.style && m.style.display !== 'none'));
            }""")
            if modal_exists:
                log.info("  检测到模态框，尝试确认")
                take_screenshot(page, f"modal_attempt{attempt}")
                confirmed = page.evaluate("""() => {
                    let confirmTexts = ['Confirm', 'Yes', 'OK', 'Ok', 'Submit', 'Renew', 'Extend', 'Continue', 'Proceed'];
                    let btns = Array.from(document.querySelectorAll('button, a, input[type="submit"], input[type="button"]'));
                    for (let t of confirmTexts) {
                        for (let b of btns) {
                            let txt = (b.innerText || b.textContent || b.value || '').trim();
                            if (txt === t || txt.toLowerCase() === t.toLowerCase()) {
                                if (b.offsetParent !== null && !b.disabled) {
                                    b.click();
                                    return true;
                                }
                            }
                        }
                    }
                    for (let b of btns) {
                        let txt = (b.innerText || b.textContent || '').trim().toLowerCase();
                        if ((txt.includes('confirm') || txt.includes('renew') || txt.includes('extend')) && b.offsetParent !== null && !b.disabled) {
                            b.click();
                            return true;
                        }
                    }
                    return false;
                }""")
                if confirmed:
                    log.info("  ✅ 模态框确认按钮已点击")
                    modal_confirmed = True
                    break
                else:
                    try:
                        page.keyboard.press("Tab")
                        time.sleep(0.5)
                        page.keyboard.press("Enter")
                        log.info("  备用：Tab+Enter 确认")
                        modal_confirmed = True
                        break
                    except:
                        pass
                time.sleep(1)
            else:
                break

        log.info("  等待 10 秒捕获网络请求...")
        time.sleep(10)

        if check_expiry_increased():
            log.info("✅ 【策略1】续期成功")
            page.remove_listener("request", intercept_request)
            return True

        log.warning(f"  第 {attempt} 次点击后 expiry 未变化")

    if captured_renew_requests:
        log.info("【策略2】重放捕获到的续期请求")
        session, headers = build_api_session()
        for i, req in enumerate(captured_renew_requests):
            log.info(f"  重放 {i+1}: {req['method']} {req['url']}")
            hdrs = dict(headers)
            for k, v in req.get("headers", {}).items():
                if k.lower() not in ("host", "content-length", "content-encoding"):
                    hdrs[k] = v
            try:
                if req["method"] == "GET":
                    resp = session.get(req["url"], headers=hdrs, timeout=10)
                elif req["method"] in ("POST", "PUT", "PATCH"):
                    data = req.get("post_data")
                    if data:
                        resp = session.request(req["method"], req["url"], data=data, headers=hdrs, timeout=10)
                    else:
                        resp = session.request(req["method"], req["url"], json={"id": server_id}, headers=hdrs, timeout=10)
                else:
                    resp = session.get(req["url"], headers=hdrs, timeout=10)
                log.info(f"    响应: {resp.status_code} {resp.text[:100]}")
                if resp.status_code in (200, 201, 204):
                    time.sleep(3)
                    if check_expiry_increased():
                        log.info("✅ 【策略2】重放成功")
                        page.remove_listener("request", intercept_request)
                        return True
            except Exception as e:
                log.warning(f"    重放异常: {e}")

    log.info("【策略3】直接 API 探测")
    session, headers = build_api_session()
    html = page.content()
    api_paths = set()
    patterns = [
        r'["\'](/[^\'"]*(?:renew|extend|refresh|subscription)[^\'"]*)["\']',
        r'fetch\(["\']([^\'"]+)["\']',
        r'axios\.[a-z]+\(["\']([^\'"]+)["\']',
        r'url:\s*["\']([^\'"]*(?:renew|extend)[^\'"]*)["\']',
    ]
    for pat in patterns:
        for m in re.finditer(pat, html, re.I):
            path = m.group(1)
            if any(kw in path.lower() for kw in ["renew", "extend", "refresh"]):
                full = path if path.startswith("http") else f"{BASE_URL}{path}"
                api_paths.add(full)

    for path in [
        f"/server/renew?id={server_id}",
        f"/api/server/renew?id={server_id}",
        f"/api/v1/server/renew?id={server_id}",
        f"/api/v2/server/renew?id={server_id}",
        f"/server/extend?id={server_id}",
        f"/api/server/extend?id={server_id}",
        f"/api/servers/{server_id}/renew",
        f"/api/servers/{server_id}/extend",
    ]:
        api_paths.add(f"{BASE_URL}{path}")

    for url in api_paths:
        if try_api_renew(session, headers, url, "GET"):
            log.info("✅ 【策略3-GET】成功")
            page.remove_listener("request", intercept_request)
            return True
        for body in [{"serverId": server_id}, {"id": server_id}, {"server_id": server_id}]:
            if try_api_renew(session, headers, url, "POST", body):
                log.info("✅ 【策略3-POST】成功")
                page.remove_listener("request", intercept_request)
                return True

    log.info("【策略4】尝试控制台调用续期函数")
    page.goto(server_url, timeout=30000, wait_until="domcontentloaded")
    time.sleep(2)
    dismiss_all_popups(page)
    result = page.evaluate("""() => {
        if (window.renewServer) { window.renewServer(); return 'window.renewServer'; }
        if (window.extendServer) { window.extendServer(); return 'window.extendServer'; }
        if (window.renewVPS) { window.renewVPS(); return 'window.renewVPS'; }
        let app = document.querySelector('#app') || document.querySelector('[data-server-id]');
        if (app) {
            let vm = app.__vue__ || app._vei || (app.__vueParentComponent && app.__vueParentComponent.proxy);
            if (vm) {
                if (vm.renewServer) { vm.renewServer(); return 'vue.renewServer'; }
                if (vm.extendServer) { vm.extendServer(); return 'vue.extendServer'; }
                if (vm.handleRenew) { vm.handleRenew(); return 'vue.handleRenew'; }
            }
        }
        return null;
    }""")
    if result:
        log.info(f"  调用成功: {result}")
        time.sleep(5)
        if check_expiry_increased():
            log.info("✅ 【策略4】控制台调用成功")
            page.remove_listener("request", intercept_request)
            return True

    log.error("❌ 所有续期策略均失败")
    page.remove_listener("request", intercept_request)
    return False

# ---------- 主函数 ----------
def main():
    if not all([USERNAME, PASSWORD, SERVER_ID]):
        log.error("❌ 缺少必要环境变量: ZAMPTO_USERNAME, ZAMPTO_PASSWORD, ZAMPTO_SERVER_ID")
        wxpush("❌ 缺少环境变量，任务中止")
        tgpush("❌ 缺少环境变量，任务中止")
        return

    proxy = "socks5://127.0.0.1:1080" if os.environ.get("USE_PROXY", "false").lower() == "true" else None
    log.info("启动 CloakBrowser...")
    browser = launch(headless=False, humanize=True, proxy=proxy, geoip=True)
    page = browser.new_page()

    try:
        if not login(page):
            wxpush("❌ Zampto 登录失败")
            tgpush("❌ Zampto 登录失败")
            return

        dismiss_all_popups(page)
        info = get_server_info(page, SERVER_ID)
        status = info.get("status", "Unknown")
        expiry = info.get("expiry", "未知")
        last_renew = info.get("lastRenewed", "未知")

        log.info(f"初始状态: {status}, 到期: {expiry}")

        renewed = False
        if SKIP_RENEW:
            log.info("⏭️ SKIP_RENEW=true，跳过续期")
        else:
            renewed = renew_server(page, SERVER_ID, expiry)

        new_expiry = expiry
        if renewed:
            # 强制刷新获取新到期时间
            page.goto(f"{BASE_URL}/server?id={SERVER_ID}", timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)
            dismiss_all_popups(page)
            new_expiry = page.evaluate("""() => {
                let m = document.body.innerText.match(/Expiry[^:]*:\\s*([^\\n]+)/i);
                return m ? m[1].trim() : null;
            }""") or expiry
            log.info(f"续期后到期: {new_expiry}")
        else:
            log.warning("续期失败")

        started = False
        if "stopped" in status.lower() or "offline" in status.lower():
            log.info("🔴 服务器已停止，尝试启动...")
            started = start_server(page)
            if started:
                status = "Running"
            else:
                status = "Start Failed"

        lines = []
        if SKIP_RENEW:
            lines.append("🚨 **Zampto 紧急启动报告**")
        else:
            lines.append("🖥️ **Zampto 服务器日报**")
        lines.append(f"服务器 ID: `{SERVER_ID}`")
        lines.append("")
        status_icon = "🟢" if "running" in status.lower() else ("🟡" if "starting" in status.lower() else "🔴")
        lines.append(f"状态: {status_icon} {status}")
        if started:
            lines.append("  → 已启动 ✅")
        elif "stopped" in status.lower() or "offline" in status.lower():
            lines.append("  ⚠️ 启动失败，请手动处理")
        lines.append("")
        lines.append(f"Expiry: `{new_expiry}`")
        if last_renew:
            lines.append(f"Last Renewed: {last_renew}")
        if SKIP_RENEW:
            lines.append("  （续期已跳过）")
        elif renewed:
            lines.append("  → 自动续期成功 ✅")
        else:
            lines.append("  ⚠️ 续期失败，请手动检查")

        msg = "\n".join(lines)
        log.info(f"推送内容:\n{msg}")
        wxpush(msg)
        tgpush(msg)

    except Exception as e:
        log.exception(e)
        take_screenshot(page, "error")
        wxpush(f"❌ 任务异常: {e}")
        tgpush(f"❌ 任务异常: {e}")
    finally:
        time.sleep(2)
        browser.close()
        log.info("任务结束")

if __name__ == "__main__":
    main()
