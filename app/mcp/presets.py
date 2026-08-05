"""User-friendly MCP server presets (stdio)."""

from __future__ import annotations

from typing import Any


def mcp_presets() -> list[dict[str, Any]]:
    """Curated one-click templates for ordinary users.

    Requires Node.js + npx on the host machine for most entries.
    """
    return [
        {
            "id": "filesystem",
            "title": "本机文件夹",
            "emoji": "📁",
            "desc": "让助手读写你指定目录里的文件（比工作区更广）。",
            "need": "需安装 Node.js",
            "name": "本机文件夹",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
            "env": {},
            "hint": "默认目录为「.」项目当前目录；高级里可改路径参数。",
        },
        {
            "id": "fetch",
            "title": "网页抓取",
            "emoji": "🌐",
            "desc": "让助手抓取公开网页内容（Fetch MCP）。",
            "need": "需安装 Node.js",
            "name": "网页抓取",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-fetch"],
            "env": {},
            "hint": "适合「打开这个链接总结一下」。",
        },
        {
            "id": "memory",
            "title": "知识图谱记忆",
            "emoji": "🧠",
            "desc": "MCP 官方 memory 服务（实体/关系记忆，不同于本应用长期记忆）。",
            "need": "需安装 Node.js",
            "name": "知识图谱记忆",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-memory"],
            "env": {},
            "hint": "与设定→记忆 是两套系统，可并存。",
        },
        {
            "id": "time",
            "title": "时间工具",
            "emoji": "⏰",
            "desc": "提供时区/当前时间等（MCP time）。",
            "need": "需安装 Node.js",
            "name": "时间工具",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-time"],
            "env": {},
            "hint": "本应用已有「当前时间」内置工具；需要时区场景可加。",
        },
        {
            "id": "git",
            "title": "Git 仓库",
            "emoji": "🌿",
            "desc": "查询本地 Git 状态、日志、差异等。",
            "need": "需 Node.js + 本机有 git",
            "name": "Git",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-git", "--repository", "."],
            "env": {},
            "hint": "默认仓库为当前项目目录。",
        },
        {
            "id": "custom",
            "title": "自定义命令",
            "emoji": "⚙️",
            "desc": "自己填命令与参数（给熟悉命令行的人）。",
            "need": "需自己准备 MCP 程序",
            "name": "",
            "command": "",
            "args": [],
            "env": {},
            "hint": "例如 command=npx，参数每行一个。",
            "advanced_only": True,
        },
    ]


def preset_by_id(preset_id: str) -> dict[str, Any] | None:
    for p in mcp_presets():
        if p.get("id") == preset_id:
            return p
    return None
