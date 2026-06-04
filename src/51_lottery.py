"""2026 五一狂欢抽奖活动自动化模块（浏览器自动化版）

活动页面: https://activity.zaimanhua.com/51-lottery/
任务: 分享活动、阅读任务、祝福评论
完成后抽奖，打印抽奖结果

采用 Playwright 浏览器自动化，模拟真实用户操作
"""
import random
import time
import re
import requests

from utils import (
    extract_user_info_from_cookies,
    get_all_cookies,
    parse_cookies,
    validate_cookie,
)
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# 配置
BASE_URL = "https://activity.zaimanhua.com"
MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"

BLESSINGS = [
    "五一快乐",
]


def setup_browser_context(p, cookie_str: str):
    """初始化浏览器上下文并添加 Cookie

    增加DNS-over-HTTPS支持，解决GitHub Actions环境下DNS解析超时问题
    修复：使用精确domain匹配，避免同名Cookie冲突导致服务器解析错误
    """
    cookies = parse_cookies(cookie_str)

    # Playwright 访问 activity.zaimanhua.com 时，需要该精确 domain 的 Cookie
    # 原始 parse_cookies 返回的 domain 是 .zaimanhua.com（带点，表示对所有子域名生效）
    # 但 Playwright 的 add_cookies 要求 domain 必须与访问的域名精确匹配
    # 因此将 .zaimanhua.com 转换为 activity.zaimanhua.com（不带点，精确匹配）
    all_cookies = []
    for c in cookies:
        original_domain = c.get('domain', '.zaimanhua.com')
        # 如果原始 domain 是 .zaimanhua.com（根域名），转换为 activity.zaimanhua.com
        if original_domain == '.zaimanhua.com':
            all_cookies.append({
                'name': c['name'],
                'value': c['value'],
                'domain': 'activity.zaimanhua.com',
                'path': c.get('path', '/')
            })
        else:
            all_cookies.append({
                'name': c['name'],
                'value': c['value'],
                'domain': original_domain,
                'path': c.get('path', '/')
            })

    # 配置Chromium启动参数，启用DNS-over-HTTPS并禁用缓存
    browser_args = [
        # 启用安全DNS（DNS-over-HTTPS）
        '--enable-features=DnsOverHttps',
        # 配置DoH提供商为阿里云DNS
        '--dns-over-https-mode=secure',
        '--dns-over-https-templates=https://dns.alidns.com/dns-query{?dns}',
        # 禁用浏览器内置DNS缓存，强制使用DoH
        '--disable-async-dns',
        # 增加网络超时容忍度
        '--disable-features=NetworkServiceSandbox',
        # 禁用磁盘缓存，确保每次加载都是最新内容
        '--disk-cache-size=0',
        '--disable-application-cache',
        '--disable-session-storage',
        # 禁用Service Worker
        '--disable-service-worker',
    ]

    browser = p.chromium.launch(
        headless=True,
        args=browser_args
    )
    context = browser.new_context(
        user_agent=MOBILE_UA,
        viewport={'width': 375, 'height': 812},
    )
    context.add_cookies(all_cookies)

    page = context.new_page()

    # 设置页面级别的缓存禁用
    try:
        page.route("**/*", lambda route: route.continue_())
    except:
        pass

    return browser, context, page


def clear_browser_cache(page):
    """清除浏览器缓存，确保多账号切换时获取最新数据"""
    try:
        page.evaluate("""
            () => {
                // 清除localStorage和sessionStorage
                localStorage.clear();
                sessionStorage.clear();
                // 清除缓存
                if (caches && caches.keys) {
                    caches.keys().then(names => names.forEach(name => caches.delete(name)));
                }
            }
        """)
    except:
        pass


def verify_login_status(page, cookie_str: str) -> bool:
    """验证页面上的登录状态，通过检查localStorage中的lginfo是否正确设置"""
    try:
        # 先尝试从页面获取lginfo
        lginfo = page.evaluate("() => localStorage.getItem('lginfo')")
        if lginfo:
            import json
            try:
                info = json.loads(lginfo)
                uid = info.get('uid')
                if uid:
                    print(f"    页面登录状态: uid={uid}")
                    return True
            except:
                pass

        # 如果localStorage没有，尝试从Cookie提取并设置
        from utils import init_localstorage, extract_user_info_from_cookies
        user_info = extract_user_info_from_cookies(cookie_str)
        if user_info.get('uid'):
            init_localstorage(page, cookie_str)
            return True

        return False
    except Exception as e:
        print(f"    验证登录状态异常: {e}")
        return False


