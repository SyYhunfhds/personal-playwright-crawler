# 标准模块
from genericpath import exists
from pathlib import Path # Python3路径解析库
from collections import defaultdict # 默认字典
from time import sleep
from turtle import pos
from typing import Literal
from unicodedata import category
import urllib.parse # URL解析库
from queue import Queue # 线程安全, 用于缓存数据行

# 第三方模块
import playwright
from playwright.sync_api import Page, expect, sync_playwright # Playwright同步API
import tablib, pendulum # Tablib用于数据表格处理，Pendulum用于日期时间处理
from alive_progress import alive_bar # 进度条库
from markdownify import markdownify as md # markdownify库用于将HTML转换为Markdown格式
from loguru import logger # 日志库
from cachetools import cached, TTLCache # 缓存库

timeout = 3000
expect.set_options(timeout=timeout) # 设置Playwright的超时时间为3000毫秒

max_size = 256
ttl = 60 * 60 # 缓存过期时间为1小时
cache = TTLCache(maxsize=max_size, ttl=ttl)

output_path = Path(__file__).parent / 'output' # 输出路径
output_path.mkdir(parents=True, exist_ok=True) # 创建输出目录

log_path = Path(__file__).parent / 'logs' # 日志路径
log_path.mkdir(parents=True, exist_ok=True) # 创建日志目录
# 添加文件控制器
logger.add(log_path / 'crawler.log', rotation='1 MB', retention='7 days', level='INFO') # 设置日志文件

# 后面必要的常量
target = "https://thehackernews.com"
article_headers = [
    "分区", "链接", "标题", "日期", "标签", "描述", "页码"
]
table = tablib.Dataset()
table.headers = article_headers

