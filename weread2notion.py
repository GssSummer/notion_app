# weread2notion.py
"""
微信读书 → Notion 同步工具
合并版：包含所有核心功能
"""

import os
import re
import json
import hashlib
import time
import logging
import calendar
import requests
from datetime import datetime, timedelta
from requests.utils import cookiejar_from_dict
from dotenv import load_dotenv

import pendulum
from retrying import retry
from notion_client import Client

# 加载环境变量
load_dotenv()

# ==================== 配置常量 ====================

RICH_TEXT = "rich_text"
URL = "url"
RELATION = "relation"
NUMBER = "number"
DATE = "date"
FILES = "files"
STATUS = "status"
TITLE = "title"
SELECT = "select"

book_properties_type_dict = {
    "书名": TITLE,
    "BookId": RICH_TEXT,
    "ISBN": RICH_TEXT,
    "链接": URL,
    "作者": RELATION,
    "Sort": NUMBER,
    "评分": NUMBER,
    "封面": FILES,
    "分类": RELATION,
    "阅读状态": STATUS,
    "阅读时长": NUMBER,
    "阅读进度": NUMBER,
    "阅读天数": NUMBER,
    "时间": DATE,
    "开始阅读时间": DATE,
    "最后阅读时间": DATE,
    "简介": RICH_TEXT,
    "书架分类": SELECT,
    "我的评分": SELECT,
    "豆瓣链接": URL,
}

tz = 'Asia/Shanghai'
MAX_LENGTH = 1024

# 图标 URL
TAG_ICON_URL = "https://www.notion.so/icons/tag_gray.svg"
USER_ICON_URL = "https://www.notion.so/icons/user-circle-filled_gray.svg"
TARGET_ICON_URL = "https://www.notion.so/icons/target_red.svg"
BOOKMARK_ICON_URL = "https://www.notion.so/icons/bookmark_gray.svg"
BOOK_ICON_URL = "https://www.notion.so/icons/book_gray.svg"

WEREAD_URL = "https://weread.qq.com/"
WEREAD_NOTEBOOKS_URL = "https://i.weread.qq.com/user/notebooks"
WEREAD_BOOKMARKLIST_URL = "https://i.weread.qq.com/book/bookmarklist"
WEREAD_CHAPTER_INFO = "https://i.weread.qq.com/book/chapterInfos"
WEREAD_READ_INFO_URL = "https://i.weread.qq.com/book/readinfo"
WEREAD_REVIEW_LIST_URL = "https://i.weread.qq.com/review/list"
WEREAD_BOOK_INFO = "https://i.weread.qq.com/book/info"

rating = {"poor": "⭐️", "fair": "⭐️⭐️⭐️", "good": "⭐️⭐️⭐️⭐️⭐️"}

# ==================== 工具函数 ====================

def get_heading(level, content):
    if level == 1:
        heading = "heading_1"
    elif level == 2:
        heading = "heading_2"
    else:
        heading = "heading_3"
    return {
        "type": heading,
        heading: {
            "rich_text": [{"type": "text", "text": {"content": content[:MAX_LENGTH]}}],
            "color": "default",
            "is_toggleable": False,
        },
    }

def get_table_of_contents():
    return {"type": "table_of_contents", "table_of_contents": {"color": "default"}}

def get_title(content):
    return {"title": [{"type": "text", "text": {"content": content[:MAX_LENGTH]}}]}

def get_rich_text(content):
    return {"rich_text": [{"type": "text", "text": {"content": content[:MAX_LENGTH]}}]}

def get_url(url):
    return {"url": url}

def get_file(url):
    return {"files": [{"type": "external", "name": "Cover", "external": {"url": url}}]}

def get_multi_select(names):
    return {"multi_select": [{"name": name} for name in names]}

def get_relation(ids):
    return {"relation": [{"id": id} for id in ids]}

def get_date(start, end=None):
    return {
        "date": {
            "start": start,
            "end": end,
            "time_zone": "Asia/Shanghai",
        }
    }

def get_icon(url):
    return {"type": "external", "external": {"url": url}}

def get_select(name):
    return {"select": {"name": name}}

def get_number(number):
    return {"number": number}

def get_quote(content):
    return {
        "type": "quote",
        "quote": {
            "rich_text": [{"type": "text", "text": {"content": content[:MAX_LENGTH]}}],
            "color": "default",
        },
    }

def get_block(content, block_type, show_color, style, colorStyle, reviewId):
    color = "default"
    if show_color:
        if colorStyle == 1:
            color = "red"
        elif colorStyle == 2:
            color = "purple"
        elif colorStyle == 3:
            color = "blue"
        elif colorStyle == 4:
            color = "green"
        elif colorStyle == 5:
            color = "yellow"
    
    block = {
        "type": block_type,
        block_type: {
            "rich_text": [{"type": "text", "text": {"content": content[:MAX_LENGTH]}}],
            "color": color,
        },
    }
    
    if block_type == "callout":
        emoji = "〰️"
        if style == 0:
            emoji = "💡"
        elif style == 1:
            emoji = "⭐"
        if reviewId is not None:
            emoji = "✍️"
        block[block_type]["icon"] = {"emoji": emoji}
    return block

def format_time(time_val):
    result = ""
    hour = time_val // 3600
    if hour > 0:
        result += f"{hour}时"
    minutes = time_val % 3600 // 60
    if minutes > 0:
        result += f"{minutes}分"
    return result

def format_date(date, fmt="%Y-%m-%d %H:%M:%S"):
    return date.strftime(fmt)

def timestamp_to_date(timestamp):
    return datetime.utcfromtimestamp(timestamp) + timedelta(hours=8)

def get_first_and_last_day_of_month(date):
    first_day = date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    _, last_day_of_month = calendar.monthrange(date.year, date.month)
    last_day = date.replace(day=last_day_of_month, hour=0, minute=0, second=0, microsecond=0)
    return first_day, last_day

