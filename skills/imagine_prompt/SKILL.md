# Grok提示词

生成或检查 Grok Imagine 图像 / 视频提示词。与 EVA 侧栏「Grok提示词」网页工具同一套规则：同一次构建生成的规则引擎 `core_bundle.js`，由 `engine.js` 用本机 Node.js 运行。输出中英文提示词、检查问题和参数建议。只生成文字，不出图、不出视频。

**怎么喊：** 帮我写一个产品图生视频提示词、文生图：一只橘猫趴在窗台，竖版 9:16、检查这段 Imagine 提示词、查一下当前视频参数 / 参数更新记录。

## 调用步骤（对话模型）
1. 可选：`action=describe`（加 mode、form），查看该表单的字段 id 和选项 key。也可以加 `field=angle`，只看一个字段。
2. `action=build`，传 `mode` + `form` + `fields`（+ `params`）：
   - mode：t2i 文生图 / i2i 图生图 / i2v 图生视频 / t2v 文生视频 / ref 参考图生视频。
   - form：person 人物 / product 产品 / other 其他（动物、场景）。
   - spicy=true 是辣椒模式，只适用于人物。
   - 选项字段（如 framing 景别、angle 角度、lens 镜头）填 key，或中文名。
   - 结构字段（如 subject）填 `{"parts":{...}}` 或自由文本。
   - 自由文本填 `{"zh":"中文","en":"英文"}`。英文由你翻译；没给英文时按网页同款词典翻译，剩下没译的列在 `translation.missing`。请补译后再调用。
   - 图生图保持 / 修改：`keep: {"face":"keep","background":{"change":"雨夜街道"}}`。
   - 图生视频时间轴：`fr: {"tl":true, "seg1":3, "segs":[{"b":6,"action":"..."}], "keys":[{"t":2,"zh":"..","en":".."}], "endf":{"zh":"..","en":".."}}`。
   - 目标比例：文生图 `params.iar`、图生图 `i2iar`、图生视频 `i2var`、文生视频和参考图 `ar`。保持原图比例时请给 `source_size {w,h}`。
   - 模型、时长、分辨率：`params.model / dur / res`。
3. 把 `prompt_en`、`prompt_zh`、`lint`（问题）、`settings`、`param_notes`（参数建议）如实转告用户。参数不写进提示词。

其他 action：
- `lint`：检查现成提示词，传 `prompt`。
- `guide`：返回写法结构。
- `restore`：还原网页导出的历史，传 `history_path` 或 `history_entry`。
- `params`：只读，当前参数。
- `params_log`：只读，参数更新记录。
- 旧版 `parts`（英文片段）调用仍然可用。

## 需要用户明确要求才可调用（confirm=true）
- `params_update`：联网更新官方参数。只抓官方白名单页面，写入 data/prompt_studio_params.json，并追加更新记录。与网页按钮相同。
- `analyze_image`：识图。只接受 workspace 内的图片（聊天上传的图片在 `uploads/`），不下载网址。用「设定 → 集成 → Vision」的识图模型，可能产生费用。返回的 `vision_id` 要在之后的 build 里带上，让未成年 / 真实人物风险标记生效。没有识图结果时，不要声称看过图片。

## 限制（如实告诉用户）
- 网页的历史记录、浏览器里的图片和本地译文缓存，都保存在浏览器中，技能读不到，也不会自动上传。需要用户在网页「历史 → 导出」后，把文件放进 workspace，或者直接把内容提供给你。
- 网页里的「使用内置参数」开关也只保存在浏览器；技能默认使用服务器上已更新的参数（`use_builtin_params=true` 可改用内置参数）。
- 网页的 AI 翻译 / 优化、识图自动填表没有移植到技能。翻译由对话模型完成。
- 找不到 Node.js 时，技能会退回旧版规则（`engine=legacy`），结果不保证与网页一致。
- 若结果里 `same_build_as_web=false`，说明技能和网页的版本不一致。

## 底线
命中硬性禁用（未成年人、真实人物性化、非同意、违法内容）时，返回 `blocked=true`，不给提示词。这项检查由网页同款规则执行，后端还会再复核一遍。请如实告诉用户，不要改写措辞绕过。辣椒模式只适用于明确的虚构成年角色。