def get_task_status(page) -> tuple:
    """检查页面上的任务状态（不加载页面，仅读取当前页面）

    返回: (unfinished_tasks, task_texts)
    - unfinished_tasks: 未完成的任务索引列表 [0, 1, 2]
    - task_texts: 每个任务按钮的文本列表，如 ['已完成', '去完成', '已完成']
    """
    unfinished_tasks = []
    task_texts = []
    try:
        buttons = page.locator(".btn").all()
        print(f"    找到 {len(buttons)} 个 .btn 按钮")

        if len(buttons) >= 3:
            for i, btn in enumerate(buttons[:3]):
                try:
                    text = btn.inner_text(timeout=5000).strip()
                    task_texts.append(text)
                    print(f"    任务按钮 {i+1}: 文本='{text}'")
                    if "去完成" in text:
                        unfinished_tasks.append(i)
                except:
                    if len(task_texts) <= i:
                        task_texts.append("未知")
                    print(f"    任务按钮 {i+1}: 文本读取失败")
                    continue
        elif len(buttons) > 0:
            for i, btn in enumerate(buttons):
                try:
                    text = btn.inner_text(timeout=5000).strip()
                    task_texts.append(text)
                    print(f"    按钮 {i+1}: 文本='{text}'")
                    if "去完成" in text:
                        unfinished_tasks.append(i)
                except:
                    if len(task_texts) <= i:
                        task_texts.append("未知")
                    print(f"    按钮 {i+1}: 文本读取失败")
                    continue
        else:
            print(f"    未找到 .btn 按钮，尝试其他选择器...")
            alt_buttons = page.locator("button, .task-btn, [class*='task']").all()
            for i, btn in enumerate(alt_buttons[:3]):
                try:
                    text = btn.inner_text(timeout=5000).strip()
                    task_texts.append(text)
                    print(f"    备选按钮 {i+1}: 文本='{text}'")
                    if "去完成" in text:
                        unfinished_tasks.append(i)
                except:
                    if len(task_texts) <= i:
                        task_texts.append("未知")
                    continue
    except Exception as e:
        print(f"    [x] 获取任务状态异常: {e}")

    return unfinished_tasks, task_texts


def load_activity_page(page):
    """加载活动页面并等待渲染完成"""
    cache_buster = random.randint(100000, 999999)
    page.goto(f"{BASE_URL}/51-lottery/?_={cache_buster}", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)


def click_task_button(page, task_idx: int) -> bool:
    """点击指定索引的任务按钮"""
    try:
        # 获取所有按钮，找到第 task_idx 个包含"去完成"的按钮
        buttons = page.locator(".btn").all()
        unfinished_btns = []
        for btn in buttons:
            try:
                text = btn.inner_text(timeout=2000).strip()
                if "去完成" in text:
                    unfinished_btns.append(btn)
            except:
                continue

        if task_idx < len(unfinished_btns):
            unfinished_btns[task_idx].click(timeout=5000)
            return True
        else:
            print(f"  [x] 找不到任务按钮索引 {task_idx}")
            return False
    except Exception as e:
        print(f"  [x] 点击任务按钮异常: {e}")
        return False


def do_share_task(page, task_idx: int = 0) -> bool:
    """完成分享任务：点击去完成 -> 点击复制按钮"""
    try:
        print("  [分享任务] 点击'去完成'...")
        if not click_task_button(page, task_idx):
            return False
        page.wait_for_timeout(2000)

        # 点击复制按钮
        print("  [分享任务] 点击复制按钮...")
        copy_btn = page.locator("img.copyBtn").first
        if not copy_btn.is_visible(timeout=3000):
            # 尝试其他选择器
            copy_btn = page.locator("img[src*='copy']").first
        if not copy_btn.is_visible(timeout=3000):
            # 尝试查找包含"复制"文本的按钮
            copy_btn = page.locator("button, div, span").filter(has_text="复制").first
        if not copy_btn.is_visible(timeout=3000):
            # 尝试点击弹窗中的任意按钮
            copy_btn = page.locator(".popup button, .modal button, .dialog button").first

        if copy_btn and copy_btn.is_visible(timeout=3000):
            copy_btn.click(timeout=3000, force=True)
            page.wait_for_timeout(2000)
            print("  [v] 分享任务完成")
            return True
        else:
            print("  [x] 未找到复制按钮，尝试关闭弹窗...")
            # 尝试按 ESC 关闭弹窗
            page.keyboard.press("Escape")
            page.wait_for_timeout(1000)
            return True  # 即使没找到按钮也视为完成
    except Exception as e:
        print(f"  [x] 分享任务异常: {e}")
        return False