def get_first_and_last_day_of_year(date):
    first_day = date.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day = date.replace(month=12, day=31, hour=0, minute=0, second=0, microsecond=0)
    return first_day, last_day

def get_first_and_last_day_of_week(date):
    first_day_of_week = (date - timedelta(days=date.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    last_day_of_week = first_day_of_week + timedelta(days=6)
    return first_day_of_week, last_day_of_week

def get_properties(dict1, dict2):
    properties = {}
    for key, value in dict1.items():
        prop_type = dict2.get(key)
        if value is None:
            continue
        property_val = None
        if prop_type == TITLE:
            property_val = {"title": [{"type": "text", "text": {"content": str(value)[:MAX_LENGTH]}}]}
        elif prop_type == RICH_TEXT:
            property_val = {"rich_text": [{"type": "text", "text": {"content": str(value)[:MAX_LENGTH]}}]}
        elif prop_type == NUMBER:
            property_val = {"number": number}
        elif prop_type == STATUS:
            property_val = {"status": {"name": value}}
        elif prop_type == FILES:
            property_val = {"files": []}
        elif prop_type == DATE:
            property_val = {
                "date": {
                    "start": pendulum.from_timestamp(value, tz="Asia/Shanghai").to_datetime_string(),
                    "time_zone": "Asia/Shanghai",
                }
            }
        elif prop_type == URL:
            property_val = {"url": value}
        elif prop_type == SELECT:
            property_val = {"select": {"name": value}}
        elif prop_type == RELATION:
            property_val = {"relation": [{"id": id} for id in value]}
        if property_val:
            properties[key] = property_val
    return properties

def get_property_value(property):
    prop_type = property.get("type")
    content = property.get(prop_type)
    if content is None:
        return None
    if prop_type in ("title", "rich_text"):
        if len(content) > 0:
            return content[0].get("plain_text")
        return None
    elif prop_type in ("status", "select"):
        return content.get("name")
    elif prop_type == "files":
        if len(content) > 0 and content[0].get("type") == "external":
            return content[0].get("external").get("url")
        return None
    elif prop_type == "date":
        return str_to_timestamp(content.get("start"))
    return content

def str_to_timestamp(date_str):
    if date_str is None:
        return 0
    dt = pendulum.parse(date_str)
    return int(dt.timestamp())

def get_rich_text_from_result(result, name):
    return result.get("properties").get(name).get("rich_text")[0].get("plain_text")

def get_number_from_result(result, name):
    return result.get("properties").get(name).get("number")

# ==================== 微信读书 API ====================

class WeReadApi:
    def __init__(self):
        self.cookie = self.get_cookie()
        self.session = requests.Session()
        self.session.cookies = self.parse_cookie_string()

    def try_get_cloud_cookie(self, url, id, password):
        if url.endswith("/"):
            url = url[:-1]
        req_url = f"{url}/get/{id}"
        data = {"password": password}
        result = None
        response = requests.post(req_url, data=data)
        if response.status_code == 200:
            data = response.json()
            cookie_data = data.get("cookie_data")
            if cookie_data and "weread.qq.com" in cookie_data:
                cookies = cookie_data["weread.qq.com"]
                cookie_str = "; ".join([f"{cookie['name']}={cookie['value']}" for cookie in cookies])
                result = cookie_str
        return result

    def get_cookie(self):
        url = os.getenv("CC_URL")
        if not url:
            url = "https://cookiecloud.malinkang.com/"
        cc_id = os.getenv("CC_ID")
        password = os.getenv("CC_PASSWORD")
        cookie = os.getenv("WEREAD_COOKIE")
        if url and cc_id and password:
            cookie = self.try_get_cloud_cookie(url, cc_id, password)
        if not cookie or not cookie.strip():
            raise Exception("没有找到cookie，请按照文档填写cookie")
        return cookie

    def parse_cookie_string(self):
        cookies_dict = {}
        pattern = re.compile(r'([^=]+)=([^;]+);?\s*')
        matches = pattern.findall(self.cookie)
        for key, value in matches:
            cookies_dict[key] = value.encode('unicode_escape').decode('ascii')
        return cookiejar_from_dict(cookies_dict)

    def handle_errcode(self, errcode):
        if errcode in (-2012, -2010):
            print(f"::error::微信读书Cookie过期了，请参考文档重新设置。")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_bookshelf(self):
        self.session.get(WEREAD_URL)
        r = self.session.get("https://i.weread.qq.com/shelf/sync?synckey=0&teenmode=0&album=1&onlyBookid=0")
        if r.ok:
            return r.json()
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"Could not get bookshelf {r.text}")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_notebooklist(self):
        self.session.get(WEREAD_URL)
        r = self.session.get(WEREAD_NOTEBOOKS_URL)
        if r.ok:
            data = r.json()
            books = data.get("books")
            books.sort(key=lambda x: x["sort"])
            return books
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"Could not get notebook list {r.text}")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_bookinfo(self, bookId):
        self.session.get(WEREAD_URL)
        params = dict(bookId=bookId)
        r = self.session.get(WEREAD_BOOK_INFO, params=params)
        if r.ok:
            return r.json()
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            print(f"Could not get book info {r.text}")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_bookmark_list(self, bookId):
        self.session.get(WEREAD_URL)
        params = dict(bookId=bookId)
        r = self.session.get(WEREAD_BOOKMARKLIST_URL, params=params)
        if r.ok:
            bookmarks = r.json().get("updated")
            return bookmarks
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"Could not get {bookId} bookmark list")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_read_info(self, bookId):
        self.session.get(WEREAD_URL)
        params = dict(
            noteCount=1, readingDetail=1, finishedBookIndex=1,
            readingBookCount=1, readingBookIndex=1, finishedBookCount=1,
            bookId=bookId, finishedDate=1,
        )
        headers = {
            "baseapi": "32",
            "appver": "8.2.5.10163885",
            "basever": "8.2.5.10163885",
            "osver": "12",
            "User-Agent": "WeRead/8.2.5 WRBrand/xiaomi Dalvik/2.1.0 (Linux; U; Android 12; Redmi Note 7 Pro Build/SQ3A.220705.004)",
        }
        r = self.session.get(WEREAD_READ_INFO_URL, headers=headers, params=params)
        if r.ok:
            return r.json()
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"get {bookId} read info failed {r.text}")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_review_list(self, bookId):
        self.session.get(WEREAD_URL)
        params = dict(bookId=bookId, listType=11, mine=1, syncKey=0)
        r = self.session.get(WEREAD_REVIEW_LIST_URL, params=params)
        if r.ok:
            reviews = r.json().get("reviews")
            reviews = list(map(lambda x: x.get("review"), reviews))
            reviews = [{"chapterUid": 1000000, **x} if x.get("type") == 4 else x for x in reviews]
            return reviews
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"get {bookId} review list failed {r.text}")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_chapter_info(self, bookId):
        self.session.get(WEREAD_URL)
        body = {"bookIds": [bookId], "synckeys": [0], "teenmode": 0}
        r = self.session.post(WEREAD_CHAPTER_INFO, json=body)
        if (r.ok and "data" in r.json() and len(r.json()["data"]) == 1 
            and "updated" in r.json()["data"][0]):
            update = r.json()["data"][0]["updated"]
            update.append({
                "chapterUid": 1000000,
                "chapterIdx": 1000000,
                "updateTime": 1683825006,
                "readAhead": 0,
                "title": "点评",
                "level": 1,
            })
            return {item["chapterUid"]: item for item in update}
        else:
            raise Exception(f"get {bookId} chapter info failed {r.text}")

    def transform_id(self, book_id):
        id_length = len(book_id)
        if re.match("^\\d*$", book_id):
            ary = []
            for i in range(0, id_length, 9):
                ary.append(format(int(book_id[i:min(i + 9, id_length)]), "x"))
            return "3", ary
        result = ""
        for i in range(id_length):
            result += format(ord(book_id[i]), "x")
        return "4", [result]

    def calculate_book_str_id(self, book_id):
        md5 = hashlib.md5()
        md5.update(book_id.encode("utf-8"))
        digest = md5.hexdigest()
        result = digest[0:3]
        code, transformed_ids = self.transform_id(book_id)
        result += code + "2" + digest[-2:]
        for i in range(len(transformed_ids)):
            hex_length_str = format(len(transformed_ids[i]), "x")
            if len(hex_length_str) == 1:
                hex_length_str = "0" + hex_length_str
            result += hex_length_str + transformed_ids[i]
            if i < len(transformed_ids) - 1:
                result += "g"
        if len(result) < 20:
            result += digest[0:20 - len(result)]
        md5 = hashlib.md5()
        md5.update(result.encode("utf-8"))
        result += md5.hexdigest()[0:3]
        return result

    def get_url(self, book_id):
        return f"https://weread.qq.com/web/reader/{self.calculate_book_str_id(book_id)}"

