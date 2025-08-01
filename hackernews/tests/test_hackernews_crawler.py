from email.policy import default
from os import link
from pathlib import Path
import re, time
from unicodedata import category
import pytest
from playwright.sync_api import Page, expect, sync_playwright
from loguru import logger
from collections import defaultdict
from random import choice
import urllib.parse
from cachetools import cached, TTLCache, LRUCache, LFUCache
import tablib
import pendulum
from markdownify import markdownify as md # markdownify库用于将HTML转换为Markdown格式

cache = TTLCache(maxsize=128, ttl=60 * 30)  # 缓存大小为128, TTL为30分钟

# 添加文件控制器, 强行写入日志来绕过Pytest无法捕获输出的问题
logger.add("test_hackernews_crawler.log", rotation="1 MB")

url = "https://thehackernews.com"

navigation_bar_xpath = "xpath=/html/body/nav/div[2]/ul"

# 获取网站标题
def test_page_title(page: Page):
    # 在与页面元素交互前, 首先需要将page导航到指定的URL
    # 这被称作Navigating, 使用page.goto方法
    page.goto(url)
    # 使用playwright-pytest的expect断言来验证页面标题
    # 不使用正则表达式, 而是直接比较字符串, 要求完全一模一样是这个标题
    expect(page).to_have_title("The Hacker News | #1 Trusted Source for Cybersecurity News")
    
# 获取页面板块
def test_horizontal_section_exists(page: Page):
    page.goto(url)
    # 板块横栏所在的XPath为 /html/body/nav/div[2]/ul
    locator = page.locator('xpath=//ul[@class="cf menu-ul"]')
    # 断言该板块可见
    expect(locator).to_be_visible()
    # 检查板块中是否有Cyber Attacks的文本
    expect(locator).to_contain_text("Cyber Attacks")

# 定位Home导航元素
def test_get_home_locator(page: Page):
    page.goto(url)
    # 定位导航栏元素
    locator = page.locator(navigation_bar_xpath)
    home_locator = locator.get_by_text("Home")
    # 断言该元素可见
    expect(home_locator).to_be_visible()
    # 获取该元素的文本
    text = home_locator.inner_text()
    logger.info(f"Home locator text: {text}")
    # 获取该元素内的href属性
    href = home_locator.get_attribute("href")
    logger.info(f"Home locator href: {href}")
    
def test_get_all_category_attr(page: Page):
    logger.info("Starting to get all category attributes...")
    page.goto(url)
    # 定位导航栏元素
    locator = page.locator(navigation_bar_xpath)
    # 获取所有板块的文本
    categorys = locator.all_inner_texts()[0].strip().splitlines()
    # 遍历所有文本, 依次取出每一个li元素
    text_with_link = defaultdict(str)
    for category_elem in categorys:
        # 打印每个板块的文本
        logger.info(f"category_elem text: {category_elem}")
        # 获取每个板块的href属性
        category_elem_locator = locator.get_by_text(category_elem)
        href = category_elem_locator.get_attribute("href")
        # logger.info(f"category_elem href: {href}")
        text_with_link[category_elem] = href
    logger.info(f"All category_elem links: \n{text_with_link}")
    
def get_all_category_links(page: Page):
    logger.info("Starting to get all category links...")
    page.goto(url)
    # 定位导航栏元素
    locator = page.locator(navigation_bar_xpath)
    # 获取li列表中的所有a元素
    # 这里的locator('a')会返回所有li元素下的a标签
    categorys = locator.locator('a')
    # 遍历所有文本, 依次取出每一个li元素
    text_with_link = {
        # 获取每个a元素的文本内容和href属性
        category_elem.text_content(): category_elem.get_attribute("href") 
        for category_elem in categorys.all() if not category_elem.get_attribute("href").endswith('.html') 
        # 过滤掉以.html结尾的链接, 因为它们不是板块链接, 没有文章列表
    }
    text_with_link.pop('Webinars', None)  # 移除Webinars板块, 因为它没有文章列表
    text_with_link.pop('Contact Us', None)  # 移除Contact Us板块, 因为它没有文章列表
    return text_with_link

