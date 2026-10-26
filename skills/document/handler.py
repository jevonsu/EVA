"""System skill: Word / Excel / PPT / PDF / Markdown in workspace."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

DESC = (
    "文档：在工作区读写编辑删除 Word(.docx)、Excel(.xlsx)、PPT(.pptx)、PDF、Markdown。"
    "action=info|list|read|write|edit|delete。"
    "批量：paths 数组，或 path 通配符如 reports/*.xlsx，最多 40 个，返回每份结果。"
    "列目录、重命名、txt/代码/图片用 workspace。旧版 .doc/.xls/.ppt 请另存为新格式。"
    "Excel 改格子用 cell+value；改一批用 rows_json。PDF 编辑会丢版式。"
)


async def handle(
    action: str = "read",
    path: str = "",
    paths: list | str | None = None,
    paths_json: str = "",
    content: str = "",
    kind: str = "",
    find: str = "",
    replace: str = "",
    sheet: str = "",
    cell: str = "",
    value: str = "",
    rows_json: str = "",
    slide: int = 0,
    append: bool = False,
    max_chars: int = 12000,
) -> str:
    from app.services.document_ops import run

    try:
        result = run(
            action=action,
            path=path,
            paths=paths,
            paths_json=paths_json,
            content=content,
            kind=kind,
            find=find,
            replace=replace,
            sheet=sheet,
            cell=cell,
            value=value,
            rows_json=rows_json,
            slide=int(slide or 0),
            append=bool(append),
            max_chars=int(max_chars or 12000),
        )
    except Exception as extra:
        logger.exception("document failed")
        result = {"ok": False, "error": str(extra)}
    return json.dumps(result, ensure_ascii=False)


def register(registry):
    registry.register(
        "document",
        DESC,
        handle,
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["info", "list", "read", "write", "edit", "delete"],
                    "description": "info=格式说明；list=列出办公文件；其余需要 path",
                },
                "path": {
                    "type": "string",
                    "description": "相对工作区，如 reports/a.docx。通配符批量：reports/*.xlsx 或 *.md",
                },
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "批量路径列表。与 path 合并去重，最多 40 个",
                },
                "paths_json": {
                    "type": "string",
                    "description": '批量路径 JSON 数组，如 ["a.docx","b.xlsx"]',
                },
                "kind": {
                    "type": "string",
                    "enum": ["word", "excel", "ppt", "pdf", "markdown", ""],
                    "description": "无扩展名时指定。word=docx，excel=xlsx",
                },
                "content": {
                    "type": "string",
                    "description": "write/edit 正文。Markdown 可用 # 标题；PPT 用 --- 或 ## 分页；Excel 可用表格或 CSV",
                },
                "find": {"type": "string", "description": "edit 查找"},
                "replace": {"type": "string", "description": "edit 替换为"},
                "sheet": {"type": "string", "description": "Excel 工作表名，默认第一个"},
                "cell": {"type": "string", "description": "Excel 格子，如 B2"},
                "value": {"type": "string", "description": "写入 cell 的值"},
                "rows_json": {
                    "type": "string",
                    "description": 'Excel 行 JSON，如 [["姓名","数量"],["A",1]]',
                },
                "slide": {
                    "type": "integer",
                    "description": "PPT 页码，从 1 起；0 表示全部",
                },
                "append": {
                    "type": "boolean",
                    "description": "true=追加（Word 段、Excel 行、PPT 页、PDF 页、Markdown 文末）",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "read 返回字符上限，默认 12000",
                },
            },
        },
        source="skill",
        metadata={"timeout_sec": 180, "group": "office", "tag": "文档"},
    )
