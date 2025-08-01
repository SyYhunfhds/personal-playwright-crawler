from typing import Any, Generator
from venv import logger
from playwright.sync_api import Page, expect, sync_playwright
import pytest
from random import choice, randint
from time import sleep
from pendulum import now

import sys
from pathlib import Path
sys.path.append("F:\\CodePractice\\playwright-crawler")
from hackernews.crawler import HackerNewsCrawler

# 使用Pytest fixture固定HackerNewsCrawler实例
@pytest.fixture(scope="module")
def hacker_news_crawler(page: Page) -> Generator[HackerNewsCrawler, Any, None]:
    crawler = HackerNewsCrawler(page=page)
    yield crawler

def test_categories(hacker_news_crawler):
    categories = hacker_news_crawler.get_menu_unordered_list()
    expect(categories).to_contain_text("Cyber Attacks")
    
# Pytest扫描不到环境, 自能自己创建
if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # 启动浏览器
        context = browser.new_context()
        page = context.new_page()
        hacker_news_crawler = HackerNewsCrawler(page=page)
        
        # 执行测试 (没报错就说明能用)
        try:
            if True:
                hacker_news_crawler.get_menu_unordered_list() # 获取菜单无序列表
                links = hacker_news_crawler.get_category_links()
                for category, link in links.items():
                    print(f"Category: {category}, Link: {link}")
                for _ in range(3):
                    random_category = choice(list(links.keys()))
                    print(f"随机选择的分区: {random_category}, 链接: {links[random_category]}")
                    hacker_news_crawler._goto_new_page(links[random_category])
                    togo_next_pages = randint(1, 3) # 翻到某一页后读取那一页的文章列表
                    for _ in range(togo_next_pages):
                        hacker_news_crawler._goto_next_page()
                    hacker_news_crawler.get_article_list(random_category)
                
                table = hacker_news_crawler._move_article_list()
                
                output_filename = now().format("YYYYMMDD_HHmmss")
                output_xlsx = table.export('xlsx')
                logger.debug("正在生成Excel文件以用于后面的测试")
                with open(Path(__file__).parent / f"test_{output_filename}.xlsx", mode="wb") as f:
                    f.write(output_xlsx)
                logger.info(f"已导出xlsx文件, 文件名为test_{output_filename}.xlsx.")
                hacker_news_crawler.save_article()
            elif False:
                url = "https://thehackernews.com"
                page.goto(url)
                page.pause()
        except KeyboardInterrupt:
            logger.info("测试被用户中断")
        
        logger.info("测试完成, 关闭浏览器...")
        
        # 关闭浏览器
        context.close()
        browser.close()