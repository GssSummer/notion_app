#!/usr/bin/env python3
"""
weread2notionpro - 微信读书同步到 Notion

Usage:
    python -m weread2notionpro [command]

Commands:
    book       同步书籍信息
    weread     同步笔记和划线
    read_time  同步阅读时长和热力图
    all        执行全部同步
"""

import sys
from weread2notionpro.sync import sync_books, sync_notes, sync_read_time


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "all"
    
    commands = {
        "book": sync_books,
        "weread": sync_notes,
        "read_time": sync_read_time,
        "all": lambda: (sync_books(), sync_notes(), sync_read_time()),
    }
    
    if command in commands:
        try:
            commands[command]()
            print(f"✅ {command} 同步完成")
        except Exception as e:
            print(f"❌ 同步失败: {e}")
            sys.exit(1)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
