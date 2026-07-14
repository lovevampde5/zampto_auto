import os, logging, random, time, json
from pathlib import Path
from datetime import datetime

# ---------- 基础配置 ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# 获取环境变量
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

# ---------- 通知工具 ----------
def notify(content: str):
    log.info(f"推送消息: {content}")
    # WxPusher
    if WXPUSHER_TOKEN and WXPUSHER_UID:
        import urllib.request
        try:
            data = json.dumps({"appToken": WXPUSHER_TOKEN, "content": content, "contentType": 1, "uids": [WXPUSHER_UID]}).encode()
            req = urllib.request.Request("https://wxpusher.zjiecode.com/api/send/message", data=data, headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=10)
        except Exception as e: log.warning(f"WxPusher 失败: {e}")
    # Telegram
    if TG_BOT_TOKEN and TG_CHAT_ID:
        import urllib.request
        try:
            data = json.dumps({"chat_id": TG_CHAT_ID, "text": content, "parse_mode": "Markdown"}).encode("utf-8")
            req = urllib.request.Request(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", data=data, headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=10)
        except Exception as e: log.warning(f"TG 失败: {e}")

# ---------- 核心辅助 ----------
def take_screenshot(page, name):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = str(SCREENSHOT_DIR / f"{ts}_{name}.png")
    page.screenshot(path=path)
    log.info(f"📸 截图已保存: {path}")

def dismiss_popups(page):
    try:
        page.evaluate("""() => {
            document.querySelectorAll('button').forEach(btn => {
                if (['×', 'Close', 'Dismiss'].some(t => btn.innerText.includes(t))) btn.click();
            });
        }""")
    except: pass

# ---------- 登录逻辑 ----------
def login(page, max_retries=3) -> bool:
    login_url = f"{BASE_URL}/auth/login"
    
    for attempt in range(1, max_retries + 1):
        log.info(f"登录第 {attempt} 次尝试...")
        try:
            page.goto(login_url, wait_until="networkidle")
            # 等待输入框出现
            page.wait_for_selector('input[type="text"], input[type="email"], input[name*="user"]', timeout=10000)
            
            # 填写账号密码
            page.fill('input[name*="user"], input[type="email"], input[type="text"]', USERNAME)
            page.fill('input[type="password"]', PASSWORD)
            
            # 点击登录按钮
            # 尝试通过不同选择器定位按钮
            login_btn = page.locator('button[type="submit"], button:has-text("Login"), button:has-text("Sign In")').first
            login_btn.click()
            
            # 等待结果
            time.sleep(5)
            
            # 检查是否成功
            if "login" not in page.url and "auth" not in page.url:
                log.info("✅ 登录成功跳转")
                return True
            
            # 如果没成功，检查页面错误提示
            page_text = page.inner_text("body")
            # 简易错误检测
            error_keywords = ["invalid", "incorrect", "wrong", "fail", "error", "验证"]
            if any(key in page_text.lower() for key in error_keywords):
                log.warning(f"⚠️ 登录失败，页面提示: {page_text[:100].replace(chr(10), ' ')}")
            else:
                log.warning("⚠️ 未检测到跳转，且无明确报错，可能被反爬拦截")
            
            take_screenshot(page, f"login_fail_{attempt}")
            
        except Exception as e:
            log.error(f"登录步骤异常: {e}")
            
    return False

# ---------- 业务逻辑 ----------
def main():
    from cloakbrowser import launch
    browser = launch(headless=False, proxy="socks5://127.0.0.1:1080", geoip=True)
    page = browser.new_page()
    
    try:
        if not login(page):
            notify("❌ Zampto 自动任务：登录失败，请检查截图")
            return
        
        # 登录后跳转到服务器页面
        page.goto(f"{BASE_URL}/server?id={SERVER_ID}", wait_until="networkidle")
        dismiss_popups(page)
        
        # 获取信息 (根据实际页面调整选择器)
        info = page.inner_text("body")
        log.info("✅ 已进入服务器详情页")
        
        # 续期逻辑
        if not SKIP_RENEW:
            renew_btn = page.locator('button:has-text("Renew")').first
            if renew_btn.is_visible():
                renew_btn.click()
                log.info("🚀 已点击续期按钮")
                time.sleep(3)
                notify("✅ Zampto 续期任务执行成功")
            else:
                notify("⚠️ 未找到续期按钮，可能无需续期")
        else:
            notify("ℹ️ 已跳过续期")
            
    except Exception as e:
        log.exception(e)
        notify(f"❌ 任务出错: {str(e)[:50]}")
    finally:
        browser.close()

if __name__ == "__main__":
    main()
