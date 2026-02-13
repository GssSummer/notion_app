import hashlib
import json
import os
import re
import requests
from requests.utils import cookiejar_from_dict
from retrying import retry
from dotenv import load_dotenv

from weread2notionpro import (
    WEREAD_URL, WEREAD_NOTEBOOKS_URL, WEREAD_BOOKMARKLIST_URL,
    WEREAD_CHAPTER_INFO, WEREAD_READ_INFO_URL, WEREAD_REVIEW_LIST_URL,
    WEREAD_BOOK_INFO, WEREAD_HISTORY_URL
)

load_dotenv()


class WeReadApi:
    def __init__(self):
        self.cookie = self._get_cookie()
        self.session = requests.Session()
        self.session.cookies = self._parse_cookie_string()

    def _try_get_cloud_cookie(self, url, user_id, password):
        if url.endswith("/"):
            url = url[:-1]
        req_url = f"{url}/get/{user_id}"
        data = {"password": password}
        
        try:
            response = requests.post(req_url, data=data)
            if response.status_code == 200:
                data = response.json()
                cookie_data = data.get("cookie_data", {})
                if "weread.qq.com" in cookie_data:
                    cookies = cookie_data["weread.qq.com"]
                    return "; ".join([f"{c['name']}={c['value']}" for c in cookies])
        except Exception as e:
            print(f"Failed to get cloud cookie: {e}")
        return None

    def _get_cookie(self):
        url = os.getenv("CC_URL", "https://cookiecloud.malinkang.com/")
        user_id = os.getenv("CC_ID")
        password = os.getenv("CC_PASSWORD")
        cookie = os.getenv("WEREAD_COOKIE")
        
        if url and user_id and password:
            cloud_cookie = self._try_get_cloud_cookie(url, user_id, password)
            if cloud_cookie:
                return cloud_cookie
        
        if not cookie or not cookie.strip():
            raise Exception("没有找到 cookie，请按照文档填写 cookie")
        return cookie

    def _parse_cookie_string(self):
        cookies_dict = {}
        pattern = re.compile(r'([^=]+)=([^;]+);?\s*')
        matches = pattern.findall(self.cookie)
        
        for key, value in matches:
            cookies_dict[key] = value.encode('unicode_escape').decode('ascii')
        
        return cookiejar_from_dict(cookies_dict)

    def _handle_error(self, errcode):
        if errcode in (-2012, -2010):
            print(f"::error::微信读书 Cookie 过期了，请参考文档重新设置。")

    def _get(self, url, **kwargs):
        self.session.get(WEREAD_URL)
        response = self.session.get(url, **kwargs)
        
        if not response.ok:
            errcode = response.json().get("errcode", 0)
            self._handle_error(errcode)
            raise Exception(f"Request failed: {response.text}")
        
        return response

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_bookshelf(self):
        """获取书架"""
        r = self.session.get(f"{WEREAD_URL}web/shelf/sync?synckey=0&teenmode=0&album=1&onlyBookid=0")
        if r.ok:
            return r.json()
        self._handle_error(r.json().get("errcode", 0))
        raise Exception(f"Could not get bookshelf {r.text}")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_notebooklist(self):
        """获取笔记本列表"""
        r = self._get(WEREAD_NOTEBOOKS_URL)
        books = r.json().get("books", [])
        books.sort(key=lambda x: x["sort"])
        return books

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_bookinfo(self, book_id):
        """获取书的详情"""
        try:
            r = self._get(WEREAD_BOOK_INFO, params={"bookId": book_id})
            return r.json()
        except Exception as e:
            print(f"Could not get book info: {e}")
            return None

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_bookmark_list(self, book_id):
        """获取划线列表"""
        r = self._get(WEREAD_BOOKMARKLIST_URL, params={"bookId": book_id})
        return r.json().get("updated", [])

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_read_info(self, book_id):
        """获取阅读信息"""
        params = {
            "noteCount": 1, "readingDetail": 1, "finishedBookIndex": 1,
            "readingBookCount": 1, "readingBookIndex": 1, "finishedBookCount": 1,
            "bookId": book_id, "finishedDate": 1,
        }
        headers = {
            "baseapi": "32",
            "appver": "8.2.5.10163885",
            "basever": "8.2.5.10163885",
            "osver": "12",
            "User-Agent": "WeRead/8.2.5 WRBrand/xiaomi Dalvik/2.1.0 (Linux; U; Android 12; Redmi Note 7 Pro Build/SQ3A.220705.004)",
        }
        r = self._get(WEREAD_READ_INFO_URL, headers=headers, params=params)
        return r.json()

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_review_list(self, book_id):
        """获取笔记列表"""
        params = {"bookId": book_id, "listType": 11, "mine": 1, "syncKey": 0}
        r = self._get(WEREAD_REVIEW_LIST_URL, params=params)
        reviews = r.json().get("reviews", [])
        reviews = [r.get("review") for r in reviews]
        # 处理想法类型的笔记
        return [{"chapterUid": 1000000, **x} if x.get("type") == 4 else x for x in reviews]

    def get_api_data(self):
        """获取阅读历史数据"""
        r = self._get(WEREAD_HISTORY_URL)
        return r.json()

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_chapter_info(self, book_id):
        """获取章节信息"""
        body = {"bookIds": [book_id], "synckeys": [0], "teenmode": 0}
        r = self.session.post(WEREAD_CHAPTER_INFO, json=body)
        
        if r.ok and "data" in r.json():
            data = r.json()["data"]
            if len(data) == 1 and "updated" in data[0]:
                update = data[0]["updated"]
                # 添加"点评"虚拟章节
                update.append({
                    "chapterUid": 1000000,
                    "chapterIdx": 1000000,
                    "updateTime": 1683825006,
                    "readAhead": 0,
                    "title": "点评",
                    "level": 1,
                })
                return {item["chapterUid"]: item for item in update}
        
        raise Exception(f"get {book_id} chapter info failed {r.text}")

    # ========== ID 转换方法 ==========

    def _transform_id(self, book_id):
        id_length = len(book_id)
        if re.match(r"^\d*$", book_id):
            ary = []
            for i in range(0, id_length, 9):
                ary.append(format(int(book_id[i:min(i + 9, id_length)]), "x"))
            return "3", ary
        
        result = "".join(format(ord(c), "x") for c in book_id)
        return "4", [result]

    def _calculate_book_str_id(self, book_id):
        md5 = hashlib.md5()
        md5.update(book_id.encode("utf-8"))
        digest = md5.hexdigest()
        result = digest[0:3]
        code, transformed_ids = self._transform_id(book_id)
        result += code + "2" + digest[-2:]

        for i, tid in enumerate(transformed_ids):
            hex_length_str = format(len(tid), "x").zfill(2)
            result += hex_length_str + tid
            if i < len(transformed_ids) - 1:
                result += "g"

        if len(result) < 20:
            result += digest[0:20 - len(result)]

        md5 = hashlib.md5()
        md5.update(result.encode("utf-8"))
        result += md5.hexdigest()[0:3]
        return result

    def get_url(self, book_id):
        return f"https://weread.qq.com/web/reader/{self._calculate_book_str_id(book_id)}"