def test_get_random_category_article(page: Page):
    logger.info("Starting to get a random category article...")
    page.goto(url)
    # 获取所有板块链接
    category_links = get_all_category_links(page)
    # 随机选择一个板块
    random_category = choice(list(category_links.keys()))
    logger.info(f"Randomly selected category: {random_category}")
    # 获取该板块的链接
    category_link = category_links[random_category]
    logger.info(f"Category link: {category_link}")
    # 导航到该板块链接 (相对路径)
    if category_link != '/':
        # 如果链接是相对路径, 则需要将其转换为绝对路径
        category_link = urllib.parse.urljoin(url, category_link)
        # 使用page.goto方法导航到该链接
        page.goto(category_link)
    # 尝试定位到文章视窗 
    # 使用xpath的话由于每个页面中文章列表的位置都有所出入, 所以需要使用css选择器
    article_viewport = page.locator("div.blog-post")
    # 断言文章视窗可见
    # expect(article_viewport).to_be_visible()
    # 断不出来, 尝试断言文本并打印文本
    # expect(article_viewport).to_be_enabled() # 断不出来一点, 不知道到底定位到了什么
    article_texts = article_viewport.all_inner_texts()
    logger.info(f"Article texts in {random_category} category: \n{article_texts}")
    
def get_random_category_article_list(page: Page, categories: dict[str, str], table: tablib.Dataset):
    """
    获取随机板块的文章列表
    :param page: Playwright页面对象
    :param categories: 板块字典, 键为板块名称, 值为板块链接
    :return: 随机板块的文章列表
    """
    logger.info("Starting to get a random category article list...")
    # 随机选择一个板块
    random_category = choice(list(categories.keys()))
    logger.info(f"Randomly selected category: {random_category}")
    # 获取该板块的链接
    category_link = categories['Home'] # 先写死, 后面再改
    logger.info(f"Category link: {category_link}")
    # 导航到该板块链接 (相对路径)
    if category_link != '/':
        # 如果链接是相对路径, 则需要将其转换为绝对路径
        category_link = urllib.parse.urljoin(url, category_link)
        # 使用page.goto方法导航到该链接
        page.goto(category_link)
    # 尝试定位到文章视窗
    article_viewport = page.locator(r'//div[@class="body-post clear"]')
    # 高亮显示文章视窗
    # article_viewport.highlight()
    logger.info(f"Highlighted article viewport in {random_category} category.")
    # 打印元素个数
    article_count = article_viewport.count()
    logger.info(f"Number of articles in {random_category} category: {article_count}")
    for i in range(0, article_count, 1):
        # 获取每个文章的标题和链接
        # 依次高亮每个子元素
        curr_article = article_viewport.nth(i)
        curr_article.highlight()
        logger.info(f"Highlighted article {i + 1} in {random_category} category.")
        # 获取文章链接、标题、标签和描述(节选一部分打印出来)
        # 不从根节点开始寻找, 而是从article_viewport开始寻找
        article_link = curr_article.locator('xpath=./a[@class="story-link"]').get_attribute('href')
        # article_link = None # 先置空,这个取不出来
        # 查找标题这里不能用./，因为./只能查找一级子节点 # 而标题是在三级子节点里
        article_title = curr_article.locator('xpath=//h2[@class="home-title"]').inner_text()
        article_label = curr_article.locator('xpath=//div[@class="item-label"]')
        article_datetime = article_label.locator('xpath=./span[@class="h-datetime"]').inner_text() if article_label else "N/A"
        # 如果没有标签, 则设置为N/A
        try:
            article_tags = article_label.locator('xpath=./span[@class="h-tags"]').inner_text(timeout=3000) if article_label else "N/A"
        except Exception as e:
            logger.error(f"Error getting article tags: {e}")
            article_tags = "N/A"
        # article_datetime = curr_article.locator('xpath=//span[@class="h-datetime"]').inner_text() 
        #article_tags = curr_article.locator('xpath=//span[@class="h-tags"]').inner_text()
        article_desc = curr_article.locator('xpath=//div[@class="home-desc"]').inner_text()[:50]  # 截取前50个字符
        table.append([
            article_link, 
            article_title, 
            article_datetime, 
            article_tags, 
            article_desc
        ])
        time.sleep(1)  # 等待1秒, 防止运行太快造成卡顿
        # input("Press Enter to highlight the next article...")
        # article_title = article.locator('h2').inner_text()
    input("Press Enter to exit after highlighting the article viewport...")
    