# ==================== Notion Helper ====================

class NotionHelper:
    database_name_dict = {
        "BOOK_DATABASE_NAME": "魔法学院",
        "REVIEW_DATABASE_NAME": "笔记",
        "BOOKMARK_DATABASE_NAME": "划线",
        "DAY_DATABASE_NAME": "日",
        "WEEK_DATABASE_NAME": "周",
        "MONTH_DATABASE_NAME": "月",
        "YEAR_DATABASE_NAME": "年",
        "CATEGORY_DATABASE_NAME": "分类",
        "AUTHOR_DATABASE_NAME": "作者",
        "CHAPTER_DATABASE_NAME": "章节",
        "READ_DATABASE_NAME": "阅读记录",
        "SETTING_DATABASE_NAME": "设置",
    }
    
    def __init__(self):
        self.client = Client(auth=os.getenv("NOTION_TOKEN"), log_level=logging.ERROR)
        self.__cache = {}
        self.page_id = self.extract_page_id(os.getenv("NOTION_PAGE"))
        self.database_id_dict = {}
        self.show_color = True
        self.block_type = "callout"
        self.sync_bookmark = True
        
        self.search_database(self.page_id)
        
        for key in self.database_name_dict.keys():
            if os.getenv(key):
                self.database_name_dict[key] = os.getenv(key)
        
        # 按顺序获取或创建数据库
        self.author_database_id = self.get_or_create_database("AUTHOR_DATABASE_NAME", USER_ICON_URL)
        self.category_database_id = self.get_or_create_database("CATEGORY_DATABASE_NAME", TAG_ICON_URL)
        self.book_database_id = self.get_or_create_database("BOOK_DATABASE_NAME", BOOK_ICON_URL, is_main=True)
        self.review_database_id = self.get_or_create_database("REVIEW_DATABASE_NAME", TAG_ICON_URL)
        self.bookmark_database_id = self.get_or_create_database("BOOKMARK_DATABASE_NAME", BOOKMARK_ICON_URL)
        self.chapter_database_id = self.get_or_create_database("CHAPTER_DATABASE_NAME", TAG_ICON_URL)
        self.year_database_id = self.get_or_create_database("YEAR_DATABASE_NAME", TARGET_ICON_URL)
        self.month_database_id = self.get_or_create_database("MONTH_DATABASE_NAME", TARGET_ICON_URL)
        self.week_database_id = self.get_or_create_database("WEEK_DATABASE_NAME", TARGET_ICON_URL)
        self.day_database_id = self.get_or_create_database("DAY_DATABASE_NAME", TARGET_ICON_URL)
        self.read_database_id = self.get_or_create_database("READ_DATABASE_NAME", TARGET_ICON_URL)
        self.setting_database_id = self.get_or_create_database("SETTING_DATABASE_NAME", "https://www.notion.so/icons/gear_gray.svg")
        
        if self.setting_database_id:
            self.insert_to_setting_database()

    def extract_page_id(self, notion_url):
        match = re.search(r"([a-f0-9]{32}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})", notion_url)
        if match:
            return match.group(0)
        raise Exception(f"获取NotionID失败，请检查输入的Url是否正确")

    def search_database(self, block_id):
        children = self.client.blocks.children.list(block_id=block_id)["results"]
        for child in children:
            if child["type"] == "child_database":
                self.database_id_dict[child.get("child_database").get("title")] = child.get("id")
            if "has_children" in child and child["has_children"]:
                self.search_database(child["id"])

    def get_or_create_database(self, env_key, icon_url, is_main=False):
        name = self.database_name_dict.get(env_key)
        db_id = self.database_id_dict.get(name)
        
        if db_id:
            print(f"找到数据库: {name}")
            return db_id
        
        print(f"创建数据库: {name}")
        
        if is_main:
            return self.create_book_database(name, icon_url)
        else:
            return self.create_simple_database(name, icon_url)

    def create_simple_database(self, name, icon_url):
        title = [{"type": "text", "text": {"content": name}}]
        properties = {"标题": {"title": {}}}
        parent = {"page_id": self.page_id, "type": "page_id"}
        database = self.client.databases.create(
            parent=parent, title=title, icon=get_icon(icon_url), properties=properties
        )
        self.database_id_dict[name] = database.get("id")
        return database.get("id")

    def create_book_database(self, name, icon_url):
        title = [{"type": "text", "text": {"content": name}}]
        properties = {
            "书名": {"title": {}},
            "BookId": {"rich_text": {}},
            "ISBN": {"rich_text": {}},
            "链接": {"url": {}},
            "Sort": {"number": {}},
            "评分": {"number": {}},
            "封面": {"files": {}},
            "阅读状态": {"status": {"options": [{"name": "想读", "color": "gray"}, {"name": "在读", "color": "blue"}, {"name": "已读", "color": "green"}]}},
            "阅读时长": {"number": {}},
            "阅读进度": {"number": {"format": "percent"}},
            "阅读天数": {"number": {}},
            "时间": {"date": {}},
            "开始阅读时间": {"date": {}},
            "最后阅读时间": {"date": {}},
            "简介": {"rich_text": {}},
            "书架分类": {"select": {}},
            "我的评分": {"select": {"options": [{"name": "⭐️"}, {"name": "⭐️⭐️⭐️"}, {"name": "⭐️⭐️⭐️⭐️⭐️"}, {"name": "未评分"}]}},
            "豆瓣链接": {"url": {}},
        }
        parent = {"page_id": self.page_id, "type": "page_id"}
        database = self.client.databases.create(
            parent=parent, title=title, icon=get_icon(icon_url), properties=properties
        )
        db_id = database.get("id")
        self.database_id_dict[name] = db_id
        return db_id

    def update_book_database(self):
        if not self.book_database_id:
            return
        response = self.client.databases.retrieve(database_id=self.book_database_id)
        db_id = response.get("id")
        properties = response.get("properties")
        update_properties = {}
        
        if properties.get("阅读时长") is None or properties.get("阅读时长").get("type") != "number":
            update_properties["阅读时长"] = {"number": {}}
        if properties.get("书架分类") is None or properties.get("书架分类").get("type") != "select":
            update_properties["书架分类"] = {"select": {}}
        if properties.get("豆瓣链接") is None or properties.get("豆瓣链接").get("type") != "url":
            update_properties["豆瓣链接"] = {"url": {}}
        if properties.get("我的评分") is None or properties.get("我的评分").get("type") != "select":
            update_properties["我的评分"] = {"select": {}}
        if properties.get("豆瓣短评") is None or properties.get("豆瓣短评").get("type") != "rich_text":
            update_properties["豆瓣短评"] = {"rich_text": {}}
        
        if update_properties:
            self.client.databases.update(database_id=db_id, properties=update_properties)

    def create_database(self):
        title = [{"type": "text", "text": {"content": self.database_name_dict.get("READ_DATABASE_NAME")}}]
        properties = {
            "标题": {"title": {}},
            "时长": {"number": {}},
            "时间戳": {"number": {}},
            "日期": {"date": {}},
            "书架": {"relation": {"database_id": self.book_database_id, "single_property": {}}},
        }
        parent = {"page_id": self.page_id, "type": "page_id"}
        self.read_database_id = self.client.databases.create(
            parent=parent, title=title, icon=get_icon("https://www.notion.so/icons/target_gray.svg"),
            properties=properties
        ).get("id")

    def create_setting_database(self):
        title = [{"type": "text", "text": {"content": self.database_name_dict.get("SETTING_DATABASE_NAME")}}]
        properties = {
            "标题": {"title": {}},
            "NotinToken": {"rich_text": {}},
            "NotinPage": {"rich_text": {}},
            "WeReadCookie": {"rich_text": {}},
            "根据划线颜色设置文字颜色": {"checkbox": {}},
            "同步书签": {"checkbox": {}},
            "样式": {
                "select": {
                    "options": [
                        {"name": "callout", "color": "blue"},
                        {"name": "quote", "color": "green"},
                        {"name": "paragraph", "color": "purple"},
                        {"name": "bulleted_list_item", "color": "yellow"},
                        {"name": "numbered_list_item", "color": "pink"},
                    ]
                }
            },
            "最后同步时间": {"date": {}},
        }
        parent = {"page_id": self.page_id, "type": "page_id"}
        self.setting_database_id = self.client.databases.create(
            parent=parent, title=title, icon=get_icon("https://www.notion.so/icons/gear_gray.svg"),
            properties=properties
        ).get("id")

    def insert_to_setting_database(self):
        existing_pages = self.query(
            database_id=self.setting_database_id,
            filter={"property": "标题", "title": {"equals": "设置"}}
        ).get("results")
        
        properties = {
            "标题": {"title": [{"type": "text", "text": {"content": "设置"}}]},
            "最后同步时间": {"date": {"start": pendulum.now("Asia/Shanghai").isoformat()}},
            "NotinToken": {"rich_text": [{"type": "text", "text": {"content": os.getenv("NOTION_TOKEN")}}]},
            "NotinPage": {"rich_text": [{"type": "text", "text": {"content": os.getenv("NOTION_PAGE")}}]},
            "WeReadCookie": {"rich_text": [{"type": "text", "text": {"content": os.getenv("WEREAD_COOKIE")}}]},
        }
        
        if existing_pages:
            remote_properties = existing_pages[0].get("properties")
            self.show_color = get_property_value(remote_properties.get("根据划线颜色设置文字颜色"))
            self.sync_bookmark = get_property_value(remote_properties.get("同步书签"))
            self.block_type = get_property_value(remote_properties.get("样式"))
            page_id = existing_pages[0].get("id")
            self.client.pages.update(page_id=page_id, properties=properties)
        else:
            properties["根据划线颜色设置文字颜色"] = {"checkbox": True}
            properties["同步书签"] = {"checkbox": True}
            properties["样式"] = {"select": {"name": "callout"}}
            self.client.pages.create(parent={"database_id": self.setting_database_id}, properties=properties)

    def get_week_relation_id(self, date):
        year = date.isocalendar().year
        week = date.isocalendar().week
        week_str = f"{year}年第{week}周"
        start, end = get_first_and_last_day_of_week(date)
        properties = {"日期": get_date(format_date(start), format_date(end))}
        return self.get_relation_id(week_str, self.week_database_id, TARGET_ICON_URL, properties)

    def get_month_relation_id(self, date):
        month_str = date.strftime("%Y年%-m月")
        start, end = get_first_and_last_day_of_month(date)
        properties = {"日期": get_date(format_date(start), format_date(end))}
        return self.get_relation_id(month_str, self.month_database_id, TARGET_ICON_URL, properties)

    def get_year_relation_id(self, date):
        year_str = date.strftime("%Y")
        start, end = get_first_and_last_day_of_year(date)
        properties = {"日期": get_date(format_date(start), format_date(end))}
        return self.get_relation_id(year_str, self.year_database_id, TARGET_ICON_URL, properties)

    def get_day_relation_id(self, date):
        new_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
        timestamp = (new_date - timedelta(hours=8)).timestamp()
        day_str = new_date.strftime("%Y年%m月%d日")
        properties = {
            "日期": get_date(format_date(date)),
            "时间戳": get_number(timestamp),
            "年": get_relation([self.get_year_relation_id(new_date)]),
            "月": get_relation([self.get_month_relation_id(new_date)]),
            "周": get_relation([self.get_week_relation_id(new_date)]),
        }
        return self.get_relation_id(day_str, self.day_database_id, TARGET_ICON_URL, properties)

    def get_relation_id(self, name, id, icon, properties=None):
        if properties is None:
            properties = {}
        key = f"{id}{name}"
        if key in self.__cache:
            return self.__cache.get(key)
        filter = {"property": "标题", "title": {"equals": name}}
        response = self.client.databases.query(database_id=id, filter=filter)
        if len(response.get("results")) == 0:
            parent = {"database_id": id, "type": "database_id"}
            properties["标题"] = get_title(name)
            page_id = self.client.pages.create(parent=parent, properties=properties, icon=get_icon(icon)).get("id")
        else:
            page_id = response.get("results")[0].get("id")
        self.__cache[key] = page_id
        return page_id

    def insert_bookmark(self, id, bookmark):
        icon = get_icon(BOOKMARK_ICON_URL)
        properties = {
            "Name": get_title(bookmark.get("markText", "")),
            "bookId": get_rich_text(bookmark.get("bookId")),
            "range": get_rich_text(bookmark.get("range")),
            "bookmarkId": get_rich_text(bookmark.get("bookmarkId")),
            "blockId": get_rich_text(bookmark.get("blockId")),
            "chapterUid": get_number(bookmark.get("chapterUid")),
            "bookVersion": get_number(bookmark.get("bookVersion")),
            "colorStyle": get_number(bookmark.get("colorStyle")),
            "type": get_number(bookmark.get("type")),
            "style": get_number(bookmark.get("style")),
            "书籍": get_relation([id]),
        }
        if "createTime" in bookmark:
            create_time = timestamp_to_date(int(bookmark.get("createTime")))
            properties["Date"] = get_date(create_time.strftime("%Y-%m-%d %H:%M:%S"))
            self.get_date_relation(properties, create_time)
        parent = {"database_id": self.bookmark_database_id, "type": "database_id"}
        self.create_page(parent, properties, icon)

    def insert_review(self, id, review):
        time.sleep(0.1)
        icon = get_icon(TAG_ICON_URL)
        properties = {
            "Name": get_title(review.get("content", "")),
            "bookId": get_rich_text(review.get("bookId")),
            "reviewId": get_rich_text(review.get("reviewId")),
            "blockId": get_rich_text(review.get("blockId")),
            "chapterUid": get_number(review.get("chapterUid")),
            "bookVersion": get_number(review.get("bookVersion")),
            "type": get_number(review.get("type")),
            "书籍": get_relation([id]),
        }
        if "range" in review:
            properties["range"] = get_rich_text(review.get("range"))
        if "star" in review:
            properties["star"] = get_number(review.get("star"))
        if "abstract" in review:
            properties["abstract"] = get_rich_text(review.get("abstract"))
        if "createTime" in review:
            create_time = timestamp_to_date(int(review.get("createTime")))
            properties["Date"] = get_date(create_time.strftime("%Y-%m-%d %H:%M:%S"))
            self.get_date_relation(properties, create_time)
        parent = {"database_id": self.review_database_id, "type": "database_id"}
        self.create_page(parent, properties, icon)

    def insert_chapter(self, id, chapter):
        time.sleep(0.1)
        icon = {"type": "external", "external": {"url": TAG_ICON_URL}}
        properties = {
            "Name": get_title(chapter.get("title")),
            "blockId": get_rich_text(chapter.get("blockId")),
            "chapterUid": {"number": chapter.get("chapterUid")},
            "chapterIdx": {"number": chapter.get("chapterIdx")},
            "readAhead": {"number": chapter.get("readAhead")},
            "updateTime": {"number": chapter.get("updateTime")},
            "level": {"number": chapter.get("level")},
            "书籍": {"relation": [{"id": id}]},
        }
        parent = {"database_id": self.chapter_database_id, "type": "database_id"}
        self.create_page(parent, properties, icon)

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def update_book_page(self, page_id, properties):
        return self.client.pages.update(page_id=page_id, properties=properties)

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def update_page(self, page_id, properties, icon=None):
        return self.client.pages.update(page_id=page_id, properties=properties, icon=icon)

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def create_page(self, parent, properties, icon):
        return self.client.pages.create(parent=parent, properties=properties, icon=icon)

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def create_book_page(self, parent, properties, icon):
        return self.client.pages.create(parent=parent, properties=properties, icon=icon)

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def query(self, **kwargs):
        kwargs = {k: v for k, v in kwargs.items() if v}
        return self.client.databases.query(**kwargs)

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_block_children(self, id):
        response = self.client.blocks.children.list(id)
        return response.get("results")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def append_blocks(self, block_id, children):
        return self.client.blocks.children.append(block_id=block_id, children=children)

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def append_blocks_after(self, block_id, children, after):
        parent = self.client.blocks.retrieve(after).get("parent")
        if parent.get("type") == "block_id":
            after = parent.get("block_id")
        return self.client.blocks.children.append(block_id=block_id, children=children, after=after)

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def delete_block(self, block_id):
        return self.client.blocks.delete(block_id=block_id)

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_all_book(self):
        results = self.query_all(self.book_database_id)
        books_dict = {}
        for result in results:
            bookId = get_property_value(result.get("properties").get("BookId"))
            books_dict[bookId] = {
                "pageId": result.get("id"),
                "readingTime": get_property_value(result.get("properties").get("阅读时长")),
                "category": get_property_value(result.get("properties").get("书架分类")),
                "Sort": get_property_value(result.get("properties").get("Sort")),
                "douban_url": get_property_value(result.get("properties").get("豆瓣链接")),
                "cover": result.get("cover"),
                "myRating": get_property_value(result.get("properties").get("我的评分")),
                "comment": get_property_value(result.get("properties").get("豆瓣短评")),
                "status": get_property_value(result.get("properties").get("阅读状态")),
            }
        return books_dict

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def query_all_by_book(self, database_id, filter):
        results = []
        has_more = True
        start_cursor = None
        while has_more:
            response = self.client.databases.query(
                database_id=database_id, filter=filter, start_cursor=start_cursor, page_size=100
            )
            start_cursor = response.get("next_cursor")
            has_more = response.get("has_more")
            results.extend(response.get("results"))
        return results

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def query_all(self, database_id):
        results = []
        has_more = True
        start_cursor = None
        while has_more:
            response = self.client.databases.query(
                database_id=database_id, start_cursor=start_cursor, page_size=100
            )
            start_cursor = response.get("next_cursor")
            has_more = response.get("has_more")
            results.extend(response.get("results"))
        return results

    def get_date_relation(self, properties, date):
        properties["年"] = get_relation([self.get_year_relation_id(date)])
        properties["月"] = get_relation([self.get_month_relation_id(date)])
        properties["周"] = get_relation([self.get_week_relation_id(date)])
        properties["日"] = get_relation([self.get_day_relation_id(date)])

