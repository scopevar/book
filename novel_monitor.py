#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小说更新监听脚本
----------------
定时抓取小说目录页，检测「最新章节」是否发生变化，一旦更新就发出通知。

使用方法:
    1. 安装依赖:  pip install requests beautifulsoup4
    2. 修改下面 BOOKS 里的配置(网址 + CSS 选择器)
    3. 运行:      python novel_monitor.py

原理: 网站不会主动推送更新, 所以采用「轮询」——每隔 INTERVAL 秒抓一次页面,
      提取最新章节标题, 和上次保存的做对比, 变了就通知你。
"""

import json
import time
import random
import os
import sys
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# ----------------------------------------------------------------------------
# 配置区: 改这里就够了
# ----------------------------------------------------------------------------

# 要监听的书。可以放多本。
#   url:      小说目录页(或最新章节所在的页面)地址
#   selector: 用来定位「最新章节」的 CSS 选择器
#             (打开网页 -> F12 -> 右键最新章节 -> 复制 selector)
BOOKS = [
    {
        "name": "奇迹作品-2039366",
        # 注意: 要监听「更新」, 用【目录页】而不是单章页。
        # 你给的 .../book/2039366/46867381 是某一章的固定页面, 不会变。
        # 先在浏览器确认下面哪个是目录/最新章节页, 再填正确的:
        "url": "https://m.qijizuopin.com/book/2039366/",
        # selector 需要你用浏览器 F12 -> Copy selector 得到。
        # 不确定就先留空 "", 然后用调试模式 (见文件末尾说明) 找。
        "selector": "",
    },
]

INTERVAL = 300          # 轮询间隔(秒)。300 = 5 分钟
JITTER = 60             # 随机抖动(秒), 让请求不那么规律
STATE_FILE = "novel_state.json"   # 保存上次状态的文件

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# ----------------------------------------------------------------------------
# 通知方式: 默认打印到控制台 + 系统响铃。
# 想推到手机可以在这里接入 Bark / Server酱 / 钉钉机器人 等(见下方 notify)。
# ----------------------------------------------------------------------------

BARK_URL = os.environ.get("BARK_URL", "")   # 例如 https://api.day.app/你的key

def notify(title: str, message: str) -> None:
    """发送通知。默认控制台打印, 若配置了 BARK_URL 则推送到手机。"""
    print(f"\n🔔 [{now()}] {title}\n   {message}\n")
    sys.stdout.write("\a")  # 终端响铃
    sys.stdout.flush()

    if BARK_URL:
        try:
            requests.get(f"{BARK_URL}/{title}/{message}", timeout=10)
        except requests.RequestException as e:
            print(f"   (Bark 推送失败: {e})")


# ----------------------------------------------------------------------------
# 以下一般不用改
# ----------------------------------------------------------------------------

def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def fetch_latest_chapter(book: dict) -> str | None:
    """抓取页面并提取最新章节文本。失败返回 None。"""
    try:
        resp = requests.get(book["url"], headers=HEADERS, timeout=15)
        resp.raise_for_status()
        # 自动识别编码(不少中文小说站用 gbk)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        el = soup.select_one(book["selector"])
        if el is None:
            print(f"   ⚠️  [{book['name']}] 选择器没匹配到内容, 请检查 selector")
            return None
        return el.get_text(strip=True)
    except requests.RequestException as e:
        print(f"   ⚠️  [{book['name']}] 抓取失败: {e}")
        return None


def check_once(state: dict) -> None:
    for book in BOOKS:
        latest = fetch_latest_chapter(book)
        if latest is None:
            continue

        key = book["url"]
        previous = state.get(key)

        if previous is None:
            # 第一次运行, 记录基线, 不通知
            print(f"   ✅ [{book['name']}] 已记录当前章节: {latest}")
        elif latest != previous:
            notify(f"《{book['name']}》更新啦", f"最新章节: {latest}")
        else:
            print(f"   … [{book['name']}] 无更新 (当前: {latest})")

        state[key] = latest
    save_state(state)


def debug_probe() -> None:
    """调试模式: 抓第一本书的页面, 打印常见的"最新章节"候选, 帮你找 selector。
    用法:  python novel_monitor.py --debug
    """
    book = BOOKS[0]
    print(f"[调试] 抓取: {book['url']}\n")
    try:
        resp = requests.get(book["url"], headers=HEADERS, timeout=15)
        resp.encoding = resp.apparent_encoding
        print(f"HTTP {resp.status_code}, 页面大小 {len(resp.text)} 字符\n")
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"抓取失败: {e}")
        print("如果是 403/被拦, 说明该站有反爬, 可能需要加 Cookie 或换请求头。")
        return

    soup = BeautifulSoup(resp.text, "html.parser")
    print("页面标题:", soup.title.get_text(strip=True) if soup.title else "(无)")

    # 逐个试常见选择器, 打印命中的文本, 你挑对的那个填进 selector
    candidates = [
        "div.listmain dd:last-child a",
        "div.listmain dd:first-child a",
        ".latest a", ".last a", ".update a",
        "#list dd a", ".chapterlist a", ".catalog a",
        "a[href*='/book/']",
    ]
    print("\n--- 候选选择器命中情况(挑内容像'最新章节'的那个) ---")
    for sel in candidates:
        els = soup.select(sel)
        if els:
            sample = els[0].get_text(strip=True)[:40]
            print(f"  [{len(els):>3} 个] {sel:<32} 例: {sample}")
    print("\n找到后, 把对应的选择器填到 BOOKS[0]['selector'], 去掉 --debug 正常运行即可。")


def main() -> None:
    if "--debug" in sys.argv:
        debug_probe()
        return
    if not all(b["selector"] for b in BOOKS):
        print("⚠️  有书还没填 selector。先运行:  python novel_monitor.py --debug  来定位。")
        return
    print(f"开始监听 {len(BOOKS)} 本小说, 间隔约 {INTERVAL}s。按 Ctrl+C 停止。\n")
    state = load_state()
    try:
        while True:
            print(f"[{now()}] 检查中...")
            check_once(state)
            sleep_for = INTERVAL + random.randint(0, JITTER)
            print(f"   下次检查约在 {sleep_for}s 后。\n")
            time.sleep(sleep_for)
    except KeyboardInterrupt:
        print("\n已停止监听。")


if __name__ == "__main__":
    main()
