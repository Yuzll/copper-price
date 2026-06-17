#!/usr/bin/env python3
"""
铜价爬虫 — 从长江有色金属网 (cjys.net) 抓取每日1#电解铜报价
用于机电造价集成工具 — GitHub Actions 每日自动运行

数据源: https://www.cjys.net/price
特点: 纯 HTML 表格, 无 WAF, 无需 JS 渲染, 交易日更新
"""

import re
import sys
import json
import time
from datetime import datetime, timezone, timedelta

import requests

# ── 配置 ──────────────────────────────────────────────
SOURCE_URL = "https://www.cjys.net/price"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 20  # 秒
MAX_RETRIES = 2       # 重试次数

# ── HTTP 请求（带重试） ──────────────────────────────
def fetch_html(url: str) -> str:
    """获取网页 HTML，带重试和中文编码处理"""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": url,
    }
    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                # 尝试 UTF-8，失败则用 requests 自动检测
                try:
                    return resp.content.decode("utf-8")
                except UnicodeDecodeError:
                    return resp.text
            if resp.status_code in (404, 429, 500, 502, 503, 504):
                last_error = f"HTTP {resp.status_code}"
            else:
                last_error = f"HTTP {resp.status_code}"
        except requests.ConnectionError as e:
            last_error = f"ConnectionError: {e}"
        except requests.Timeout as e:
            last_error = f"Timeout: {e}"

        if attempt < MAX_RETRIES:
            wait = 2 ** attempt  # 1s, 2s, ...
            time.sleep(wait)

    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


# ── 解析铜价 ──────────────────────────────────────────
def parse_copper(html: str) -> dict | None:
    """
    从 HTML 表格中提取 1#电解铜 报价行
    cjys.net 的表格格式:
    <tr><td>长江 1#电解铜</td><td>最低价</td><td>最高价</td>
    <td>元/吨</td><td>均价</td><td>涨跌</td>...</tr>
    """
    # 匹配包含 "1#电解铜" 的整行
    row_pattern = re.compile(
        r"<tr[^>]*>(.*?1#电解铜.*?)</tr>",
        re.IGNORECASE | re.DOTALL,
    )
    m = row_pattern.search(html)
    if not m:
        return None

    row = m.group(1)
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
    if len(cells) < 9:
        return None

    def strip_tags(s: str) -> str:
        """去除 HTML 标签和空白"""
        s = re.sub(r"<[^>]+>", "", s)
        return s.strip()

    cells = [strip_tags(c) for c in cells]
    # cells 布局:
    # [0] 品名    [1] 最低价   [2] 最高价   [3] 单位
    # [4] 均价    [5] 涨跌     [6] 产地牌号 [7] 交货地  [8] 日期

    try:
        price_low = int(cells[1])
        price_high = int(cells[2])
        price_mean = int(cells[4])
        change_raw = cells[5]
        date_str = cells[8]
    except (ValueError, IndexError):
        return None

    # 解析涨跌: "↑710" → +710; "↓-1060" → -1060
    change = 0
    if change_raw:
        up = "↑" in change_raw
        down = "↓" in change_raw
        num_str = re.sub(r"[↑↓\s]", "", change_raw).replace(",", "")
        try:
            change = int(num_str)
            if down and change > 0:
                change = -change
            elif up and change < 0:
                change = abs(change)
        except ValueError:
            change = 0

    # 涨跌百分比
    prev_price = price_mean - change
    change_pct = round((change / prev_price) * 100, 2) if prev_price else 0

    return {
        "price": price_mean,
        "date": date_str,
        "change": change,
        "changePercent": change_pct,
        "priceLow": price_low,
        "priceHigh": price_high,
        "source": "长江有色金属网",
        "sourceUrl": SOURCE_URL,
        "unit": "元/吨",
        "updatedAt": datetime.now(timezone(timedelta(hours=8))).isoformat(),
    }


# ── 主流程 ────────────────────────────────────────────
def main():
    try:
        html = fetch_html(SOURCE_URL)
        copper = parse_copper(html)
        if copper is None:
            print(json.dumps({"error": "未找到1#电解铜数据"}, ensure_ascii=False, indent=2))
            sys.exit(1)

        output = json.dumps(copper, ensure_ascii=False, indent=2)
        print(output)

        # 写入 copper.json
        with open("copper.json", "w", encoding="utf-8") as f:
            f.write(output)
            f.write("\n")

        print(f"\n✅ 铜价更新成功: ¥{copper['price']}/吨 ({copper['date']})")

    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
