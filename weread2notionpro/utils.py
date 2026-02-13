import calendar
import hashlib
import os
import re
import base64
import requests
from datetime import datetime, timedelta

import pendulum

from weread2notionpro import (
    RICH_TEXT, URL, RELATION, NUMBER, DATE, FILES, STATUS, TITLE, SELECT,
    MAX_LENGTH, TZ
)


# ========== Notion Block Builders ==========

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
            "time_zone": TZ,
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


def get_embed(url):
    return {"type": "embed", "embed": {"url": url}}


def get_block(content, block_type, show_color, style, color_style, review_id):
    color = "default"
    if show_color:
        color_map = {1: "red", 2: "purple", 3: "blue", 4: "green", 5: "yellow"}
        color = color_map.get(color_style, "default")
    
    block = {
        "type": block_type,
        block_type: {
            "rich_text": [{"type": "text", "text": {"content": content[:MAX_LENGTH]}}],
            "color": color,
        },
    }
    
    if block_type == "callout":
        emoji_map = {0: "💡", 1: "⭐", 2: "〰️"}
        emoji = "✍️" if review_id is not None else emoji_map.get(style, "〰️")
        block[block_type]["icon"] = {"emoji": emoji}
    
    return block


# ========== Property Builders ==========

def get_properties(data_dict, type_dict):
    properties = {}
    for key, value in data_dict.items():
        prop_type = type_dict.get(key)
        if value is None or prop_type is None:
            continue
        
        prop = None
        if prop_type == TITLE:
            prop = {"title": [{"type": "text", "text": {"content": str(value)[:MAX_LENGTH]}}]}
        elif prop_type == RICH_TEXT:
            prop = {"rich_text": [{"type": "text", "text": {"content": str(value)[:MAX_LENGTH]}}]}
        elif prop_type == NUMBER:
            prop = {"number": value}
        elif prop_type == STATUS:
            prop = {"status": {"name": value}}
        elif prop_type == FILES:
            prop = {"files": [{"type": "external", "name": "Cover", "external": {"url": value}}]}
        elif prop_type == DATE:
            prop = {
                "date": {
                    "start": pendulum.from_timestamp(value, tz=TZ).to_datetime_string(),
                    "time_zone": TZ,
                }
            }
        elif prop_type == URL:
            prop = {"url": value}
        elif prop_type == SELECT:
            prop = {"select": {"name": value}}
        elif prop_type == RELATION:
            prop = {"relation": [{"id": rid} for rid in value]}
        
        if prop:
            properties[key] = prop
    
    return properties


# ========== Data Extractors ==========

def get_rich_text_from_result(result, name):
    rich_text = result.get("properties", {}).get(name, {}).get("rich_text", [])
    return rich_text[0].get("plain_text") if rich_text else None


def get_number_from_result(result, name):
    return result.get("properties", {}).get(name, {}).get("number")


def get_property_value(property_data):
    """从 Property 中提取值"""
    prop_type = property_data.get("type")
    content = property_data.get(prop_type)
    
    if content is None:
        return None
    
    if prop_type in ("title", "rich_text"):
        return content[0].get("plain_text") if content else None
    elif prop_type in ("status", "select"):
        return content.get("name")
    elif prop_type == "files":
        if content and content[0].get("type") == "external":
            return content[0].get("external", {}).get("url")
        return None
    elif prop_type == "date":
        return str_to_timestamp(content.get("start"))
    else:
        return content


# ========== Date & Time Utilities ==========

def format_time(seconds):
    """将秒格式化为 xx时xx分格式"""
    result = []
    hours = seconds // 3600
    if hours > 0:
        result.append(f"{hours}时")
    minutes = (seconds % 3600) // 60
    if minutes > 0:
        result.append(f"{minutes}分")
    return "".join(result) if result else "0分"


def format_date(date, fmt="%Y-%m-%d %H:%M:%S"):
    return date.strftime(fmt)


def timestamp_to_date(timestamp):
    """时间戳转化为 date"""
    return datetime.utcfromtimestamp(timestamp) + timedelta(hours=8)


def str_to_timestamp(date_str):
    if date_str is None:
        return 0
    dt = pendulum.parse(date_str)
    return int(dt.timestamp())


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
    first_day = (date - timedelta(days=date.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    last_day = first_day + timedelta(days=6)
    return first_day, last_day


# ========== Image Utilities ==========

UPLOAD_URL = "https://wereadassets.malinkang.com/"


def upload_image(folder_path, filename, file_path):
    with open(file_path, "rb") as file:
        content_base64 = base64.b64encode(file.read()).decode("utf-8")
    
    data = {"file": content_base64, "filename": filename, "folder": folder_path}
    response = requests.post(UPLOAD_URL, json=data)
    
    if response.status_code == 200:
        print("File uploaded successfully.")
        return response.text
    return None


def url_to_md5(url):
    md5_hash = hashlib.md5()
    md5_hash.update(url.encode("utf-8"))
    return md5_hash.hexdigest()


def download_image(url, save_dir="cover"):
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    
    file_name = url_to_md5(url) + ".jpg"
    save_path = os.path.join(save_dir, file_name)
    
    if os.path.exists(save_path):
        print(f"File {file_name} already exists. Skipping download.")
        return save_path
    
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with open(save_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=128):
                file.write(chunk)
        print(f"Image downloaded successfully to {save_path}")
    else:
        print(f"Failed to download image. Status code: {response.status_code}")
    
    return save_path
