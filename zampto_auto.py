import os, re, logging, random, json, time
from pathlib import Path
from datetime import datetime

# ---------- 配置 ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

USERNAME  = os.environ.get("ZAMPTO_USERNAME", "")
PASSWORD  = os.environ.get("ZAMPTO_PASSWORD", "")
SERVER_ID = os.environ.get("ZAMPTO_SERVER_ID", "")
SKIP_RENEW = os.environ.get("SKIP_RENEW", "false").lower() == "true"
WXPUSHER_TOKEN = os.environ.get("WXPUSHER_TOKEN", "")
WXPUSHER_UID   = os.environ.get("WXPUSHER_UID", "")
TG_BOT_TOKEN   = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID     = os.environ.get("TG_CHAT_ID", "")

BASE_URL    = "https://dash.zampto.net"
SCREENSHOT_DIR = Path("./screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

# ---------- 通知函数 ----------
def wxpush(content: str):
    if not WXPUSHER_TOKEN or not WXPUSHER_UID: return
    import urllib.request
    try:
        payload = json.dumps({"appToken": WXPUSHER_TOKEN, "content": content, "contentType": 1, "uids": [WXPUSHER_UID]}).encode()
        req = urllib.request.Request("https://wxpusher.zjiecode.com/api/send/message", data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp: log.info("📨 WxPusher 推送成功")
    except Exception as e: log.warning(f"WxPusher 推送异常: {e}")

def tgpush(content: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID: return
    import urllib.request
    try:
        payload = json.dumps({"chat_id": TG_CHAT_ID, "text": content, "parse_mode": "Markdown"}).encode("utf-8")
        req = urllib.request.Request(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp: log.info("🚀 Telegram 推送成功")
    except Exception as e: log.warning(f"Telegram 推送异常: {e}")

# ---------- 核心工具函数 ----------
def take_screenshot(page, name):
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        page.screenshot(path=str(SCREENSHOT_DIR / f"{ts}_{name}.png"), full_page=False)
        log.info(f"📸 截图: {ts}_{name}.png")
    except: pass

def get_text(page) -> str:
    try: return page.inner_text("body") or ""
    except: return ""

def dismiss_all_popups(page):
    # 强大的弹窗 JS 注入清理
    page.evaluate("""() => {
        document.querySelectorAll('iframe, div[style*="fixed"], ins').forEach(el => {
            if (el.style) el.style.display = 'none';
        });
        document.querySelectorAll('button, a, [role="button"]').forEach(el => {
            const txt = (el.innerText||'').toLowerCase();
            if (txt.includes('close') || txt.includes('×') || txt.includes('dismiss')) el.click();
        });
    }""")

# ---------- 登录函数 (已合并 Enter 键触发 + NetworkIdle) ----------
def login(page, max_retries=3) -> bool:
    login_url = "https://dash.zampto.net/auth/login"
    user_sel = 'input[name="identifier"], input[name="username"], input[name="email"], input[type="email"]'
    pass_sel = 'input[name="password"], input[type="password"]'

    for attempt in range(1, max_retries + 1):
        log.info(f"登录 {attempt}/{max_retries} - 导航至 {login_url}")
        try:
            page.goto(login_url, timeout=30000, wait_until="networkidle")
            page.wait_for_selector(user_sel, timeout=15000)
            
            # 填入数据
            page.locator(user_sel).first.fill(USERNAME)
            pass_el = page.locator(pass_sel).first
            pass_el.fill(PASSWORD)
            
            log.info("模拟按下回车键提交登录...")
            pass_el.press("Enter")
            
            # 检查跳转
            for _ in range(20):
                time.sleep(1)
                if "zampto.net" in page.url and "login" not in page.url and "sign-in" not in page.url:
                    log.info("✅ 登录成功")
                    return True
                
                # 检查报错
                body_text = get_text(page).lower()
                if any(err in body_text for err in ["invalid", "wrong", "error"]):
                    log.warning("⚠️ 登录页面提示错误")
                    break
            
            take_screenshot(page, f"login_fail_{attempt}")
        except Exception as e:
            log.warning(f"登录过程异常: {e}")
            
    return False

# ---------- 服务器操作逻辑 ----------
def get_server_info(page, server_id: str) -> dict:
    page.goto(f"{BASE_URL}/server?id={server_id}", wait_until="networkidle")
    time.sleep(3)
    dismiss_all_popups(page)
    return page.evaluate("""() => {
        const body = document.body.innerText;
        return {
            expiry: body.match(/Expiry[^:]*:\\s*([^\\n]+)/i)?.[1].trim() || '未知',
            status: body.includes('Running') ? 'Running' : (body.includes('Stopped') ? 'Stopped' : 'Unknown')
        };
    }""")

def renew_server(page, server_id: str) -> bool:
    page.goto(f"{BASE_URL}/server?id={server_id}", wait_until="networkidle")
    time.sleep(3)
    dismiss_all_popups(page)
    try:
        btn = page.locator('button:has-text("Renew"), a:has-text("Renew")').first
        if btn.is_visible():
            btn.click()
            time.sleep(5)
            log.info("✅ 已点击续期")
            return True
    except Exception as e: log.warning(f"续期失败: {e}")
    return False

# ---------- 主逻辑 ----------
def main():
    from cloakbrowser import launch
    # 注意：确保 proxy 设置正确，或者如果本地网络可直连则移除 proxy 参数
    browser = launch(headless=False, proxy="socks5://127.0.0.1:1080", geoip=True)
    page = browser.new_page()

    try:
        if not login(page):
            msg = "❌ Zampto 登录失败"
            wxpush(msg); tgpush(msg)
            return

        info = get_server_info(page, SERVER_ID)
        log.info(f"服务器状态: {info.get('status')} | 到期时间: {info.get('expiry')}")

        if not SKIP_RENEW:
            renew_server(page, SERVER_ID)

        msg = f"✅ Zampto 任务执行完毕\n状态: {info.get('status')}\n到期时间: {info.get('expiry')}"
        wxpush(msg)
        tgpush(msg)

    except Exception as e:
        log.exception(e)
        take_screenshot(page, "error")
    finally:
        browser.close()
        log.info("任务结束")

if __name__ == "__main__":
    main()
