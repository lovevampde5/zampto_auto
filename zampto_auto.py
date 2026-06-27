import os, re, logging, random, json, time, requests
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

USERNAME  = os.environ["ZAMPTO_USERNAME"]
PASSWORD  = os.environ["ZAMPTO_PASSWORD"]
SERVER_ID = os.environ.get("ZAMPTO_SERVER_ID", "")
WXPUSHER_TOKEN = os.environ.get("WXPUSHER_TOKEN", "")
WXPUSHER_UID   = os.environ.get("WXPUSHER_UID", "")
SKIP_RENEW     = os.environ.get("SKIP_RENEW", "false").lower() == "true"
TG_BOT_TOKEN   = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID     = os.environ.get("TG_CHAT_ID", "")
BASE_URL    = "https://dash.zampto.net"
AUTH_URL    = "https://auth.zampto.net"
SCREENSHOT_DIR = Path("./screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

def wxpush(content: str):
    if not WXPUSHER_TOKEN or not WXPUSHER_UID:
        log.warning("📨 WXPUSHER_TOKEN 或 WXPUSHER_UID 未配置，跳过推送")
        return
    import urllib.request
    payload = json.dumps({"appToken": WXPUSHER_TOKEN, "content": content, "contentType": 1, "uids": [WXPUSHER_UID]}).encode()
    try:
        req = urllib.request.Request("https://wxpusher.zjiecode.com/api/send/message", data=payload, headers={"Content-Type": "application/json"}, method="POST")
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
    payload = json.dumps({"chat_id": TG_CHAT_ID, "text": content, "parse_mode": "Markdown"}).encode("utf-8")
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                log.info("🚀 Telegram 通知发送成功！")
            else:
                log.warning(f"❌ Telegram 推送返回错误: {result}")
    except Exception as e:
        log.warning(f"❌ Telegram 推送异常: {e}")

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
    if m: total += int(m.group(1)) * 24 * 60
    m = re.search(r'(\d+)\s*h', expiry_str, re.I)
    if m: total += int(m.group(1)) * 60
    m = re.search(r'(\d+)\s*m(?:in)?', expiry_str, re.I)
    if m: total += int(m.group(1))
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
                        if (f.parentElement.parentElement)
                            f.parentElement.parentElement.style.setProperty('display', 'none', 'important');
                    }
                    count++;
                }
            });
            document.querySelectorAll('div[style*="position: fixed"], div[style*="position:fixed"]').forEach(function(ov) {
                if (!ov.offsetParent && ov.style.display === 'none') return;
                var z = parseInt(window.getComputedStyle(ov).zIndex) || 0;
                if (z >= 9000 && !ov.id.includes('renew') && !ov.id.includes('modal')) {
                    ov.style.setProperty('display', 'none', 'important'); count++;
                }
            });
            document.querySelectorAll('ins.adsbygoogle').forEach(function(ins) {
                ins.style.setProperty('display', 'none', 'important'); count++;
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
            var ariaClose = document.querySelector('button[aria-label="Close"], button[aria-label="close"], [aria-label="Dismiss"], button[aria-label="CLOSE"]');
            if (ariaClose && ariaClose.offsetParent !== null) { ariaClose.click(); count++; }
            var gdprTexts = ['Nicht einwilligen', 'Decline', 'Reject', 'Do not consent'];
            for (var gt of gdprTexts) {
                var gb = Array.from(document.querySelectorAll('button')).find(b => b.innerText.trim() === gt);
                if (gb && gb.offsetParent !== null) { gb.click(); count++; break; }
            }
            var cpClose = document.querySelector('.close-button-protector, .dismiss-button, .dismiss-button-protector, [class*="continue-prompt"] button, [class*="close-button-protector"]');
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
            var selectors = ['[class*="modal"]:not([id*="renew"]):not([style*="display: none"])','[class*="popup"]:not([style*="display: none"])','[class*="vignette"]:not([style*="display: none"])'];
            for (var s of selectors) { var el = document.querySelector(s); if (el && el.offsetParent !== null) return true; }
            var iframes = document.querySelectorAll('iframe');
            for (var f of iframes) { if ((f.id && f.id.includes('google_vignette')) && f.style.display !== 'none') return true; }
            return false;
        }""")
        if not has_popup: break
        if not closed_any: break
        time.sleep(0.8)

# ---------- 改进的 Cloudflare Turnstile 处理 ----------
def handle_cf_turnstile_improved(page, timeout=90) -> bool:
    """
    改进的 Turnstile 处理：
    1. 等待 iframe 出现（最多 10s），若无则视为无需验证。
    2. 若出现，尝试多种方式点击复选框，并等待 iframe 消失（验证完成）。
    3. 增加模拟鼠标移动和点击，提高通过率。
    """
    cf_selector = "iframe[src*='challenges.cloudflare.com']"
    # 等待 iframe 出现
    try:
        page.wait_for_selector(cf_selector, timeout=10000)
        log.info("🔄 检测到 Cloudflare Turnstile iframe")
    except:
        log.info("✅ 未检测到 Cloudflare Turnstile，跳过")
        return True

    # 尝试点击复选框
    for attempt in range(3):
        log.info(f"  [Turnstile 尝试 {attempt+1}] 点击复选框...")
        try:
            # 方法1: frame_locator 定位
            frame = page.frame_locator(cf_selector)
            checkbox = frame.locator('[role="checkbox"], .challenge, .checkbox, input[type="checkbox"]').first
            if checkbox.count() > 0:
                # 模拟鼠标悬停
                box = checkbox.bounding_box()
                if box:
                    page.mouse.move(box['x'] + box['width']/2, box['y'] + box['height']/2)
                    time.sleep(0.5)
                checkbox.click(timeout=5000)
                log.info("  已点击复选框，等待验证...")
            else:
                # 方法2: 点击 iframe 左上角区域
                iframe = page.locator(cf_selector).first
                box = iframe.bounding_box()
                if box:
                    page.mouse.move(box['x'] + 20, box['y'] + 20)
                    time.sleep(0.3)
                    page.mouse.click(box['x'] + 20, box['y'] + 20)
                    log.info("  已点击 iframe 左上角")
        except Exception as e:
            log.warning(f"  点击失败: {e}")

        # 等待验证完成（iframe 消失）
        deadline = time.time() + timeout
        while time.time() < deadline:
            if page.locator(cf_selector).count() == 0:
                log.info("✅ Cloudflare Turnstile 验证通过")
                return True
            time.sleep(2)
        log.warning(f"  Turnstile 未在 {timeout}s 内消失，继续尝试")
        # 刷新页面重试？不刷新，以免丢失状态，只是重试点击
        if attempt < 2:
            time.sleep(3)

    # 如果所有尝试都失败，尝试暴力刷新页面并重新加载（可能触发新的验证）
    log.warning("⚠️ Turnstile 未能自动通过，尝试刷新页面重试...")
    page.reload()
    time.sleep(5)
    # 递归调用自身一次（限制避免无限）
    return handle_cf_turnstile_improved(page, timeout=60)

# ---------- 改进的续期主函数 ----------
def renew_server(page, server_id: str, expiry_before: str) -> bool:
    """
    改进的续期流程：
    1. 导航到服务器详情页。
    2. 找到并点击 "Renew Server" 按钮（支持多种文本和定位方式）。
    3. 处理 Cloudflare Turnstile（如果出现）。
    4. 处理续期确认模态框。
    5. 捕获并重放续期 API 请求（若捕获到）。
    6. 轮询检查到期时间是否增加。
    7. 若标准流程失败，尝试直接调用 API（从页面提取 token）。
    """
    server_url = f"{BASE_URL}/server?id={server_id}"
    all_requests = []
    all_responses = []
    captured_renew_reqs = []

    def log_req(request):
        url = request.url; method = request.method
        log.info(f"📤 REQ: {method} {url}")
        all_requests.append((method, url))
        if any(kw in url.lower() for kw in ["renew", "extend", "refresh", "subscription"]) and method in ("GET", "POST", "PUT", "PATCH"):
            post_data = None
            try: post_data = request.post_data
            except: pass
            if post_data:
                log.info(f"    POST数据: {post_data[:300]}")
            entry = {"method": method, "url": url, "post_data": post_data}
            captured_renew_reqs.append(entry)
            log.info(f"🎯 捕获到疑似续期请求: {method} {url}")

    def log_resp(response):
        url = response.url; status = response.status
        log.info(f"📥 RESP: {status} {url}")
        all_responses.append((status, url))
        try:
            if "application/json" in response.headers.get("content-type", ""):
                body = response.json()
                log.info(f"    响应JSON: {json.dumps(body, ensure_ascii=False)[:300]}")
        except: pass

    page.on("request", log_req)
    page.on("response", log_resp)

    # 辅助：从页面提取 CSRF 和 Auth Token
    def get_tokens_from_page():
        csrf = page.evaluate("""() => {
            var m = document.querySelector('meta[name="csrf-token"]');
            if (m) return m.content;
            var inp = document.querySelector('input[name="_token"], input[name="csrf"]');
            if (inp) return inp.value;
            return null;
        }""")
        auth = page.evaluate("""() => {
            try {
                return localStorage.getItem('token') || localStorage.getItem('auth_token') ||
                       localStorage.getItem('access_token') || sessionStorage.getItem('token') || null;
            } catch(e) { return null; }
        }""")
        return csrf, auth

    # 辅助：构建 API 会话
    def build_api_session():
        cookies = page.context.cookies()
        session = requests.Session()
        for cookie in cookies:
            session.cookies.set(cookie['name'], cookie['value'])
        csrf, auth = get_tokens_from_page()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": server_url,
            "Origin": BASE_URL,
        }
        if csrf:
            headers["X-CSRF-Token"] = csrf
            headers["CSRF-Token"] = csrf
        if auth:
            headers["Authorization"] = f"Bearer {auth}"
        return session, headers

    # 辅助：检查到期时间是否增加
    def check_expiry_increased():
        try:
            # 重新加载详情页获取最新 expiry
            page.goto(server_url, timeout=20000, wait_until="domcontentloaded")
            time.sleep(3)
            dismiss_all_popups(page)
            info = page.evaluate("""() => {
                var body = document.body.innerText || '';
                var m = body.match(/Expiry[^:]*:\\s*([^\\n]+)/i);
                return m ? m[1].trim() : null;
            }""")
            if info is None:
                return False
            log.info(f"  当前 expiry: {info}（续期前: {expiry_before}）")
            if not expiry_before or expiry_before in ("未知", "Unknown", ""):
                return info != "未知"  # 只要非空且非未知就视为成功
            return parse_expiry_minutes(info) > parse_expiry_minutes(expiry_before)
        except Exception as e:
            log.warning(f"检查到期时间异常: {e}")
            return False

    # 辅助：点击模态框确认按钮
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
            # 回退：Tab + Enter
            try:
                page.keyboard.press("Tab")
                time.sleep(0.5)
                page.keyboard.press("Enter")
                log.info("  回退：Tab + Enter 确认")
                return True
            except:
                return False

    # ---------- 主流程 ----------
    # 尝试最多 3 次完整续期流程
    for attempt in range(1, 4):
        log.info(f"🔄 续期尝试 {attempt}/3")
        # 导航到详情页
        try:
            page.goto(server_url, timeout=30000, wait_until="domcontentloaded")
        except:
            log.warning("导航超时，重试")
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
        cf_ok = handle_cf_turnstile_improved(page, timeout=60)
        log.info(f"  CF Turnstile 处理结果: {cf_ok}")

        # 3. 处理模态框
        time.sleep(2)
        modal_confirmed = False
        if page.locator('#renewModal, [role="dialog"], .modal:not([style*="display: none"])').count() > 0:
            log.info("检测到模态框，尝试确认...")
            modal_confirmed = click_modal_confirm()
            take_screenshot(page, f"renew_modal_after_confirm_{attempt}")
        else:
            log.info("未检测到模态框，可能直接触发续期或按钮未响应")

        # 4. 等待网络请求完成（捕获续期请求）
        log.info("等待 15 秒捕获网络请求...")
        time.sleep(15)

        # 5. 尝试重放捕获的续期请求
        if captured_renew_reqs:
            log.info(f"🎯 捕获到 {len(captured_renew_reqs)} 个续期请求，尝试重放...")
            session, headers = build_api_session()
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
                            for body in [{"serverId": server_id}, {"id": server_id}, {"server_id": server_id}]:
                                resp = session.request(method, url, json=body, headers=headers, timeout=15)
                                if resp.status_code in (200, 201, 204):
                                    break
                    else:
                        continue
                    log.info(f"    重放响应: {resp.status_code} {resp.text[:200]}")
                    if resp.status_code in (200, 201, 204):
                        time.sleep(5)
                        if check_expiry_increased():
                            log.info(f"✅ 重放请求 {idx+1} 成功续期")
                            page.remove_listener("request", log_req)
                            page.remove_listener("response", log_resp)
                            return True
                except Exception as e:
                    log.warning(f"    重放异常: {e}")

        # 6. 检查到期时间是否已增加（也许直接成功了）
        if check_expiry_increased():
            log.info("✅ 续期成功（到期时间已增加）")
            page.remove_listener("request", log_req)
            page.remove_listener("response", log_resp)
            return True

        # 7. 如果未成功，尝试直接调用 API（不依赖捕获）
        log.info("尝试直接调用续期 API...")
        session, headers = build_api_session()
        # 尝试多个可能的 API 路径
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
                        if check_expiry_increased():
                            log.info(f"✅ 直接 API 调用成功: {path}")
                            page.remove_listener("request", log_req)
                            page.remove_listener("response", log_resp)
                            return True
                except Exception as e:
                    log.warning(f"  API 调用异常: {e}")

        # 如果仍未成功，记录失败并继续下一次尝试
        log.warning(f"第 {attempt} 次续期尝试失败")
        take_screenshot(page, f"renew_fail_{attempt}")

    # 所有尝试失败
    log.error("❌ 所有续期方法均失败。")
    # 输出捕获的请求供诊断
    log.info("===== 捕获的请求 =====")
    for meth, url in all_requests:
        log.info(f"  {meth} {url}")
    log.info("===== 捕获的响应 =====")
    for status, url in all_responses:
        log.info(f"  {status} {url}")
    page.remove_listener("request", log_req)
    page.remove_listener("response", log_resp)
    return False

# ---------- 其他函数保持不变，仅保留改进的 renew_server ----------
def login(page, max_retries=3) -> bool:
    # 与原代码相同，略作优化（为保持完整性，保留原实现）
    def get_login_url() -> str:
        try:
            page.goto(BASE_URL, timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)
            href = page.evaluate("""() => {
                var links = Array.from(document.querySelectorAll('a[href*="auth.zampto.net"], a[href*="sign-in"], a[href*="login"]'));
                for (var l of links) { if (l.href && l.href.includes('auth.zampto.net')) return l.href; }
                return null;
            }""")
            if href:
                log.info(f"动态获取到登录链接: {href}")
                return href
        except Exception as e:
            log.warning(f"动态获取登录链接失败: {e}")
        return f"{AUTH_URL}/sign-in"

    login_url = get_login_url()
    log.info(f"使用登录 URL: {login_url}")
    for attempt in range(1, max_retries + 1):
        log.info(f"登录 {attempt}/{max_retries}")
        try:
            page.goto(login_url, timeout=30000, wait_until="domcontentloaded")
        except Exception as e:
            log.warning(f"goto 异常: {e}")
        try:
            page.wait_for_selector('input[name="identifier"], input[autocomplete="username email"], input[type="email"], input[type="text"]', timeout=15000)
        except:
            log.warning("找不到用户名输入框，重试")
            take_screenshot(page, f"login_no_input_{attempt}")
            time.sleep(2)
            continue
        try:
            user_el = page.locator('input[name="identifier"], input[type="email"]').first
            user_el.click(); user_el.fill("")
            user_el.type(USERNAME, delay=random.randint(60, 130))
            log.info("已填写用户名")
        except Exception as e:
            log.warning(f"填写用户名失败: {e}"); continue
        human_delay()
        try:
            page.locator('button[name="submit"], button[type="submit"]').first.click()
            log.info("已点击登录按钮（第一步）")
        except Exception as e:
            log.warning(f"点击登录失败: {e}"); continue
        try:
            page.wait_for_selector('input[name="password"], input[autocomplete="current-password"], input[type="password"]', timeout=15000)
            log.info("已进入密码输入页")
        except:
            log.warning("未出现密码输入框，重试")
            take_screenshot(page, f"login_no_password_{attempt}"); continue
        try:
            pass_el = page.locator('input[name="password"], input[type="password"]').first
            pass_el.click(); pass_el.fill("")
            pass_el.type(PASSWORD, delay=random.randint(60, 130))
            log.info("已填写密码")
        except Exception as e:
            log.warning(f"填写密码失败: {e}"); continue
        human_delay()
        try:
            page.locator('button[name="submit"], button[type="submit"]').first.click()
            log.info("已点击继续按钮（第二步）")
        except Exception as e:
            log.warning(f"点击继续失败: {e}"); continue
        if wait_for_url_contains(page, "dash.zampto.net", 20):
            log.info("✅ 登录成功")
            take_screenshot(page, "01_login_success")
            return True
        time.sleep(3)
        if "dash.zampto.net" in page.url or "zampto.net/server" in page.url:
            log.info("✅ 登录成功")
            take_screenshot(page, "01_login_success")
            return True
        log.warning("登录后未跳转，请检查账号密码")
        take_screenshot(page, f"login_fail_{attempt}")
        time.sleep(2)
    return False

def get_server_info(page, server_id: str) -> dict:
    server_url = f"{BASE_URL}/server?id={server_id}"
    log.info("访问服务器详情页")
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
    log.info("访问 Console 页读取运行状态")
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
    log.info(f"服务器信息: expiry={info.get('expiry')}, status={info.get('status')}")
    return info

def start_server(page) -> bool:
    # 与原代码相同，保留
    console_url = f"{BASE_URL}/server-console?id={SERVER_ID}"
    MAX_START_ATTEMPTS = 3
    final_status = "Unknown"
    for attempt in range(1, MAX_START_ATTEMPTS + 1):
        log.info(f"导航到 Console 页（第 {attempt}/{MAX_START_ATTEMPTS} 次）")
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
                    log.info("Start 按钮不可见，页面已显示 Running")
                else:
                    log.warning(f"Start 按钮不可见且状态不是 Running，跳过")
                    continue
        except Exception as e:
            log.warning(f"点击 Start 失败（第 {attempt} 次）: {e}"); continue
        log.info("⏳ 等待服务器变为 Running（最多 5 分钟）...")
        elapsed = 0
        offline_streak = 0
        while elapsed < 300:
            time.sleep(10); elapsed += 10
            try:
                page.reload(timeout=20000, wait_until="domcontentloaded")
                time.sleep(4); dismiss_all_popups(page); time.sleep(1)
                body = get_text(page)
                if "Running" in body:
                    final_status = "Running"; offline_streak = 0
                    log.info(f"✅ 服务器已变为 Running（等待了 {elapsed}s）")
                    take_screenshot(page, f"05_running_confirmed_attempt{attempt}"); break
                elif "Starting" in body:
                    final_status = "Starting"; offline_streak = 0
                    log.info(f"  [{elapsed}s] 还在 Starting，继续等待...")
                elif "Offline" in body or "Stopped" in body:
                    offline_streak += 1
                    log.info(f"  [{elapsed}s] 读到 Offline（连续第 {offline_streak} 次）")
                    if offline_streak >= 3:
                        final_status = "Offline"
                        take_screenshot(page, f"05_start_failed_attempt{attempt}_{elapsed}s"); break
                else:
                    offline_streak = 0; log.info(f"  [{elapsed}s] 状态未知，继续等待...")
            except Exception as e:
                log.warning(f"  [{elapsed}s] 刷新异常: {e}")
        else:
            log.warning(f"⚠️ 第 {attempt} 次等待超时，最后状态: {final_status}")
            take_screenshot(page, f"05_start_timeout_attempt{attempt}")
        if final_status == "Running": break
        if attempt < MAX_START_ATTEMPTS:
            log.info(f"⏳ 第 {attempt} 次失败，5s 后重试..."); time.sleep(5)
    if final_status != "Running":
        return False
    addr_raw = None
    try:
        addr_raw = page.evaluate("""() => {
            var body = document.body.innerText || '';
            var m = body.match(/node\\d+\\.zampto\\.net:\\d+/i);
            return m ? m[0] : null;
        }""")
    except:
        pass
    if addr_raw:
        parts = addr_raw.rsplit(":", 1)
        if len(parts) == 2:
            host, port_str = parts[0], parts[1]
            try:
                port = int(port_str)
                if wait_for_port(host, port, max_wait=120, interval=10):
                    log.info("✅ TCP 端口验证通过")
                    take_screenshot(page, "06_port_verified"); return True
                log.warning("⚠️ 端口不可达，尝试 Restart...")
                take_screenshot(page, "06_port_unreachable_before_restart")
                restarted = False
                try:
                    restart_btn = page.locator('button:has-text("Restart")').first
                    if restart_btn.is_visible(timeout=5000):
                        restart_btn.click(); log.info("🔄 已点击 Restart"); time.sleep(5)
                        take_screenshot(page, "07_after_restart"); restarted = True
                    else:
                        log.warning("Restart 按钮不可见")
                except Exception as e:
                    log.warning(f"点击 Restart 失败: {e}")
                if not restarted: return False
                elapsed2 = 0; running_again = False
                while elapsed2 < 300:
                    time.sleep(10); elapsed2 += 10
                    try:
                        page.reload(timeout=20000, wait_until="domcontentloaded")
                        time.sleep(3); dismiss_all_popups(page); time.sleep(1)
                        body2 = get_text(page)
                        if "Running" in body2:
                            log.info(f"✅ Restart 后面板已变为 Running（等待了 {elapsed2}s）")
                            take_screenshot(page, "08_restart_running"); running_again = True; break
                        elif "Starting" in body2:
                            log.info(f"  [{elapsed2}s] 还在 Starting...")
                        elif "Offline" in body2 or "Stopped" in body2:
                            log.warning(f"  [{elapsed2}s] Restart 后回到 Offline，放弃"); break
                    except Exception as e:
                        log.warning(f"  [{elapsed2}s] 刷新异常: {e}")
                if not running_again:
                    log.warning("⚠️ Restart 后未能恢复 Running")
                    take_screenshot(page, "08_restart_failed"); return False
                if wait_for_port(host, port, max_wait=120, interval=10):
                    log.info("✅ Restart 后端口验证通过")
                    take_screenshot(page, "09_port_verified_after_restart"); return True
                log.warning("⚠️ Restart 后端口仍不可达")
                take_screenshot(page, "09_port_still_unreachable"); return False
            except ValueError:
                pass
    else:
        log.warning("⚠️ 未能从页面读取服务器地址，跳过端口验证")
    return True

def main():
    from cloakbrowser import launch
    if not SERVER_ID:
        log.error("❌ 未配置 ZAMPTO_SERVER_ID 环境变量")
        wxpush("❌ 未配置 ZAMPTO_SERVER_ID，任务中止")
        tgpush("❌ 未配置 `ZAMPTO_SERVER_ID`，任务中止")
        return
    PROXY_SERVER = "socks5://127.0.0.1:1080"
    log.info("启动 CloakBrowser...")
    browser = launch(headless=False, humanize=True, proxy=PROXY_SERVER, geoip=True)
    page = browser.new_page()
    try:
        if not login(page):
            msg_fail = "❌ Zampto 登录失败，请检查账号密码"
            wxpush(msg_fail); tgpush(msg_fail); return
        dismiss_all_popups(page)
        info = get_server_info(page, SERVER_ID)
        status     = info.get("status", "Unknown")
        expiry     = info.get("expiry", "未知")
        last_renew = info.get("lastRenewed", "未知")
        log.info(f"服务器状态: {status} | 到期: {expiry}")
        if SKIP_RENEW:
            log.info("⏭️ SKIP_RENEW=true，跳过续期步骤"); renewed = False
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
                status = "Running"; log.info("✅ 服务器已确认 Running")
            else:
                status = "Start Failed / Timeout"; log.warning("⚠️ 服务器启动失败或超时")
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
        wxpush(msg); tgpush(msg)
    except Exception as e:
        log.exception(e)
        take_screenshot(page, "99_error")
        err_msg = f"❌ Zampto 任务异常: {e}"
        wxpush(err_msg); tgpush(err_msg)
    finally:
        time.sleep(3); browser.close(); log.info("任务结束")

if __name__ == "__main__":
    main()
