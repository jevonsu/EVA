# 办公文档

系统技能。在 **workspace** 里读写、编辑、删除 Word / Excel / PPT / PDF / Markdown。

**怎么喊：** 读这份 Word、改 Excel、做 PPT、看 PDF、写 Markdown。

**何时用：** `.docx` `.xlsx` `.pptx` `.pdf` `.md`。普通 txt / 代码 / 图片仍用 `workspace`。

**不要用：** 列目录、重命名、txt/代码/图片（用 `workspace`）；旧版 `.doc` `.xls` `.ppt`（请另存为新格式）；Hub HTTP 绑定下的二进制文档（改用共享文件夹）。

## 动作

| action | 说明 |
|---|---|
| `info` | 工作区路径与支持格式 |
| `list` | 列出办公文件，可 `kind=excel` |
| `read` | 抽出文本。Excel 可 `sheet=`；PPT 可 `slide=` |
| `write` | 新建或覆盖。无扩展名时加 `kind=` |
| `edit` | 查找替换、改格子、追加页/段 |
| `delete` | 删除该文件 |

**批量（同一动作应用到多份文件）：**

- `paths=["a.docx","b.xlsx","c.md"]`
- 或 `path="reports/*.xlsx"`（也支持 `*.md`）
- 最多 40 个；返回 `ok_count` / `fail_count` / `results[]`（每份单独 ok/error）
- 一份失败不会中断其余文件

Excel：`cell=B2` + `value=`，或 `rows_json='[["A","B"],["1","2"]]'`。  
PPT：正文用 `---` 或 `##` 分页。  
PDF：`edit` 会丢原版式；追加文本页相对安全。
