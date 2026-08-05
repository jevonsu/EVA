"""Built-in workflow definitions (seeded if missing)."""

from __future__ import annotations

from typing import Any


def demo_workspace_hello() -> dict[str, Any]:
    return {
        "id": "demo_workspace_hello",
        "name": "示例：工作区问候",
        "description": "演示线性工作流：列工作区 → 写一条说明到 temp（可删）。删后重启可恢复内置。",
        "version": "0.2.0",
        "enabled": True,
        "builtin": True,
        "inputs": {
            "note": {
                "type": "string",
                "default": "workflow demo",
                "label": "备注内容",
            }
        },
        "steps": [
            {
                "id": "list_ws",
                "type": "tool",
                "tool": "workspace",
                "args": {"action": "list", "path": "."},
                "save_as": "listing",
            },
            {
                "id": "write_note",
                "type": "tool",
                "tool": "workspace",
                "args": {
                    "action": "write",
                    "path": "temp/workflow_demo.txt",
                    "content": "Workflow demo note: {{inputs.note}}\nListed ok.",
                },
                "save_as": "written",
            },
            {
                "id": "done",
                "type": "note",
                "message": "示例工作流完成。可在设定→工作流中编辑步骤。",
            },
        ],
    }


def commercial_content_pipeline() -> dict[str, Any]:
    """编排骨架：kb → 阶段1 → gate → 1.5? → gate → 2 → gate → 3（只出文案/Prompt，不生图视频）。"""
    return {
        "id": "commercial_content_pipeline",
        "name": "商业内容生产流水线",
        "description": (
            "产品内容 SOP 编排骨架：拉知识库 → 阶段1识别 → 确认 → "
            "可选1.5咨询 → 阶段2策略 → 确认 → 阶段3按需生成文案/Prompt。"
            "不自动生图/视频；确认后可在对话中用 grok_media。"
            "可在 UI 编辑；删后重启可恢复内置。"
        ),
        "version": "1.0.0",
        "enabled": True,
        "builtin": True,
        "inputs": {
            "brief": {
                "type": "string",
                "default": "",
                "label": "产品/需求说明",
            },
            "image_path": {
                "type": "string",
                "default": "",
                "label": "产品图路径（workspace 相对，可空）",
            },
            "need_consult": {
                "type": "boolean",
                "default": True,
                "label": "目标不明时走阶段1.5咨询",
            },
            "content_type": {
                "type": "string",
                "default": "图片",
                "label": "需要内容类型（图片/视频/小红书/淘宝/抖音/文案）",
            },
            "platform": {
                "type": "string",
                "default": "",
                "label": "销售平台（可空=待咨询或默认小红书）",
            },
            "audience": {
                "type": "string",
                "default": "",
                "label": "目标人群（可空）",
            },
        },
        "steps": [
            {
                "id": "load_sop",
                "type": "tool",
                "tool": "kb",
                "args": {
                    "action": "search",
                    "query": "产品内容流水线SOP 阶段1 阶段2 阶段3",
                },
                "save_as": "load_sop",
                "on_error": "continue",
            },
            {
                "id": "stage1",
                "type": "agent",
                "use_tools": True,
                "use_memory": True,
                "save_as": "stage1",
                "prompt": (
                    "你正在执行【商业内容生产流水线·阶段1 产品识别】。\n"
                    "严格遵循知识库「产品内容流水线SOP」阶段1格式输出：\n"
                    "✅ 可确认 / 🔍 推测 / ❓ 需补充。禁止编造产品细节。\n\n"
                    "用户说明：{{inputs.brief}}\n"
                    "图片路径（若有且非空，请用 analyze_image_auto 分析）：{{inputs.image_path}}\n"
                    "平台提示：{{inputs.platform}}\n"
                    "人群提示：{{inputs.audience}}\n\n"
                    "知识库检索摘录：\n{{steps.load_sop.output}}\n\n"
                    "若图片路径为空，仅根据文字说明做识别并标清信息不足。"
                    "本步不要进入完整阶段3生成；不要调用 grok_media。"
                ),
            },
            {
                "id": "gate_after_1",
                "type": "human_gate",
                "prompt": "请确认阶段1识别结果。继续将进入咨询/策略阶段；不对可先停下修改说明后重跑。",
            },
            {
                "id": "stage15",
                "type": "agent",
                "use_tools": False,
                "use_memory": True,
                "save_as": "stage15",
                "when": {"path": "inputs.need_consult", "truthy": True},
                "prompt": (
                    "【阶段1.5 主动咨询】目标仍可能不明确时，最多问 3 个关键选择题（A/B/C），"
                    "选题参考：平台 / 人群 / 内容类型 / 色调。不要超过3问，不要开放长答题。\n"
                    "若用户说明已很清楚，可简短确认并列出将采用的默认假设。\n"
                    "用户说「随便/默认」时：平台小红书、人群宝妈/女性、内容图片+文案，"
                    "并标注 ⚠️ 基于默认策略。\n\n"
                    "用户说明：{{inputs.brief}}\n"
                    "已填平台：{{inputs.platform}} 人群：{{inputs.audience}} 内容类型：{{inputs.content_type}}\n"
                    "阶段1结果：\n{{steps.stage1.output}}\n"
                    "不要调用生图/视频工具。"
                ),
            },
            {
                "id": "gate_brief",
                "type": "human_gate",
                "prompt": "请确认平台/人群/内容类型（或回复「随便」用默认策略）。确认后进入阶段2策略。",
            },
            {
                "id": "stage2",
                "type": "agent",
                "use_tools": False,
                "use_memory": True,
                "save_as": "stage2",
                "prompt": (
                    "【阶段2 商业策略】基于阶段1与用户确认，输出严格五段：\n"
                    "📌 推荐平台 / 推荐内容类型 / 目标人群画像 / 核心传播策略 / 视觉调性。\n"
                    "内部可按痛点/场景思考，但不要输出长篇思考过程。\n\n"
                    "用户说明：{{inputs.brief}}\n"
                    "内容类型意向：{{inputs.content_type}}\n"
                    "平台：{{inputs.platform}} 人群：{{inputs.audience}}\n"
                    "阶段1：\n{{steps.stage1.output}}\n"
                    "阶段1.5（若有）：\n{{steps.stage15.output}}\n"
                    "不要调用 grok_media；不要一次输出全部生成模式。"
                ),
            },
            {
                "id": "gate_strategy",
                "type": "human_gate",
                "prompt": "请确认策略方向。确认后进入阶段3：仅生成你需要的内容类型的文案/Prompt（不自动出图/视频）。",
            },
            {
                "id": "stage3",
                "type": "agent",
                "use_tools": False,
                "use_memory": True,
                "save_as": "stage3",
                "prompt": (
                    "【阶段3 按需生成】只生成用户需要的内容类型，不要全部模式一起输出。\n"
                    "需要类型：{{inputs.content_type}}\n"
                    "平台：{{inputs.platform}} 人群：{{inputs.audience}}\n\n"
                    "规则：\n"
                    "- 图片 → 模式 A 图片 Prompt（中英）\n"
                    "- 视频 / 图生视频 / 主图视频 → 默认先完整输出模式 A′ 首帧改图 Prompt，再输出模式 B CRITICAL 视频模板；"
                    "用户明确跳过改图时仅输出 B 并标注原图参考\n"
                    "- 小红书 → 模式 C\n"
                    "- 淘宝/天猫 → 模式 D\n"
                    "- 抖音/视频号脚本 → 模式 E（画面投喂文用模式 B 时注明）\n"
                    "- 文案 → 按平台给可发布文案\n\n"
                    "严格遵守 SOP 输出格式。本步只产出可复制文本/Prompt，禁止调用 grok_media 真正生成媒体。\n\n"
                    "阶段1：\n{{steps.stage1.output}}\n"
                    "阶段2：\n{{steps.stage2.output}}\n"
                    "用户说明：{{inputs.brief}}\n"
                    "图片路径（仅供描述，勿强行生成）：{{inputs.image_path}}"
                ),
            },
            {
                "id": "done",
                "type": "note",
                "message": (
                    "流水线编排完成。阶段3 产出见上一步。"
                    "若要真正生图/改图/视频，请在对话中说明并使用 grok_media，或继续聊天微调 Prompt。"
                ),
            },
        ],
    }


