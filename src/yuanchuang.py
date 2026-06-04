"""原创漫画征稿季自动化模块

活动入口: https://yuanchuang.zaimanhua.com/2026spring/
功能:
  1. 自动完成关注主办官号、分享页面、阅读参赛作品任务
  2. 自动执行所有可用抽奖次数
"""
import hashlib
import time

import requests
from auto_read import ZaimanhuaAppReader
from playwright.sync_api import sync_playwright

from utils import extract_user_info_from_cookies, get_all_cookies, parse_cookies, validate_cookie

# 配置
BASE_URL = "https://yuanchuang.zaimanhua.com"
ENTRY_URL = f"{BASE_URL}/2026spring/"
MANHUA_BASE_URL = "https://manhua.zaimanhua.com/"
SECRET = "z&m$h*_318345twt"
MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
REQUEST_TIMEOUT = 10
READ_RETRY_COUNT = 2
READ_SIMULATE_MINUTES = 0.1
VOTE_TAG_ID = 36172


def generate_sign(channel: str, timestamp: int) -> str:
    """生成签名"""
    raw = f"{channel}{timestamp}{SECRET}"
    return hashlib.md5(raw.encode()).hexdigest()


def get_signed_params() -> dict:
    """生成带签名的通用活动参数"""
    timestamp = int(time.time() * 1000)
    return {
        "channel": "h5",
        "timestamp": timestamp,
        "sign": generate_sign("h5", timestamp),
    }


