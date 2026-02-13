"""
weread2notionpro - 微信读书同步到 Notion
"""

# 配置常量
RICH_TEXT = "rich_text"
URL = "url"
RELATION = "relation"
NUMBER = "number"
DATE = "date"
FILES = "files"
STATUS = "status"
TITLE = "title"
SELECT = "select"

BOOK_PROPERTIES_TYPE_DICT = {
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

TZ = 'Asia/Shanghai'
MAX_LENGTH = 1024  # NOTION 2000个字符限制

# 图标 URL
TAG_ICON_URL = "https://www.notion.so/icons/tag_gray.svg"
USER_ICON_URL = "https://www.notion.so/icons/user-circle-filled_gray.svg"
TARGET_ICON_URL = "https://www.notion.so/icons/target_red.svg"
BOOKMARK_ICON_URL = "https://www.notion.so/icons/bookmark_gray.svg"
BOOK_ICON_URL = "https://www.notion.so/icons/book_gray.svg"

RATING_MAP = {"poor": "⭐️", "fair": "⭐️⭐️⭐️", "good": "⭐️⭐️⭐️⭐️⭐️"}

# API URL
WEREAD_URL = "https://weread.qq.com/"
WEREAD_NOTEBOOKS_URL = "https://i.weread.qq.com/user/notebooks"
WEREAD_BOOKMARKLIST_URL = "https://i.weread.qq.com/book/bookmarklist"
WEREAD_CHAPTER_INFO = "https://i.weread.qq.com/book/chapterInfos"
WEREAD_READ_INFO_URL = "https://i.weread.qq.com/book/readinfo"
WEREAD_REVIEW_LIST_URL = "https://i.weread.qq.com/review/list"
WEREAD_BOOK_INFO = "https://i.weread.qq.com/book/info"
WEREAD_READDATA_DETAIL = "https://i.weread.qq.com/readdata/detail"
WEREAD_HISTORY_URL = "https://i.weread.qq.com/readdata/summary?synckey=0"

__version__ = "0.2.5"
