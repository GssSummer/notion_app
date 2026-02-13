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