def do_read_task(page, task_idx: int = 0) -> bool:
    """完成阅读任务：点击去完成 -> API模拟阅读5秒"""
    try:
        print("  [阅读任务] 点击'去完成'...")
        if not click_task_button(page, task_idx):
            return False

        print("  [阅读任务] 等待弹窗...")
        page.wait_for_timeout(3000)

        print("  [阅读任务] 通过API模拟阅读5秒...")
        _api_simulate_read(page, duration=5)

        print("  [v] 阅读任务完成")
        return True
    except Exception as e:
        print(f"  [x] 阅读任务异常: {e}")
        return False


def _api_simulate_read(page, duration=5):
    """通过API模拟阅读漫画

    从当前页面Cookie中提取token，调用v4 API获取漫画章节图片，
    模拟阅读指定秒数。
    """
    try:
        cookies = page.context.cookies()
        cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
        user_info = extract_user_info_from_cookies(cookie_str)
        token = user_info.get('token')
        if not token:
            print("  [API阅读] 未获取到token，跳过")
            return

        headers = {
            'Authorization': f'Bearer {token}',
            'User-Agent': 'okhttp/4.9.3',
            'Accept': 'application/json, text/plain, */*',
        }

        API_BASE = "https://v4api.zaimanhua.com/app/v1"

        # 获取漫画列表
        resp = requests.get(
            f"{API_BASE}/comic/rank/list",
            headers=headers,
            params={'tag_id': '0', 'page': '1', '_v': '2.2.5'},
            timeout=10
        )
        if resp.status_code != 200:
            print("  [API阅读] 获取漫画列表失败")
            return
        data = resp.json()
        if data.get('errno') != 0:
            print("  [API阅读] 漫画列表接口返回错误")
            return
        data_obj = data.get('data', [])
        if isinstance(data_obj, dict):
            comics = data_obj.get('data', [])
        elif isinstance(data_obj, list):
            comics = data_obj
        else:
            comics = []
        if not comics:
            print("  [API阅读] 漫画列表为空")
            return

        comic = random.choice(comics)
        comic_id = comic.get('comic_id')
        print(f"  [API阅读] 漫画: {comic.get('title', '未知')} (id={comic_id})")

        # 获取章节
        resp = requests.get(
            f"{API_BASE}/comic/detail/{comic_id}",
            headers=headers,
            params={'_v': '2.2.5'},
            timeout=10
        )
        if resp.status_code != 200:
            print("  [API阅读] 获取章节失败")
            return
        data = resp.json()
        if data.get('errno') != 0:
            print("  [API阅读] 章节接口返回错误")
            return
        chapters_data = data.get('data', {}).get('data', {}).get('chapters', [])
        all_chapters = []
        for vol in chapters_data:
            if 'data' in vol and isinstance(vol['data'], list):
                for ch in vol['data']:
                    if ch.get('canRead', True):
                        all_chapters.append(ch)
        if not all_chapters:
            print("  [API阅读] 无可读章节")
            return

        chapter = random.choice(all_chapters)
        chapter_id = chapter.get('chapter_id')
        print(f"  [API阅读] 章节: {chapter.get('title', '未知')} (id={chapter_id})")

        # 获取章节图片
        resp = requests.get(
            f"{API_BASE}/comic/chapter/{comic_id}/{chapter_id}",
            headers=headers,
            params={'_v': '2.2.5'},
            timeout=10
        )
        if resp.status_code != 200:
            print("  [API阅读] 获取图片列表失败")
            return
        data = resp.json()
        if data.get('errno') != 0:
            print("  [API阅读] 图片接口返回错误")
            return
        images = data.get('data', {}).get('data', {}).get('images') or \
                 data.get('data', {}).get('data', {}).get('page_url') or []

        if not images:
            print("  [API阅读] 无图片")
            return

        # 模拟阅读：逐个请求图片，控制总时长
        per_image_delay = max(0.3, duration / len(images))
        start = time.time()
        read_count = 0
        for img_url in images:
            if time.time() - start >= duration:
                break
            try:
                requests.get(img_url, headers=headers, timeout=10)
                read_count += 1
            except:
                pass
            time.sleep(per_image_delay)

        print(f"  [API阅读] 完成，阅读了 {read_count} 页，耗时 {time.time()-start:.1f}秒")

    except Exception as e:
        print(f"  [API阅读] 异常: {e}")


