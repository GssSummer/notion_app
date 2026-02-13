"""
同步模块：包含书籍同步、笔记同步、阅读时长同步
"""

import os
import pendulum
from datetime import datetime, timedelta

from weread2notionpro import (
    BOOK_PROPERTIES_TYPE_DICT, TZ, TAG_ICON_URL, USER_ICON_URL,
    BOOK_ICON_URL, RATING_MAP
)
from weread2notionpro.utils import (
    get_block, get_heading, get_number, get_number_from_result,
    get_quote, get_rich_text_from_result, get_table_of_contents,
    get_title, get_date, get_relation, get_icon, format_date
)
from weread2notionpro.notion_helper import NotionHelper
from weread2notionpro.weread_api import WeReadApi


# ========== 全局实例 ==========
weread_api = WeReadApi()
notion_helper = NotionHelper()


# ========== 书籍同步 (原 book.py) ==========

def insert_book_to_notion(books, index, book_id, notion_books, archive_dict):
    """插入单本书籍到 Notion"""
    book = {}
    if book_id in archive_dict:
        book["书架分类"] = archive_dict.get(book_id)
    if book_id in notion_books:
        book.update(notion_books.get(book_id))
    
    # 获取书籍信息
    book_info = weread_api.get_bookinfo(book_id)
    if book_info:
        book.update(book_info)
    
    read_info = weread_api.get_read_info(book_id)
    read_info.update(read_info.get("readDetail", {}))
    read_info.update(read_info.get("bookInfo", {}))
    book.update(read_info)
    
    # 计算阅读状态
    book["阅读进度"] = (100 if book.get("markedStatus") == 4 else book.get("readingProgress", 0)) / 100
    marked_status = book.get("markedStatus")
    status = "想读"
    if marked_status == 4:
        status = "已读"
    elif book.get("readingTime", 0) >= 60:
        status = "在读"
    book["阅读状态"] = status
    
    # 设置字段
    book["阅读时长"] = book.get("readingTime")
    book["阅读天数"] = book.get("totalReadDay")
    book["评分"] = book.get("newRating")
    
    if book.get("newRatingDetail", {}).get("myRating"):
        book["我的评分"] = RATING_MAP.get(book.get("newRatingDetail").get("myRating"))
    elif status == "已读":
        book["我的评分"] = "未评分"
    
    book["时间"] = book.get("finishedDate") or book.get("lastReadingDate") or book.get("readingBookDate")
    book["开始阅读时间"] = book.get("beginReadingDate")
    book["最后阅读时间"] = book.get("lastReadingDate")
    
    cover = book.get("cover", "").replace("/s_", "/t7_")
    if not cover or not cover.startswith("http"):
        cover = BOOK_ICON_URL
    
    # 新建书籍需要的字段
    if book_id not in notion_books:
        book["书名"] = book.get("title")
        book["BookId"] = book.get("bookId")
        book["ISBN"] = book.get("isbn")
        book["链接"] = weread_api.get_url(book_id)
        book["简介"] = book.get("intro")
        book["作者"] = [
            notion_helper.get_relation_id(x.strip(), notion_helper.author_database_id, USER_ICON_URL)
            for x in book.get("author", "").split(" ") if x.strip()
        ]
        if book.get("categories"):
            book["分类"] = [
                notion_helper.get_relation_id(x.get("title"), notion_helper.category_database_id, TAG_ICON_URL)
                for x in book.get("categories")
            ]
    
    from weread2notionpro.utils import get_properties
    properties = get_properties(book, BOOK_PROPERTIES_TYPE_DICT)
    
    if book.get("时间"):
        notion_helper.get_date_relation(
            properties,
            pendulum.from_timestamp(book.get("时间"), tz=TZ)
        )
    
    print(f"正在插入《{book.get('title')}》, 一共{len(books)}本，当前是第{index+1}本。")
    parent = {"database_id": notion_helper.book_database_id, "type": "database_id"}
    
    if book_id in notion_books:
        result = notion_helper.update_page(
            page_id=notion_books.get(book_id).get("pageId"),
            properties=properties,
            cover=get_icon(cover),
        )
    else:
        result = notion_helper.create_book_page(
            parent=parent,
            properties=properties,
            icon=get_icon(cover),
        )
    
    page_id = result.get("id")
    
    # 插入详细阅读数据
    if book.get("readDetail", {}).get("data"):
        data = book.get("readDetail").get("data")
        read_times = {item.get("readDate"): item.get("readTime") for item in data}
        insert_read_data(page_id, read_times)