# 二次重构上面的函数
def get_single_page_category_article_list(page: Page, category_name: str, category_link: str, table: tablib.Dataset):
    """
    获取单个板块的文章列表
    :param page: Playwright页面对象
    :param category_link: 板块链接
    :param table: tablib数据集对象
    """
    logger.info(f"Getting article list for category link: {category_link}")
    # 导航到该板块链接 (相对路径)
    if category_link != '/':
        # 如果链接是相对路径, 则需要将其转换为绝对路径
        category_link = urllib.parse.urljoin(url, category_link)
        # 使用page.goto方法导航到该链接
        page.goto(category_link)
    # 尝试定位到文章视窗
    article_viewport = page.locator(r'//div[@class="body-post clear"]')
    
    # 因为playwright内部仍然是异步的, 所以下面要重写tqdm的使用方式
    with tqdm(total=article_viewport.count(), desc=f"Processing articles in {category_name}") as pbar:
        for link_idx in range(article_viewport.count()):
            # 获取每个文章的标题和链接
            # 依次高亮每个子元素
            curr_article = article_viewport.nth(link_idx)
            pbar.update(1) # 更新进度条
            curr_article.highlight()
            logger.info(f"Highlighted article {link_idx + 1} in {category_name} category.")
            # 获取文章链接、标题、标签和描述(节选一部分打印出来)
            # 不从根节点开始寻找, 而是从article_viewport开始寻找
            # 使用//查找当前位置下的所有节点
            article_link = curr_article.locator('xpath=./a[@class="story-link"]').get_attribute('href')
            # 把上面的东西原样拿下来
            article_title = curr_article.locator('xpath=//h2[@class="home-title"]').inner_text()
            article_label = curr_article.locator('xpath=//div[@class="item-label"]')
            article_datetime = article_label.locator('xpath=./span[@class="h-datetime"]').inner_text() if article_label else "N/A"
            # 使用.count判断要不要执行
            if article_label.count() > 0:
                try:
                    article_tags = article_label.locator('xpath=./span[@class="h-tags"]').inner_text(timeout=3000)
                except Exception as e:
                    tqdm.write(f"Error getting article tags: {e}") 
                    # 使用tqdm.write而不是logger.error, 避免干扰进度条显示
                    article_tags = "N/A"
            else:
                article_tags = "不存在标签"
            # 最后是描述
            article_desc = curr_article.locator('xpath=//div[@class="home-desc"]').inner_text()[:50]  # 截取前50个字符
            table.append([
                category_name,
                article_link,
                article_title,
                article_datetime,
                article_tags,
                article_desc
            ])
            
def test_newer_link_button_exists(page: Page):
    """
    测试是否存在Newer Link和Older Link按钮
    :param page: Playwright页面对象
    """
    page.goto(url)
    # 定位Newer Link按钮
    newer_link_button = page.locator('xpath=//a[@title="Newer Posts"]')
    # 断言该按钮可见
    expect(newer_link_button).to_be_visible()
    # 获取按钮的文本
    button_text = newer_link_button.inner_text()
    logger.info(f"Newer Link button text: {button_text}")

    # 定位Older Link按钮
    older_link_button = page.locator('xpath=//a[@title="Older Posts"]')
    # 断言该按钮可见
    expect(older_link_button).to_be_visible()
    # 获取按钮的文本
    button_text = older_link_button.inner_text()
    logger.info(f"Older Link button text: {button_text}")
    
def real_test_link_button_exists(page: Page):
    # 导航到url
    page.goto(url)
    # 先定位Newer Posts按钮并高亮
    try:
        # link_button = page.locator('xpath=//span[@id="blog-pager-older-link"]')
        link_button = page.get_by_text('Next Page')
        while True:
            logger.debug("Try to highlight Newer Posts button.")
            # 这里的class名称有点反直觉
            # 下一页里的是更老的文章
            
            # 注意到来到第二页后定位会失效
            # 因为page实例还没有解析好新一页的DOM树 # 要给page实例一点时间
            
            if link_button.count() > 0:
                # 先用断言确保按钮加载出来
                expect(link_button).to_be_visible()
                # expect会不断尝试直到按钮元素加载出来
                link_button.first.highlight()
                # 按下按键
                input("Newer Posts button found. clicking it by pressing enter...")
                link_button.first.click()
                logger.debug("Newer Posts button clicked.")
                # 显式刷新page
                page.reload()
                continue

            elif link_button.count() == 0:
                logger.warning("No Newer Posts button found.")
                # 使用.pause进入inspector交互模式
                page.pause()
                logger.debug("Exitted from inspector mode")
                break
    except Exception as e:
        logger.error(f"Error highlighting Newer Posts button: {e}")
    input("Press Enter to exit...")