def get_api_headers(token: str, referer: str = ENTRY_URL) -> dict:
    """生成活动 API 请求头"""
    headers = {
        "User-Agent": MOBILE_UA,
        "Referer": referer,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def request_json(method: str, path: str, token: str, *, params: dict | None = None,
                 json_body: dict | None = None, referer: str = ENTRY_URL) -> dict:
    """请求活动接口并返回 JSON"""
    headers = get_api_headers(token, referer)
    if json_body is not None:
        headers["Content-Type"] = "application/json"

    try:
        resp = requests.request(
            method=method,
            url=f"{BASE_URL}{path}",
            params=params,
            headers=headers,
            json=json_body,
            timeout=REQUEST_TIMEOUT,
        )
        try:
            return resp.json()
        except ValueError:
            return {
                "errno": resp.status_code,
                "errmsg": resp.text[:200] or f"HTTP {resp.status_code}",
                "http_status": resp.status_code,
                "raw_text": resp.text[:500],
            }
    except Exception as e:
        print(f"  [x] 请求 {path} 异常: {e}")
        return {}


def is_success(result: dict) -> bool:
    """判断接口是否成功"""
    return result.get("errno") == 0


def is_already_done(result: dict) -> bool:
    """判断接口是否提示任务已完成"""
    errmsg = result.get("errmsg", "")
    return any(keyword in errmsg for keyword in ("已完成", "已分享", "已关注", "已经完成", "已经分享", "已经关注"))


def check_status(token: str) -> dict:
    """获取活动状态"""
    return request_json("GET", "/drawApi/draw/draw_load", token)


def do_follow(token: str) -> bool:
    """完成关注主办官号任务"""
    result = request_json("GET", "/drawApi/draw/follow", token, params=get_signed_params())
    if is_success(result):
        can_draw_times = result.get("data", {}).get("canDrawTimes")
        if can_draw_times is not None:
            print(f"  [v] 关注任务完成，当前抽奖次数: {can_draw_times}")
        else:
            print("  [v] 关注任务完成")
        return True

    if is_already_done(result):
        print("  [v] 关注任务已完成")
        return True

    print(f"  [x] 关注任务失败: {result.get('errmsg', '未知错误')}")
    return False


def do_share(token: str) -> bool:
    """完成分享任务"""
    result = request_json("GET", "/drawApi/draw/share", token, params=get_signed_params())
    if is_success(result):
        can_draw_times = result.get("data", {}).get("canDrawTimes")
        if can_draw_times is not None:
            print(f"  [v] 分享任务完成，当前抽奖次数: {can_draw_times}")
        else:
            print("  [v] 分享任务完成")
        return True

    if is_already_done(result):
        print("  [v] 分享任务已完成")
        return True

    print(f"  [x] 分享任务失败: {result.get('errmsg', '未知错误')}")
    return False


def do_drawing(token: str) -> dict:
    """执行一次抽奖"""
    result = request_json("GET", "/drawApi/draw/drawing", token, params=get_signed_params())
    if is_success(result):
        prize = result.get("data", {}).get("prize", {})
        prize_name = prize.get("name") or result.get("data", {}).get("prize_name") or "未知奖品"
        print(f"  [v] 抽奖成功！获得: {prize_name}")
    else:
        print(f"  [x] 抽奖失败: {result.get('errmsg', '未知错误')}")
    return result


def get_comic_list(token: str, page: int = 1, size: int = 100) -> dict:
    """获取参赛作品列表"""
    return request_json(
        "GET",
        "/drawApi/comic/list",
        token,
        params={"tagId": VOTE_TAG_ID, "page": page, "size": size},
    )


def extract_comic_candidates(result: dict) -> list[int | str]:
    """从作品列表接口中提取作品 ID"""
    data = result.get("data", {})
    if not isinstance(data, dict):
        return []

    comics = data.get("list", [])
    if not isinstance(comics, list):
        return []

    ids = []
    for item in comics:
        if not isinstance(item, dict):
            continue
        comic_id = item.get("comic_id") or item.get("id")
        if comic_id is not None and comic_id not in ids:
            ids.append(comic_id)
    return ids


def build_activity_cookies(cookie_str: str) -> list[dict]:
    """构造活动页和主站可复用的 cookies"""
    cookies = parse_cookies(cookie_str)
    activity_cookies = [
        {"name": c["name"], "value": c["value"], "domain": "yuanchuang.zaimanhua.com", "path": "/"}
        for c in cookies
    ]
    main_cookies = [
        {"name": c["name"], "value": c["value"], "domain": ".zaimanhua.com", "path": "/"}
        for c in cookies
    ]
    return activity_cookies + main_cookies


def choose_read_target(token: str):
    """选择一个参赛作品用于完成阅读任务"""
    comic_list = get_comic_list(token)
    candidates = extract_comic_candidates(comic_list)
    if candidates:
        return candidates[0]

    return None


def is_read_done(data: dict) -> bool:
    """判断阅读任务是否完成"""
    return data.get("readingComicTimes", 0) > 0


def read_contest_comic(cookie_str: str, token: str) -> bool:
    """尝试完成阅读任务：先访问活动/详情页，再回退到 API 模拟阅读"""
    target_id = choose_read_target(token)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=MOBILE_UA,
            viewport={"width": 375, "height": 812},
        )
        context.add_cookies(build_activity_cookies(cookie_str))
        page = context.new_page()
        page.set_default_timeout(60000)

        try:
            print("  [阅读] 尝试完成阅读任务...")
            page.goto(ENTRY_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)

            if target_id is not None:
                target_url = f"{MANHUA_BASE_URL}details/{target_id}"
                print(f"    访问参赛作品: {target_url}")
                page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
            else:
                print("    未获取到参赛作品 ID，回退到漫画站首页")
                page.goto(MANHUA_BASE_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
        except Exception as e:
            print(f"  [!] 浏览器访问阅读页失败，改用 API 模拟阅读: {e}")
        finally:
            browser.close()

    for attempt in range(1, READ_RETRY_COUNT + 1):
        status_data = refresh_status_data(token)
        if status_data and is_read_done(status_data):
            print("  [v] 阅读任务完成")
            return True

        print(f"    第 {attempt}/{READ_RETRY_COUNT} 次回退到 API 模拟阅读...")
        reader = ZaimanhuaAppReader(cookie_str, debug=False)
        reader.simulate_reading(minutes=READ_SIMULATE_MINUTES)
        status_data = refresh_status_data(token)
        if status_data and is_read_done(status_data):
            print("  [v] 阅读任务完成")
            return True

    print("  [!] 阅读任务已尝试，但状态暂未更新")
    return False


def print_status(data: dict):
    """输出活动状态摘要"""
    print(f"    抽奖次数: {data.get('times', 0)}")
    print(f"    关注官号: {'已完成' if data.get('followAccountTimes', 0) > 0 else '未完成'}")
    print(f"    分享页面: {'已完成' if data.get('shareTimes', 0) > 0 else '未完成'}")
    print(f"    阅读作品: {'已完成' if data.get('readingComicTimes', 0) > 0 else '未完成'}")


def refresh_status_data(token: str) -> dict:
    """重新获取状态并返回 data"""
    status = check_status(token)
    if not is_success(status):
        print(f"  [x] 获取状态失败: {status.get('errmsg', '未知错误')}")
        return {}
    return status.get("data", {})


def complete_task_stage(cookie_str: str, token: str, data: dict) -> dict:
    """完成活动任务"""
    if data.get("followAccountTimes", 0) <= 0:
        do_follow(token)

    if data.get("shareTimes", 0) <= 0:
        do_share(token)

    if data.get("readingComicTimes", 0) <= 0:
        read_contest_comic(cookie_str, token)

    return refresh_status_data(token)


def draw_all(token: str) -> int:
    """用完所有可用抽奖次数"""
    data = refresh_status_data(token)
    times = data.get("times", 0)
    if times <= 0:
        return 0

    print(f"\n  [抽奖] 可用次数: {times}")
    success_count = 0
    for i in range(times):
        print(f"    第 {i + 1}/{times} 次:")
        result = do_drawing(token)
        if is_success(result):
            success_count += 1
        if i < times - 1:
            time.sleep(2)
    return success_count


def run_yuanchuang(cookie_str: str, account_name: str) -> bool:
    """执行单账号原创活动流程"""
    print("\n  === 开始原创征稿季活动 ===")

    user_info = extract_user_info_from_cookies(cookie_str)
    token = user_info.get("token", "")
    if not token:
        print("  [x] Cookie 中未找到 token")
        return False

    nickname = user_info.get("nickname") or user_info.get("username") or "未知"
    print(f"  用户: {nickname}")
    print(f"  账号标签: {account_name}")

    print("\n  [1] 获取活动状态...")
    status = check_status(token)
    if not is_success(status):
        errmsg = status.get("errmsg", "未知错误")
        print(f"  [x] 获取状态失败: {errmsg}")
        if "活动" in errmsg or "时间" in errmsg:
            print("  提示: 活动可能不在开放时间段内")
        return False

    data = status.get("data", {})
    uid = data.get("userInfo", {}).get("uid", 0)
    if uid == 0:
        print("  [x] 未登录，token 可能已失效")
        return False

    print_status(data)

    print("\n  [2] 执行任务...")
    data = complete_task_stage(cookie_str, token, data)
    print_status(data)

    draw_count = draw_all(token)

    final_data = refresh_status_data(token)
    if final_data:
        print("\n  [3] 最终状态...")
        print_status(final_data)

    print(f"\n  === 原创征稿季活动结束 (抽奖 {draw_count} 次) ===")
    return True


def main():
    """主函数"""
    print("=== 原创漫画征稿季自动化 ===\n")

    cookies_list = get_all_cookies()
    if not cookies_list:
        print("错误: 请设置 ZAIMANHUA_COOKIE 环境变量")
        return False

    all_success = True
    for index, (account_name, cookie_str) in enumerate(cookies_list):
        print(f"\n{'=' * 50}")
        print(f"账号: {account_name}")
        print("=" * 50)

        # 验证 Cookie 有效性，如果失效尝试自动登录
        # 使用对应的账号索引获取对应的多账号凭据
        from auto_login import get_valid_cookie
        valid_cookie, is_auto_login = get_valid_cookie(cookie_str, account_name, account_index=index if index > 0 else None)
        
        if not valid_cookie:
            print(f"  [ERROR] 无法获取有效Cookie")
            all_success = False
            continue
        
        if is_auto_login:
            print(f"  [v] 使用自动登录获取的新Cookie")
            cookie_str = valid_cookie
        else:
            print(f"  [v] 使用配置的Cookie")

        success = run_yuanchuang(cookie_str, account_name)
        if not success:
            all_success = False

    return all_success


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