def insert_read_data(page_id, read_times):
    """插入阅读详细数据"""
    read_times = dict(sorted(read_times.items()))
    filter = {"property": "书架", "relation": {"contains": page_id}}
    results = notion_helper.query_all_by_book(notion_helper.read_database_id, filter)
    
    for result in results:
        props = result.get("properties", {})
        timestamp = props.get("时间戳", {}).get("number")
        duration = props.get("时长", {}).get("number")
        entry_id = result.get("id")
        
        if timestamp in read_times:
            value = read_times.pop(timestamp)
            if value != duration:
                _insert_read_entry(entry_id, timestamp, value, page_id)
    
    for key, value in read_times.items():
        _insert_read_entry(None, int(key), value, page_id)


def _insert_read_entry(page_id, timestamp, duration, book_database_id):
    parent = {"database_id": notion_helper.read_database_id, "type": "database_id"}
    properties = {
        "标题": get_title(pendulum.from_timestamp(timestamp, tz=TZ).to_date_string()),
        "日期": get_date(pendulum.from_timestamp(timestamp, tz=TZ).format("YYYY-MM-DD HH:mm:ss")),
        "时长": get_number(duration),
        "时间戳": get_number(timestamp),
        "书架": get_relation([book_database_id]),
    }
    
    if page_id:
        notion_helper.client.pages.update(page_id=page_id, properties=properties)
    else:
        notion_helper.client.pages.create(
            parent=parent,
            icon=get_icon("https://www.notion.so/icons/target_red.svg"),
            properties=properties,
        )


def sync_books():
    """同步书籍主函数"""
    bookshelf = weread_api.get_bookshelf()
    notion_books = notion_helper.get_all_book()
    
    book_progress = {b.get("bookId"): b for b in bookshelf.get("bookProgress", [])}
    
    # 构建归档字典
    archive_dict = {}
    for archive in bookshelf.get("archive", []):
        name = archive.get("name")
        for book_id in archive.get("bookIds", []):
            archive_dict[book_id] = name
    
    # 筛选需要同步的书籍
    not_need_sync = []
    for key, value in notion_books.items():
        in_progress = key in book_progress
        time_match = in_progress and value.get("readingTime") == book_progress.get(key, {}).get("readingTime")
        category_match = archive_dict.get(key) == value.get("category")
        has_cover = value.get("cover") is not None
        rating_ok = value.get("status") != "已读" or value.get("myRating") is not None
        
        if time_match and category_match and has_cover and rating_ok:
            not_need_sync.append(key)
    
    notebooks = weread_api.get_notebooklist()
    notebook_ids = [d["bookId"] for d in notebooks if "bookId" in d]
    shelf_ids = [d["bookId"] for d in bookshelf.get("books", []) if "bookId" in d]
    
    books_to_sync = list((set(notebook_ids) | set(shelf_ids)) - set(not_need_sync))
    
    for index, book_id in enumerate(books_to_sync):
        insert_book_to_notion(books_to_sync, index, book_id, notion_books, archive_dict)


# ========== 笔记同步 (原 weread.py) ==========

def get_bookmark_list(page_id, book_id):
    """获取并同步划线"""
    filter = {
        "and": [
            {"property": "书籍", "relation": {"contains": page_id}},
            {"property": "blockId", "rich_text": {"is_not_empty": True}},
        ]
    }
    results = notion_helper.query_all_by_book(notion_helper.bookmark_database_id, filter)
    
    dict1 = {get_rich_text_from_result(x, "bookmarkId"): get_rich_text_from_result(x, "blockId") for x in results}
    dict2 = {get_rich_text_from_result(x, "blockId"): x.get("id") for x in results}
    
    bookmarks = weread_api.get_bookmark_list(book_id)
    for bm in bookmarks:
        if bm.get("bookmarkId") in dict1:
            bm["blockId"] = dict1.pop(bm.get("bookmarkId"))
    
    for block_id in dict1.values():
        notion_helper.delete_block(block_id)
        notion_helper.delete_block(dict2.get(block_id))
    
    return bookmarks


def get_review_list(page_id, book_id):
    """获取并同步笔记"""
    filter = {
        "and": [
            {"property": "书籍", "relation": {"contains": page_id}},
            {"property": "blockId", "rich_text": {"is_not_empty": True}},
        ]
    }
    results = notion_helper.query_all_by_book(notion_helper.review_database_id, filter)
    
    dict1 = {get_rich_text_from_result(x, "reviewId"): get_rich_text_from_result(x, "blockId") for x in results}
    dict2 = {get_rich_text_from_result(x, "blockId"): x.get("id") for x in results}
    
    reviews = weread_api.get_review_list(book_id)
    for review in reviews:
        if review.get("reviewId") in dict1:
            review["blockId"] = dict1.pop(review.get("reviewId"))
    
    for block_id in dict1.values():
        notion_helper.delete_block(block_id)
        notion_helper.delete_block(dict2.get(block_id))
    
    return reviews


