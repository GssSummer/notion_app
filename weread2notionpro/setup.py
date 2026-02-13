from setuptools import setup, find_packages

setup(
    name="weread2notionpro",
    version="0.2.5",
    packages=find_packages(),
    install_requires=[
        "requests",
        "pendulum",
        "retrying",
        "notion-client",
        "github-heatmap",
        "python-dotenv",
    ],
    entry_points={
        "console_scripts": [
            "weread2notionpro = weread2notionpro.__main__:main",
            "book = weread2notionpro.__main__:main",
            "weread = weread2notionpro.__main__:main",
            "read_time = weread2notionpro.__main__:main",
        ],
    },
    author="malinkang",
    author_email="linkang.ma@gmail.com",
    description="自动将微信读书笔记和阅读记录同步到 Notion",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/malinkang/weread2notion-pro",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
)