class HackerNewsCrawler:
    def __init__(self,
                 enable_random_sleep: bool = False,  # 是否启用随机睡眠
                 page: Page = None,  # Playwright页面对象
                 table: tablib.Dataset = table # tablib数据表格用于文章列表存储
                 ):
        self.enable_random_sleep = enable_random_sleep
        self.page = page
        self.page.goto(target) # 访问目标网站
        logger.info(f"已访问目标网站: {target}")
        
        # 初始化各种选择器和临时变量
        self._category_locator = None # 板块横栏的无序列表选择器
        self._category_links = defaultdict(str) # 板块横栏的链接dict
        self._page_index = 1 # 当前页码索引
        self._is_last_page = False # 是否是最后一页
        self._posts_list = table # 文章列表
        self._queue = Queue() # 用于缓存数据行的队列

    def get_menu_unordered_list(self):
        """
        获取板块横栏的无序列表
        :param page: Playwright页面对象
        :return: 无序列表的Locator分区对象, 已调用all处理, 可以遍历处理
        """
        # 板块横栏所在的XPath为 //ul[@class="cf menu-ul"]
        logger.debug("正在获取所有分区的无序列表的选择器...")
        # self.page.pause()  # 暂停页面加载
        locator = self.page.locator('xpath=//ul[@class="cf menu-ul"]')
        expect(locator).to_be_visible()  # 确保无序列表可见(能够解析出来)
        self._category_locator = locator.locator('a').all()  
        # 获取无序列表下的所有a标签
        logger.info(f"已获取到分区的无序列表选择器, 共有{len(self._category_locator)}个分区")
        return self._category_locator  # 兼容链式调用

    def get_category_links(self):
        """
        获取Cyber Attacks板块的链接
        :param page: Playwright页面对象
        :return: dict[str, str] Cyber Attacks板块的链接
        """
        # 获取无序列表内分区的个数 # 相信调用者已经执行了get_menu_unordered_list方法
        category_count = len(self._category_locator)
        categories = self._category_locator # 这里应该已经定位到了分区列表上
        # categories.highlight()  # 高亮显示当前分区列表
        # self.page.pause()  # 暂停页面加载, 方便调试
        # 返回父容器下的所有a标签容器
        logger.debug(f"正在获取{category_count}个分区的链接...")
        
        links = {
            category.inner_text(): category.get_attribute('href')
            for category in categories if not category.get_attribute("href").endswith('.html')
            # 过滤掉以.html结尾的链接 # 这些单页面的分区没有文章列表, 不是爬取目标
        }
        links.pop('Webinars', None)  # 移除Webinars分区, 因为它不是文章列表
        links.pop('Contact', None)  # 移除Contact分区, 因为它不是文章列表
        self._category_links = links  # 保存链接到实例变量
        logger.info(f"已获取到{len(tuple(links.keys()))}个分区的链接, \
            剔除了不存在文章列表的分区")
        return links

    def _goto_new_page(self, direction: str):
        """跳转到新页面
        Args:
            direction (str): 目标页面的新路径(手动进行路径拼接处理)
        """
        # 先拼接路径
        if direction.startswith('http://') or direction.startswith('https://'):
            new_url = direction
        else:
            new_url = urllib.parse.urljoin(target, direction)
        logger.debug(f"正在跳转到新页面: {new_url}")
        self.page.goto(new_url)  # 跳转到新页面
        self._page_index = 1 # 重置页码
        logger.info(f"已跳转到新页面: {new_url}")
    
    def _goto_next_page(self):
        """
        跳转到下一页
        :param page: Playwright页面对象
        :return: Page对象
        """
        
        next_page_button = self.page.get_by_text("Next Page")
        logger.debug("正在跳转到下一页...")
        try:
            expect(next_page_button).to_be_visible() # 全局设置为3秒超时时间
            next_page_button.click()
            self._page_index += 1
            logger.info(f"已跳转到第{self._page_index}页")
        except AssertionError:
            logger.warning("已到达最后一页或下一页按钮不可见")
            # self._is_last_page = True  # 设置为最后一页
        
        return self.page

    def _goto_prev_page(self):
        """
        跳转到上一页
        :param page: Playwright页面对象
        :return: None
        """
        
        prev_page_button = self.page.get_by_text("Prev Page")
        logger.debug("正在跳转到上一页...")
        try:
            expect(prev_page_button).to_be_visible()  # 全局设置为3秒超时时间
            prev_page_button.click()
            self._page_index -= 1
            logger.info(f"已跳转到第{self._page_index}页")
        except AssertionError:
            logger.warning("上一页按钮不可见或已到达第一页")
        return self.page

    def get_article_list(self, category: str):
        """
        获取单个分区单页的文章列表
        :param page: Playwright页面对象
        :return: 文章列表
        """
        page = self._page_index
        # 定位到列表视窗
        '''
        测试时发现很容易定位不到, 这就很难绷了
        '''
        logger.debug("正在使用XPath定位到文章列表容器...")
        posts_list_locator = self.page.locator('.blog-posts').locator('.body-post')
        posts = posts_list_locator
        # 用.last作为标志确保文章列表全部加载完成
        expect(posts.last).to_be_visible(timeout=30 * 1000)
        if posts_list_locator.count() == 0:
            logger.warning("无法找到文章列表容器, 将返回空表格...")
            return table
        '''try:
            posts_list_locator.highlight()
        except Exception as e:
            logger.error(f"尝试高亮文章列表时发生错误: {e}")
            return None'''
        # input("请按下回车键处理当前文章列表的信息...")
        expect(posts_list_locator.last).to_be_visible(timeout=30 * 1000)
        logger.info(f"正在获取{category}分区第{page}页的文章列表, 预计有{posts_list_locator.count()}篇文章...")
        for post_idx in range(posts_list_locator.count()):
            curr = posts_list_locator.nth(post_idx)
            # curr.highlight()
            # input("请按下回车键处理当前文章的信息...")
            sleep(0.5) # 等待0.5秒, 防止过快点击导致页面卡顿
            link = curr.locator('xpath=./a[@class="story-link"]').get_attribute('href')
            title = curr.locator('xpath=//h2[@class="home-title"]').inner_text()
            desc = curr.locator('xpath=//div[@class="home-desc"]').inner_text()[:50]  # 截取前50个字符
            label = curr.locator('xpath=//div[@class="item-label"]')
            tags = label.locator('xpath=./span[@class="h-tags"]')
            tags = tags.inner_text() if tags.count() > 0 else '空 / 文章未设置标签'
            post_date = label.locator('xpath=./span[@class="h-datetime"]').inner_text()

            self._queue.put(
                [
                    category,
                    link,
                    title,
                    post_date,
                    tags,
                    desc,
                    page
                ]
            )
        logger.info(f"已获取到{category}分区第{page}页的文章列表, 共计{posts_list_locator.count()}篇")
        
    def _move_article_list(self): 
        # 在执行完爬取链接任务后调用这个方法转移数据
        while not self._queue.empty():
            table.append(self._queue.get())
        table.remove_duplicates() # 去除重复行
        return table
            
    # 推荐用PDF格式, 
    # MD格式导出时由于没有单独剔出文章部分，会导致导出格式变得很混乱
    def save_article(self, 
                     output_mode: Literal["markdown", "html", "pdf"] = 'pdf',
                     ):
        """保存文章到本地
        Args:
            output_mode (str, optional): 导出格式, 默认为markdown、html或pdf
        """
        
        def _safe_load_page(post: list):
            category, url, title = post[0], post[1], post[2]
            category, title = category.replace(' ', '-'), title.replace(' ', '-')
            logger.debug(f"正在打开{url}页面...")
            self.page.goto(url)
            logger.info(f"{url}页面打开成功")
            # logger.debug(f"等待{url}页面加载完成...")
            # self.page.wait_for_load_state('networkidle')
            logger.info(f"{url}页面加载完成")
            return self.page

        
        def _save_md_post(post, page: Page):
                category, url, title = post[0], post[1], post[2]
                category, title = category.replace(' ', '-'), title.replace(' ', '-')
                try:
                    page = _safe_load_page(post)
                except playwright._impl._errors.TimeoutError as e:
                    logger.error(f"打开{url}页面时发生超时异常: {e}")
                    return False
                except Exception as e:
                    logger.error(f"打开{url}页面时发生异常: {e}")
                    return False
                
                page_html = page.content()
                with open(output_path/ category / f"{title}.md", 'w', encoding='utf-8') as f:
                    f.write(md(page_html))
                    logger.info(f"{url}页面保存为Markdown成功")

                return True
        
        def _save_html_post(post, page: Page):
                category, url, title = post[0], post[1], post[2]
                category, title = category.replace(' ', '-'), title.replace(' ', '-')
                try:
                    page = _safe_load_page(post)
                except playwright._impl._errors.TimeoutError as e:
                    logger.error(f"打开{url}页面时发生超时异常: {e}")
                    return False
                except Exception as e:
                    logger.error(f"打开{url}页面时发生异常: {e}")
                    return False
                page_html = self.page.content()
                with open(output_path/ category / f"{title}.html", 'w', encoding='utf-8') as f:
                    f.write(page_html)
                    logger.info(f"{post[1]}页面保存为html成功")

                return True
        
        def _save_pdf_post(post, page: Page):
                category, url, title = post[0], post[1], post[2]
                category, title = category.replace(' ', '-'), title.replace(' ', '-')
                try:
                    page = _safe_load_page(post)
                except playwright._impl._errors.TimeoutError as e:
                    logger.error(f"打开{url}页面时发生超时异常: {e}")
                    return False
                except Exception as e:
                    logger.error(f"打开{url}页面时发生异常: {e}")
                    return False
                page_pdf = self.page.pdf()
                with open(output_path/ category / f"{title}.pdf", 'wb') as f:
                    f.write(page_pdf)
                    logger.info(f"{post[1]}页面保存为PDF成功")

                return True
        
        # 调用模块作用域范围内的tablib表格取出链接
        # 先对分区进行去重
        categories = table['分区']
        categories = list(set(categories))
        for category in categories:
            # 一个一个创建目录
            output_dir = output_path / category.replace(' ', '-')
            output_dir.mkdir(parents=True, exist_ok=True)
        
        output_methods = {
            'markdown': _save_md_post,
            'html': _save_html_post,
            'pdf': _save_pdf_post
        }
        curr_output_method =  output_methods[output_mode.lower()]
        logger.debug(f"开始保存文章, 导出模式为{output_mode}...")
        logger.debug(f"共{len(table)}篇文章需要保存...")
        with alive_bar(len(table), bar='blocks', spinner='elements') as bar:
            for post in table:
                try:
                    if not curr_output_method(post, self.page):
                        logger.warning(f"{post[1]}页面保存失败")
                except Exception as e:
                    logger.error(f"{post[1]}页面保存失败, 错误信息: {e}")
                bar()