def sort_notes(page_id, chapter, bookmark_list):
    """对笔记进行排序"""
    bookmark_list = sorted(
        bookmark_list,
        key=lambda x: (
            x.get("chapterUid", 1),
            0 if not x.get("range") or x.get("range", "").split("-")[0] == "" 
            else int(x.get("range").split("-")[0]),
        ),
    )
    
    notes = []
    if chapter:
        filter = {"property": "书籍", "relation": {"contains": page_id}}
        results = notion_helper.query_all_by_book(notion_helper.chapter_database_id, filter)
        
        dict1 = {get_number_from_result(x, "chapterUid"): get_rich_text_from_result(x, "blockId") for x in results}
        dict2 = {get_rich_text_from_result(x, "blockId"): x.get("id") for x in results}
        
        chapter_notes = {}
        for bm in bookmark_list:
            cuid = bm.get("chapterUid", 1)
            chapter_notes.setdefault(cuid, []).append(bm)
        
        for cuid, bms in chapter_notes.items():
            if cuid in chapter:
                if cuid in dict1:
                    chapter[cuid]["blockId"] = dict1.pop(cuid)
                notes.append(chapter[cuid])
            notes.extend(bms)
        
        for block_id in dict1.values():
            notion_helper.delete_block(block_id)
            notion_helper.delete_block(dict2.get(block_id))
    else:
        notes.extend(bookmark_list)
    
    return notes


def content_to_block(content):
    """将内容转换为 Notion Block"""
    if "bookmarkId" in content:
        return get_block(
            content.get("markText", ""),
            notion_helper.block_type,
            notion_helper.show_color,
            content.get("style"),
            content.get("colorStyle"),
            content.get("reviewId"),
        )
    elif "reviewId" in content:
        return get_block(
            content.get("content", ""),
            notion_helper.block_type,
            notion_helper.show_color,
            content.get("style"),
            content.get("colorStyle"),
            content.get("reviewId"),
        )
    else:
        return get_heading(content.get("level"), content.get("title"))


def append_blocks_to_notion(page_id, blocks, after, contents):
    """批量添加 blocks"""
    response = notion_helper.append_blocks_after(block_id=page_id, children=blocks, after=after)
    results = response.get("results", [])
    
    processed = []
    for idx, content in enumerate(contents):
        result = results[idx]
        if content.get("abstract"):
            notion_helper.append_blocks(
                block_id=result.get("id"),
                children=[get_quote(content.get("abstract"))]
            )
        content["blockId"] = result.get("id")
        processed.append(content)
    
    return processed


def append_blocks(page_id, contents):
    """添加笔记内容到页面"""
    print(f"笔记数 {len(contents)}")
    
    # 获取或创建目录
    block_children = notion_helper.get_block_children(page_id)
    if block_children and block_children[0].get("type") == "table_of_contents":
        before_block_id = block_children[0].get("id")
    else:
        response = notion_helper.append_blocks(block_id=page_id, children=[get_table_of_contents()])
        before_block_id = response.get("results")[0].get("id")
    
    blocks = []
    sub_contents = []
    processed = []
    
    for content in contents:
        if len(blocks) == 100:
            results = append_blocks_to_notion(page_id, blocks, before_block_id, sub_contents)
            before_block_id = results[-1].get("blockId")
            processed.extend(results)
            blocks.clear()
            sub_contents.clear()
            
            if not notion_helper.sync_bookmark and content.get("type") == 0:
                continue
            blocks.append(content_to_block(content))
            sub_contents.append(content)
        
        elif "blockId" in content:
            if blocks:
                processed.extend(append_blocks_to_notion(page_id, blocks, before_block_id, sub_contents))
                blocks.clear()
                sub_contents.clear()
            before_block_id = content["blockId"]
        else:
            if not notion_helper.sync_bookmark and content.get("type") == 0:
                continue
            blocks.append(content_to_block(content))
            sub_contents.append(content)
    
    if blocks:
        processed.extend(append_blocks_to_notion(page_id, blocks, before_block_id, sub_contents))
    
    # 插入到数据库
    for idx, value in enumerate(processed):
        print(f"正在插入第 {idx+1} 条笔记，共 {len(processed)} 条")
        if "bookmarkId" in value:
            notion_helper.insert_bookmark(page_id, value)
        elif "reviewId" in value:
            notion_helper.insert_review(page_id, value)
        else:
            notion_helper.insert_chapter(page_id, value)