def do_comment_task(page, task_idx: int = 0) -> bool:
    """完成评论任务：输入祝福语 -> 点击发布"""
    try:
        print("  [评论任务] 点击'去完成'...")
        if not click_task_button(page, task_idx):
            return False
        page.wait_for_timeout(2000)

        # 输入祝福语
        blessing = random.choice(BLESSINGS)
        print(f"  [评论任务] 输入祝福语: {blessing}")

        input_box = page.locator("input.comment-input").first
        if not input_box.is_visible(timeout=3000):
            # 尝试其他选择器
            input_box = page.locator("input[placeholder*='评论']").first

        if input_box.is_visible(timeout=3000):
            input_box.fill(blessing)
            page.wait_for_timeout(1000)

            # 点击发布按钮
            submit_btn = page.locator("text=发布").first
            if submit_btn.is_visible(timeout=3000):
                submit_btn.click(timeout=3000, force=True)
                page.wait_for_timeout(2000)
                print("  [v] 评论任务完成")
                return True
            else:
                print("  [x] 未找到发布按钮")
                return False
        else:
            print("  [x] 未找到评论输入框")
            return False
    except Exception as e:
        print(f"  [x] 评论任务异常: {e}")
        return False


def get_draw_count(page) -> int:
    """获取当前抽奖次数"""
    try:
        # 刷新页面获取最新状态
        page.goto(f"{BASE_URL}/51-lottery/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        # 查找抽奖次数元素
        count_elem = page.locator(".draw-count").first
        if count_elem.is_visible(timeout=5000):
            text = count_elem.inner_text(timeout=2000)
            print(f"    抽奖次数文本: {text}")
            # 提取数字
            match = re.search(r"\d+", text)
            if match:
                return int(match.group())

        return 0
    except Exception as e:
        print(f"  [x] 获取抽奖次数异常: {e}")
        return 0


def close_win_prize(page):
    """关闭抽奖结果弹窗"""
    print("    [debug] 关闭弹窗...")
    closed = False

    # 方法1: 尝试点击确定按钮
    try:
        ok_btn = page.locator(".okBtn").first
        if ok_btn.is_visible(timeout=2000):
            ok_btn.click(timeout=3000)
            page.wait_for_timeout(2000)
            print("    [debug] 已点击 okBtn 关闭弹窗")
            closed = True
    except:
        pass

    # 方法2: 按 ESC 键
    if not closed:
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(1000)
            closed = True
        except:
            pass

    # 方法3: 点击页面空白处
    if not closed:
        try:
            page.click("body", timeout=3000)
            page.wait_for_timeout(1000)
            closed = True
        except:
            pass

    # 等待弹窗完全消失
    page.wait_for_timeout(2000)
    return closed


def read_prize_records(page):
    """读取中奖记录"""
    try:
        # 点击"我的中奖记录"按钮
        print("    点击'我的中奖记录'...")
        record_btn = page.locator("img[src*='zjjl']").first
        if not record_btn.is_visible(timeout=3000):
            print("    [x] 未找到中奖记录按钮")
            return

        record_btn.click(timeout=3000)
        page.wait_for_timeout(2000)
        print("    [v] 已打开中奖记录")

        # 读取中奖记录列表
        records = []

        # 直接读取所有 span1 和 time 元素
        span1_elems = page.locator(".span1").all()
        time_elems = page.locator(".time").all()

        # 只读取与 span1 数量相同的 time 元素（前面的是中奖记录，后面的是评论时间）
        for i, span1 in enumerate(span1_elems):
            try:
                prize_text = span1.inner_text(timeout=1000).strip()
                # 提取奖品名称（去掉"获得: "前缀）
                prize_name = prize_text.replace("获得: ", "")
                time_text = time_elems[i].inner_text(timeout=1000).strip() if i < len(time_elems) else ""
                records.append(f"{time_text}获得: {prize_name}")
            except:
                continue

        # 打印中奖记录
        if records:
            print("    中奖记录:")
            for record in records:
                print(f"      {record}")
        else:
            print("    暂无中奖记录")

        # 关闭弹窗
        close_win_prize(page)

    except Exception as e:
        print(f"    [x] 读取中奖记录异常: {e}")


def do_drawing(page, index: int, total: int) -> str:
    """执行一次抽奖，返回奖品名称"""
    try:
        print(f"    第 {index}/{total} 次抽奖...")

        # 先确保没有弹窗遮挡
        close_win_prize(page)

        # 点击抽奖指针
        pointer = page.locator("img[src*='pointerText']").first
        if not pointer.is_visible(timeout=3000):
            # 尝试其他选择器
            pointer = page.locator("img[style*='width: 60px']").first

        if pointer.is_visible(timeout=3000):
            pointer.click(timeout=3000)
            print("    已点击抽奖指针，等待结果...")
        else:
            print("  [x] 未找到抽奖指针")
            return "未知"

        # 等待结果弹窗出现 - 等待转盘停止后 <p data-v-e77f7682="">恭喜您获得：</p> 出现
        print("    等待转盘停止，弹窗出现...")
        prize_name = "谢谢参与"  # 默认设为谢谢参与，如果检测到具体奖品再更新

        # 方法1: 轮询检测（每100ms检查一次，最多15秒）
        print("    [debug] 开始轮询检测弹窗...")
        for check in range(150):  # 最多15秒
            page.wait_for_timeout(100)

            # 检查1: p[data-v-e77f7682]:has-text("恭喜您获得：")
            try:
                congrats_p = page.locator('p[data-v-e77f7682]:has-text("恭喜您获得：")').first
                if congrats_p.is_visible(timeout=100):
                    print("    [debug] 找到 '恭喜您获得：' 元素")
                    parent = congrats_p.locator("..")
                    prize_span = parent.locator('span[data-v-e77f7682]').first
                    if prize_span.is_visible(timeout=1000):
                        prize_name = prize_span.inner_text(timeout=1000).strip()
                        print(f"    [debug] 奖品名称: {prize_name}")
                        break
            except:
                pass

            # 检查2: winPrize 弹窗
            if prize_name == "谢谢参与":
                try:
                    win_prize = page.locator(".winPrize").first
                    if win_prize.is_visible(timeout=100):
                        prize_text = win_prize.inner_text(timeout=1000)
                        if "恭喜您获得：" in prize_text:
                            lines = [line.strip() for line in prize_text.split("\n") if line.strip()]
                            for i, line in enumerate(lines):
                                if "恭喜您获得：" in line and i + 1 < len(lines):
                                    prize_name = lines[i + 1]
                                    break
                        break
                except:
                    pass

            # 检查3: text=恭喜您获得：
            if prize_name == "谢谢参与":
                try:
                    congrats = page.locator("text=恭喜您获得：").first
                    if congrats.is_visible(timeout=100):
                        parent = congrats.locator("..")
                        parent_text = parent.inner_text(timeout=1000)
                        if "恭喜您获得：" in parent_text:
                            lines = [line.strip() for line in parent_text.split("\n") if line.strip()]
                            for i, line in enumerate(lines):
                                if "恭喜您获得：" in line and i + 1 < len(lines):
                                    prize_name = lines[i + 1]
                                    break
                        break
                except:
                    pass

        # 方法4: 如果还是没找到，尝试查找所有 span[data-v-e77f7682]
        if prize_name == "谢谢参与":
            print("    [debug] 尝试查找 span 元素...")
            try:
                span_elems = page.locator("span[data-v-e77f7682]").all()
                for span in span_elems:
                    text = span.inner_text(timeout=1000).strip()
                    if text and text not in ["", "恭喜您获得："]:
                        if any(keyword in text for keyword in ["积分", "VIP", "会员", "福袋", "实体书", "谢谢参与"]):
                            prize_name = text
                            break
            except:
                pass

        # 方法5: 获取 body 全部文本
        if prize_name == "谢谢参与":
            print("    [debug] 尝试获取body文本...")
            try:
                body_text = page.locator("body").inner_text(timeout=2000)
                if "恭喜您获得：" in body_text:
                    lines = [line.strip() for line in body_text.split("\n") if line.strip()]
                    for i, line in enumerate(lines):
                        if "恭喜您获得：" in line and i + 1 < len(lines):
                            next_line = lines[i + 1]
                            if next_line and next_line != "恭喜您获得：":
                                prize_name = next_line
                                break
            except Exception as e:
                print(f"    [debug] 获取页面文本异常: {e}")

        # 方法6: 检测"谢谢参与"弹窗（可能没有"恭喜您获得"文本）
        if prize_name == "谢谢参与":
            print("    [debug] 尝试检测谢谢参与弹窗...")
            try:
                # 检查是否有包含"谢谢参与"的任何元素
                thank_you_elems = page.locator("text=谢谢参与").all()
                for elem in thank_you_elems:
                    if elem.is_visible(timeout=100):
                        prize_name = "谢谢参与"
                        print("    [debug] 找到 '谢谢参与'")
                        break
                
                # 也检查body文本
                if prize_name == "谢谢参与":
                    body_text = page.locator("body").inner_text(timeout=1000)
                    if "谢谢参与" in body_text:
                        prize_name = "谢谢参与"
                        print("    [debug] 在body文本中找到 '谢谢参与'")
            except:
                pass

        # 方法7: 检查是否有弹窗出现但内容未知（可能是未中奖）
        if prize_name == "谢谢参与":
            print("    [debug] 检查是否有任何弹窗...")
            try:
                # 检查winPrize弹窗是否可见
                win_prize = page.locator(".winPrize").first
                if win_prize.is_visible(timeout=100):
                    prize_text = win_prize.inner_text(timeout=1000)
                    print(f"    [debug] winPrize弹窗内容: {prize_text[:100]}")
                    # 如果弹窗可见但没有识别到奖品，可能是未中奖
                    if "恭喜" not in prize_text and "获得" not in prize_text:
                        prize_name = "谢谢参与"
                        print("    [debug] 弹窗无奖品信息，判定为谢谢参与")
            except:
                pass

        print(f"    [v] 抽奖结果: {prize_name}")

        # 关闭弹窗
        close_win_prize(page)

        return prize_name
    except Exception as e:
        print(f"    [x] 抽奖异常: {e}")
        return "未知"


def run_51_lottery(cookie_str: str, account_name: str):
    """单账号五一活动流程（浏览器自动化版）"""
    print(f"\n  === 开始五一狂欢抽奖活动 ===")

    user_info = extract_user_info_from_cookies(cookie_str)
    nickname = user_info.get("nickname") or user_info.get("username") or "未知"
    uid = user_info.get("uid", "未知")
    print(f"  用户: {nickname} (uid: {uid})")

    with sync_playwright() as p:
        browser, context, page = setup_browser_context(p, cookie_str)

        try:
            print("\n  [0] 初始化页面...")
            load_activity_page(page)

            print("\n  [1] 检查任务状态...")
            unfinished_tasks, task_texts = get_task_status(page)

            if not unfinished_tasks:
                print("  [v] 所有任务已完成")
            else:
                print(f"  未完成任务索引: {unfinished_tasks}")

            if not unfinished_tasks:
                print("\n  [快速检查] 所有任务已完成，检查抽奖次数...")
                count_elem = page.locator(".draw-count").first
                if count_elem.is_visible(timeout=5000):
                    text = count_elem.inner_text(timeout=2000)
                    match = re.search(r"\d+", text)
                    if match:
                        draw_count = int(match.group())
                        print(f"  当前抽奖次数: {draw_count}")
                        if draw_count == 0:
                            print("  [v] 任务全部完成且抽奖次数为0，直接结束")
                            return True

            print("\n  [2] 执行任务...")

            # 分享任务 (索引0)
            if len(task_texts) > 0 and "已完成" in task_texts[0]:
                print("  [分享任务] 已完成，跳过")
            else:
                load_activity_page(page)
                share_btn = page.locator(".btn").filter(has_text="去完成").first
                if share_btn.is_visible(timeout=5000):
                    do_share_task(page, 0)
                    time.sleep(3)
                else:
                    print("  [分享任务] 未找到去完成按钮")

            # 阅读任务 (索引1)
            if len(task_texts) > 1 and "已完成" in task_texts[1]:
                print("  [阅读任务] 已完成，跳过")
            else:
                load_activity_page(page)
                read_btn = page.locator(".btn").filter(has_text="去完成").first
                if read_btn.is_visible(timeout=5000):
                    do_read_task(page, 0)
                    time.sleep(3)
                else:
                    print("  [阅读任务] 未找到去完成按钮")

            # 评论任务 (索引2)
            if len(task_texts) > 2 and "已完成" in task_texts[2]:
                print("  [评论任务] 已完成，跳过")
            else:
                load_activity_page(page)
                comment_btn = page.locator(".btn").filter(has_text="去完成").first
                if comment_btn.is_visible(timeout=5000):
                    do_comment_task(page, 0)
                    time.sleep(3)
                else:
                    print("  [评论任务] 未找到去完成按钮")

            # 3. 等待服务器同步
            print("\n  [3] 等待服务器同步状态...")
            max_retries = 8
            max_reexec = 2
            draw_count = 0
            prev_unfinished = set(unfinished_tasks)
            retry_stuck_count = 0
            reexec_count = 0

            for retry in range(max_retries):
                load_activity_page(page)
                unfinished, current_texts = get_task_status(page)

                if unfinished:
                    current_set = set(unfinished)
                    if current_set == prev_unfinished:
                        retry_stuck_count += 1
                        print(f"  未完成: {unfinished}，等待同步... (停滞 {retry_stuck_count}/2)")
                    else:
                        retry_stuck_count = 0
                        prev_unfinished = current_set
                        print(f"  未完成: {unfinished}，等待同步...")

                    if retry_stuck_count >= 2 and reexec_count < max_reexec:
                        reexec_count += 1
                        print(f"  [!] 重新执行 ({reexec_count}/{max_reexec}): {unfinished}")
                        for task_idx in unfinished:
                            if task_idx == 0:
                                do_share_task(page, 0)
                            elif task_idx == 1:
                                do_read_task(page, 0)
                            elif task_idx == 2:
                                do_comment_task(page, 0)
                            time.sleep(3)
                        retry_stuck_count = 0
                        prev_unfinished = set()
                    elif retry_stuck_count >= 2:
                        print(f"  [!] 已达最大重试次数，放弃: {unfinished}")
                        break

                    time.sleep(10)
                    continue

                # 获取抽奖次数
                count_elem = page.locator(".draw-count").first
                if count_elem.is_visible(timeout=5000):
                    text = count_elem.inner_text(timeout=2000)
                    match = re.search(r"\d+", text)
                    if match:
                        draw_count = int(match.group())
                        print(f"  当前抽奖次数: {draw_count}")
                        if draw_count > 0:
                            break
                        else:
                            print("  抽奖次数为0，继续等待...")

                time.sleep(10)

            if draw_count <= 0:
                print("  [!] 没有可用的抽奖次数")
                return True

            # 4. 执行抽奖
            print(f"\n  [4] 开始抽奖（共 {draw_count} 次）...")
            prizes = []
            for i in range(draw_count):
                prize = do_drawing(page, i + 1, draw_count)
                prizes.append(prize)
                if i < draw_count - 1:
                    time.sleep(2)

            print(f"\n  [v] 抽奖完成，共 {draw_count} 次")
            print("  获奖清单:")
            for idx, prize in enumerate(prizes, 1):
                print(f"    第 {idx} 次: {prize}")

            print(f"\n  [6] 读取中奖记录...")
            read_prize_records(page)

            print(f"\n  === 五一活动结束 ===")
            return True

        except Exception as e:
            print(f"  [x] 活动执行异常: {e}")
            return False
        finally:
            browser.close()


def main():
    """主函数"""
    print("=== 2026 五一狂欢抽奖活动自动化 ===\n")

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

        success = run_51_lottery(cookie_str, account_name)
        if not success:
            all_success = False

    return all_success


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