def commercial_video_a_prime_then_b() -> dict[str, Any]:
    """视频默认路径：A′ 首帧改图 Prompt → 确认 → 模式 B（不自动生成媒体）。"""
    return {
        "id": "commercial_video_a_prime_then_b",
        "name": "视频路径：A′→B",
        "description": (
            "视频默认编排：知识库 → 模式 A′ 首帧改图 Prompt → 人工确认 → 模式 B CRITICAL 视频模板。"
            "不自动调用 grok_media。skip_a_prime=true 时跳过 A′。"
            "可在 UI 编辑；删后重启可恢复内置。"
        ),
        "version": "1.0.0",
        "enabled": True,
        "builtin": True,
        "inputs": {
            "product_desc": {
                "type": "string",
                "default": "",
                "label": "产品描述",
            },
            "image_path": {
                "type": "string",
                "default": "",
                "label": "参考图路径（可空）",
            },
            "platform": {
                "type": "string",
                "default": "小红书",
                "label": "平台",
            },
            "audience": {
                "type": "string",
                "default": "",
                "label": "目标人群",
            },
            "skip_a_prime": {
                "type": "boolean",
                "default": False,
                "label": "跳过改图，直接模式 B（用原图）",
            },
        },
        "steps": [
            {
                "id": "load_modes",
                "type": "tool",
                "tool": "kb",
                "args": {
                    "action": "search",
                    "query": "产品内容流水线SOP 模式A′ 模式B 首帧 视频",
                },
                "save_as": "load_modes",
                "on_error": "continue",
            },
            {
                "id": "a_prime",
                "type": "agent",
                "use_tools": True,
                "use_memory": True,
                "save_as": "a_prime",
                "when": {"path": "inputs.skip_a_prime", "truthy": False},
                "prompt": (
                    "【模式 A′ 首帧改图 Prompt】把随拍提升为可商用静帧母版。\n"
                    "只改背景/环境光/景深/干净度/居中；严禁改产品颜色/外形/材质/Logo/角度大变。\n"
                    "按 SOP 输出：首帧改图目标 + 英文/中文 Edit Prompt + 使用说明。\n"
                    "信息不足时默认浅色棚拍+柔光+居中并标注默认策略。\n\n"
                    "产品：{{inputs.product_desc}}\n"
                    "参考图：{{inputs.image_path}}\n"
                    "平台：{{inputs.platform}} 人群：{{inputs.audience}}\n"
                    "知识库：\n{{steps.load_modes.output}}\n"
                    "若有图可用 analyze_image_auto 辅助锁定外观；不要调用 grok_media 真正出图；不要写模式 B 分镜旁白。"
                ),
            },
            {
                "id": "gate_frame",
                "type": "human_gate",
                "prompt": "请确认首帧改图方案（或确认跳过 A′）。确认后生成模式 B 视频 Prompt。",
            },
            {
                "id": "mode_b",
                "type": "agent",
                "use_tools": False,
                "use_memory": True,
                "save_as": "mode_b",
                "prompt": (
                    "【模式 B AI 视频 Prompt】使用 CRITICAL 锁定参考图外观的完整商业展示视频模板"
                    "（含旁白与字幕时间轴）。\n"
                    "开头注明 Reference：\n"
                    "- 若未跳过 A′：Reference=改图后首帧（模式 A′）\n"
                    "- 若 skip_a_prime：标注 ⚠️ 参考图为原始随拍\n"
                    "视频阶段不要再大改背景。视觉特征只能来自可确认信息。\n\n"
                    "产品：{{inputs.product_desc}}\n"
                    "图：{{inputs.image_path}}\n"
                    "平台：{{inputs.platform}} 人群：{{inputs.audience}}\n"
                    "skip_a_prime={{inputs.skip_a_prime}}\n"
                    "A′ 输出（若有）：\n{{steps.a_prime.output}}\n"
                    "知识库：\n{{steps.load_modes.output}}\n"
                    "只输出可复制 Prompt，禁止调用 grok_media。"
                ),
            },
            {
                "id": "done",
                "type": "note",
                "message": (
                    "A′→B 编排完成。真正生成视频请在对话中使用 grok_media，"
                    "并以确认后的首帧（或原图）作为参考图。"
                ),
            },
        ],
    }


def all_builtin_definitions() -> list[dict[str, Any]]:
    return [
        demo_workspace_hello(),
        commercial_content_pipeline(),
        commercial_video_a_prime_then_b(),
    ]
