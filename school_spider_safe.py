import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import random
import logging
import re
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ================= 1. 通用爬虫配置区（可随意更换目标网站） =================
# 目标网站 URL（可替换为任何学校的官网）
TARGET_URL = "https://www.csysgz.com/index.htm" 

# 数据库名称
DB_NAME = "university_news.db"

# 【自适应解析配置】请根据目标网站 F12 结构修改以下标签
# 支持传入多个父级容器的 class，完美兼容左右两列不同结构
LIST_CONTAINER_CLASSES = ["news-list", "news-right"] 
NEWS_ITEM_TAG = "li"                   # 单条新闻的包裹标签
TITLE_CONTAINER_CLASS = "news-list-tt" # 标题所在的 div 的 class
DATE_TAG = "span"                      # 日期所在的标签
# =========================================================================

# ================= 2. 日志配置 =================
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("spider.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# ================= 3. 数据库初始化 =================
def init_db():
    conn = sqlite3.connect(DB_NAME) 
    cursor = conn.cursor()
    # 建立数据表，利用 UNIQUE 约束进行去重
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT UNIQUE,
            date TEXT,
            link TEXT
        )
    ''')
    conn.commit()
    return conn, cursor

# ================= 4. 数据清洗 =================
def clean_text(text):
    if not text: 
        return ""
    # 正则清洗：将换行、制表符、多余空格替换为单个空格
    return re.sub(r'\s+', ' ', text).strip()

# ================= 5. 核心爬虫逻辑 =================
def crawl_news(target_url, max_items=15):
    conn, cursor = init_db()
    item_count = 0

    # 重试机制（应对网络波动）
    session = requests.Session()
    retry = Retry(connect=2, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount('http://', HTTPAdapter(max_retries=retry))
    session.mount('https://', HTTPAdapter(max_retries=retry))

    # 【安全增强】锁定 PC 端 UA，防止被重定向到手机版网页导致解析失败
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": target_url
    }

    logging.info(f"🕷️ 开始访问网页，目标获取前 {max_items} 条新闻...")
    
    try:
        response = session.get(target_url, headers=headers, timeout=10)
        response.raise_for_status() 
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")

        # 【核心升级】遍历多个容器，兼容左右两列
        all_items = []
        for ul_class in LIST_CONTAINER_CLASSES:
            ul = soup.find("ul", class_=ul_class)
            if ul:
                all_items.extend(ul.find_all(NEWS_ITEM_TAG))

        if not all_items:
            logging.warning(f"未找到新闻列表容器，请检查配置。")
            return

        logging.info(f"共找到 {len(all_items)} 个新闻节点，开始解析...")

        for news in all_items:
            if item_count >= max_items:
                break
                
            # 1. 提取标题（兼容外层有 div.news-list-tt 和直接是 a 的两种情况）
            title_div = news.find("div", class_=TITLE_CONTAINER_CLASS)
            if title_div:
                title_tag = title_div.find("a")
            else:
                title_tag = news.find("a")

            # 2. 提取日期
            date_tag = news.find(DATE_TAG)

            if title_tag:
                title = clean_text(title_tag.text)
                link = title_tag.get("href")
                
                if not title or not link: 
                    continue
                
                # 3. 处理相对路径（防止缺失 http 导致链接打不开）
                if not link.startswith("http"):
                    domain = "/".join(target_url.split("/")[:3]) 
                    link = domain + "/" + link.lstrip("/")
                
                # 4. 容错处理：如果没有日期，填“未知”
                date = clean_text(date_tag.text) if date_tag else "未知"

                # 5. 入库去重 (利用 UNIQUE 约束)
                cursor.execute(
                    "INSERT OR IGNORE INTO news (title, date, link) VALUES (?, ?, ?)",
                    (title, date, link)
                )
                
                if cursor.rowcount > 0:
                    item_count += 1
                    logging.info(f"[{item_count}] 成功入库: {date} - {title[:20]}...")

    except Exception as e:
        logging.error(f"❌ 抓取失败: {e}")

    conn.commit()
    conn.close()
    logging.info(f"🎉 抓取完毕！本次共入库 {item_count} 条数据。")

if __name__ == "__main__":
    crawl_news(TARGET_URL, max_items=15)
