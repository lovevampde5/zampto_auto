#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zampto 自动续期脚本（深度改进版 v2）
- 修复 strict mode violation（使用 .first 或具体 id）
- reCAPTCHA 使用 force 点击，避免 scroll 错误
- Turnstile 检测更稳健，支持多个 token input
- 续期流程增加更多等待和备选操作
"""

import os
import re
import logging
import random
import json
import time
import requests
import urllib.request
import socket
from pathlib import Path
from datetime import datetime

from cloakbrowser import launch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# ---------- 环境变量 ----------
USERNAME  = os.environ.get("ZAMPTO_USERNAME", "")
PASSWORD  = os.environ.get("ZAMPTO_PASSWORD", "")
SERVER_ID = os.environ.get("ZAMPTO_SERVER_ID", "")

WXPUSHER_TOKEN = os.environ.get("WXPUSHER_TOKEN", "")
WXPUSHER_UID   = os.environ.get("WXPUSHER_UID", "")
SKIP_RENEW     = os.environ.get("SKIP_RENEW", "false").lower() == "true"

TG_BOT_TOKEN   = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID     = os.environ.get("TG_CHAT_ID", "")

RENEW_RETRY_TIMES = int(os.environ.get("RENEW_RETRY_TIMES", "3"))
RENEW_RETRY_INTERVAL = int(os.environ.get("RENEW_RETRY_INTERVAL", "300"))

BASE_URL    = "https://dash.zampto.net"
SCREENSHOT_DIR = Path("./screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

PROXY_SERVER = "socks5://127.0.0.1:1080"

# ---------- 推送函数 ----------
def wxpush(content: str):
    if not WXPUSHER_TOKEN or not WXPUSHER_UID:
        log.warning("WXPUSHER_TOKEN 或 WXPUSHER_UID 未配置，跳过推送")
        return
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

def tcp_check(host: str, port: int, timeout: int = 5) -> bool:
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

# ---------- 安全的弹窗清理 ----------
def dismiss_safe_popups(page):
    log.debug("执行安全弹窗清理...")
    page.evaluate("""() => {
        document.querySelectorAll(
            'iframe[id*="google_vignette"], iframe[name*="google_vignette"], ' +
            'ins.adsbygoogle, div[class*="ad-container"], div[class*="vignette"]'
        ).forEach(el => el.style.display = 'none');
    }""")
    # 点击关闭按钮，但排除续期模态框
    close_btns = page.locator(
        'button[aria-label="Close"], button:has-text("×"), button:has-text("Close"), ' +
        'button[aria-label="close"], button:has-text("Schließen")'
    )
    for btn in close_btns.all():
        try:
            parent = btn.evaluate_handle("el => el.closest('[class*=\"renew\"], [id*=\"renew\"], [class*=\"modal\"], [id*=\"modal\"]')")
            if parent is None:
                if btn.is_visible():
                    btn.click(force=True)
                    log.debug("点击了广告关闭按钮")
                    time.sleep(0.5)
        except:
            pass
    gdpr_texts = ['Nicht einwilligen', 'Decline', 'Reject', 'Do not consent']
    for text in gdpr_texts:
        try:
            btn = page.locator(f'button:has-text("{text}")').first
            if btn.is_visible():
                btn.click(force=True)
                log.debug("点击了 GDPR 拒绝按钮")
                time.sleep(0.5)
        except:
            pass

# ---------- 修复的 Turnstile 处理 ----------
def handle_turnstile(page, timeout=60):
    """处理 Cloudflare Turnstile，修复 strict mode 冲突"""
    log.info("处理 Cloudflare Turnstile 验证...")
    selectors = [
        "iframe[src*='challenges.cloudflare.com']",
        "iframe[src*='turnstile']",
        "div[data-sitekey]",
        "div[id^='cf-turnstile']",
        "div[class*='turnstile']",
        "div[id*='turnstile']"
    ]
    found = False
    for sel in selectors:
        if page.locator(sel).count() > 0:
            found = True
            break
    if not found:
        log.warning("未检测到 Turnstile 元素，跳过")
        return True

    # 尝试点击 iframe 复选框
    try:
        iframe_sel = "iframe[src*='challenges.cloudflare.com']"
        if page.locator(iframe_sel).count() > 0:
            frame = page.frame_locator(iframe_sel).first
            checkbox = frame.locator('[role="checkbox"], .challenge-checkbox, input[type="checkbox"]').first
            if checkbox.count() > 0:
                checkbox.click(timeout=5000)
                log.info("已点击 Turnstile 复选框")
                time.sleep(3)
    except Exception as e:
        log.debug(f"点击 iframe 复选框失败: {e}")

    # 尝试点击 div
    try:
        div_sel = "div[data-sitekey], div[id^='cf-turnstile']"
        if page.locator(div_sel).count() > 0:
            page.locator(div_sel).first.click(force=True)
            log.info("已点击 Turnstile div 区域")
            time.sleep(3)
    except Exception as e:
        log.debug(f"点击 div 区域失败: {e}")

    # 等待验证消失或 token 出现（修复定位冲突）
    start = time.time()
    while time.time() - start < timeout:
        still_exists = False
        for sel in selectors:
            if page.locator(sel).count() > 0:
                still_exists = True
                break
        if not still_exists:
            log.info("Turnstile 验证通过（元素消失）")
            return True

        # 检查 token 输入框（使用 first 避免 strict mode）
        try:
            # 使用更具体的 id 优先
            token_input = page.locator('#renewTurnstileResponse, #cf-chl-widget-*_response').first
            if token_input.count() > 0 and token_input.get_attribute("value"):
                log.info("检测到 Turnstile token，验证通过")
                return True
        except:
            pass
        # 备选：通过 name 属性取第一个
        try:
            token_input = page.locator('input[name="cf-turnstile-response"]').first
            if token_input.count() > 0 and token_input.get_attribute("value"):
                log.info("检测到 Turnstile token（via first），验证通过")
                return True
        except:
            pass

        time.sleep(1)

    log.error("Turnstile 验证超时")
    take_screenshot(page, "turnstile_timeout")
    return False

# ---------- 修复的 reCAPTCHA 处理 ----------
def handle_recaptcha(page):
    try:
        recaptcha_iframe = page.locator('iframe[src*="recaptcha/api2/aframe"]')
        if recaptcha_iframe.count() == 0:
            return
        log.info("检测到 Google reCAPTCHA，尝试点击...")
        try:
            frame = page.frame_locator('iframe[src*="recaptcha/api2/aframe"]').first
            checkbox = frame.locator('.recaptcha-checkbox-border, .recaptcha-checkbox-checkmark, #recaptcha-anchor').first
            if checkbox.count() > 0:
                # 使用 force 避免 scroll into view 错误
                checkbox.click(force=True, timeout=5000)
                log.info("已点击 reCAPTCHA")
                time.sleep(5)
                return
        except:
            pass
        # 点击 iframe 本身
        recaptcha_iframe.first.click(force=True)
        log.info("点击 reCAPTCHA iframe")
        time.sleep(5)
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
    dismiss_safe_popups(page)
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
    dismiss_safe_popups(page)
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
        dismiss_safe_popups(page)
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
                dismiss_safe_popups(page)
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

# ---------- 检查 expiry 是否更新 ----------
def check_expiry_updated(page, old_expiry_str) -> bool:
    new_expiry = page.evaluate("""() => {
        var body = document.body.innerText || '';
        var m = body.match(/Expiry[^:]*:\\s*([^\\n]+)/i);
        return m ? m[1].trim() : null;
    }""")
    if new_expiry:
        old_min = parse_expiry_minutes(old_expiry_str)
        new_min = parse_expiry_minutes(new_expiry)
        if new_min > old_min:
            log.info(f"Expiry 已更新: {old_expiry_str} -> {new_expiry}")
            return True
        else:
            log.debug(f"Expiry 未变化: {new_expiry}")
    return False

# ---------- 核心续期函数（增强容错） ----------
def renew_server(page, server_id: str, expiry_before: str) -> bool:
    server_url = f"{BASE_URL}/server?id={server_id}"
    api_captured = {}
    def on_request(request):
        if request.method == "POST" and "renew" in request.url.lower():
            api_captured["url"] = request.url
            api_captured["headers"] = request.headers
            api_captured["post_data"] = request.post_data
            log.info(f"捕获到续期 API: {request.url}")
    page.on("request", on_request)

    for attempt in range(1, 4):
        log.info(f"续期尝试 {attempt}/3")
        try:
            page.goto(server_url, timeout=30000, wait_until="domcontentloaded")
        except:
            pass
        time.sleep(3)
        dismiss_safe_popups(page)
        time.sleep(1)

        # 点击 Renew Server
        try:
            clicked = page.evaluate("""() => {
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
            if clicked:
                log.info("已点击 Renew Server (JS)")
            else:
                btn = page.locator('a:has-text("Renew Server"), button:has-text("Renew Server")').first
                if btn.count() > 0:
                    btn.scroll_into_view_if_needed()
                    btn.click(force=True)
                    log.info("已点击 Renew Server (locator)")
                else:
                    log.warning("无法定位 Renew Server 按钮")
                    continue
        except Exception as e:
            log.warning(f"点击 Renew Server 失败: {e}")
            continue

        # 等待确认弹窗（但若未出现也不强求）
        try:
            page.wait_for_selector(
                '.modal:has-text("Renew"), .dialog:has-text("Confirm"), ' +
                'button:has-text("Confirm"), button:has-text("Yes"), ' +
                'button:has-text("确认")',
                timeout=8000
            )
            log.info("检测到续期确认弹窗")
            # 点击确认按钮
            confirm_clicked = False
            confirm_texts = ["Confirm", "Yes", "Renew", "确认", "确定"]
            for text in confirm_texts:
                try:
                    btn = page.locator(f'button:has-text("{text}")').first
                    if btn.is_visible():
                        btn.click(force=True)
                        log.info(f"点击确认按钮: {text}")
                        confirm_clicked = True
                        break
                except:
                    pass
            if not confirm_clicked:
                page.keyboard.press("Enter")
                log.info("按 Enter 键确认")
        except:
            log.warning("未出现续期确认弹窗，可能直接进入验证或已续期")

        # 处理验证码
        handle_recaptcha(page)
        turnstile_ok = handle_turnstile(page, timeout=40)

        # 等待并刷新检查
        time.sleep(5)
        page.reload(wait_until="domcontentloaded")
        time.sleep(3)
        if check_expiry_updated(page, expiry_before):
            log.info("续期成功！")
            return True

        # 若未成功，尝试直接点击“Renew Server”再次触发（可能未生效）
        if attempt < 3:
            log.info("续期未生效，再次尝试点击 Renew Server")
            continue

    # 备选 API 调用
    if api_captured:
        log.info("尝试使用捕获的 API 直接续期")
        try:
            session = requests.Session()
            cookies = page.context.cookies()
            for c in cookies:
                session.cookies.set(c['name'], c['value'])
            headers = api_captured.get("headers", {})
            headers["Content-Type"] = "application/json"
            data = api_captured.get("post_data")
            resp = session.post(
                api_captured["url"],
                headers=headers,
                data=data if data else "",
                timeout=10
            )
            if resp.status_code == 200:
                log.info(f"API 调用成功，状态码 {resp.status_code}")
                time.sleep(5)
                page.goto(server_url, wait_until="domcontentloaded")
                if check_expiry_updated(page, expiry_before):
                    log.info("API 续期成功")
                    return True
                else:
                    info_after = get_server_info(page, server_id)
                    if info_after.get("expiry"):
                        if parse_expiry_minutes(info_after.get("expiry")) > parse_expiry_minutes(expiry_before):
                            return True
            else:
                log.warning(f"API 调用返回非200: {resp.status_code}")
        except Exception as e:
            log.warning(f"API 调用异常: {e}")

    return False

# ---------- 主流程 ----------
def main():
    if not USERNAME or not PASSWORD:
        log.error("请设置 ZAMPTO_USERNAME 和 ZAMPTO_PASSWORD 环境变量")
        return

    if not SERVER_ID:
        log.error("未配置 ZAMPTO_SERVER_ID")
        wxpush("未配置 ZAMPTO_SERVER_ID，任务中止")
        tgpush("未配置 `ZAMPTO_SERVER_ID`，任务中止")
        return

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
            log.error(msg)
            wxpush(msg)
            tgpush(msg)
            return

        info = get_server_info(page, SERVER_ID)
        status = info.get("status", "Unknown")
        expiry = info.get("expiry", "未知")
        last_renew = info.get("lastRenewed", "未知")
        log.info(f"初始状态: {status} | 到期: {expiry}")

        if SKIP_RENEW:
            log.info("SKIP_RENEW=true，跳过续期")
            renewed = False
        else:
            renewed = False
            for retry in range(RENEW_RETRY_TIMES):
                log.info(f"=== 续期主循环 第 {retry+1}/{RENEW_RETRY_TIMES} 次 ===")
                if retry > 0:
                    if not login(page):
                        log.warning("重新登录失败，等待后重试")
                        time.sleep(60)
                        continue
                info_retry = get_server_info(page, SERVER_ID)
                expiry_current = info_retry.get("expiry", expiry)
                renewed = renew_server(page, SERVER_ID, expiry_current)
                if renewed:
                    log.info("续期成功，退出重试循环")
                    break
                else:
                    log.warning(f"续期失败，等待 {RENEW_RETRY_INTERVAL} 秒后重试")
                    time.sleep(RENEW_RETRY_INTERVAL)
            if not renewed:
                log.error("所有续期重试均失败")

        time.sleep(3)
        info_final = get_server_info(page, SERVER_ID)
        final_status = info_final.get("status", status)
        final_expiry = info_final.get("expiry", expiry)
        final_last_renew = info_final.get("lastRenewed", last_renew)

        started = False
        if "stopped" in final_status.lower() or "offline" in final_status.lower():
            log.info("服务器已停止，尝试启动...")
            started = start_server(page)
            if started:
                final_status = "Running"
            else:
                final_status = "Start Failed"

        lines = ["🖥️ **Zampto 服务器日报**"]
        lines.append(f"服务器 ID: `{SERVER_ID}`")
        lines.append("")
        status_icon = "🟢" if "running" in final_status.lower() else ("🟡" if "starting" in final_status.lower() else "🔴")
        lines.append(f"状态: {status_icon} {final_status}")
        if started:
            lines.append("  → 已启动 ✅")
        elif "failed" in final_status.lower():
            lines.append("  ⚠️ 启动失败，请手动处理")
        lines.append("")
        lines.append(f"Expiry: `{final_expiry}`")
        if final_last_renew:
            lines.append(f"Last Renewed: {final_last_renew}")
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