# ==================== 同步功能 ====================

class WeReadSync:
    def __init__(self):
        self.weread_api = WeReadApi()
        self.notion_helper = NotionHelper()
        self.archive_dict = {}
        self.notion_books = {}

    def insert_book_to_notion(self, books, index, bookId):
        book = {}
        if bookId in self.archive_dict:
            book["书架分类"] = self.archive_dict.get(bookId)
        if bookId in self.notion_books:
            book.update(self.notion_books.get(bookId))
        
        bookInfo = self.weread_api.get_bookinfo(bookId)
        if bookInfo:
            book.update(bookInfo)
        
        readInfo = self.weread_api.get_read_info(bookId)
        readInfo.update(readInfo.get("readDetail", {}))
        readInfo.update(readInfo.get("bookInfo", {}))
        book.update(readInfo)
        
        book["阅读进度"] = (100 if book.get("markedStatus") == 4 else book.get("readingProgress", 0)) / 100
        markedStatus = book.get("markedStatus")
        status = "想读"
        if markedStatus == 4:
            status = "已读"
        elif book.get("readingTime", 0) >= 60:
            status = "在读"
        book["阅读状态"] = status
        book["阅读时长"] = book.get("readingTime")
        book["阅读天数"] = book.get("totalReadDay")
        book["评分"] = book.get("newRating")
        
        if book.get("newRatingDetail") and book.get("newRatingDetail").get("myRating"):
            book["我的评分"] = rating.get(book.get("newRatingDetail").get("myRating"))
        elif status == "已读":
            book["我的评分"] = "未评分"
        
        book["时间"] = book.get("finishedDate") or book.get("lastReadingDate") or book.get("readingBookDate")
        book["开始阅读时间"] = book.get("beginReadingDate")
        book["最后阅读时间"] = book.get("lastReadingDate")
        
        book["封面"] = None
        
        if bookId not in self.notion_books:
            book["书名"] = book.get("title")
            book["BookId"] = book.get("bookId")
            book["ISBN"] = book.get("isbn")
            book["链接"] = self.weread_api.get_url(bookId)
            book["简介"] = book.get("intro")
            book["作者"] = [
                self.notion_helper.get_relation_id(x, self.notion_helper.author_database_id, USER_ICON_URL)
                for x in book.get("author", "").split(" ")
            ]
            if book.get("categories"):
                book["分类"] = [
                    self.notion_helper.get_relation_id(x.get("title"), self.notion_helper.category_database_id, TAG_ICON_URL)
                    for x in book.get("categories")
                ]
        
        properties = get_properties(book, book_properties_type_dict)
        if book.get("时间"):
            self.notion_helper.get_date_relation(
                properties, pendulum.from_timestamp(book.get("时间"), tz="Asia/Shanghai")
            )
        
        print(f"正在插入《{book.get('title')}》,一共{len(books)}本，当前是第{index+1}本。")
        parent = {"database_id": self.notion_helper.book_database_id, "type": "database_id"}
        
        if bookId in self.notion_books:
            result = self.notion_helper.update_page(
                page_id=self.notion_books.get(bookId).get("pageId"),
                properties=properties
            )
        else:
            result = self.notion_helper.create_book_page(parent=parent, properties=properties, icon=get_icon(BOOK_ICON_URL))
        
        page_id = result.get("id")
        if book.get("readDetail") and book.get("readDetail").get("data"):
            data = book.get("readDetail").get("data")
            data = {item.get("readDate"): item.get("readTime") for item in data}
            self.insert_read_data(page_id, data)

    def insert_read_data(self, page_id, readTimes):
        readTimes = dict(sorted(readTimes.items()))
        filter = {"property": "书架", "relation": {"contains": page_id}}
        results = self.notion_helper.query_all_by_book(self.notion_helper.read_database_id, filter)
        
        for result in results:
            timestamp = result.get("properties").get("时间戳").get("number")
            duration = result.get("properties").get("时长").get("number")
            id = result.get("id")
            if timestamp in readTimes:
                value = readTimes.pop(timestamp)
                if value != duration:
                    self.insert_to_notion(page_id=id, timestamp=timestamp, duration=value, book_database_id=page_id)
        
        for key, value in readTimes.items():
            self.insert_to_notion(None, int(key), value, page_id)

    def insert_to_notion(self, page_id, timestamp, duration, book_database_id):
        parent = {"database_id": self.notion_helper.read_database_id, "type": "database_id"}
        properties = {
            "标题": get_title(pendulum.from_timestamp(timestamp, tz=tz).to_date_string()),
            "日期": get_date(start=pendulum.from_timestamp(timestamp, tz=tz).format("YYYY-MM-DD HH:mm:ss")),
            "时长": get_number(duration),
            "时间戳": get_number(timestamp),
            "书架": get_relation([book_database_id]),
        }
        if page_id:
            self.notion_helper.client.pages.update(page_id=page_id, properties=properties)
        else:
            self.notion_helper.client.pages.create(parent=parent, icon=get_icon("https://www.notion.so/icons/target_red.svg"), properties=properties)

    def sync_books(self):
        self.notion_books = self.notion_helper.get_all_book()
        bookshelf_books = self.weread_api.get_bookshelf()
        
        bookProgress = bookshelf_books.get("bookProgress", [])
        bookProgress = {book.get("bookId"): book for book in bookProgress}
        
        for archive in bookshelf_books.get("archive", []):
            name = archive.get("name")
            bookIds = archive.get("bookIds", [])
            self.archive_dict.update({bookId: name for bookId in bookIds})
        
        not_need_sync = []
        for key, value in self.notion_books.items():
            if ((key not in bookProgress or value.get("readingTime") == bookProgress.get(key, {}).get("readingTime"))
                and (self.archive_dict.get(key) == value.get("category"))
                and (value.get("cover") is not None)
                and (value.get("status") != "已读" or (value.get("status") == "已读" and value.get("myRating")))):
                not_need_sync.append(key)
        
        notebooks = self.weread_api.get_notebooklist()
        notebooks = [d["bookId"] for d in notebooks if "bookId" in d]
        books = bookshelf_books.get("books", [])
        books = [d["bookId"] for d in books if "bookId" in d]
        books = list((set(notebooks) | set(books)) - set(not_need_sync))
        
        for index, bookId in enumerate(books):
            self.insert_book_to_notion(books, index, bookId)

    def get_bookmark_list(self, page_id, bookId):
        filter = {
            "and": [
                {"property": "书籍", "relation": {"contains": page_id}},
                {"property": "blockId", "rich_text": {"is_not_empty": True}},
            ]
        }
        results = self.notion_helper.query_all_by_book(self.notion_helper.bookmark_database_id, filter)
        dict1 = {get_rich_text_from_result(x, "bookmarkId"): get_rich_text_from_result(x, "blockId") for x in results}
        dict2 = {get_rich_text_from_result(x, "blockId"): x.get("id") for x in results}
        bookmarks = self.weread_api.get_bookmark_list(bookId)
        
        for i in bookmarks:
            if i.get("bookmarkId") in dict1:
                i["blockId"] = dict1.pop(i.get("bookmarkId"))
        for blockId in dict1.values():
            self.notion_helper.delete_block(blockId)
            self.notion_helper.delete_block(dict2.get(blockId))
        return bookmarks

    def get_review_list(self, page_id, bookId):
        filter = {
            "and": [
                {"property": "书籍", "relation": {"contains": page_id}},
                {"property": "blockId", "rich_text": {"is_not_empty": True}},
            ]
        }
        results = self.notion_helper.query_all_by_book(self.notion_helper.review_database_id, filter)
        dict1 = {get_rich_text_from_result(x, "reviewId"): get_rich_text_from_result(x, "blockId") for x in results}
        dict2 = {get_rich_text_from_result(x, "blockId"): x.get("id") for x in results}
        reviews = self.weread_api.get_review_list(bookId)
        
        for i in reviews:
            if i.get("reviewId") in dict1:
                i["blockId"] = dict1.pop(i.get("reviewId"))
        for blockId in dict1.values():
            self.notion_helper.delete_block(blockId)
            self.notion_helper.delete_block(dict2.get(blockId))
        return reviews

    def sort_notes(self, page_id, chapter, bookmark_list):
        bookmark_list = sorted(
            bookmark_list,
            key=lambda x: (
                x.get("chapterUid", 1),
                0 if (x.get("range", "") == "" or x.get("range").split("-")[0] == "") else int(x.get("range").split("-")[0]),
            ),
        )
        
        notes = []
        if chapter:
            filter = {"property": "书籍", "relation": {"contains": page_id}}
            results = self.notion_helper.query_all_by_book(self.notion_helper.chapter_database_id, filter)
            dict1 = {get_number_from_result(x, "chapterUid"): get_rich_text_from_result(x, "blockId") for x in results}
            dict2 = {get_rich_text_from_result(x, "blockId"): x.get("id") for x in results}
            d = {}
            for data in bookmark_list:
                chapterUid = data.get("chapterUid", 1)
                if chapterUid not in d:
                    d[chapterUid] = []
                d[chapterUid].append(data)
            for key, value in d.items():
                if key in chapter:
                    if key in dict1:
                        chapter.get(key)["blockId"] = dict1.pop(key)
                    notes.append(chapter.get(key))
                notes.extend(value)
            for blockId in dict1.values():
                self.notion_helper.delete_block(blockId)
                self.notion_helper.delete_block(dict2.get(blockId))
        else:
            notes.extend(bookmark_list)
        return notes

    def content_to_block(self, content):
        if "bookmarkId" in content:
            return get_block(
                content.get("markText", ""), self.notion_helper.block_type,
                self.notion_helper.show_color, content.get("style"),
                content.get("colorStyle"), content.get("reviewId")
            )
        elif "reviewId" in content:
            return get_block(
                content.get("content", ""), self.notion_helper.block_type,
                self.notion_helper.show_color, content.get("style"),
                content.get("colorStyle"), content.get("reviewId")
            )
        else:
            return get_heading(content.get("level"), content.get("title"))

    def append_blocks_to_notion(self, id, blocks, after, contents):
        response = self.notion_helper.append_blocks_after(block_id=id, children=blocks, after=after)
        results = response.get("results")
        l = []
        for index, content in enumerate(contents):
            result = results[index]
            if content.get("abstract"):
                self.notion_helper.append_blocks(block_id=result.get("id"), children=[get_quote(content.get("abstract"))])
            content["blockId"] = result.get("id")
            l.append(content)
        return l

    def append_blocks(self, id, contents):
        print(f"笔记数{len(contents)}")
        before_block_id = ""
        block_children = self.notion_helper.get_block_children(id)
        
        if len(block_children) > 0 and block_children[0].get("type") == "table_of_contents":
            before_block_id = block_children[0].get("id")
        else:
            response = self.notion_helper.append_blocks(block_id=id, children=[get_table_of_contents()])
            before_block_id = response.get("results")[0].get("id")
        
        blocks = []
        sub_contents = []
        l = []
        
        for content in contents:
            if len(blocks) == 100:
                results = self.append_blocks_to_notion(id, blocks, before_block_id, sub_contents)
                before_block_id = results[-1].get("blockId")
                l.extend(results)
                blocks.clear()
                sub_contents.clear()
                if not self.notion_helper.sync_bookmark and content.get("type") == 0:
                    continue
                blocks.append(self.content_to_block(content))
                sub_contents.append(content)
            elif "blockId" in content:
                if len(blocks) > 0:
                    l.extend(self.append_blocks_to_notion(id, blocks, before_block_id, sub_contents))
                    blocks.clear()
                    sub_contents.clear()
                before_block_id = content["blockId"]
            else:
                if not self.notion_helper.sync_bookmark and content.get("type") == 0:
                    continue
                blocks.append(self.content_to_block(content))
                sub_contents.append(content)
        
        if len(blocks) > 0:
            l.extend(self.append_blocks_to_notion(id, blocks, before_block_id, sub_contents))
        
        for index, value in enumerate(l):
            print(f"正在插入第{index+1}条笔记，共{len(l)}条")
            if "bookmarkId" in value:
                self.notion_helper.insert_bookmark(id, value)
            elif "reviewId" in value:
                self.notion_helper.insert_review(id, value)
            else:
                self.notion_helper.insert_chapter(id, value)

    def sync_notes(self):
        notion_books = self.notion_helper.get_all_book()
        books = self.weread_api.get_notebooklist()
        
        if books:
            for index, book in enumerate(books):
                bookId = book.get("bookId")
                title = book.get("book", {}).get("title")
                sort = book.get("sort")
                
                if bookId not in notion_books:
                    continue
                if sort == notion_books.get(bookId, {}).get("Sort"):
                    continue
                
                pageId = notion_books.get(bookId).get("pageId")
                print(f"正在同步《{title}》,一共{len(books)}本，当前是第{index+1}本。")
                
                chapter = self.weread_api.get_chapter_info(bookId)
                bookmark_list = self.get_bookmark_list(pageId, bookId)
                reviews = self.get_review_list(pageId, bookId)
                bookmark_list.extend(reviews)
                content = self.sort_notes(pageId, chapter, bookmark_list)
                self.append_blocks(pageId, content)
                self.notion_helper.update_book_page(page_id=pageId, properties={"Sort": get_number(sort)})

    def run(self, mode="all"):
        if mode in ("all", "books"):
            print("=== 同步书籍信息 ===")
            self.sync_books()
        
        if mode in ("all", "notes"):
            print("=== 同步笔记划线 ===")
            self.sync_notes()
        
        print("=== 同步完成 ===")

# ==================== 主程序入口 ====================

if __name__ == "__main__":
    import sys
    mode = "all"
    if len(sys.argv) > 1:
        mode = sys.argv[1]
    sync = WeReadSync()
    sync.run(mode)
