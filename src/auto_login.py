"""自动登录模块 - Cookie失效时的备用方案"""
import os
import time
import hashlib
import json
import requests
from playwright.sync_api import sync_playwright


def get_login_credentials(index=None):
    """从环境变量获取登录凭据"""
    if index is None or index == 0:
        username = os.environ.get('ZAIMANHUA_USERNAME')
        password = os.environ.get('ZAIMANHUA_PASSWORD')
    else:
        username = os.environ.get(f'ZAIMANHUA_USERNAME_{index}')
        password = os.environ.get(f'ZAIMANHUA_PASSWORD_{index}')
    
    if not username or not password:
        return None, None
    return username, password


def get_all_login_credentials():
    """获取所有配置的登录凭据"""
    credentials_list = []
    
    username, password = get_login_credentials(None)
    if username and password:
        credentials_list.append(('默认账号', username, password))
    
    i = 1
    while True:
        username, password = get_login_credentials(i)
        if username and password:
            credentials_list.append((f'账号 {i}', username, password))
            i += 1
        else:
            break
    return credentials_list


def clear_browser_cache(page, context=None):
    """清除浏览器缓存，确保多账号切换时获取最新数据"""
    try:
        page.evaluate("""
            () => {
                localStorage.clear();
                sessionStorage.clear();
                if (caches && caches.keys) {
                    caches.keys().then(names => names.forEach(name => caches.delete(name)));
                }
            }
        """)
    except:
        pass

    if context:
        try:
            context.clear_cookies()
        except:
            pass


def mask_username(username):
    """部分打码用户名，保留前2个字符便于识别账号"""
    if not username:
        return "***"
    if len(username) <= 2:
        return username + "***"
    return username[:2] + "***"


def login_and_get_cookie(username, password, account_label=""):
    """使用API登录并获取Cookie"""
    label_prefix = f"[{account_label}] " if account_label else ""
    print(f"\n{label_prefix}=== 自动登录 ===")
    print(f"{label_prefix}  用户名: ***")

    try:
        pwd_md5 = hashlib.md5(password.encode()).hexdigest()

        data = {
            "username": username,
            "passwd": pwd_md5,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }

        print(f"{label_prefix}  发送登录请求...")
        resp = requests.post(
            "https://account-api.zaimanhua.com/v1/login/passwd",
            data=data,
            headers=headers,
            timeout=30,
        )

        if resp.status_code != 200:
            print(f"{label_prefix}  [x] 登录失败: HTTP {resp.status_code}")
            return None

        result = resp.json()
        log_data = {
            "errno": result.get("errno"),
            "errmsg": result.get("errmsg"),
            "data": {
                "user": {
                    "uid": "***",
                    "username": "***",
                    "nickname": "***",
                    "email": "***",
                    "bind_phone": "***",
                }
            }
        }
        print(f"{label_prefix}  响应: {json.dumps(log_data, ensure_ascii=False)}")

        if result.get("errno") != 0:
            errmsg = result.get("errmsg", "未知错误")
            print(f"{label_prefix}  [x] 登录失败: {errmsg}")
            return None

        user_data = result.get("data", {}).get("user", {})
        if not user_data:
            print(f"{label_prefix}  [x] 登录失败: 未获取到用户数据")
            return None

        uid = user_data.get("uid", "")
        nickname = user_data.get("nickname", "")
        bind_phone = user_data.get("bind_phone", "")
        token = user_data.get("token", "")

        if not token:
            print(f"{label_prefix}  [x] 登录失败: 未获取到token")
            return None

        phone_status = "已绑定" if bind_phone and str(bind_phone) not in ['0', '', 'None', 'False'] else "未绑定"
        print(f"{label_prefix}  登录成功! UID: ***, 昵称: {nickname}, 手机: {phone_status}")

        lginfo = {
            "uid": uid,
            "username": user_data.get("username", nickname),
            "nickname": nickname,
            "email": user_data.get("email", ""),
            "photo": user_data.get("photo", ""),
            "bind_phone": bind_phone,
            "sex": user_data.get("sex", 0),
            "token": token,
            "setPasswd": user_data.get("setPasswd", 1),
            "bindWechat": user_data.get("bindWechat", False),
            "bindQq": user_data.get("bindQq", False),
            "bindSina": user_data.get("bindSina", False),
            "status": user_data.get("status", 1),
            "is_sign": user_data.get("is_sign", False),
            "user_level": user_data.get("user_level", 0),
            "isInUserWhitelist": user_data.get("isInUserWhitelist", False),
        }

        from urllib.parse import quote
        lginfo_encoded = quote(json.dumps(lginfo, ensure_ascii=False))

        cookie_parts = [
            f"lginfo={lginfo_encoded}",
            f"token={token}",
        ]
        cookie_str = "; ".join(cookie_parts)

        print(f"{label_prefix}  验证Cookie有效性...")
        from utils import validate_cookie
        is_valid, error_msg = validate_cookie(cookie_str)

        if is_valid:
            print(f"{label_prefix}  [v] 自动登录成功，获取到有效Cookie (长度: {len(cookie_str)})")
            return cookie_str
        else:
            print(f"{label_prefix}  [x] 获取的Cookie无效: {error_msg}")
            return None

    except Exception as e:
        print(f"{label_prefix}  [x] 自动登录异常: {e}")
        return None


def get_valid_cookie(original_cookie_str, account_name="", account_index=None):
    """获取有效的Cookie，如果原Cookie失效则尝试自动登录"""
    from utils import validate_cookie
    
    print(f"\n{'='*50}")
    if account_name:
        print(f"账号: {account_name}")
    
    if original_cookie_str and original_cookie_str.strip():
        print("验证Cookie有效性...")
        is_valid, error_msg = validate_cookie(original_cookie_str)
        
        if is_valid:
            print("  [v] Cookie有效，直接使用")
            return original_cookie_str, False
        
        print(f"  [!] Cookie无效: {error_msg}")
    else:
        print("未配置Cookie，尝试自动登录...")
    
    print("  尝试自动登录获取新Cookie...")
    username, password = get_login_credentials(account_index)

    if not username or not password:
        print("  [x] 未配置自动登录凭据")
        return None, False

    new_cookie = login_and_get_cookie(username, password, account_label=account_name)

    if new_cookie:
        return new_cookie, True
    else:
        print("  [x] 自动登录失败，无法获取有效Cookie")
        return None, False


if __name__ == '__main__':
    cookie, is_auto = get_valid_cookie("", "测试账号")
    if cookie:
        print(f"\n获取到Cookie: {cookie[:100]}...")
        print(f"是否自动登录: {is_auto}")
    else:
        print("\n无法获取有效Cookie")