def get_head_n_articles_in_every_category(n: int = 3):
    # 获取每个板块前n页各自的前n篇文章
    output_path = Path('./output')
    output_path.mkdir(parents=True, exist_ok=True)  # 确保输出目录存在
    
    with sync_playwright() as p:
        # 启动浏览器
        browser = p.chromium.launch(headless=False) # 设置headless=False以便可视化浏览器操作
        # 创建一个新的浏览器页面
        page = browser.new_page()
        logger.info("已启动浏览器, 正在获取所有板块链接...")
        
        # 先获取所有板块链接
        category_links = get_all_category_links(page)
        logger.info(f"获取到的所有板块链接: {category_links}")
        
        table = tablib.Dataset()
        table.headers = ['Category', 'Link', 'Title', 'Date', 'Label', 'Description']
        for category, link in category_links.items():
            logger.info(f"Processing category: {category} with link: {link}")
            # 获取单个板块的文章列表
            get_single_page_category_article_list(page, category, link, table)
    pass

def test_locate_posts_list_by_XPath(page: Page):
    page.goto(url)
    posts_list = page.locator(r'//div[@class="body-post clear"]')
    # expect(posts_list).to_be_visible() 
    # 这里获得的是可通过nth遍历的抽象容器，不能断言是否可见
    logger.info(f"posts_list count: {posts_list.count()}")

def test_locate_posts_list_by_CSS(page: Page):
    page.goto(url)
    posts_list = page.locator('.blog-posts').locator('.body-post')
    # posts = posts_list.locator('.body-post')
    posts = posts_list
    logger.info(f"posts_list count before: {posts.count()}")
    expect(posts.last).to_be_visible(timeout=30 * 1000)
    logger.info(f"posts_list count after: {posts.count()}")
    

if __name__ == '__main__':
    # 启动playwright上下文管理器
    with sync_playwright() as p:
        # 启动浏览器
        browser = p.chromium.launch(headless=False)  # 设置headless=False以便可视化浏览器操作
        # 创建一个新的浏览器页面
        page = browser.new_page()
        try:
            if False:
                # 获取分板块的文本和链接
                category_links = get_all_category_links(page)
                category_links.pop('Webinars', None)  # 移除Webinars板块, 因为它没有文章列表
                # 高亮显示随机板块的文章列表
                table = tablib.Dataset()
                table.headers = ['Category', 'Link', 'Title', 'Date', 'Label', 'Description']
                for category_name, category_link in category_links.items():
                    logger.info(f"Processing category: {category_name} with link: {category_link}")
                    # 获取单个板块的文章列表
                    get_single_page_category_article_list(page, category_name, category_link, table)
                output_xlsx = table.export('xlsx')
                # 使用pendulum获取当前时间
                current_time = pendulum.now().format('YYYY-MM-DD_HH-mm-ss')
                # 保存为xlsx文件
                with open(f'hackernews_articles_{current_time}.xlsx', 'wb') as f:
                    # 这里写入文件时tablib或者说excel会先在目录中生成一个`~$xxx`的文件
                    # 这是Excel读取或创建文件时生成的文件锁
                    # 如果看到这个临时文件残留在了文件列表里, 那么无需担心, 只要最终生成的文件是正常的就行
                    f.write(output_xlsx)
                    # 最新发现, 原来临时文件残留是因为我后台挂着WPS导致的, 
                    # 所以我把WPS关了, 就没问题了
            elif False:
                real_test_link_button_exists(page)
            elif True:
                test_locate_posts_list_by_XPath(page)
                test_locate_posts_list_by_CSS(page)
            
        except KeyboardInterrupt:
            logger.info("Test interrupted by user (Ctrl+C).")
            # 捕获Ctrl+C中断, 以便在测试过程中可以手动停止
            browser.close()
            exit(1) # 浏览器关闭后可以退出程序了
            
        # 关闭浏览器
        browser.close()
    