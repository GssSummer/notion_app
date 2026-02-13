import logging
import os
import re
import time
from datetime import timedelta

import pendulum
from notion_client import Client
from retrying import retry
from dotenv import load_dotenv

from weread2notionpro import (
    TAG_ICON_URL, USER_ICON_URL, TARGET_ICON_URL, BOOKMARK_ICON_URL,
    format_date, get_date, get_first_and_last_day_of_month,
    get_first_and_last_day_of_week, get_first_and_last_day_of_year,
    get_icon, get_number, get_relation, get_rich_text, get_title,
    timestamp_to_date, get_property_value
)

load_dotenv()


class NotionHelper:
    DATABASE_NAME_DICT = {
        "BOOK_DATABASE_NAME": "书架",
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
        self.database_id_dict = {}
        self.heatmap_block_id = None
        self.show_color = True
        self.block_type = "callout"
        self.sync_bookmark = True
        
        self.page_id = self._extract_page_id(os.getenv("NOTION_PAGE"))
        self._search_database(self.page_id)
        self._load_custom_names()
        self._init_database_ids()
        
        self.update_book_database()
        if self.read_database_id is None:
            self.create_read_database()
        if self.setting_database_id is None:
            self.create_setting_database()
        if self.setting_database_id:
            self.insert_to_setting_database()

    def _extract_page_id(self, notion_url):
        match = re.search(
            r"([a-f0-9]{32}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})",
            notion_url,
        )
        if match:
            return match.group(0)
        raise Exception(f"获取 Notion ID 失败，请检查输入的 Url 是否正确")

    def _search_database(self, block_id):
        children = self.client.blocks.children.list(block_id=block_id)["results"]
        for child in children:
            if child["type"] == "child_database":
                self.database_id_dict[child.get("child_database").get("title")] = child.get("id")
            elif child["type"] == "embed":
                url = child.get("embed", {}).get("url", "")
                if url.startswith("https://heatmap.malinkang.com/"):
                    self.heatmap_block_id = child.get("id")
            
            if child.get("has_children"):
                self._search_database(child["id"])

    def _load_custom_names(self):
        for key in self.DATABASE_NAME_DICT.keys():
            env_value = os.getenv(key)
            if env_value:
                self.DATABASE_NAME_DICT[key] = env_value

    def _init_database_ids(self):
        self.book_database_id = self.database_id_dict.get(self.DATABASE_NAME_DICT["BOOK_DATABASE_NAME"])
        self.review_database_id = self.database_id_dict.get(self.DATABASE_NAME_DICT["REVIEW_DATABASE_NAME"])
        self.bookmark_database_id = self.database_id_dict.get(self.DATABASE_NAME_DICT["BOOKMARK_DATABASE_NAME"])
        self.day_database_id = self.database_id_dict.get(self.DATABASE_NAME_DICT["DAY_DATABASE_NAME"])
        self.week_database_id = self.database_id_dict.get(self.DATABASE_NAME_DICT["WEEK_DATABASE_NAME"])
        self.month_database_id = self.database_id_dict.get(self.DATABASE_NAME_DICT["MONTH_DATABASE_NAME"])
        self.year_database_id = self.database_id_dict.get(self.DATABASE_NAME_DICT["YEAR_DATABASE_NAME"])
        self.category_database_id = self.database_id_dict.get(self.DATABASE_NAME_DICT["CATEGORY_DATABASE_NAME"])
        self.author_database_id = self.database_id_dict.get(self.DATABASE_NAME_DICT["AUTHOR_DATABASE_NAME"])
        self.chapter_database_id = self.database_id_dict.get(self.DATABASE_NAME_DICT["CHAPTER_DATABASE_NAME"])
        self.read_database_id = self.database_id_dict.get(self.DATABASE_NAME_DICT["READ_DATABASE_NAME"])
        self.setting_database_id = self.database_id_dict.get(self.DATABASE_NAME_DICT["SETTING_DATABASE_NAME"])

    def update_book_database(self):
        """更新书籍数据库结构"""
        response = self.client.databases.retrieve(database_id=self.book_database_id)
        properties = response.get("properties", {})
        update_properties = {}
        
        field_types = {
            "阅读时长": "number",
            "书架分类": "select",
            "豆瓣链接": "url",
            "我的评分": "select",
            "豆瓣短评": "rich_text",
        }
        
        for field, field_type in field_types.items():
            if properties.get(field) is None or properties.get(field, {}).get("type") != field_type:
                update_properties[field] = {field_type: {}}
        
        if update_properties:
            self.client.databases.update(database_id=self.book_database_id, properties=update_properties)

    def create_read_database(self):
        """创建阅读记录数据库"""
        title = [{"type": "text", "text": {"content": self.DATABASE_NAME_DICT["READ_DATABASE_NAME"]}}]
        properties = {
            "标题": {"title": {}},
            "时长": {"number": {}},
            "时间戳": {"number": {}},
            "日期": {"date": {}},
            "书架": {
                "relation": {
                    "database_id": self.book_database_id,
                    "single_property": {},
                }
            },
        }
        parent = {"page_id": self.page_id, "type": "page_id"}
        self.read_database_id = self.client.databases.create(
            parent=parent,
            title=title,
            icon=get_icon("https://www.notion.so/icons/target_gray.svg"),
            properties=properties,
        ).get("id")

    def create_setting_database(self):
        """创建设置数据库"""
        title = [{"type": "text", "text": {"content": self.DATABASE_NAME_DICT["SETTING_DATABASE_NAME"]}}]
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
            parent=parent,
            title=title,
            icon=get_icon("https://www.notion.so/icons/gear_gray.svg"),
            properties=properties,
        ).get("id")

    def insert_to_setting_database(self):
        """插入或更新设置"""
        filter = {"property": "标题", "title": {"equals": "设置"}}
        existing = self.query(database_id=self.setting_database_id, filter=filter).get("results", [])
        
        properties = {
            "标题": get_title("设置"),
            "最后同步时间": get_date(pendulum.now("Asia/Shanghai").isoformat()),
            "NotinToken": get_rich_text(os.getenv("NOTION_TOKEN", "")),
            "NotinPage": get_rich_text(os.getenv("NOTION_PAGE", "")),
            "WeReadCookie": get_rich_text(os.getenv("WEREAD_COOKIE", "")),
        }
        
        if existing:
            remote_props = existing[0].get("properties", {})
            self.show_color = get_property_value(remote_props.get("根据划线颜色设置文字颜色"))
            self.sync_bookmark = get_property_value(remote_props.get("同步书签"))
            self.block_type = get_property_value(remote_props.get("样式"))
            self.client.pages.update(page_id=existing[0].get("id"), properties=properties)
        else:
            properties.update({
                "根据划线颜色设置文字颜色": {"checkbox": True},
                "同步书签": {"checkbox": True},
                "样式": {"select": {"name": "callout"}},
            })
            self.client.pages.create(
                parent={"database_id": self.setting_database_id},
                properties=properties,
            )

    def update_heatmap(self, block_id, url):
        return self.client.blocks.update(block_id=block_id, embed={"url": url})

    # ========== Relation Helpers ==========

    def get_relation_id(self, name, db_id, icon, properties=None):
        key = f"{db_id}{name}"
        if key in self.__cache:
            return self.__cache[key]
        
        filter = {"property": "标题", "title": {"equals": name}}
        response = self.client.databases.query(database_id=db_id, filter=filter)
        
        if response.get("results"):
            page_id = response["results"][0].get("id")
        else:
            parent = {"database_id": db_id, "type": "database_id"}
            props = {"标题": get_title(name)}
            if properties:
                props.update(properties)
            page_id = self.client.pages.create(
                parent=parent, properties=props, icon=get_icon(icon)
            ).get("id")
        
        self.__cache[key] = page_id
        return page_id

    def get_year_relation_id(self, date):
        year = date.isocalendar().year
        week = date.isocalendar().week
        name = f"{year}年第{week}周"
        start, end = get_first_and_last_day_of_week(date)
        return self.get_relation_id(name, self.week_database_id, TARGET_ICON_URL, 
                                    {"日期": get_date(format_date(start), format_date(end))})

    def get_month_relation_id(self, date):
        name = date.strftime("%Y年%-m月")
        start, end = get_first_and_last_day_of_month(date)
        return self.get_relation_id(name, self.month_database_id, TARGET_ICON_URL,
                                    {"日期": get_date(format_date(start), format_date(end))})

    def get_year_relation_id(self, date):
        year = date.strftime("%Y")
        start, end = get_first_and_last_day_of_year(date)
        return self.get_relation_id(year, self.year_database_id, TARGET_ICON_URL,
                                    {"日期": get_date(format_date(start), format_date(end))})

    def get_day_relation_id(self, date):
        new_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
        timestamp = (new_date - timedelta(hours=8)).timestamp()
        day = new_date.strftime("%Y年%m月%d日")
        properties = {
            "日期": get_date(format_date(date)),
            "时间戳": get_number(timestamp),
            "年": get_relation([self.get_year_relation_id(new_date)]),
            "月": get_relation([self.get_month_relation_id(new_date)]),
            "周": get_relation([self.get_week_relation_id(new_date)]),
        }
        return self.get_relation_id(day, self.day_database_id, TARGET_ICON_URL, properties)

    def get_date_relation(self, properties, date):
        properties["年"] = get_relation([self.get_year_relation_id(date)])
        properties["月"] = get_relation([self.get_month_relation_id(date)])
        properties["周"] = get_relation([self.get_week_relation_id(date)])
        properties["日"] = get_relation([self.get_day_relation_id(date)])

    # ========== Insert Methods ==========

    def insert_bookmark(self, book_id, bookmark):
        time.sleep(0.1)
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
            "书籍": get_relation([book_id]),
        }
        if "createTime" in bookmark:
            create_time = timestamp_to_date(int(bookmark.get("createTime")))
            properties["Date"] = get_date(create_time.strftime("%Y-%m-%d %H:%M:%S"))
            self.get_date_relation(properties, create_time)
        
        parent = {"database_id": self.bookmark_database_id, "type": "database_id"}
        self.create_page(parent, properties, get_icon(BOOKMARK_ICON_URL))

    def insert_review(self, book_id, review):
        time.sleep(0.1)
        properties = {
            "Name": get_title(review.get("content", "")),
            "bookId": get_rich_text(review.get("bookId")),
            "reviewId": get_rich_text(review.get("reviewId")),
            "blockId": get_rich_text(review.get("blockId")),
            "chapterUid": get_number(review.get("chapterUid")),
            "bookVersion": get_number(review.get("bookVersion")),
            "type": get_number(review.get("type")),
            "书籍": get_relation([book_id]),
        }
        
        optional_fields = ["range", "star", "abstract"]
        for field in optional_fields:
            if field in review:
                mapper = {"range": get_rich_text, "star": get_number, "abstract": get_rich_text}
                properties[field] = mapper[field](review.get(field))
        
        if "createTime" in review:
            create_time = timestamp_to_date(int(review.get("createTime")))
            properties["Date"] = get_date(create_time.strftime("%Y-%m-%d %H:%M:%S"))
            self.get_date_relation(properties, create_time)
        
        parent = {"database_id": self.review_database_id, "type": "database_id"}
        self.create_page(parent, properties, get_icon(TAG_ICON_URL))

    def insert_chapter(self, book_id, chapter):
        time.sleep(0.1)
        properties = {
            "Name": get_title(chapter.get("title")),
            "blockId": get_rich_text(chapter.get("blockId")),
            "chapterUid": get_number(chapter.get("chapterUid")),
            "chapterIdx": get_number(chapter.get("chapterIdx")),
            "readAhead": get_number(chapter.get("readAhead")),
            "updateTime": get_number(chapter.get("updateTime")),
            "level": get_number(chapter.get("level")),
            "书籍": get_relation([book_id]),
        }
        parent = {"database_id": self.chapter_database_id, "type": "database_id"}
        icon = {"type": "external", "external": {"url": TAG_ICON_URL}}
        self.create_page(parent, properties, icon)

    # ========== API Wrappers ==========

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def update_book_page(self, page_id, properties):
        return self.client.pages.update(page_id=page_id, properties=properties)

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def update_page(self, page_id, properties, cover):
        return self.client.pages.update(page_id=page_id, properties=properties, cover=cover)

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def create_page(self, parent, properties, icon):
        return self.client.pages.create(parent=parent, properties=properties, icon=icon)

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def create_book_page(self, parent, properties, icon):
        return self.client.pages.create(parent=parent, properties=properties, icon=icon, cover=icon)

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def query(self, **kwargs):
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        return self.client.databases.query(**kwargs)

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_block_children(self, block_id):
        return self.client.blocks.children.list(block_id).get("results", [])

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

    # ========== Query Methods ==========

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def query_all(self, database_id):
        results = []
        has_more = True
        start_cursor = None
        while has_more:
            response = self.client.databases.query(
                database_id=database_id,
                start_cursor=start_cursor,
                page_size=100,
            )
            start_cursor = response.get("next_cursor")
            has_more = response.get("has_more")
            results.extend(response.get("results", []))
        return results

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def query_all_by_book(self, database_id, filter):
        results = []
        has_more = True
        start_cursor = None
        while has_more:
            response = self.client.databases.query(
                database_id=database_id,
                filter=filter,
                start_cursor=start_cursor,
                page_size=100,
            )
            start_cursor = response.get("next_cursor")
            has_more = response.get("has_more")
            results.extend(response.get("results", []))
        return results

    def get_all_book(self):
        """获取所有书籍"""
        results = self.query_all(self.book_database_id)
        books_dict = {}
        for result in results:
            props = result.get("properties", {})
            book_id = get_property_value(props.get("BookId"))
            books_dict[book_id] = {
                "pageId": result.get("id"),
                "readingTime": get_property_value(props.get("阅读时长")),
                "category": get_property_value(props.get("书架分类")),
                "Sort": get_property_value(props.get("Sort")),
                "douban_url": get_property_value(props.get("豆瓣链接")),
                "cover": result.get("cover"),
                "myRating": get_property_value(props.get("我的评分")),
                "comment": get_property_value(props.get("豆瓣短评")),
                "status": get_property_value(props.get("阅读状态")),
            }
        return books_dict