def sync_notes():
    """同步笔记主函数"""
    notion_books = notion_helper.get_all_book()
    books = weread_api.get_notebooklist()
    
    if not books:
        return
    
    for index, book in enumerate(books):
        book_id = book.get("bookId")
        title = book.get("book", {}).get("title")
        sort = book.get("sort")
        
        if book_id not in notion_books:
            continue
        if sort == notion_books.get(book_id, {}).get("Sort"):
            continue
        
        page_id = notion_books.get(book_id).get("pageId")
        print(f"正在同步《{title}》, 一共 {len(books)} 本，当前是第 {index+1} 本。")
        
        chapter = weread_api.get_chapter_info(book_id)
        bookmark_list = get_bookmark_list(page_id, book_id)
        reviews = get_review_list(page_id, book_id)
        bookmark_list.extend(reviews)
        
        content = sort_notes(page_id, chapter, bookmark_list)
        append_blocks(page_id, content)
        
        notion_helper.update_book_page(page_id=page_id, properties={"Sort": get_number(sort)})


# ========== 阅读时长同步 (原 read_time.py) ==========

HEATMAP_GUIDE = "https://mp.weixin.qq.com/s?__biz=MzI1OTcxOTI4NA==&mid=2247484145&idx=1&sn=81752852420b9153fc292b7873217651&chksm=ea75ebeadd0262fc65df100370d3f983ba2e52e2fcde2deb1ed49343fbb10645a77570656728&token=157143379&lang=zh_CN#rd"


def get_heatmap_file():
    """获取热力图文件"""
    folder_path = "./OUT_FOLDER"
    if os.path.exists(folder_path) and os.path.isdir(folder_path):
        entries = [e for e in os.listdir(folder_path) if e.endswith('.svg')]
        return entries[0] if entries else None
    return None


def insert_read_time_entry(page_id, timestamp, duration):
    """插入单条阅读时长记录"""
    date = datetime.utcfromtimestamp(timestamp) + timedelta(hours=8)
    
    parent = {"database_id": notion_helper.day_database_id, "type": "database_id"}
    properties = {
        "标题": get_title(format_date(date, "%Y年%m月%d日")),
        "日期": get_date(start=format_date(date)),
        "时长": get_number(duration),
        "时间戳": get_number(timestamp),
        "年": get_relation([notion_helper.get_year_relation_id(date)]),
        "月": get_relation([notion_helper.get_month_relation_id(date)]),
        "周": get_relation([notion_helper.get_week_relation_id(date)]),
    }
    
    if page_id:
        notion_helper.client.pages.update(page_id=page_id, properties=properties)
    else:
        notion_helper.client.pages.create(
            parent=parent,
            icon=get_icon("https://www.notion.so/icons/target_red.svg"),
            properties=properties,
        )


def sync_read_time():
    """同步阅读时长主函数"""
    # 更新热力图
    image_file = get_heatmap_file()
    if image_file:
        image_url = f"https://raw.githubusercontent.com/{os.getenv('REPOSITORY')}/{os.getenv('REF', '').split('/')[-1]}/OUT_FOLDER/{image_file}"
        heatmap_url = f"https://heatmap.malinkang.com/?image={image_url}"
        
        if notion_helper.heatmap_block_id:
            notion_helper.update_heatmap(block_id=notion_helper.heatmap_block_id, url=heatmap_url)
        else:
            print(f"更新热力图失败，没有添加热力图占位。具体参考：{HEATMAP_GUIDE}")
    else:
        print(f"更新热力图失败，没有生成热力图。具体参考：{HEATMAP_GUIDE}")
    
    # 同步阅读数据
    api_data = weread_api.get_api_data()
    read_times = {int(k): v for k, v in api_data.get("readTimes", {}).items()}
    
    now = pendulum.now("Asia/Shanghai").start_of("day")
    today_timestamp = now.int_timestamp
    if today_timestamp not in read_times:
        read_times[today_timestamp] = 0
    
    read_times = dict(sorted(read_times.items()))
    
    # 查询现有记录
    results = notion_helper.query_all(database_id=notion_helper.day_database_id)
    existing = {}
    for result in results:
        props = result.get("properties", {})
        ts = props.get("时间戳", {}).get("number")
        duration = props.get("时长", {}).get("number")
        existing[ts] = {"id": result.get("id"), "duration": duration}
    
    # 更新或插入
    for timestamp, duration in read_times.items():
        if timestamp in existing:
            if duration != existing[timestamp]["duration"]:
                insert_read_time_entry(existing[timestamp]["id"], timestamp, duration)
        else:
            insert_read_time_entry(None, timestamp, duration)
