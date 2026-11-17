const IPS_BUILD='c23756db496f';/* 共享规则构建号：网页与 EVA 技能 core_bundle 相同即同源 */
'use strict';
/* ================= 知识库（来自《Grok Imagine 使用白皮书 修订版 2026-11-09》） ================= */
const KB = {
  version:'修订版 2026-11-09',
  actions:[
    {k:'turn',zh:'缓慢转头',en:'{S} slowly turns {P} head toward the camera',zt:'{Z}缓慢转头看向镜头',cam:'Static locked shot 或 Slow push-in',note:'自然、可控，最常用'},
    {k:'smile',zh:'轻轻微笑',en:'{S} slowly smiles',zt:'{Z}轻轻微笑',cam:'Close-up 或 Medium shot',note:'表情微变，适合肖像'},
    {k:'blink',zh:'眨眼',en:'{S} blinks occasionally',zt:'{Z}偶尔眨眼',cam:'Static locked shot',note:'呼吸待机必备'},
    {k:'breathe',zh:'自然呼吸',en:'{S} breathes slowly and naturally',zt:'{Z}自然缓慢地呼吸',cam:'Static locked shot',note:'胸腔起伏，增加生命感'},
    {k:'wave',zh:'轻轻挥手',en:'{S} raises {P} hand to wave',zt:'{Z}抬手轻轻挥手',cam:'Medium shot, Static locked shot',note:'单一动作，避免手部变形'},
    {k:'walk',zh:'缓慢行走',en:'{S} walks slowly toward the camera',zt:'{Z}缓慢走向镜头',cam:'Slow tracking shot 或 Static with push-in',note:'需要明确方向'},
    {k:'lookback',zh:'回头看',en:'{S} looks back over {P} shoulder',zt:'{Z}回头越过肩膀看',cam:'Medium shot, Slow pan',note:'增加故事感'},
    {k:'lower',zh:'低头',en:'{S} lowers {P} gaze slowly',zt:'{Z}缓慢低头垂下目光',cam:'Close-up',note:'情绪表达'},
    {k:'hair',zh:'整理头发',en:'{S} tucks {P} hair behind {P} ear',zt:'{Z}把头发别到耳后',cam:'Close-up, Static locked shot',note:'小动作，稳定性好'},
    {k:'stand',zh:'缓慢起身',en:'{S} slowly stands up',zt:'{Z}缓慢起身',cam:'Medium-wide shot',note:'动作幅度较大，需谨慎'}
  ],
  cameras:[
    {k:'static',zh:'静止锁定',zt:'静止机位',en:'Static locked shot',note:'最稳定，主体清晰；肖像、呼吸、产品'},
    {k:'push',zh:'缓慢推进',en:'Slow push-in',note:'强调人物、增加沉浸'},
    {k:'pull',zh:'缓慢拉远',en:'Slow pull-out',note:'揭示环境、结束镜头'},
    {k:'panl',zh:'缓慢左移',en:'Gentle pan left',note:'展示场景、跟随动作'},
    {k:'panr',zh:'缓慢右移',en:'Gentle pan right',note:'展示场景、跟随动作'},
    {k:'track',zh:'侧向跟踪',en:'Slow tracking shot from the side',note:'行走、移动'},
    {k:'orbit',zh:'缓慢环绕',en:'Slow orbit',note:'展示角色、产品，360°感'},
    {k:'hand',zh:'轻微手持晃动',en:'Subtle handheld sway',note:'纪录片、真实感'},
    {k:'crane',zh:'升起俯拍',en:'Rising crane shot',note:'揭示大场景'},
    {k:'low',zh:'低角度仰拍',en:'Low angle looking up',note:'力量感、英雄感'},
    {k:'high',zh:'高角度俯拍',en:'High angle looking down',note:'脆弱感、环境关系'},
    {k:'ots',zh:'过肩镜头',en:'Over-the-shoulder shot',note:'对话、互动'}
  ],
  framing:[
    {k:'cu',zh:'特写',en:'Close-up'},{k:'ms',zh:'中景',en:'Medium shot'},{k:'mws',zh:'中远景',en:'Medium-wide shot'},
    {k:'ws',zh:'全景',en:'Wide shot'},{k:'macro',zh:'微距',en:'Macro shot'},{k:'tq',zh:'45° 四分之三视角',en:'Seen from a 45-degree three-quarter view'},
    {k:'low',zh:'低角度',en:'Low angle'},{k:'high',zh:'高角度',en:'High angle'},{k:'front',zh:'正面中景',en:'Front medium shot'}
  ],
  shot:[
    {k:'cu',zh:'特写',en:'Close-up'},{k:'ms',zh:'中景',en:'Medium shot'},{k:'mws',zh:'中远景',en:'Medium-wide shot'},
    {k:'ws',zh:'全景',en:'Wide shot'},{k:'macro',zh:'微距',en:'Macro shot'},
    {k:'ecu',zh:'大特写',en:'Extreme close-up'},{k:'mcu',zh:'近景',en:'Medium close-up'},{k:'full',zh:'全身',en:'Full-body shot',only:['person']},{k:'ews',zh:'大远景',en:'Extreme wide shot'}
  ],
  angle:[
    {k:'front',zh:'正面',en:'front view',zt:'正面视角'},{k:'tq',zh:'45° 四分之三',en:'seen from a 45-degree three-quarter view',zt:'45° 四分之三视角'},
    {k:'low',zh:'低角度仰拍',en:'low angle looking up',zt:'低角度仰拍'},{k:'high',zh:'高角度俯拍',en:'high angle looking down',zt:'高角度俯拍'},
    {k:'eye',zh:'平视',en:'eye-level view',zt:'平视视角'},{k:'worm',zh:'虫视角（贴地仰拍）',en:"worm's-eye view from ground level looking up",zt:'虫视角，贴地仰拍'},
    {k:'bird',zh:'鸟瞰',en:"bird's-eye view from high above",zt:'鸟瞰视角'},{k:'top',zh:'正俯拍（顶视）',en:'directly overhead top-down view',zt:'正上方垂直俯拍'},
    {k:'side',zh:'侧面',en:'side view',zt:'侧面视角'},{k:'back',zh:'背面',en:'view from behind',zt:'从背后拍摄'},
    {k:'ots',zh:'过肩',en:'over-the-shoulder view',zt:'过肩视角',only:['person']},{k:'pov',zh:'第一人称',en:'first-person point-of-view shot',zt:'第一人称视角',only:['person','other']},
    {k:'dutch',zh:'荷兰倾斜',en:'tilted Dutch angle with a slanted horizon',zt:'荷兰角倾斜构图'}
  ],
  lens:[
    {k:'uwide',zh:'超广角',en:'shot on an ultra-wide-angle lens',zt:'超广角镜头'},{k:'wide',zh:'广角',en:'shot on a wide-angle lens',zt:'广角镜头'},
    {k:'std',zh:'标准（50mm）',en:'shot on a standard 50mm lens',zt:'50mm 标准镜头'},{k:'port',zh:'中长焦（85mm）',en:'shot on an 85mm lens',zt:'85mm 中长焦镜头'},
    {k:'tele',zh:'长焦压缩',en:'shot on a telephoto lens with compressed perspective',zt:'长焦镜头，空间压缩感'},{k:'macro',zh:'微距镜头',en:'shot on a macro lens',zt:'微距镜头'},
    {k:'fish',zh:'鱼眼',en:'shot on a fisheye lens with strong barrel distortion',zt:'鱼眼镜头，明显桶形畸变'}
  ],
  depth:[
    {k:'shallow',zh:'浅景深',en:'shallow depth of field',zt:'浅景深，背景柔和虚化'},
    {k:'fg',zh:'前景',en:'a softly blurred element in the foreground',zt:'前景有轻微虚化的元素'},
    {k:'layer',zh:'分层',en:'layered composition with clear foreground, midground and background',zt:'前中后景分层构图'},
    {k:'atmo',zh:'大气透视',en:'distant elements fade into atmospheric haze',zt:'远景隐入大气薄雾（大气透视）'},
    {k:'focus',zh:'焦点锁定',en:'sharp focus on the subject, soft background',zt:'焦点锁定主体，背景柔和'},
    {k:'refl',zh:'反射',en:'reflections on wet pavement',zt:'湿地面上的反射'}
  ],
  preserve:[
    {k:'face',zh:'脸',en:'face'},{k:'expr',zh:'表情',en:'expression'},{k:'pose',zh:'姿势',en:'pose'},
    {k:'cloth',zh:'服装',en:'clothing'},{k:'hair',zh:'发型',en:'hair'},{k:'bg',zh:'背景',en:'background'},
    {k:'light',zh:'光线',en:'lighting'},{k:'angle',zh:'机位',en:'camera angle'},{k:'id',zh:'身份',en:'identity'},
    {k:'bone',zh:'骨相与发际线',en:'bone structure and hairline'}
  ],
  who:[
    {k:'she',zh:'她',en:'She',p:'her'},{k:'he',zh:'他',en:'He',p:'his'},{k:'person',zh:'人物',en:'The person',p:'their'},
    {k:'dh',zh:'数字人',en:'The digital human',p:'their'},{k:'they',zh:'他们',en:'They',p:'their'}
  ],
  sound:[
    {k:'',zh:'不指定'},{k:'room',zh:'仅房间底噪',en:'Soft room tone only.',zt:'只有轻微的房间底噪。'},
    {k:'amb',zh:'环境音（自填）'},{k:'dlg',zh:'对白（自填，自动加引号）'},{k:'nodlg',zh:'环境音 + 无对白',en:'No dialogue.',zt:'无对白。'}
  ],
  ambChips:[['distant traffic','远处车流声'],['soft rain','细雨声'],['soft rain on metal','雨打金属声'],['wind through the trees','风吹树叶声'],['gentle ocean waves','轻柔海浪声'],['soft room tone','轻微房间底噪'],['footsteps on wet pavement','湿地面上的脚步声']],
  refRoles:[
    {k:'char',zh:'角色',en:'character'},{k:'cloth',zh:'服装',en:'garment'},{k:'prod',zh:'产品',en:'product'},
    {k:'scene',zh:'场景',en:'scene'},{k:'prop',zh:'道具',en:'prop'},{k:'style',zh:'风格',en:'style'}
  ],
  models:[
    {k:'v15',name:'grok-imagine-video-1.5',pos:'最高质量',cap:'文生/图生视频原生1080p；参考图生视频（最多14张参考图）；预设声音最多3个；可固定首帧/尾帧及最多4个中间关键帧；原生音频含口型同步',lim:'参考图生视频最长15秒、输出最高720p',price:{480:0.08,720:0.14,1080:0.25}},
    {k:'lite',name:'grok-imagine-video-1.5-lite',pos:'最低单价',cap:'文生/图生视频；口型同步语音',lim:'720p 上采样至1080p；不支持参考图、预设声音、固定帧',price:{480:0.02,720:0.03,1080:0.14}},
    {k:'old',name:'grok-imagine-video',pos:'旧版',cap:'视频编辑（源视频最长8.7秒）；视频续写（增加2–10秒）；参考图生视频（最多7张、最长10秒）',lim:'最高720p',price:{480:0.05,720:0.07,1080:null}}
  ],
  ratios:['1:1','16:9','9:16','4:3','3:4','3:2','2:3','21:9','5:2'],
  faq:[
    ['脸部漂移','动作过大或重新描述','减小动作 + 明确 preserve face / bone structure / hairline','先锁定静态帧'],
    ['机位乱晃','未指定机位','加上 static locked shot 或单一明确机位','每条提示只写一个机位'],
    ['动作太弱','动词太被动','使用 walks / turns / lifts 等主动动词','加 slowly / gently'],
    ['背景变形','提示发明新元素','删除多余描述 + 加 preserve 列表','只写已有元素的变化'],
    ['手部畸形','复杂手部动作','简化或隐藏手部','避免精细手势'],
    ['文字错误','文字过长或未加引号','短句 + 双引号 + 标明位置','先用图像模式测试文字'],
    ['循环不自然','首尾帧不一致','提示 seamless loop + 后处理正反播放（Grok App 内 loop 功能未核实；API 可用同一图做首帧与尾帧）','静态机位 + 周期性微动作'],
    ['身份不一致','描述词变化','每镜头使用完全相同的描述词 + 参考图','先做角色表/关键帧'],
    ['被辣椒模式拦截','敏感词密度过高或边界模糊','简化提示、明确虚构、逐步加细节','先锁干净帧再进入辣椒模式；查阅禁用词库'],
    ['缺乏镜头感','未指定机位或景深','加入明确机位（Slow push-in）和浅景深','参考人物动作镜头表'],
    ['画面扁平','缺少纵深元素','加入前景虚化、分层构图、大气透视','明确前中后景']
  ],
  opt:[
    ['cinematic beautiful woman standing','主体不明确，质量词无效','A fictional adult woman in a white shirt standing by a window, soft natural light, medium shot, shallow depth of field.','主体优先 + 具体细节'],
    ['she walks and turns and smiles','多个动作叠加','She slowly turns her head toward the camera. Static locked shot.','单一动作 + 明确机位'],
    ['keep everything, just change background','保留句太笼统','Keep the exact face, pose, and clothing. Replace only the background with a neon-lit Tokyo street at night.','先改后保，具体保留'],
    ['high quality 8k masterpiece no blur','质量词无效，负面描述','Soft window light from the left, sharp focus on the subject, shallow depth of field.','正向描述光线与焦点'],
    ['young girl in school uniform','年龄模糊，易触发','A fictional adult woman in her mid-20s wearing a white shirt, sitting by a window.','明确成年 + 虚构']
  ],
  params:[
    ['时长（duration）','8 秒','1–15 秒','超过15秒需分段生成再拼接'],
    ['分辨率（resolution）','480p','480p / 720p / 1080p','默认 480p，需要更高分辨率必须显式指定；旧版最高720p'],
    ['画幅比例（aspect ratio）','—','1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, 21:9, 5:2','图生视频自动匹配输入图片比例'],
    ['音频','开启','—','原生音频默认开启'],
    ['多图编辑','—','最多合并5张源图片进行编辑','见 docs.x.ai Imagine 文档'],
    ['API 调用方式','异步','提交请求 → 用返回的 request_id 轮询 → 完成后下载视频','xAI SDK 可自动轮询']
  ],
  adv:[
    ['参考图生视频','参考图提供角色、产品、场景，但不固定首帧（不同于图生视频）。','每张图只承担一个角色、在画面中有固定位置；角色数量保持少；道具保持静止。按列表顺序用 <IMAGE_0>、<IMAGE_1>… 引用；若同时设置首帧 image，首帧占 <IMAGE_0>，参考图从 <IMAGE_1> 开始。','1.5：最多14张、15秒、720p；旧版：最多7张、10秒、720p'],
    ['参考图典型用途','虚拟试穿、产品植入、固定角色故事','例：the model from <IMAGE_0> wears the shirt from <IMAGE_1>.','同上'],
    ['首帧/尾帧固定','用 image 固定首帧、last_frame 固定尾帧，模型补全中间运动。','首尾用同一张图可做循环；提示词可选，用于控制运动与机位。','grok-imagine-video-1.5'],
    ['中间关键帧','在片中指定时间点固定画面，最多4个。','先生成一张静帧，再用图像编辑做出其他关键帧，只改需要变化的部分。','grok-imagine-video-1.5'],
    ['预设声音','通过 voice_id 选择预设声音，最多3个角色。','为多个说话角色分别指定声音，对白放引号内。','grok-imagine-video-1.5'],
    ['视频编辑','上传视频片段 + 修改指令，其余部分尽量保持不变。','写清楚必须保持不变的内容；源视频最长8.7秒。','grok-imagine-video'],
    ['视频续写','从源视频最后一帧继续生成，并合并为一段视频。','每次增加2–10秒。','grok-imagine-video']
  ],
  rules:[
    ['未成年人','零容忍：禁止任何涉及未成年人的性化内容','直接拒绝或封号'],
    ['真实人物','禁止非同意性亲密影像（NCII）、裸化真实人物、深度伪造性化','严格拦截；仅使用虚构成人'],
    ['暴力/犯罪','禁止教唆犯罪、恐怖主义、严重暴力指令','可能拒绝'],
    ['水印','禁止移除或篡改 Grok 生成水印/溯源标识（未核实）','违反政策'],
    ['时长','单次视频最长15秒','超长需分段生成再拼接'],
    ['参考图','1.5 参考图生视频：最多14张、最长15秒、输出最高720p；旧版：最多7张、最长10秒、720p','文生/图生视频：1.5 原生最高1080p；1.5-lite 720p上采样至1080p；旧版最高720p'],
    ['音频','原生音频默认开启（含唇形同步）','可在API请求静音'],
    ['辣椒模式','对虚构成人相对宽松，但仍受上述硬性底线约束','明确虚构、逐步加细节']
  ],
  flow:[
    ['1. 锁定静态帧','用文生图或图生图把关键帧做到满意','检查脸、手、文字、比例、灯光、纵深'],
    ['2. 短提示动画','只写动作+机位+保留+声音','2–3句为宜'],
    ['3. 检查结果','对比原图与提示','记录失败点'],
    ['4. 单点修复','只改失败的那一点，保留其余原文','一次只改一个变量'],
    ['5. 保存','保存最终提示词、日期、参数','便于复现与系列化（本工具「保存到历史」）'],
    ['额度建议','API 默认 480p，先低分辨率试动作，满意再指定 720p/1080p','API 按秒计费，见「参数与价格」'],
    ['人物类建议','动作 + 明确机位 + 纵深元素一起写','参考人物动作镜头与纵深表'],
    ['禁用词检查','写完提示后对照禁用词库','避免硬性拦截']
  ],
  sources:[
    ['xAI 视频概览','https://docs.x.ai/developers/model-capabilities/video/overview'],
    ['xAI 参考图生视频','https://docs.x.ai/developers/model-capabilities/video/reference-to-video'],
    ['xAI Imagine 文档','https://docs.x.ai/developers/model-capabilities/imagine'],
    ['xAI Imagine API 页面','https://x.ai/api/imagine']
  ],
  spicy:['仅适用于明确的虚构成年角色：提示中写 “fictional adult” 或具体年龄。',
    '硬性底线不可突破：未成年人、真实人物裸化/性化、非同意深度伪造、CSAM 零容忍。',
    '推荐工作流：先在普通模式锁定干净的静态关键帧，再做小幅度编辑或动画。',
    '身份漂移仍是主要问题：Preserve exact face, bone structure, and hairline，并使用参考图。',
    '一次一个主要动作，优先静态或微动；音频默认开启，对白放引号、短句。',
    '被拦截时：简化提示、明确虚构、逐步加细节，不要一次写满。']
};

/* ================= 禁用词库（手册「明确禁用词库」+「提示词优化指南」） ================= */
const LEX = {
  hard:[ // 硬性禁用（零容忍）
    {cat:'未成年人',re:/\b(child|children|kids?|little (girl|boy)|loli|lolita|shota|underage|under-age|teens?|teenagers?|teenage|schoolgirls?|schoolboys?|toddlers?|preteens?|minors)\b/gi},
    {cat:'未成年人',re:/(儿童|小孩|少女(?!感)|萝莉|正太|学生妹|未成年|幼女|幼童|女童|男童|小学生|初中生|中学生)/g},
    {cat:'非同意性化',re:/\b(nudify|non-?consensual|deepfakes?|upskirt|hidden camera|spycam)\b/gi},
    {cat:'非同意性化',re:/(偷拍|裸化|深度伪造|强迫|强制|换脸)/g},
    {cat:'违法内容',re:/\b(csam|bestiality|zoophilia)\b/gi},
    {cat:'违法内容',re:/(儿童色情|兽交)/g}
  ],
  risky:[ // 易触发
    {cat:'年龄模糊',re:/\b(young|youthful|young-looking|teen-like|school uniform|petite girl)\b/gi,fix:'明确写 “fictional adult” 或具体年龄（如 a 25-year-old woman / in her mid-20s）'},
    {cat:'年龄模糊',re:/(年轻|少女感|看起来很小|校服|稚嫩|童颜)/g,fix:'明确写「虚构成年」或具体年龄（如 25岁）'},
    {cat:'真实暗示',re:/\b(real person|real people|celebrity|celebrities|celebrity face|actual photo|real photo|famous (actor|actress|singer|person))\b/gi,fix:'写 “fictional” 或 “AI generated character”；不要使用真实人物/明星名'},
    {cat:'真实暗示',re:/(真人照片|真实人物|明星脸|明星|名人)/g,fix:'写「虚构」或「AI 生成角色」；不要使用真实人物/明星名'},
    {cat:'过度性化',re:/\b(nude|naked|explicit|genitals?|topless|nsfw)\b/gi,fix:'容易被拒。成人内容仅适用于辣椒模式下明确的虚构成年角色，硬性底线不变'},
    {cat:'过度性化',re:/(全裸|裸体|裸露|性器官|露点)/g,fix:'容易被拒。成人内容仅适用于辣椒模式下明确的虚构成年角色，硬性底线不变'},
    {cat:'暴力相关',re:/\b(gore|gory|dismember\w*|real injury|bloodbath|mutilat\w*)\b/gi,fix:'虚构场景需谨慎，避免指令性语言'},
    {cat:'暴力相关',re:/(血腥|肢解|真实伤害|断肢)/g,fix:'虚构场景需谨慎，避免指令性语言'}
  ],
  weak:[ // 低效
    {re:/\b(8k|4k|16k|masterpiece|high quality|best quality|ultra[- ]detailed|highly detailed)\b/gi,why:'质量词对 Grok 效果有限',fix:'写视觉结果：具体光线、材质、镜头，如 soft window light, shallow depth of field'},
    {re:/\b(perfect face|no distortion)\b/gi,why:'模糊指令',fix:'具体特征 + preserve，如 Preserve exact face, bone structure, and hairline'},
    {re:/\b(no blur|not shiny|without text|no text|not blurry)\b/gi,why:'负面列表容易被忽略',fix:'直接描述想要的材质和清晰度，如 brushed metal with fine grain, sharp focus'},
    {re:/\b(keep everything)\b/gi,why:'几乎不动 / 保留太笼统',fix:'明确写出要改和要保的部分：Change only the background. Keep the face exactly.'},
    {re:/\b(beautiful|gorgeous|stunning|sexy|hot|pretty)\b/gi,why:'过于主观',fix:'写具体服装、姿态、光线，如 wearing a linen dress, soft morning light'},
    {re:/(高质量|杰作|超清|8K|完美脸|美丽|漂亮|性感|保持一切|不要模糊)/g,why:'质量词/主观词/笼统词效果有限',fix:'改用具体光线、材质、镜头、服装与姿态描述'}
  ],
  sexual:/\b(nude|naked|sexy|sheer|lingerie|erotic|topless|seductive|sensual|nsfw|explicit|bikini)\b|性感|裸|情趣|内衣|诱惑|薄纱|色情/i,
  ageAmbig:/\b(young|youthful|young-looking|teen-like|school uniform|childlike|petite girl)\b|年轻|少女感|看起来很小|校服|稚嫩|童颜/i,
  adult:/\b(adult|grown|[2-9]\d-year-old|(18|19)-year-old|in (her|his|their) (early |mid-|mid |late )?(20s|30s|40s|50s|60s|twenties|thirties|forties)|mature)\b|成年|成人|([2-9]\d|1[89])岁/i,
  person:/\b(woman|women|man|men|person|people|girl|boy|lady|guy|she|he|her|his|model|actress|actor|digital human|character|portrait|selfie|face)\b|女性|男性|女人|男人|女孩|男孩|人物|她|他|数字人|角色|肖像|自拍|模特/i,
  mood:/^(cinematic|beautiful|moody|epic|dramatic|stunning|aesthetic|high quality|masterpiece|8k|4k|ultra|best quality|atmospheric|dreamy|gorgeous)\b|^(电影感|唯美|氛围感|高质量|杰作|梦幻|史诗)/i,
  camTerms:[['push-in',/push[- ]in|dolly in/i],['pull-out',/pull[- ]out|dolly out/i],['pan',/\bpans?\b|\bpanning\b/i],['orbit',/\borbit/i],['tracking',/\btracking\b/i],['crane',/\bcrane\b/i],['handheld',/handheld/i],['zoom',/\bzoom/i],['tilt',/\btilts?\b/i]],
  mainVerbs:/\b(walks?|turns?|smiles?|waves?|raises?|stands? up|sits? down|runs?|jumps?|dances?|looks? back|lowers?|tucks?|spins?|picks? up|throws?|opens?|nods?|claps?|kneels?|reaches?|lifts?|points?|hugs?|laughs?|drinks?|eats?)\b/gi
};

/* ================= 可选项库（手册术语 + 常用写法）与结构化字段 ================= */
const O=(k,zh,en,x)=>Object.assign({k,zh,en},x||{});
KB.o={
  subjType:[O('animal','动物','animal'),O('scene','场景 / 风景','scene')],
  gender:[O('f','女性','woman',{p:'her'}),O('m','男性','man',{p:'his'})],
  age:[O('e20','20出头','in {P} early 20s',{zt:'20岁出头'}),O('20','20多岁','in {P} 20s'),O('l20','20多岁（后半）','in {P} late 20s',{zt:'将近30岁'}),O('30','30多岁','in {P} 30s'),O('40','40多岁','in {P} 40s'),O('50','50多岁','in {P} 50s'),O('60','60岁以上','in {P} 60s'),O('a25','25岁','25-year-old',{pre:true}),O('a30','30岁','30-year-old',{pre:true})],
  hair:[O('lbk','黑色长发','long black hair'),O('sbk','黑色短发','short black hair'),O('ssv','银白色短发','short silver-white hair'),O('cbr','棕色卷发','curly brown hair'),O('pony','高马尾','a high ponytail'),O('bob','齐肩短发','a shoulder-length bob'),O('wavy','金色波浪长发','long wavy blonde hair'),O('beard','短胡茬','light stubble'),O('frk','雀斑','freckles')],
  cloth:[O('wsh','白色衬衫','a white shirt'),O('rrc','红色雨衣','a red raincoat'),O('bsu','黑色西装','a black suit'),O('lnd','亚麻连衣裙','a linen dress'),O('dnj','牛仔外套','a denim jacket'),O('knit','针织毛衣','a knit sweater'),O('wts','白色T恤','a white T-shirt'),O('tech','半透明科技服装','semi-transparent tech clothing'),O('trc','米色风衣','a beige trench coat'),O('hood','灰色连帽衫','a grey hoodie')],
  acc:[O('gls','眼镜','glasses'),O('rgl','圆框眼镜','round glasses'),O('straw','草帽','a straw hat'),O('ear','耳环','earrings'),O('scarf','围巾','a scarf'),O('watch','手表','a wristwatch'),O('bag','双肩包','a backpack'),O('umb','透明雨伞','a clear umbrella'),O('neck','项链','a necklace'),O('hp','耳机','headphones')],
  pose:[O('stand','站立','standing',{zp:'站在'}),O('sit','坐着','sitting',{zp:'坐在'}),O('sitw','坐在窗边','sitting by a window'),O('walk','行走','walking',{zp:'走在'}),O('lean','倚靠墙边','leaning against a wall'),O('read','看书','reading a book'),O('look','望向远方','gazing into the distance'),O('lie','趴着','lying down',{zp:'趴在'})],
  product:[O('mug','马克杯','mug'),O('drip','手冲滤杯','pour-over dripper'),O('buds','无线耳机盒','wireless earbud case'),O('perf','香水瓶','perfume bottle'),O('watch','手表','wristwatch'),O('shoe','运动鞋','sneaker'),O('bottle','玻璃瓶','glass bottle'),O('skin','护肤品瓶','skincare bottle'),O('phone','手机','smartphone'),O('bag','手提包','handbag')],
  animal:[O('cat','猫','cat'),O('dog','狗','dog'),O('gold','金毛犬','golden retriever'),O('corgi','柯基','corgi'),O('bird','小鸟','small bird'),O('horse','马','horse'),O('fox','狐狸','fox')],
  material:[O('mcer','哑光陶瓷','matte ceramic'),O('gcer','光面陶瓷','glossy ceramic'),O('glass','透明玻璃','clear glass'),O('fglass','磨砂玻璃','frosted glass'),O('bmet','拉丝金属','brushed metal'),O('pmet','抛光金属','polished metal'),O('lea','皮革','leather'),O('wood','原木','natural wood'),O('mpl','哑光塑料','matte plastic')],
  color:[O('black','黑色','black'),O('white','白色','white'),O('sage','鼠尾草绿','sage green'),O('emer','深祖母绿','deep emerald green'),O('amber','深琥珀色','dark amber'),O('oak','浅橡木色','pale oak'),O('silver','银色','silver'),O('gold','金色','gold'),O('cream','米白色','cream'),O('dblue','雾霾蓝','dusty blue'),O('red','红色','red'),O('navy','藏青色','navy blue')],
  placement:[O('wtab','放在浅色木桌上','sitting on a pale wooden table'),O('marb','放在大理石台面上','sitting on a marble countertop'),O('carafe','放在玻璃分享壶上','sitting on a glass carafe'),O('linen','放在亚麻布上','resting on a linen cloth'),O('float','悬浮在空中','floating in midair'),O('hand','被一只手握着','held in a hand'),O('ped','放在白色展台上','on a white pedestal')],
  locType:[O('in','室内','indoors'),O('out','室外','outdoors'),O('city','城市','in the city'),O('nature','自然','in nature'),O('studio','摄影棚','in a studio')],
  place:[O('win','窗边','by a window',{g:'in'}),O('cafe','咖啡馆','in a café',{g:'in'}),O('hall','走廊','in a hallway',{g:'in'}),O('kit','厨房台面（浅橡木 + 白色方砖墙）','on a pale oak counter against white square tile',{g:'in'}),O('tokyo','东京霓虹街头','on a neon-lit Tokyo street',{g:'city'}),O('alley','雨夜小巷','in a narrow rainy alley',{g:'city'}),O('roof','城市天台','on a city rooftop',{g:'city'}),O('beach','海边','on a beach',{g:'nature'}),O('forest','森林','in a forest',{g:'nature'}),O('field','花田','in a flower field',{g:'nature'}),O('pier','码头','on a wooden pier',{g:'out'}),O('park','公园','in a park',{g:'out'}),O('bright','明亮的摄影棚','in a bright studio',{g:'studio'}),O('seam','纯色背景摄影棚','in a studio with a seamless solid backdrop',{g:'studio'})],
  time:[O('dawn','清晨','at dawn'),O('morn','上午','in the morning'),O('noon','正午','at noon'),O('aft','午后','in the afternoon'),O('gold','黄昏','at golden hour'),O('blue','蓝调时刻','at blue hour'),O('night','夜晚','at night')],
  weather:[O('clear','晴朗','on a clear day'),O('cloud','阴天','under an overcast sky'),O('rain','细雨','in light rain'),O('snow','飘雪','in falling snow'),O('fog','薄雾','in soft mist'),O('wind','微风','in a gentle breeze')],
  props:[O('towel','亚麻毛巾','a linen towel'),O('plant','小盆绿植','a small potted plant'),O('books','一摞书','a stack of books'),O('beans','散落的咖啡豆','scattered coffee beans'),O('flower','鲜花','fresh flowers'),O('candle','蜡烛','a candle'),O('glass','玻璃杯','a glass'),O('tray','木托盘','a wooden tray'),O('leaf','绿叶','green leaves')],
  surface:[O('oak','橡木台面','an oak counter'),O('tile','白色方砖墙','white square tile'),O('marb','大理石台面','a marble countertop'),O('conc','清水混凝土墙','a concrete wall'),O('linen','亚麻布','linen cloth'),O('seam','纯色背景','a seamless solid backdrop')],
  lightSrc:[O('nat','自然光','natural light'),O('win','窗光','window light'),O('sun','午后阳光','afternoon sun'),O('morn','晨光','morning light'),O('neon','霓虹灯光','neon light'),O('soft','柔光箱','softbox light'),O('candle','烛光','candlelight'),O('moon','月光','moonlight')],
  lightDir:[O('l','左侧','from the left'),O('r','右侧','from the right'),O('f','正面','from the front'),O('b','背光','from behind'),O('t','顶光','from above'),O('s','侧光','from the side')],
  lightHard:[O('soft','柔和','soft'),O('hard','硬朗','hard'),O('diff','漫射','diffused')],
  lightFill:[O('soft','柔和补光','with soft fill'),O('bounce','反光板补光','with bounce fill'),O('rim','轮廓光','with a subtle rim light')],
  crop:[O('ctr','居中构图','centered composition'),O('thirds','三分法构图','rule-of-thirds composition'),O('tight','紧凑裁切','tightly cropped'),O('rim','裁切在盘沿内侧','cropped just inside the plate rim'),O('neg','大量留白','generous negative space'),O('sym','对称构图','symmetrical composition'),O('flat','俯拍平铺','flat lay from above')],
  focus:[O('subj','主体清晰','sharp focus on the subject'),O('top','最上层清晰','the top layer in sharp focus'),O('deep','全画面清晰','deep focus throughout'),O('fg','前景清晰','sharp foreground')],
  env:[O('rain','细雨落下，地面倒影荡漾','light rain falls, reflections ripple on the pavement'),O('hair','头发轻微摆动','hair slightly swaying'),O('steam','背后有轻微蒸汽飘动','soft steam drifts behind'),O('curt','窗帘随微风轻动','curtains move gently in the breeze'),O('dust','光里有微尘漂浮','dust motes float in the light'),O('snow','雪花缓缓飘落','snow drifts down slowly'),O('leaves','树叶轻轻摇动','leaves sway gently'),O('ripple','水面泛起涟漪','ripples spread across the water'),O('neon','霓虹灯轻微闪烁','neon signs flicker softly'),O('cloud','云层缓慢飘过','clouds drift slowly')],
  amb:[O('traffic','远处车流声','distant traffic'),O('rain','细雨声','soft rain'),O('metal','雨打金属声','soft rain on metal'),O('wind','风吹树叶声','wind through the trees'),O('waves','轻柔海浪声','gentle ocean waves'),O('room','轻微房间底噪','soft room tone'),O('steps','湿地面上的脚步声','footsteps on wet pavement'),O('cafe','咖啡馆低语声','quiet café chatter')],
  speed:[O('slowly','缓慢','slowly'),O('gently','轻轻','gently'),O('naturally','自然','naturally'),O('subtly','微微','subtly')],
  dir:[O('cam','向镜头','toward the camera'),O('l','向左','to the left'),O('r','向右','to the right'),O('fwd','向前','forward'),O('away','远离镜头','away from the camera'),O('up','向上','upward')],
  editTarget:[O('bg','背景','background'),O('cloth','服装','clothing'),O('color','颜色','color'),O('mat','材质','material'),O('hair','发型','hairstyle'),O('expr','表情','expression'),O('light','光线','lighting'),O('weather','天气','weather'),O('add','添加物体','add'),O('text','画面文字','text')],
  editObj:[O('liquid','瓶内液体','the liquid inside the bottle'),O('cloth','衣服','the clothing'),O('product','产品','the product'),O('wall','墙面','the wall'),O('car','汽车','the car'),O('hair','头发','the hair'),O('sky','天空','the sky')],
  expr:[O('smile','温和微笑','a gentle smile'),O('calm','平静','a calm expression'),O('surp','惊讶','a surprised expression'),O('laugh','开怀大笑','a bright laugh'),O('think','若有所思','a thoughtful expression')],
  editText:[]
};
KB.o.preserve=KB.preserve;KB.o.actions=KB.actions;KB.o.cameras=KB.cameras;KB.o.refRoles=KB.refRoles;
const EDIT_TO={bg:'place',cloth:'cloth',color:'color',mat:'material',hair:'hair',expr:'expr',light:'lightSrc',weather:'weather',add:'props',text:'editText'};
const LIST_LABEL={subjType:'主体类型',gender:'性别',age:'年龄',hair:'外貌 / 发型',cloth:'服装',acc:'配饰',pose:'姿态',product:'产品品类',animal:'动物',material:'材质',color:'颜色',placement:'摆放 / 支撑物',locType:'地点类型',place:'具体场景',time:'时间',weather:'天气',props:'道具',surface:'色块 / 表面',lightSrc:'光源',lightDir:'光线方向',lightHard:'光线硬度',lightFill:'补光',crop:'裁切 / 构图',focus:'焦点',env:'环境响应',amb:'环境音',speed:'速度修饰',dir:'方向',editTarget:'改动对象',editObj:'改动部位',expr:'表情',editText:'画面文字',preserve:'保留项',actions:'动作',cameras:'机位',refRoles:'参考图角色'};
const isHum=p=>['person','dh'].includes(p.stype);
const STRUCT={
  subject:{parts:[
    {id:'stype',list:'subjType',kind:'one',label:'主体类型'},
    {id:'gender',list:'gender',kind:'one',label:'性别',show:isHum},
    {id:'age',list:'age',kind:'one',label:'年龄（仅成年）',show:p=>p.stype==='person'},
    {id:'fic',kind:'flag',label:'虚构成年角色',show:p=>p.stype==='person',def:true},
    {id:'hair',list:'hair',kind:'many',max:2,label:'外貌 / 发型',show:isHum},
    {id:'cloth',list:'cloth',kind:'many',max:3,label:'服装',show:isHum},
    {id:'acc',list:'acc',kind:'many',max:3,label:'配饰',show:isHum},
    {id:'cat',list:'product',kind:'one',label:'品类',show:p=>p.stype==='product'},
    {id:'animal',list:'animal',kind:'one',label:'动物',show:p=>p.stype==='animal'},
    {id:'material',list:'material',kind:'one',label:'材质',show:p=>p.stype==='product'||isCustomType(p)},
    {id:'color',list:'color',kind:'one',label:'颜色',show:p=>['product','animal'].includes(p.stype)||isCustomType(p)},
    {id:'pose',list:'pose',kind:'one',label:'姿态',show:p=>isHum(p)||p.stype==='animal'},
    {id:'place',list:'placement',kind:'one',label:'摆放 / 支撑物',show:p=>p.stype==='product'||isCustomType(p)}],extraPh:'其它主体细节，如：数量、品牌无关的外形特征'},
  setting:{parts:[
    {id:'loc',list:'locType',kind:'one',label:'地点类型'},
    {id:'place',list:'place',kind:'one',label:'具体场景'},
    {id:'time',list:'time',kind:'one',label:'时间'},
    {id:'weather',list:'weather',kind:'one',label:'天气'}],extraPh:'其它场景细节'},
  art:{parts:[{id:'props',list:'props',kind:'many',max:3,label:'道具（建议 2–3 个）'},{id:'surf',list:'surface',kind:'many',max:2,label:'色块 / 表面'}],extraPh:'其它美术细节'},
  light:{parts:[{id:'src',list:'lightSrc',kind:'one',label:'光源'},{id:'dir',list:'lightDir',kind:'one',label:'方向'},{id:'hard',list:'lightHard',kind:'one',label:'硬度'},{id:'fill',list:'lightFill',kind:'one',label:'补光'}],extraPh:'其它光线细节'},
  color:{parts:[{id:'subj',list:'color',kind:'many',max:2,label:'主体色'},{id:'bg',list:'color',kind:'many',max:2,label:'背景色'}],extraPh:'其它色彩说明'},
  comp:{parts:[{id:'crop',list:'crop',kind:'one',label:'裁切 / 构图'},{id:'focus',list:'focus',kind:'one',label:'焦点'}],extraPh:'其它构图说明'},
  env:{parts:[{id:'env',list:'env',kind:'many',max:3,label:'环境响应'}],extraPh:'其它环境变化（不要发明新物体）'},
  change:{parts:[{id:'target',list:'editTarget',kind:'one',label:'改动对象（一次一处）'},{id:'obj',list:'editObj',kind:'one',label:'改动部位',show:p=>['color','mat'].includes(p.target)},{id:'to',list:p=>EDIT_TO[p.target]||'editText',kind:'one',label:'改成',show:p=>!!p.target}],extraPh:'补充，如：湿地面反射；画面文字要短'}
};
/* ---- 人物表单 / 产品表单 / 辣椒模式人物表单 专用选项 ---- */
Object.assign(KB.o,{
  style:[O('photo','写实摄影','photorealistic photography',{ev:'photorealistic live-action footage'}),O('cine','电影感','a cinematic film still',{ev:'a cinematic film look'}),O('anime','二次元动漫','anime style',{sty:1}),O('cel','日系动画赛璐璐','Japanese anime, cel-shaded',{sty:1}),O('manga','漫画线稿','manga line art, black and white ink',{sty:1}),O('3d','3D 渲染','a high-detail 3D render'),O('pixar','皮克斯风','Pixar-style 3D animation',{sty:1}),O('game','游戏CG','video game CG artwork',{sty:1}),O('oil','油画','an oil painting'),O('water','水彩','a watercolor painting'),O('ink','国风水墨','traditional Chinese ink wash painting'),O('cyber','赛博朋克','cyberpunk style'),O('film','复古胶片','a vintage 35mm film photo',{ev:'a vintage 35mm film look'}),O('pola','拍立得','a Polaroid photo',{ev:'a Polaroid-like look'}),O('lowpoly','低多边形','low-poly 3D art',{sty:1}),O('pixel','像素风','pixel art',{sty:1}),O('clay','黏土定格','claymation stop-motion style',{sty:1})],
  ptype:[O('real','真人风格（虚构）','person'),O('dh','数字人','digital human')],
  plight:[O('rem','伦勃朗光','Rembrandt lighting'),O('bfly','蝴蝶光（派拉蒙光）','butterfly lighting'),O('win','窗光','soft window light'),O('rim','轮廓光','rim light'),O('loop','环形光','loop lighting'),O('split','分割光','split lighting'),O('clam','蚌壳光','clamshell lighting'),O('back','逆光','backlight'),O('ring','环形灯','ring light'),O('nat','自然光','natural light')],
  glight:[O('box','柔光箱','large softbox light'),O('sback','侧逆光','side-back light'),O('hard','硬光','hard directional light'),O('top','顶光','top light'),O('edge','轮廓勾边光','edge light tracing the contours'),O('grad','渐变背景光','a gradient light on the backdrop'),O('tent','柔光棚（无影）','shadowless light-tent lighting'),O('win','窗光','soft window light'),O('sun','午后阳光','afternoon sun')],
  pmotion:[O('cond','冷凝水珠缓慢滑落','condensation beads slowly slide down the surface'),O('steam','热气缓缓升起','steam rises slowly'),O('rot','缓慢旋转','the product rotates slowly'),O('sweep','光线缓慢扫过表面','light sweeps slowly across the surface'),O('liq','液体轻轻晃动','the liquid ripples gently'),O('bub','气泡缓缓上升','bubbles rise slowly'),O('mist','薄雾在周围流动','soft mist drifts around it'),O('petal','花瓣轻轻飘落','petals drift down gently'),O('drop','水滴轻轻落下','a single drop of water falls gently')],
  pkeep:[O('shape','产品形状','product shape'),O('label','标签','label'),O('logo','标志位置','logo placement'),O('mat','材质','material'),O('color','颜色','color'),O('prop','比例','proportions'),O('light','光线','lighting'),O('angle','机位','camera angle')],
  exprCh:[O('cs','从平静到轻轻微笑','{P} expression shifts from calm to a gentle smile',{zt:'{Z}的表情从平静变为轻轻微笑'}),O('soft','眼神慢慢变柔和','{P} gaze slowly softens',{zt:'{Z}的眼神慢慢变柔和'}),O('think','变得若有所思','{P} expression becomes thoughtful',{zt:'{Z}的神情变得若有所思'}),O('bl','眨眼后微笑','{S} blinks, then smiles softly',{zt:'{Z}眨眼后轻轻微笑'}),O('laugh','微笑变成笑出声','{P} smile breaks into a quiet laugh',{zt:'{Z}的微笑变成轻声笑出来'})],
  spCloth:[O('lace','蕾丝内衣','black lace lingerie'),O('sheer','透视纱衣','a sheer gauze top'),O('hshirt','半解衬衫','a half-unbuttoned white shirt'),O('backless','开背长裙','a backless silk gown'),O('fish','网袜吊袜','fishnet stockings with a garter belt'),O('robe','薄纱睡袍','a sheer robe'),O('wet','湿身白衬衫','a wet white shirt clinging to the skin'),O('towel','浴巾裹身','only a bath towel',{zt:'只裹着一条浴巾',nw:1}),O('only','仅着衬衫','only an oversized shirt',{zt:'只穿一件宽松衬衫',nw:1}),O('slip','丝缎吊带睡裙','a satin slip nightgown'),O('body','蕾丝连体衣','a lace bodysuit'),O('silkopen','敞开的丝绸衬衫','an open silk shirt')],
  spClothState:[O('strap','肩带滑落','one strap slipping off {P} shoulder'),O('open','衣摆半敞','the fabric falling half open'),O('btn','纽扣半解','the buttons half undone'),O('collar','衣领滑至肩下','the collar slipping below {P} shoulder'),O('cling','湿透贴身','the fabric wet and clinging'),O('back','露出后背','{P} back left bare'),O('hem','裙摆滑至大腿','the hem riding up {P} thigh')],
  spHair:[O('wet','湿发','wet hair'),O('messy','凌乱长发','tousled long hair'),O('pillow','长发散落枕上','long hair spilling across the pillow'),O('updo','盘发几缕垂落','a loose updo with a few strands falling'),O('wave','波浪长发披肩','long wavy hair over {P} shoulders'),O('slick','湿润后梳短发','short hair slicked back')],
  spAcc:[O('choker','细项圈','a thin choker'),O('pearl','珍珠项链','a pearl necklace'),O('chain','金色细腰链','a fine gold body chain'),O('ear','耳坠','drop earrings'),O('glove','蕾丝手套','lace gloves'),O('anklet','细脚链','a delicate anklet')],
  spPose:[O('sidelie','侧卧回眸','lying on {P} side, glancing back over {P} shoulder'),O('wall','靠墙仰头','leaning against the wall with {P} head tilted back'),O('kneel','跪坐床边','kneeling on the edge of the bed'),O('hug','抱膝侧坐','sitting sideways hugging {P} knees'),O('prone','趴卧托腮','lying on {P} stomach, chin resting in {P} hand'),O('backturn','背对镜头回头','standing with {P} back to the camera, looking over {P} shoulder'),O('stretch','伸展身体','stretching {P} body languidly'),O('recline','斜倚床头','reclining against the headboard'),O('sill','坐在窗台','sitting on the windowsill, one knee raised')],
  spExpr:[O('hazy','迷离眼神','a hazy, half-lidded gaze'),O('bite','咬唇','{P} lower lip caught between {P} teeth'),O('half','半闭眼','{P} eyes half closed'),O('tease','挑逗微笑','a teasing smile'),O('direct','直视镜头','a direct, intense gaze into the camera'),O('languid','慵懒神情','a languid expression')],
  spAct:[{k:'strap',zh:'缓慢拨开肩带',en:'{S} slowly slides a strap off {P} shoulder',zt:'{Z}缓慢拨开肩带'},{k:'collar',zh:'手指滑过锁骨',en:'{S} slowly traces {P} fingertips along {P} collarbone',zt:'{Z}的手指缓慢滑过锁骨'},{k:'hairup',zh:'撩起头发',en:'{S} slowly lifts {P} hair off {P} neck',zt:'{Z}缓慢撩起头发，露出脖颈'},{k:'bite',zh:'咬唇回眸',en:'{S} glances back over {P} shoulder, biting {P} lip',zt:'{Z}咬唇回眸'},{k:'arch',zh:'缓慢伸展腰背',en:'{S} slowly arches and stretches {P} back',zt:'{Z}缓慢伸展腰背'},{k:'stroke',zh:'轻抚发丝',en:'{S} gently runs {P} fingers through {P} hair',zt:'{Z}轻抚发丝'},{k:'roll',zh:'翻身侧卧',en:'{S} slowly rolls onto {P} side',zt:'{Z}缓慢翻身侧卧'},{k:'eyes',zh:'缓慢抬眼看镜头',en:'{S} slowly raises {P} eyes to the camera',zt:'{Z}缓慢抬眼看向镜头'}],
  spPlace:[O('bed','昏暗卧室','in a dim bedroom'),O('steam','雾气浴室','in a steamy bathroom'),O('hotel','酒店窗边','by a hotel window overlooking the city lights'),O('sheets','凌乱床单上','on rumpled white sheets'),O('tub','浴缸边','beside a clawfoot bathtub'),O('velvet','丝绒沙发上','on a velvet sofa'),O('mirror','更衣镜前','in front of a dressing-room mirror'),O('pool','夜晚泳池边','beside a pool at night')],
  spMood:[O('candle','烛光','warm candlelight'),O('blinds','百叶窗光影','slatted light through window blinds'),O('low','暖色低调光','warm low-key lighting'),O('neon','霓虹边缘光','a neon rim light'),O('thru','轮廓透光','soft backlight glowing through the fabric'),O('curtain','晨光透纱帘','soft morning light through sheer curtains'),O('lamp','床头暖灯','the warm glow of a bedside lamp'),O('red','红色氛围灯','moody red ambient light')],
  spEnv:[O('flame','烛火摇曳','candle flames flicker'),O('steam','雾气缓缓飘动','steam drifts slowly through the air'),O('curt','薄纱窗帘轻拂','sheer curtains billow softly'),O('hair','发丝轻动','loose strands of hair move gently'),O('drops','水珠沿皮肤滑落','water droplets slide slowly down the skin'),O('light','光影缓慢移动','light shifts slowly across the skin')],
  spCam:[{k:'push',zh:'缓慢推进（推荐）',zt:'缓慢推进',en:'Slow push-in',note:'手册推荐：一个机位'},{k:'orbit',zh:'缓慢环绕',en:'Slow orbit',note:'展示身形轮廓'},{k:'low',zh:'低角度仰拍',en:'Low angle looking up',note:'力量感'},{k:'cu',zh:'近景特写（静止）',zt:'近景特写，静止机位',en:'Static close-up',note:'表情与质感'},{k:'static',zh:'静止锁定',zt:'静止机位',en:'Static locked shot',note:'最稳定'}],
  spEditTarget:[O('cloth','服装','clothing'),O('state','服装状态','the state of the clothing'),O('expr','表情 / 眼神','expression'),O('pose','姿态','pose'),O('light','氛围布光','lighting'),O('bg','场景','background')],
  spKeep:[O('face','脸','face'),O('bone','骨相与发际线','bone structure and hairline'),O('id','身份','identity'),O('hair','发型','hair'),O('body','体型比例','body proportions'),O('bg','背景','background'),O('light','光线','lighting'),O('angle','机位','camera angle')]
});
const EDIT_TO_SP={cloth:'spCloth',state:'spClothState',expr:'spExpr',pose:'spPose',light:'spMood',bg:'spPlace'};
Object.assign(LIST_LABEL,{ptype:'人物类型',plight:'人像布光',glight:'产品布光',pmotion:'产品微动',pkeep:'保真保留',exprCh:'表情变化',spCloth:'服装（辣椒）',spClothState:'服装状态（辣椒）',spHair:'发型（辣椒）',spAcc:'配饰（辣椒）',spPose:'姿态（辣椒）',spExpr:'表情 / 眼神（辣椒）',spAct:'动作（辣椒）',spPlace:'场景（辣椒）',spMood:'布光（辣椒）',spEnv:'环境响应（辣椒）',spCam:'机位（辣椒）',spEditTarget:'改动对象（辣椒）',spKeep:'保留（辣椒）',style:'风格'});
const SPICY_LISTS=new Set(['spCloth','spClothState','spHair','spAcc','spPose','spExpr','spAct','spPlace','spMood','spEnv','spCam','spEditTarget','spKeep']);
Object.assign(STRUCT,{
  person:{typeOf:p=>p.ptype==='dh'?'dh':'person',parts:[
    {id:'ptype',list:'ptype',kind:'one',label:'人物类型'},
    {id:'gender',list:'gender',kind:'one',label:'性别'},
    {id:'age',list:'age',kind:'one',label:'年龄（仅成年）',show:p=>p.ptype!=='dh'},
    {id:'fic',kind:'flag',label:'虚构成年角色',show:p=>p.ptype!=='dh',def:true,tip:'勾选后提示词会写入 “fictional adult”（虚构成年人物）。手册建议人物类都写明，可降低被误判为真实人物或年龄模糊的概率；取消勾选则不写。'},
    {id:'hair',list:'hair',kind:'many',max:2,label:'外貌 / 发型'},
    {id:'cloth',list:'cloth',kind:'many',max:3,label:'服装'},
    {id:'acc',list:'acc',kind:'many',max:3,label:'配饰'},
    {id:'pose',list:'pose',kind:'one',label:'姿态'},
    {id:'expr',list:'expr',kind:'one',label:'表情'}],extraPh:'其它人物细节，如：雀斑、手里拿着咖啡'},
  spicy:{typeOf:()=>'person',ficLocked:true,parts:[
    {id:'ficInfo',kind:'info',label:'🔒 辣椒模式下提示词会自动写入 fictional adult + 具体年龄（Grok 硬性底线，缺少更易被拦截）',tip:'Grok 的辣椒模式只适用于明确的虚构成年角色。本表单会在提示词开头自动写入 “fictional adult” 和你选的具体年龄（如 in her 30s），无需手动勾选；未选年龄时禁止复制。'},
    {id:'gender',list:'gender',kind:'one',label:'性别'},
    {id:'age',list:'age',kind:'one',label:'明确成年年龄（必选）',req:true},
    {id:'hair',list:'spHair',kind:'many',max:2,label:'发型'},
    {id:'cloth',list:'spCloth',kind:'many',max:2,label:'服装'},
    {id:'cstate',list:'spClothState',kind:'many',max:2,label:'服装状态'},
    {id:'acc',list:'spAcc',kind:'many',max:2,label:'配饰'},
    {id:'pose',list:'spPose',kind:'one',label:'姿态'},
    {id:'expr',list:'spExpr',kind:'one',label:'表情 / 眼神'}],extraPh:'只写可见的视觉细节，具体、简短'},
  spenv:{parts:[{id:'env',list:'spEnv',kind:'many',max:2,label:'环境响应'}],extraPh:'其它环境变化（不要发明新物体）'},
  spset:{parts:[{id:'place',list:'spPlace',kind:'one',label:'场景'},{id:'time',list:'time',kind:'one',label:'时间'}],extraPh:'其它场景细节'},
  sid:{typeOf:()=>'person',ficLocked:true,parts:[
    {id:'ficInfo',kind:'info',label:'🔒 辣椒模式下提示词会自动写入 fictional adult + 具体年龄（Grok 硬性底线，缺少更易被拦截）',tip:'Grok 的辣椒模式只适用于明确的虚构成年角色。本表单会在提示词开头自动写入 “fictional adult” 和你选的具体年龄（如 in her 30s），无需手动勾选；未选年龄时禁止复制。'},
    {id:'gender',list:'gender',kind:'one',label:'性别'},
    {id:'age',list:'age',kind:'one',label:'明确成年年龄（必选）',req:true}],extraPh:'原图人物的简短可见特征（可选）'},
  product:{typeOf:()=>'product',parts:[
    {id:'cat',list:'product',kind:'one',label:'品类'},
    {id:'material',list:'material',kind:'one',label:'材质'},
    {id:'color',list:'color',kind:'one',label:'颜色'},
    {id:'place',list:'placement',kind:'one',label:'摆放 / 支撑物'}],extraPh:'其它产品外形细节（不写品牌）'},
  pset:{parts:[
    {id:'surf',list:'surface',kind:'many',max:2,label:'背景 / 台面'},
    {id:'bgc',list:'color',kind:'one',label:'背景色'},
    {id:'props',list:'props',kind:'many',max:3,label:'道具（≤3）'}],extraPh:'其它背景细节'},
  plight:{parts:[{id:'pat',list:'plight',kind:'one',label:'人像布光'},{id:'dir',list:'lightDir',kind:'one',label:'方向'},{id:'hard',list:'lightHard',kind:'one',label:'硬度'},{id:'fill',list:'lightFill',kind:'one',label:'补光'}],extraPh:'其它光线细节'},
  glight:{parts:[{id:'pat',list:'glight',kind:'one',label:'产品布光'},{id:'dir',list:'lightDir',kind:'one',label:'方向'},{id:'hard',list:'lightHard',kind:'one',label:'硬度'}],extraPh:'其它布光细节，如：高光沿杯沿'},
  smood:{parts:[{id:'pat',list:'spMood',kind:'one',label:'氛围布光'},{id:'dir',list:'lightDir',kind:'one',label:'方向'},{id:'hard',list:'lightHard',kind:'one',label:'硬度'}],extraPh:'其它光线细节'},
  schange:{parts:[{id:'target',list:'spEditTarget',kind:'one',label:'改动对象（一次一处）'},{id:'to',list:p=>EDIT_TO_SP[p.target]||'spCloth',kind:'one',label:'改成',show:p=>!!p.target}],extraPh:'补充：只写可见的视觉变化，小幅度'}
});
/* v9：图生图 / 图生视频 · 产品与其他（动物 / 场景）表单 */
Object.assign(KB.o,{
  pEditTarget:[O('bg','背景 / 台面','background'),O('place','摆放 / 支撑物','placement'),O('color','颜色','color'),O('mat','材质','material'),O('light','产品布光','lighting'),O('props','道具','props'),O('text','标签文字','text')],
  pEditObj:[O('body','产品主体','the product body'),O('cap','盖子 / 瓶盖','the cap'),O('label','标签底色','the label background'),O('liquid','瓶内液体','the liquid inside the bottle'),O('strap','表带 / 提手','the strap'),O('handle','杯柄 / 把手','the handle')],
  oEditTarget:[O('bg','背景','background'),O('weather','天气','weather'),O('time','时间','time of day'),O('light','光线','lighting'),O('color','色调 / 颜色','color'),O('add','添加物体','add')],
  oEditObj:[O('fur','毛色','the fur'),O('sky','天空','the sky'),O('water','水面','the water'),O('leaves','树叶','the leaves'),O('wall','墙面','the wall'),O('grade','整体色调','the overall color grade')],
  oKeep:[O('fur','毛色花纹','fur color and markings'),O('face','面部特征','facial features'),O('pose','姿态','pose'),O('terrain','地形与建筑结构','terrain and building layout'),O('sky','天空','sky'),O('bg','背景','background'),O('light','光线','lighting'),O('angle','机位','camera angle')],
  oAct:[O('aturn','🐾 缓慢转头看镜头','the animal slowly turns its head toward the camera',{zt:'动物缓慢转头看向镜头',g:'animal'}),O('ablink','🐾 缓慢眨眼','the animal blinks slowly',{zt:'动物缓慢眨眼',g:'animal'}),O('atail','🐾 尾巴轻轻摆动','the animal gently swishes its tail',{zt:'动物轻轻摆动尾巴',g:'animal'}),O('aear','🐾 耳朵微微抖动','the animal twitches its ears slightly',{zt:'动物耳朵微微抖动',g:'animal'}),O('abreath','🐾 平稳呼吸','the animal breathes slowly and steadily',{zt:'动物平稳缓慢地呼吸',g:'animal'}),O('asniff','🐾 低头嗅闻','the animal lowers its head and sniffs the ground',{zt:'动物低头嗅闻地面',g:'animal'}),O('awalk','🐾 缓慢向前走','the animal walks slowly forward',{zt:'动物缓慢向前走',g:'animal'}),
    O('sclouds','🏞 云层缓慢流动','clouds drift slowly across the sky',{zt:'云层缓慢流过天空',g:'scene'}),O('swater','🏞 水面泛起涟漪','the water ripples gently',{zt:'水面轻轻泛起涟漪',g:'scene'}),O('swaves','🏞 海浪轻拍岸边','waves roll gently onto the shore',{zt:'海浪轻轻拍向岸边',g:'scene'}),O('strees','🏞 树叶随风摇动','the trees sway gently in the breeze',{zt:'树木随微风轻轻摇动',g:'scene'}),O('sfog','🏞 薄雾缓缓流动','mist drifts slowly through the valley',{zt:'薄雾缓缓流过山谷',g:'scene'}),O('slight','🏞 光影缓慢变化','sunlight shifts slowly across the scene',{zt:'阳光在画面上缓慢移动',g:'scene'}),O('scity','🏞 城市灯光渐次亮起','city lights flicker on one by one',{zt:'城市灯光逐一亮起',g:'scene'})]
});
KB.otype=[{k:'animal',zh:'动物',en:'animal'},{k:'scene',zh:'场景 / 风景',en:'scene'}];
const EDIT_TO_P={bg:'surface',place:'placement',color:'color',mat:'material',light:'glight',props:'props',text:'editText'};
const EDIT_TO_O={bg:'place',weather:'weather',time:'time',light:'lightSrc',color:'color',add:'props'};
Object.assign(LIST_LABEL,{pEditTarget:'改动对象（产品）',pEditObj:'改动部位（产品）',oEditTarget:'改动对象（动物 / 场景）',oEditObj:'改动部位（动物 / 场景）',oKeep:'保留（动物 / 场景）',oAct:'动作 / 变化（动物 / 场景）'});
Object.assign(STRUCT,{
  pchange:{parts:[{id:'target',list:'pEditTarget',kind:'one',label:'改动对象（一次一处）'},{id:'obj',list:'pEditObj',kind:'one',label:'改动部位',show:p=>['color','mat'].includes(p.target)},{id:'to',list:p=>EDIT_TO_P[p.target]||'editText',kind:'one',label:'改成',show:p=>!!p.target}],extraPh:'补充，如：保留瓶身高光；标签文字要短'},
  ochange:{parts:[{id:'target',list:'oEditTarget',kind:'one',label:'改动对象（一次一处）'},{id:'obj',list:'oEditObj',kind:'one',label:'改动部位',show:p=>p.target==='color'},{id:'to',list:p=>EDIT_TO_O[p.target]||'props',kind:'one',label:'改成',show:p=>!!p.target}],extraPh:'补充，如：雪地上留下浅浅的爪印'}
});
function isCustomType(p){return !!p.stype&&!KB.o.subjType.some(x=>x.k===p.stype)}
/* ---- 选项解析 ---- */
let USER_OPTS={};let optEnHook=null;
function optItem(list,k){if(!k)return null;const b=(KB.o[list]||KB[list]||[]).find(o=>o.k===k);if(b)return b;const u=(USER_OPTS[list]||[]).find(o=>o.k===k);return u?Object.assign({custom:true},u):null}
function itEn(it){if(!it)return '';if(trim(it.en))return trim(it.en);return optEnHook?optEnHook(it.zh):glossTranslate(it.zh).text}
function itZh(it){return it?(it.zt||it.zh):''}
function partList(def,parts){return typeof def.list==='function'?def.list(parts):def.list}
function sv(n,id){const p=n&&n.parts||{};return p[id]}
function one(n,def,id){const d=def.parts.find(x=>x.id===id);if(!d)return null;const v=sv(n,id);return typeof v==='string'&&v?optItem(partList(d,n.parts||{}),v):null}
function many(n,def,id){const d=def.parts.find(x=>x.id===id);if(!d)return [];const v=sv(n,id);return Array.isArray(v)?v.map(k=>optItem(partList(d,n.parts||{}),k)).filter(Boolean):[]}
function structHas(n){if(!n)return false;if(trim(n.zh)||trim(n.en))return true;const p=n.parts||{};return Object.entries(p).some(([k,v])=>k!=='fic'&&(Array.isArray(v)?v.length:!!v))}
function anA(s){return /^[aeiou]/i.test(s)?'An':'A'}
function stripPrep(s){return trim(s).replace(/^(on|in|at|by|inside|under)\s+/i,'')}
function lf(s){return lowerFirst(trim(s).replace(/[.。]+$/,''))}
/* 主体 + 场景 → 首句（主体优先） */
function composeLead(sub,set,lang,D,E){
  D=D||STRUCT.subject;E=E||STRUCT.setting;const p=sub&&sub.parts||{};const t=D.typeOf?D.typeOf(p):(p.stype||'');const T=one(sub,D,'stype');
  const G=one(sub,D,'gender'),A=one(sub,D,'age');const fic=t==='person'&&(D.ficLocked||p.fic!==false);const EX=one(sub,D,'expr');
  const hair=many(sub,D,'hair'),cl=many(sub,D,'cloth'),ac=many(sub,D,'acc');const pose=one(sub,D,'pose');const cst=many(sub,D,'cstate');
  const cat=one(sub,D,'cat'),an=one(sub,D,'animal'),mat=one(sub,D,'material'),col=one(sub,D,'color'),pl=one(sub,D,'place');
  const loc=one(set,E,'loc'),place=one(set,E,'place'),tm=one(set,E,'time'),we=one(set,E,'weather');
  const xs=pick(sub,lang),xe=pick(set,lang);
  if(lang==='en'){
    let head='';const pr=G?G.p:'their';
    if(t==='person'||t==='dh'){const noun=(t==='dh'?'digital human'+(G?' '+G.en:''):(G?G.en:'person'));
      const ageEn=A?itEn(A).replace('{P}',pr):'';const pre=A&&(A.pre||/year-old/.test(ageEn));
      const core=(pre?ageEn+' ':'')+(fic?'fictional adult ':'')+noun+(A&&!pre?' '+ageEn:'');head=anA(core)+' '+core;
      const PE=it=>lf(itEn(it)).replace(/\{P\}/g,pr);
      if(hair.length)head+=' with '+joinList(hair.map(PE),'en');
      const wear=cl.concat(ac).map(PE);if(wear.length)head+=', wearing '+joinList(wear,'en');
      if(cst.length)head+=', '+joinList(cst.map(PE),'en');
      if(pose)head+=', '+PE(pose);}
    else if(t==='animal'){const core=[col&&itEn(col),an?itEn(an):'animal'].filter(Boolean).map(lf).join(' ');head=anA(core)+' '+core;if(pose)head+=', '+lf(itEn(pose))}
    else if(t&&t!=='scene'){let ce=cat?lf(itEn(cat)):(T&&t!=='product'?itEn(T):'product');if(mat){const lw=lf(itEn(mat)).split(' ').pop();if(ce.startsWith(lw+' '))ce=ce.slice(lw.length+1)}const core=[col&&itEn(col),mat&&itEn(mat),ce].filter(Boolean).map(lf).join(' ');head=anA(core)+' '+core;if(pl)head+=', '+lf(itEn(pl))}
    let where=place?lf(itEn(place)):(loc?lf(itEn(loc)):'');
    if(!head&&!xs){if(!where&&!tm&&!we&&!xe)return '';let s=where?stripPrep(where):'';s=s?(/^(a|an|the)\s/i.test(s)?s:'a '+s):'a scene';return cj([s+(tm?' '+lf(itEn(tm)):''),we&&lf(itEn(we)),xe])}
    let tail=(where?' '+where:'')+(tm?' '+lf(itEn(tm)):'');
    if(!head)return cj([xs+tail,we&&lf(itEn(we)),xe]);
    return cj([head+tail,EX?'with '+lf(itEn(EX)).replace(/\{P\}/g,G?G.p:'their'):'',we&&lf(itEn(we)),xs,xe]);
  }
  const exZ=EX?itZh(EX):'';let head='';
  if(t==='person'||t==='dh'){head='一位'+(A?itZh(A)+'的':'')+(fic?'虚构成年':'')+(t==='dh'?'数字人':'')+(G?G.zh:(t==='dh'?'':'人物'));
    if(hair.length)head+='，'+hair.map(itZh).join('、');{const w=cl.filter(x=>!x.nw),o=cl.filter(x=>x.nw);if(w.length)head+='，穿'+w.map(itZh).join('、');if(o.length)head+='，'+o.map(itZh).join('、')}if(cst.length)head+='，'+cst.map(itZh).join('、');if(ac.length)head+='，戴'+ac.map(itZh).join('、')}
  else if(t==='animal')head='一只'+(col?itZh(col):'')+(an?itZh(an):'动物');
  else if(t&&t!=='scene'){let cz=cat?itZh(cat):(T&&t!=='product'?itZh(T):'产品');const mz=mat?itZh(mat):'';if(mz.length>=2&&cz.startsWith(mz.slice(-2)))cz=cz.slice(2);head='一个'+(col?itZh(col):'')+mz+cz+(pl?'，'+itZh(pl):'')}
  const where=place?itZh(place):(loc?itZh(loc):'');
  if(!head&&!xs){if(!where&&!tm&&!we&&!xe)return '';return [ [tm&&itZh(tm),where].filter(Boolean).join('的')||'场景',we&&itZh(we),xe].filter(Boolean).join('，')}
  if(!head)head=xs;else if(xs)head+='，'+xs;
  let posePart='';
  if(pose&&(t==='person'||t==='dh'||t==='animal')){posePart=where&&pose.zp?pose.zp+where:itZh(pose)+(where?'，在'+where:'')}
  else if(where)posePart='在'+where;
  return [head,posePart,exZ,tm&&itZh(tm),we&&itZh(we),xe].filter(Boolean).join('，');
}
function composeStruct(name,n,lang){const D=STRUCT[name];const x=pick(n,lang);const E=lang==='en';const J=a=>E?joinList(a.map(itEn).map(lf),'en'):a.map(itZh).join('、');
  if(name==='art'){const a=many(n,D,'props').concat(many(n,D,'surf'));return E?cj([a.length?J(a):'',x]):[a.length?J(a):'',x].filter(Boolean).join('，')}
  if(name==='pset'){const a=many(n,D,'surf').concat(many(n,D,'props'));const b=one(n,D,'bgc');
    return E?cj([a.length?J(a):'',b?lf(itEn(b))+' background':'',x]):[a.length?J(a):'',b?'背景'+itZh(b):'',x].filter(Boolean).join('，')}
  if(name==='light'||name==='plight'||name==='glight'||name==='smood'){const s=one(n,D,name==='light'?'src':'pat'),d=one(n,D,'dir'),h=one(n,D,'hard'),f=one(n,D,'fill');
    if(E){const se=s?lf(itEn(s)):'';const he=h&&!new RegExp('\\b'+lf(itEn(h))+'\\b','i').test(se)?lf(itEn(h)):'';const main=[he,s?se:(h||d?'light':'')].filter(Boolean).join(' ')+(d?' '+lf(itEn(d)):'')+(f?' '+lf(itEn(f)):'');return cj([main,x])}
    return [[d&&itZh(d),h&&itZh(h),s?itZh(s):(h||d?'光线':'')].filter(Boolean).join(''),f&&itZh(f),x].filter(Boolean).join('，')}
  if(name==='color'){const s=many(n,D,'subj'),b=many(n,D,'bg');
    if(E){let m='';if(s.length&&b.length)m=J(s)+' against '+J(b);else if(s.length)m=J(s)+' tones';else if(b.length)m=J(b)+' background';return cj([m,x])}
    return [s.length?'主体'+J(s):'',b.length?'背景'+J(b):'',x].filter(Boolean).join('，')}
  if(name==='comp'){const c=one(n,D,'crop'),f=one(n,D,'focus');return E?cj([c&&itEn(c),f&&itEn(f),x]):[c&&itZh(c),f&&itZh(f),x].filter(Boolean).join('，')}
  if(name==='env'||name==='spenv'){const a=many(n,D,'env');return E?cj(a.map(itEn).concat([x])):a.map(itZh).concat([x]).filter(Boolean).join('，')}
  if(name==='change'||name==='schange'||name==='pchange'||name==='ochange'){const p=n&&n.parts||{};const T=one(n,D,'target'),ob=one(n,D,'obj'),to=one(n,D,'to');const tk=p.target;
    if(!T)return x;const toE=to?lf(itEn(to)):'',toZ=to?itZh(to):'';let s='';
    if(E){if(tk==='bg')s='Replace only the background with '+(toE?((/^(a|an|the)\s/i.test(stripPrep(toE))?'':'a ')+stripPrep(toE)):'a new background');
      else if(tk==='add')s='Add '+(toE||'a small object');
      else if(tk==='text')s=to?'Change the text to "'+(to.en||to.zh)+'"':'';
      else if(tk==='color'||tk==='mat')s='Change only the '+(tk==='color'?'color':'material')+' of '+(ob?lf(itEn(ob)):(name==='pchange'?'the product':'the subject'))+' to '+(toE||'…');
      else if(tk==='props')s='Add '+(toE||'a small prop')+' beside the product';
      else s='Change only the '+lf(itEn(T))+' to '+(toE?(/^(at|in|on|under)\s/i.test(toE)&&tk!=='light'?stripPrep(toE):toE):'…');
      return cj([s,x])}
    if(tk==='bg')s='只把背景换成'+(toZ||'新背景');else if(tk==='add')s='添加'+(toZ||'一个小物体');else if(tk==='text')s=to?'把画面文字改为“'+to.zh+'”':'';
    else if(tk==='color'||tk==='mat')s='只把'+(ob?itZh(ob):(name==='pchange'?'产品':'主体'))+'的'+(tk==='color'?'颜色':'材质')+'改成'+(toZ||'…');else if(tk==='props')s='在产品旁添加'+(toZ||'一个小道具');else s='只把'+itZh(T)+'改成'+(toZ||'…');
    return [s,x].filter(Boolean).join('，')}
  return x}
/* 动作 + 速度修饰 + 方向 */
function actionText(n,lang,who,list){if(!n||!n.v)return '';let s='';const w=byK('who',who)||KB.who[0];
  if(n.v==='_custom')s=pick(n,lang);else{const it=optItem(list||'actions',n.v);if(!it)return '';s=it.custom?(lang==='en'?itEn(it):it.zh):fillWho(lang==='en'?it.en:(it.zt||it.zh),who)}
  const p=n.parts||{};const sp=p.speed&&optItem('speed',p.speed),dr=p.dir&&optItem('dir',p.dir);
  if(lang==='en'){if(sp){const a=lf(itEn(sp));if(/\b(slowly|gently|naturally|subtly)\b/i.test(s))s=s.replace(/\b(slowly|gently|naturally|subtly)\b/i,a);else if(s.startsWith(w.en+' '))s=w.en+' '+a+s.slice(w.en.length);else s=s.replace(/^(\S+)/,'$1 '+a)}
    if(dr){const a=lf(itEn(dr));if(/toward the camera/i.test(s))s=s.replace(/toward the camera/i,a);else s=s.replace(/[.\s]+$/,'')+' '+a}}
  else{if(sp){const a=itZh(sp);if(/(缓慢|轻轻|自然|微微)/.test(s))s=s.replace(/(缓慢|轻轻|自然|微微)/,a);else if(s.startsWith(w.zh))s=w.zh+a+s.slice(w.zh.length);else s=a+s}
    if(dr){const a=itZh(dr);if(/向镜头/.test(s))s=s.replace(/向镜头/,a);else s=s.replace(/[。\s]+$/,'')+'，'+a}}
  return s}

/* 表情变化（含 {S}/{P}/{Z} 模板） */
function exprText(o,lang,who){if(!o||!o.v)return '';if(o.v==='_custom')return pick(o,lang);const it=optItem('exprCh',o.v);if(!it)return '';
  const w=byK('who',who)||KB.who[0];if(it.custom)return lang==='en'?itEn(it):it.zh;
  if(lang==='en')return cap(it.en.replace('{S}',w.en).replace(/\{P\}/g,w.p));return (it.zt||it.zh).replace(/\{Z\}/g,w.zh)}

/* 风格：单选；辣椒模式 + 二次元/动漫类风格时显式写入成年角色设定 */
function styleText(o,lang,spicy,vid){if(!o||!o.v)return '';const it=o.v==='_custom'?{zh:trim(o.zh),en:trim(o.en)||trim(o.zh),custom:true}:optItem('style',o.v);if(!it||!it.zh)return '';
  const sty=it.sty||(it.custom&&STYLIZED_RX.test(it.zh+' '+(it.en||'')));
  if(lang==='en'){let e=lf(o.v==='_custom'?pick(o,'en'):(vid&&it.ev)||itEn(it));if(spicy&&sty)e+=', mature adult character design';return e}
  let z=itZh(it);if(!/(风格|风|感)$/.test(z))z+='风格';if(spicy&&sty)z+='，成熟的成年角色设定';return z}
const STYLIZED_RX=/anime|manga|cartoon|toon|pixar|cel|chibi|二次元|动漫|动画|漫画|卡通|皮克斯|游戏|像素|黏土|萌/i;

/* ================= 模式与表单 ================= */
const IDLOCK={id:'idlock',type:'toggle',label:'身份锁定：Preserve exact face, bone structure, and hairline',def:true,en:'Preserve exact face, bone structure, and hairline.',zt:'保持脸部、骨相与发际线完全一致。'};
const SPICY_INTRO='🌶 辣椒模式人物表单（手册「辣椒模式专项」）：仅限明确的虚构成年角色；先在普通模式锁定干净的静态关键帧，再做小幅度编辑或动画；一次一个主要动作，优先静态或微动；被拦截时简化提示、明确虚构、逐步加细节。硬性底线不变。';
const F_FRAMING={id:'framing',type:'seg',label:'景别（单选）',opts:'shot',none:'不指定'};
const F_ANGLE={id:'angle',type:'seg',label:'拍摄角度（单选）',opts:'angle',none:'不指定'};
const F_LENS={id:'lens',type:'seg',label:'镜头 / 焦段（单选）',opts:'lens',none:'不指定'};
const F_STYLE={id:'style',type:'combo',list:'style',kind:'one',label:'风格（单选，可选）',hint:'不选 = 不指定；可「＋ 添加自定义」'};
const F_ISTYLE={id:'style',type:'combo',list:'style',kind:'one',label:'风格转换（单选，可选）',hint:'把整张图转换为某种风格；与其它改动分开做更稳'};
const F_DEPTH={id:'depth',type:'checks',label:'纵深（最多 2 项）',opts:'depth',max:2,hint:'人物类建议至少选一项'};
const F_IMGS=(role,max,label,hint)=>({id:'imgs',type:'imgs',role,max,label,hint});
const F_KEEP=(kind)=>({id:'keep',type:'aspects',label:'对照原图：保持 / 修改（每项单选）',hint:'先改后保：选「修改」并写改成什么；选「保持」的会写成 Keep … unchanged',
  aspects:kind===true||kind==='spicy'?['cloth','pose','scene','light','comp']:kind==='product'?['shape','matc','logo','scene','light','comp']:kind==='other'?(d=>(d&&d.otype&&d.otype.v==='scene')?['subj','scene','light','comp']:['subj','pose','scene','light','comp']):['id','cloth','pose','scene','light','comp']});
const F_OTYPE={id:'otype',type:'seg',label:'主体类型（单选）',opts:'otype',hint:'动物 / 场景风景；决定保持项与建议动作'};
const F_FRAMES={id:'fr',type:'frames',label:'帧与时间轴（可选）',hint:'第 0 帧 = 上传的图片（首帧）；与文生视频的「第一帧 + then 节拍」对应'};
const F_SOUND={id:'sound',type:'sound',label:'声音 / 对白（类型单选）'};
const F_CAM={id:'camera',type:'combo',list:'cameras',kind:'one',label:'一个机位（单选）',hint:'不指定容易机位乱晃'};
const F_SPCAM={id:'camera',type:'combo',list:'spCam',kind:'one',label:'机位（单选）',def:'push',hint:'一个机位：缓慢推进 / 缓慢环绕 / 低角度 / 近景特写'};
const F_SPSOUND={id:'sound',type:'sound',label:'声音 / 对白（对白用短句）',hint:'音频默认开启；对白放引号、短句'};
const MODES = {
  t2i_p:{base:'t2i',form:'person',name:'文生图',fname:'人物',sub:'Text-to-Image · 人物',video:false,intro:'人物表单：主体（虚构成年人物）→ 场景 → 景别 / 角度 → 人像布光 → 纵深。系列图保持相同顺序。',
    fields:[
      {id:'subject',type:'struct',struct:'person',label:'人物',req:true,hint:'人物须为虚构成年角色；逐项下拉选择，可「＋ 添加自定义」'},
      {id:'setting',type:'struct',struct:'setting',label:'场景'},
      F_FRAMING,F_ANGLE,F_LENS,F_STYLE,
      {id:'light',type:'struct',struct:'plight',label:'人物光线',hint:'一个主光：人像布光 + 方向 + 硬度'},
      F_DEPTH]},
  t2i_ps:{base:'t2i',form:'person',spicy:true,name:'文生图',fname:'人物 · 🌶',sub:'Text-to-Image · 人物 · 辣椒模式',video:false,intro:SPICY_INTRO,
    fields:[
      {id:'subject',type:'struct',struct:'spicy',label:'人物（虚构成年）',req:true,hint:'必须选择明确的成年年龄'},
      {id:'setting',type:'struct',struct:'spset',label:'场景 / 氛围'},
      F_FRAMING,F_ANGLE,F_LENS,F_STYLE,
      {id:'light',type:'struct',struct:'smood',label:'布光',hint:'一个主光，具体写光源'},
      F_DEPTH,IDLOCK]},
  t2i_g:{base:'t2i',form:'product',name:'文生图',fname:'产品',sub:'Text-to-Image · 产品',video:false,intro:'产品表单：产品（品类 / 材质 / 颜色 / 摆放）→ 景别 / 角度 → 背景台面与道具 → 产品布光 → 构图裁切。材质与数量写具体。',
    fields:[
      {id:'subject',type:'struct',struct:'product',label:'产品',req:true,hint:'品类、材质、颜色、摆放各单选'},
      {id:'framing',type:'seg',label:'景别（单选，产品常用微距）',opts:'shot',none:'不指定'},F_ANGLE,F_LENS,F_STYLE,
      {id:'set',type:'struct',struct:'pset',label:'背景台面与道具',hint:'道具 2–3 个即可'},
      {id:'light',type:'struct',struct:'glight',label:'产品布光'},
      {id:'comp',type:'struct',struct:'comp',label:'构图裁切',hint:'裁切、焦点'},
      {id:'depth',type:'checks',label:'纵深（可选，最多 2 项）',opts:'depth',max:2}]},
  t2i:{base:'t2i',form:'other',name:'文生图',fname:'其他',sub:'Text-to-Image · 动物 / 场景',video:false,intro:'推荐结构（经验总结，xAI 未发布官方 Imagine 提示词指南）：主体 → 细节 → 美术与道具 → 光线 → 色彩 → 构图。系列图须保持相同顺序。',
    fields:[
      {id:'subject',type:'struct',struct:'subject',label:'主体',req:true,hint:'动物或场景；也可「＋ 添加自定义」主体类型'},
      {id:'setting',type:'struct',struct:'setting',label:'场景'},
      F_FRAMING,F_ANGLE,F_LENS,F_STYLE,
      {id:'art',type:'struct',struct:'art',label:'美术与道具',hint:'2–3 个具名道具'},
      {id:'light',type:'struct',struct:'light',label:'光线',hint:'一个主光：光源、方向、硬度各单选'},
      {id:'color',type:'struct',struct:'color',label:'色彩',hint:'主体色与背景色分开写'},
      {id:'comp',type:'struct',struct:'comp',label:'构图',hint:'裁切、焦点、单一场景'},
      F_DEPTH]},
  i2i:{base:'i2i',form:'person',name:'图生图',fname:'人物',sub:'Image Editing · 人物',video:false,intro:'推荐结构：先改后保。只写要变化的部分，不要重写整段场景；再明确列出保留项（比 “不要什么” 更有效）。',
    fields:[
      F_IMGS('i2i',5,'原图（可多张，最多 5 张）','点击 / 拖入 / 粘贴；图片只留在本页内存'),
      {id:'change',type:'struct',struct:'change',label:'要改什么',req:true,hint:'先改后保：一次只改一处；画面文字要短'},
      F_ISTYLE,
      F_KEEP('person'),
      {id:'preserve',type:'combo',list:'preserve',kind:'many',label:'保留列表',hint:'越具体越好；不要写 keep everything'},
      {id:'matchLight',type:'toggle',label:'匹配新环境光线（换背景时推荐）',en:'Match the new light direction naturally.',zt:'自然匹配新的光线方向。'}]},
  i2i_s:{base:'i2i',form:'person',spicy:true,name:'图生图',fname:'人物 · 🌶',sub:'Image Editing · 辣椒模式人物',video:false,intro:SPICY_INTRO+' 图生图：一次只改一处小幅变化，先改后保。',
    fields:[
      F_IMGS('i2i',5,'原图（可多张，最多 5 张）','点击 / 拖入 / 粘贴；图片只留在本页内存'),
      {id:'sid',type:'struct',struct:'sid',label:'原图人物（虚构成年）',req:true,hint:'必须选择明确的成年年龄'},
      {id:'change',type:'struct',struct:'schange',label:'要改什么（一次一处）',req:true},
      F_ISTYLE,
      F_KEEP('spicy'),
      {id:'preserve',type:'combo',list:'spKeep',kind:'many',label:'保留列表',def:['face','bone','id'],hint:'身份漂移是主要问题：锁定脸、骨相与发际线'},
      IDLOCK,
      {id:'matchLight',type:'toggle',label:'匹配新环境光线（换背景时推荐）',en:'Match the new light direction naturally.',zt:'自然匹配新的光线方向。'}]},
  i2v:{base:'i2v',form:'person',name:'图生视频',fname:'人物',sub:'Image-to-Video · 人物',video:true,intro:'核心公式：只描述变化。一个主要动作 + 一个机位 + 环境响应 + 保留 + 声音，2–3 句为宜；不要重新描述已有画面。',
    fields:[
      F_IMGS('i2v',6,'首帧图片（第 0 帧）+ 可选尾帧 / 关键帧图','第 1 张 = 首帧（API 参数 image）；其余可设为尾帧或关键帧'),
      {id:'who',type:'seg',label:'主体称呼（单选）',opts:'who'},
      {id:'subj',type:'text2',label:'首帧主体称呼（可选）',hint:'识别后自动填入，用在动作句开头代替“她 / 他”',ph:['the woman in the white linen shirt','穿白色亚麻衬衫的女性']},
      {id:'action',type:'action',list:'actions',label:'一个主要动作（单选）',req:true,hint:'动作 + 速度修饰 + 方向；用主动动词'},
      F_FRAMES,
      F_CAM,
      {id:'env',type:'struct',struct:'env',label:'环境响应',hint:'让背景有轻微生命感，不要发明新物体'},
      {id:'preserve',type:'combo',list:'preserve',kind:'many',label:'保留',hint:'明确锁死不能变的部分'},
      {id:'depth',type:'checks',label:'纵深（可选，最多 2 项）',opts:'depth',max:2},
      F_SOUND,
      {id:'loop',type:'toggle',label:'无缝循环（呼吸待机等）',en:'Seamless loop, first frame matches last frame exactly.',zt:'无缝循环，首尾帧完全一致。'}]},
  i2v_s:{base:'i2v',form:'person',spicy:true,name:'图生视频',fname:'人物 · 🌶',sub:'Image-to-Video · 辣椒模式人物',video:true,intro:SPICY_INTRO+' 图生视频：只描述变化，一个微动作 + 静止或缓慢推进。',
    fields:[
      F_IMGS('i2v',6,'首帧图片（第 0 帧）+ 可选尾帧 / 关键帧图','第 1 张 = 首帧（API 参数 image）；其余可设为尾帧或关键帧'),
      {id:'sid',type:'struct',struct:'sid',label:'原图人物（虚构成年）',req:true,hint:'必须选择明确的成年年龄'},
      {id:'who',type:'seg',label:'主体称呼（单选）',opts:'who'},
      {id:'action',type:'action',list:'spAct',label:'一个主要动作（单选）',req:true,hint:'手册：一次一个主要动作，慢速、小幅'},
      F_FRAMES,
      F_SPCAM,
      {id:'env',type:'struct',struct:'spenv',label:'环境响应',hint:'烛火、雾气、纱帘、发丝；不要发明新物体'},
      {id:'preserve',type:'combo',list:'spKeep',kind:'many',label:'保留',def:['face','bone','id']},
      IDLOCK,F_SPSOUND,
      {id:'loop',type:'toggle',label:'无缝循环',en:'Seamless loop, first frame matches last frame exactly.',zt:'无缝循环，首尾帧完全一致。'}]},
  i2i_g:{base:'i2i',form:'product',name:'图生图',fname:'产品',sub:'Image Editing · 产品',video:false,intro:'产品表单：先改后保，一次只改一处（背景台面 / 摆放 / 颜色 / 材质 / 布光 / 道具 / 标签文字）；明确锁定产品外形、标志与文字、材质颜色。',
    fields:[
      F_IMGS('i2i',5,'产品原图（可多张，最多 5 张）','点击 / 拖入 / 粘贴；图片只留在本页内存'),
      {id:'change',type:'struct',struct:'pchange',label:'要改什么（产品，一次一处）',req:true,hint:'换背景台面、摆放、颜色、材质、布光或道具；标签文字要短'},
      F_ISTYLE,
      F_KEEP('product'),
      {id:'preserve',type:'combo',list:'pkeep',kind:'many',label:'保真保留',def:['shape','label','logo'],hint:'锁定产品形状、标签与标志位置'},
      {id:'matchLight',type:'toggle',label:'匹配新环境光线与反射（换背景时推荐）',en:'Match the new light direction and reflections naturally.',zt:'自然匹配新的光线方向与反射。'}]},
  i2i_o:{base:'i2i',form:'other',name:'图生图',fname:'其他',sub:'Image Editing · 动物 / 场景',video:false,intro:'动物 / 场景表单：先改后保，一次只改一处（背景 / 天气 / 时间 / 光线 / 色调 / 添加物体）；锁定动物毛色花纹或景物结构。',
    fields:[
      F_IMGS('i2i',5,'原图（可多张，最多 5 张）','点击 / 拖入 / 粘贴；图片只留在本页内存'),
      F_OTYPE,
      {id:'change',type:'struct',struct:'ochange',label:'要改什么（一次一处）',req:true,hint:'换背景、天气、时间、光线、色调或添加小物体'},
      F_ISTYLE,
      F_KEEP('other'),
      {id:'preserve',type:'combo',list:'oKeep',kind:'many',label:'保留列表',hint:'动物：毛色花纹、面部特征；场景：地形与建筑结构'},
      {id:'matchLight',type:'toggle',label:'匹配新环境光线（换背景时推荐）',en:'Match the new light direction naturally.',zt:'自然匹配新的光线方向。'}]},
  i2v_g:{base:'i2v',form:'product',name:'图生视频',fname:'产品',sub:'Image-to-Video · 产品',video:true,intro:'产品表单：只描述变化。一个产品微动（冷凝水 / 蒸汽 / 旋转 / 光线扫过）+ 一个机位（缓慢环绕或推进）+ 锁定形状与标签，2–3 句为宜。',
    fields:[
      F_IMGS('i2v',6,'产品首帧图片（第 0 帧）+ 可选尾帧 / 关键帧图','第 1 张 = 首帧（API 参数 image）；其余可设为尾帧或关键帧'),
      {id:'subj',type:'text2',label:'首帧产品称呼（可选）',hint:'识别后自动填入，用在微动句里代替“产品 / 表面”',ph:['the matte ceramic mug','哑光陶瓷马克杯']},
      {id:'action',type:'action',list:'pmotion',label:'一个产品微动（单选）',req:true,hint:'细小变化，不要让产品变形'},
      F_FRAMES,
      {id:'camera',type:'combo',list:'cameras',kind:'one',label:'一个机位（单选）',hint:'产品常用：缓慢环绕 / 缓慢推进 / 静止'},
      {id:'preserve',type:'combo',list:'pkeep',kind:'many',label:'保真保留',def:['shape','label','logo'],hint:'锁定产品形状、标签、标志位置'},
      {id:'depth',type:'checks',label:'纵深（可选，最多 2 项）',opts:'depth',max:2},
      F_SOUND,
      {id:'loop',type:'toggle',label:'无缝循环（旋转展示等）',en:'Seamless loop, first frame matches last frame exactly.',zt:'无缝循环，首尾帧完全一致。'}]},
  i2v_o:{base:'i2v',form:'other',name:'图生视频',fname:'其他',sub:'Image-to-Video · 动物 / 场景',video:true,intro:'动物 / 场景表单：只描述变化。动物一个小动作（眨眼、甩尾、转头），场景一个自然变化（云、水、雾、光）；一个机位 + 环境响应 + 保留。',
    fields:[
      F_IMGS('i2v',6,'首帧图片（第 0 帧）+ 可选尾帧 / 关键帧图','第 1 张 = 首帧（API 参数 image）；其余可设为尾帧或关键帧'),
      F_OTYPE,
      {id:'subj',type:'text2',label:'首帧主体称呼（可选）',hint:'识别后自动填入，用在动作句里代替“动物”',ph:['the orange tabby cat','那只橘色虎斑猫']},
      {id:'action',type:'action',list:'oAct',label:'一个主要动作 / 变化（单选）',req:true,hint:'🐾 = 动物动作，🏞 = 场景变化'},
      F_FRAMES,
      F_CAM,
      {id:'env',type:'struct',struct:'env',label:'环境响应',hint:'已有元素轻微动起来，不要发明新物体'},
      {id:'preserve',type:'combo',list:'oKeep',kind:'many',label:'保留',hint:'动物：毛色花纹、面部特征；场景：地形与建筑结构'},
      {id:'depth',type:'checks',label:'纵深（可选，最多 2 项）',opts:'depth',max:2},
      F_SOUND,
      {id:'loop',type:'toggle',label:'无缝循环（风景动图等）',en:'Seamless loop, first frame matches last frame exactly.',zt:'无缝循环，首尾帧完全一致。'}]},
  t2v_p:{base:'t2v',form:'person',name:'文生视频',fname:'人物',sub:'Text-to-Video · 人物',video:true,intro:'人物表单：前 1/3 写第一帧（景别 + 人物 + 场景 + 布光），再用 then 串联 1–2 个动作节拍、表情变化、一个机位、身份锁定与声音。',
    fields:[
      F_FRAMING,F_ANGLE,F_LENS,F_STYLE,
      {id:'first',type:'struct',struct:'person',label:'第一帧人物',req:true,hint:'人物须为虚构成年角色'},
      {id:'setting',type:'struct',struct:'setting',label:'第一帧场景'},
      {id:'light',type:'struct',struct:'plight',label:'人物光线'},
      {id:'who',type:'seg',label:'动作主体称呼（单选）',opts:'who'},
      {id:'beats',type:'beats',label:'动作序列（用 then 串联）',hint:'每个节拍单选一个动作；建议 1–2 个，最多 3 个',max:3},
      {id:'exprCh',type:'combo',list:'exprCh',kind:'one',label:'表情变化（单选，可选）'},
      F_CAM,
      {id:'throughout',type:'toggle',label:'机位贯穿全片（throughout the clip）',def:true},
      F_DEPTH,
      {id:'idlock',type:'toggle',label:'身份锁定：Preserve exact face, bone structure, and hairline',def:true,en:'Preserve exact face, bone structure, and hairline.',zt:'保持脸部、骨相与发际线完全一致。'},
      {id:'continuity',type:'combo',list:'preserve',kind:'many',label:'连续性（必须保持）',hint:'如服装、街道几何结构'},
      {id:'sound',type:'sound',label:'声音（类型单选）'}]},
  t2v_ps:{base:'t2v',form:'person',spicy:true,name:'文生视频',fname:'人物 · 🌶',sub:'Text-to-Video · 人物 · 辣椒模式',video:true,intro:SPICY_INTRO,
    fields:[
      F_FRAMING,F_ANGLE,F_LENS,F_STYLE,
      {id:'first',type:'struct',struct:'spicy',label:'第一帧人物（虚构成年）',req:true,hint:'必须选择明确的成年年龄'},
      {id:'setting',type:'struct',struct:'spset',label:'第一帧场景 / 氛围'},
      {id:'light',type:'struct',struct:'smood',label:'布光'},
      {id:'who',type:'seg',label:'动作主体称呼（单选）',opts:'who'},
      {id:'action',type:'action',list:'spAct',label:'一个主要动作（单选）',req:true,hint:'手册：一次一个主要动作，慢速、小幅'},
      F_SPCAM,
      {id:'throughout',type:'toggle',label:'机位贯穿全片（throughout the clip）',def:true},
      F_DEPTH,IDLOCK,
      {id:'continuity',type:'combo',list:'spKeep',kind:'many',label:'连续性（必须保持）'},
      F_SPSOUND]},
  t2v_g:{base:'t2v',form:'product',name:'文生视频',fname:'产品',sub:'Text-to-Video · 产品',video:true,intro:'产品表单：第一帧写产品与背景台面、布光，再写 1–2 个产品微动（冷凝水、蒸汽、旋转…）、一个机位，最后锁定产品形状与标签。',
    fields:[
      {id:'framing',type:'seg',label:'第一帧景别（单选）',opts:'shot',none:'不指定'},F_ANGLE,F_LENS,F_STYLE,
      {id:'first',type:'struct',struct:'product',label:'第一帧产品',req:true},
      {id:'set',type:'struct',struct:'pset',label:'背景台面与道具'},
      {id:'light',type:'struct',struct:'glight',label:'产品布光'},
      {id:'motion',type:'combo',list:'pmotion',kind:'many',max:2,label:'产品微动（≤2）',req:true,hint:'一次 1–2 个细小变化，不要让产品变形'},
      F_CAM,
      {id:'throughout',type:'toggle',label:'机位贯穿全片（throughout the clip）',def:true},
      {id:'depth',type:'checks',label:'纵深（可选，最多 2 项）',opts:'depth',max:2},
      {id:'preserve',type:'combo',list:'pkeep',kind:'many',label:'保真保留',def:['shape','label'],hint:'锁定产品形状、标签、标志位置'},
      {id:'sound',type:'sound',label:'声音（类型单选）'}]},
  t2v:{base:'t2v',form:'other',name:'文生视频',fname:'其他',sub:'Text-to-Video · 动物 / 场景',video:true,intro:'模型会先从提示生成第一帧再动画：前 1/3 当作静态构图写清楚，再用 then 串联动作节拍，一个机位，写明连续性与声音。',
    fields:[
      {id:'framing',type:'seg',label:'第一帧景别（单选）',opts:'shot',none:'不指定'},
      {id:'angle',type:'seg',label:'第一帧拍摄角度（单选）',opts:'angle',none:'不指定'},F_LENS,F_STYLE,
      {id:'first',type:'struct',struct:'subject',label:'第一帧主体',req:true},
      {id:'setting',type:'struct',struct:'setting',label:'第一帧场景'},
      {id:'who',type:'seg',label:'动作主体称呼（单选）',opts:'who'},
      {id:'beats',type:'beats',label:'动作序列（用 then 串联）',hint:'每个节拍单选一个动作；建议 1–2 个，最多 3 个',max:3},
      F_CAM,
      {id:'throughout',type:'toggle',label:'机位贯穿全片（throughout the clip）',def:true},
      {id:'depth',type:'checks',label:'纵深（最多 2 项）',opts:'depth',max:2},
      {id:'continuity',type:'combo',list:'preserve',kind:'many',label:'连续性（必须保持）',hint:'如脸、服装、街道几何结构'},
      {id:'sound',type:'sound',label:'声音（类型单选）'}]},
  ref:{base:'ref',name:'参考图生视频',sub:'Reference-to-Video',video:true,intro:'参考图提供角色、产品、场景，但不固定首帧。每张图只承担一个角色、在画面中有固定位置；角色数量保持少；道具保持静止。按列表顺序用 <IMAGE_0>、<IMAGE_1>… 引用。',
    fields:[
      F_IMGS('ref',15,'参考图（可多张）','顺序 = 编号；1.5 最多 14 张参考图（旧版 7 张），开启首帧时第 1 张为首帧'),
      {id:'firstFrame',type:'toggle',label:'同时设置首帧 image（首帧占 <IMAGE_0>，参考图从 <IMAGE_1> 开始）'},
      {id:'refs',type:'refs',label:'参考图列表（顺序 = 编号；每张图单选一个角色）'},
      F_STYLE,
      {id:'scene',type:'text2',label:'画面与动作描述',req:true,area:true,tags:true,hint:'用 <IMAGE_n> 引用参考图；一个主要动作',ph:['The model from <IMAGE_0> wears the shirt from <IMAGE_1> and slowly turns toward the camera','<IMAGE_0> 中的模特穿上 <IMAGE_1> 中的衬衫，缓慢转向镜头']},
      F_CAM,
      {id:'depth',type:'checks',label:'纵深（可选，最多 2 项）',opts:'depth',max:2},
      F_SOUND]}
};
const BASES=['t2i','i2i','i2v','t2v','ref'];
const FORMS={i2i:[['person','人物'],['product','产品'],['other','其他（动物 / 场景）']],i2v:[['person','人物'],['product','产品'],['other','其他（动物 / 场景）']],t2i:[['person','人物'],['product','产品'],['other','其他（动物 / 场景）']],t2v:[['person','人物'],['product','产品'],['other','其他（动物 / 场景）']]};
function baseOf(k){return (MODES[k]&&MODES[k].base)||k}
function spicyAllowed(base,form){return ['t2i','t2v','i2i','i2v'].includes(base)&&(form||'person')==='person'}
function resolveKey(base,form,spicy){if(base==='t2i'||base==='t2v'){if(form==='product')return base+'_g';if(form==='other')return base;return base+(spicy?'_ps':'_p')}
  if(base==='i2i'||base==='i2v'){if(form==='product')return base+'_g';if(form==='other')return base+'_o';return spicy?base+'_s':base}return base}
function modeTitle(k){const M=MODES[k];return M?M.name+(M.fname?' · '+M.fname:''):k}

/* ================= 预设（手册「分类提示词示例」等） ================= */
const PRESETS=[
 {g:'人物',name:'窗边看书（虚构成年女性）',mode:'t2i_p',data:{subject:{parts:{ptype:'real',gender:'f',age:'a25',fic:true,hair:['lbk'],cloth:['wsh'],pose:'read'},zh:'',en:''},setting:{parts:{place:'win'},zh:'',en:''},light:{parts:{pat:'win',hard:'soft'},zh:'',en:''},framing:{v:'ms'},depth:{v:['shallow']}}},
 {g:'人物',name:'伦勃朗光肖像（虚构成年男性）',mode:'t2i_p',data:{subject:{parts:{ptype:'real',gender:'m',age:'40',fic:true,hair:['beard'],cloth:['bsu'],expr:'think'},zh:'',en:''},setting:{parts:{place:'seam'},zh:'',en:''},light:{parts:{pat:'rem',dir:'l',hard:'soft'},zh:'',en:''},framing:{v:'cu'},angle:{v:'tq'},depth:{v:['focus']}}},
 {g:'数字人',name:'数字人 · 未来感',mode:'t2i_p',data:{subject:{parts:{ptype:'dh',gender:'f',hair:['ssv'],cloth:['tech']},zh:'',en:''},setting:{parts:{},en:'holographic blue light background',zh:'全息蓝光背景'},light:{parts:{pat:'rim'},zh:'',en:''},framing:{v:'ms'},angle:{v:'front'}}},
 {g:'人物',name:'真实人物（虚构）· 转头微笑',mode:'i2v',data:{who:{v:'she'},action:{v:'_custom',en:'She slowly turns her head toward the camera and smiles gently',zh:'她缓慢转头看向镜头，轻轻微笑'},camera:{v:'static'},preserve:{v:['face','hair','cloth']}}},
 {g:'人物',name:'窗边肖像 · 转头 + 浅景深',mode:'i2v',data:{who:{v:'she'},action:{v:'turn'},camera:{v:'static'},depth:{v:['shallow']},preserve:{v:['face','cloth']}}},
 {g:'人物',name:'雨夜街头 · 转头然后微笑',mode:'t2v_p',data:{framing:{v:'ms'},first:{parts:{ptype:'real',gender:'f',age:'l20',fic:true,cloth:['rrc'],pose:'stand'},zh:'',en:''},setting:{parts:{loc:'city',place:'tokyo',time:'night'},zh:'',en:''},who:{v:'she'},beats:[{v:'turn'},{v:'smile'}],camera:{v:'push'},throughout:true,depth:{v:['refl']},idlock:true,continuity:{v:[],en:'her jacket and the street geometry',zh:'她的外套和街道几何结构'},sound:{v:'nodlg',parts:{amb:['traffic','rain']},en:'',zh:''}}},
 {g:'人物',name:'咖啡馆 · 眨眼后微笑',mode:'t2v_p',data:{framing:{v:'cu'},first:{parts:{ptype:'real',gender:'m',age:'30',fic:true,hair:['sbk'],cloth:['knit']},zh:'',en:''},setting:{parts:{place:'cafe',time:'morn'},zh:'',en:''},light:{parts:{pat:'win',dir:'l',hard:'soft'},zh:'',en:''},who:{v:'he'},beats:[{v:'blink'}],exprCh:{v:'cs'},camera:{v:'static'},throughout:true,depth:{v:['shallow']},idlock:true,sound:{v:'nodlg',parts:{amb:['cafe']},en:'',zh:''}}},
 {g:'数字人',name:'数字人 · 呼吸待机',mode:'i2v',data:{who:{v:'dh'},action:{v:'_custom',en:'The digital human breathes slowly and naturally, chest rising and falling gently, eyes blinking occasionally',zh:'数字人自然缓慢呼吸，胸腔轻微起伏，偶尔眨眼'},env:{parts:{env:['hair']},en:'',zh:''},camera:{v:'static'},preserve:{v:['face','pose','id']}}},
 {g:'呼吸循环',name:'数字人呼吸循环 · 无缝循环',mode:'i2v',data:{who:{v:'dh'},action:{v:'_custom',en:'Natural breathing and subtle head micro-movements',zh:'自然呼吸与轻微头部微动'},camera:{v:'static'},preserve:{v:['id']},loop:true}},
 {g:'产品',name:'无线耳机盒 · 微距',mode:'t2i_g',data:{subject:{parts:{color:'black',material:'mpl',cat:'buds',place:'wtab'},zh:'',en:''},light:{parts:{pat:'box',hard:'soft',dir:'s'},zh:'',en:''},framing:{v:'macro'},comp:{parts:{focus:'subj'},zh:'',en:''},depth:{v:['shallow']}}},
 {g:'产品',name:'手冲滤杯（结构示例）',mode:'t2i_g',data:{subject:{parts:{cat:'drip',material:'mcer',color:'sage',place:'carafe'},en:'the carafe half full of coffee',zh:'分享壶里有半壶咖啡'},angle:{v:'tq'},set:{parts:{surf:['oak','tile'],props:['towel']},zh:'',en:''},light:{parts:{pat:'sun',dir:'l',hard:'hard'},en:'with soft fill',zh:'柔和补光'},comp:{parts:{},en:'at counter height',zh:'台面高度'}}},
 {g:'产品',name:'冰镇玻璃瓶 · 冷凝水 + 缓慢推进',mode:'t2v_g',data:{framing:{v:'cu'},first:{parts:{cat:'bottle',material:'glass',place:'marb'},zh:'',en:''},set:{parts:{bgc:'dblue'},zh:'',en:''},light:{parts:{pat:'sback',hard:'soft'},zh:'',en:''},motion:{v:['cond'],en:'',zh:''},camera:{v:'push'},throughout:true,preserve:{v:['shape','label']},sound:{v:'room'}}},
 {g:'产品',name:'香水瓶 · 缓慢旋转',mode:'t2v_g',data:{framing:{v:'ms'},first:{parts:{cat:'perf',material:'fglass',place:'ped'},zh:'',en:''},set:{parts:{surf:['seam'],bgc:'cream'},zh:'',en:''},light:{parts:{pat:'edge'},zh:'',en:''},motion:{v:['rot','sweep'],en:'',zh:''},camera:{v:'static'},throughout:true,preserve:{v:['shape','label','logo']}}},
 {g:'产品',name:'冷凝水珠（图生视频）',mode:'i2v_g',data:{subj:{en:'the glass bottle',zh:'玻璃瓶'},action:{v:'cond',parts:{},en:'',zh:''},camera:{v:'_custom',en:'Slow push-in, locked horizon',zh:'缓慢向前推进，地平线锁定'},preserve:{v:['shape','label','logo'],en:'lighting',zh:'光线'}}},
 {g:'产品',name:'缓慢旋转展示（图生视频）',mode:'i2v_g',data:{action:{v:'rot',parts:{},en:'',zh:''},camera:{v:'static'},preserve:{v:['shape','label','logo','color']},loop:true}},
 {g:'产品',name:'改液体颜色',mode:'i2i_g',data:{change:{parts:{target:'color',obj:'liquid',to:'emer'},zh:'',en:''},preserve:{v:['shape','label','logo','light','angle']}}},
 {g:'产品',name:'换成大理石台面',mode:'i2i_g',data:{change:{parts:{target:'bg',to:'marb'},zh:'',en:''},keep:{m:{shape:'keep',logo:'keep',matc:'keep'}},matchLight:true}},
 {g:'动物',name:'换成雪景背景（动物）',mode:'i2i_o',data:{otype:{v:'animal'},change:{parts:{target:'weather',to:'snow'},zh:'',en:''},keep:{m:{subj:'keep',pose:'keep'}},preserve:{v:['fur','face']}}},
 {g:'场景',name:'改成黄昏（风景）',mode:'i2i_o',data:{otype:{v:'scene'},change:{parts:{target:'time',to:'gold'},zh:'',en:''},keep:{m:{subj:'keep',comp:'keep'}},preserve:{v:['terrain']}}},
 {g:'动物',name:'猫咪眨眼甩尾（图生视频）',mode:'i2v_o',data:{otype:{v:'animal'},subj:{en:'the cat',zh:'猫'},action:{v:'ablink',parts:{},en:'',zh:''},camera:{v:'static'},preserve:{v:['fur','face']}}},
 {g:'场景',name:'云层流动（风景图生视频）',mode:'i2v_o',data:{otype:{v:'scene'},action:{v:'sclouds',parts:{},en:'',zh:''},env:{parts:{env:['leaves']},en:'',zh:''},camera:{v:'static'},preserve:{v:['terrain','bg']},loop:true}},
 {g:'照片',name:'换成雨夜东京背景',mode:'i2i',data:{change:{parts:{target:'bg',to:'tokyo'},en:'wet asphalt reflections at night',zh:'夜晚，湿地面反射'},preserve:{v:['face','expr','pose','cloth']},matchLight:true}},
 {g:'照片',name:'眨眼呼吸',mode:'i2v',data:{who:{v:'person'},action:{v:'_custom',en:'The person slowly blinks and breathes gently',zh:'人物缓慢眨眼并轻轻呼吸'},env:{parts:{env:['hair']},en:'',zh:''},camera:{v:'static'},preserve:{v:[],en:'every detail of the original photo',zh:'原图一切细节'}}},
 {g:'风格',name:'水彩 · 窗边看书',mode:'t2i_p',data:{subject:{parts:{ptype:'real',gender:'f',age:'20',fic:true,pose:'read'},zh:'',en:''},setting:{parts:{place:'win'},zh:'',en:''},style:{v:'water'},framing:{v:'ms'}}},
 {g:'动物 / 场景',name:'黄昏公园里的柯基',mode:'t2i',data:{subject:{parts:{stype:'animal',animal:'corgi',pose:'sit'},zh:'',en:''},setting:{parts:{place:'park',time:'gold'},zh:'',en:''},framing:{v:'ms'},depth:{v:['shallow']}}},
 {g:'参考图',name:'虚拟试穿',mode:'ref',data:{firstFrame:false,refs:[{role:'char',en:'model',zh:'模特'},{role:'cloth',en:'shirt',zh:'衬衫'}],scene:{en:'The model from <IMAGE_0> wears the shirt from <IMAGE_1> and slowly turns toward the camera in a bright studio',zh:'<IMAGE_0> 中的模特穿上 <IMAGE_1> 中的衬衫，在明亮的摄影棚里缓慢转向镜头'},camera:{v:'static'}}},
 {g:'🌶 辣椒模式',name:'烛光卧室 · 蕾丝内衣 · 侧卧回眸（虚构成年）',mode:'t2i_ps',data:{subject:{parts:{gender:'f',age:'30',hair:['pillow'],cloth:['lace'],cstate:['strap'],pose:'sidelie',expr:'hazy'},zh:'',en:''},setting:{parts:{place:'sheets',time:'night'},zh:'',en:''},light:{parts:{pat:'candle',hard:'soft'},zh:'',en:''},style:{v:'cine'},framing:{v:'ms'},depth:{v:['shallow']},idlock:true}},
 {g:'🌶 辣椒模式',name:'酒店窗边 · 仅着衬衫 · 霓虹边缘光（虚构成年）',mode:'t2i_ps',data:{subject:{parts:{gender:'f',age:'a30',hair:['messy'],cloth:['only'],cstate:['btn'],pose:'sill',expr:'direct'},zh:'',en:''},setting:{parts:{place:'hotel',time:'night'},zh:'',en:''},light:{parts:{pat:'neon'},zh:'',en:''},style:{v:'photo'},framing:{v:'ms'},angle:{v:'tq'},depth:{v:['shallow']},idlock:true}},
 {g:'🌶 辣椒模式',name:'二次元 · 丝缎吊带睡裙（成年角色）',mode:'t2i_ps',data:{subject:{parts:{gender:'f',age:'20',hair:['wave'],cloth:['slip'],cstate:['strap'],pose:'recline',expr:'tease'},zh:'',en:''},setting:{parts:{place:'bed',time:'night'},zh:'',en:''},light:{parts:{pat:'lamp'},zh:'',en:''},style:{v:'anime'},framing:{v:'ms'},idlock:true}},
 {g:'🌶 辣椒模式',name:'百叶窗光影 · 敞开丝绸衬衫（虚构成年男性）',mode:'t2i_ps',data:{subject:{parts:{gender:'m',age:'30',hair:['slick'],cloth:['silkopen'],pose:'wall',expr:'direct'},zh:'',en:''},setting:{parts:{place:'bed'},zh:'',en:''},light:{parts:{pat:'blinds',dir:'l'},zh:'',en:''},style:{v:'film'},framing:{v:'ms'},angle:{v:'low'},idlock:true}},
 {g:'🌶 辣椒模式',name:'浴室雾气 · 浴巾裹身 · 撩起头发（虚构成年）',mode:'t2v_ps',data:{framing:{v:'ms'},first:{parts:{gender:'f',age:'l20',hair:['wet'],cloth:['towel'],expr:'half'},zh:'',en:''},setting:{parts:{place:'steam'},zh:'',en:''},light:{parts:{pat:'thru',hard:'soft'},zh:'',en:''},style:{v:'cine'},who:{v:'she'},action:{v:'hairup',parts:{},en:'',zh:''},camera:{v:'push'},throughout:true,depth:{v:['shallow']},idlock:true,sound:{v:'nodlg',parts:{amb:['room']},en:'',zh:''}}},
 {g:'🌶 辣椒模式',name:'丝绒沙发 · 缓慢伸展腰背 · 缓慢环绕（虚构成年）',mode:'t2v_ps',data:{framing:{v:'mws'},first:{parts:{gender:'f',age:'30',cloth:['backless'],cstate:['back'],pose:'stretch',expr:'languid'},zh:'',en:''},setting:{parts:{place:'velvet',time:'night'},zh:'',en:''},light:{parts:{pat:'red'},zh:'',en:''},who:{v:'she'},action:{v:'arch',parts:{},en:'',zh:''},camera:{v:'orbit'},throughout:true,idlock:true,sound:{v:'dlg',zh:'别走',en:'Stay'}}},
 {g:'🌶 辣椒模式',name:'拨开肩带 · 缓慢推进（图生视频，虚构成年）',mode:'i2v_s',data:{sid:{parts:{gender:'f',age:'l20'},zh:'',en:''},who:{v:'she'},action:{v:'strap',parts:{speed:'slowly'},en:'',zh:''},camera:{v:'push'},env:{parts:{env:['flame']},en:'',zh:''},idlock:true,sound:{v:'room'}}},
 {g:'🌶 辣椒模式',name:'换成透视纱衣（图生图，虚构成年）',mode:'i2i_s',data:{sid:{parts:{gender:'f',age:'30'},zh:'',en:''},change:{parts:{target:'cloth',to:'sheer'},zh:'',en:''},idlock:true}},
 {g:'🌶 辣椒模式',name:'改成百叶窗光影（图生图，虚构成年）',mode:'i2i_s',data:{sid:{parts:{gender:'m',age:'40'},zh:'',en:''},change:{parts:{target:'light',to:'blinds'},zh:'',en:''},idlock:true,matchLight:false}}
];

/* ================= 核心：拼装与检查（纯函数） ================= */
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const byK=(list,k)=>KB[list].find(o=>o.k===k);
const trim=s=>(s||'').trim();
function cap(s){s=trim(s);return s?s.charAt(0).toUpperCase()+s.slice(1):s}
function lowerFirst(s){s=trim(s);if(!s)return s;if(/^(I\b|<IMAGE|Rembrandt|Tokyo)/.test(s))return s;return s.charAt(0).toLowerCase()+s.slice(1)}
function sEn(s){s=trim(s);if(!s)return '';s=cap(s);return /[.!?"”]$/.test(s)?s:s+'.'}
function sZh(s){s=trim(s).replace(/[。.]+$/,'');return s?s+'。':''}
function cj(arr){arr=arr.map(trim).filter(Boolean).map(x=>x.replace(/[.。]+$/,''));return arr.map((x,i)=>i?lowerFirst(x):x).join(', ')}
function pick(o,lang){if(!o)return '';const a=trim(o[lang]),b=trim(o[lang==='en'?'zh':'en']);return a||b}
function joinList(arr,lang){arr=arr.filter(Boolean);if(lang==='zh')return arr.join('、');if(arr.length<=1)return arr.join('');if(arr.length===2)return arr[0]+' and '+arr[1];return arr.slice(0,-1).join(', ')+', and '+arr[arr.length-1]}
function fillWho(t,who){const w=byK('who',who)||KB.who[0];return t.replace('{S}',w.en).replace(/\{P\}/g,w.p).replace('{Z}',w.zh)}
function listOf(f){return f.list||f.opts}
function selVal(f,o,lang,who){
  if(!o||!o.v)return '';
  if(o.v==='_custom')return pick(o,lang);
  const L=listOf(f);const it=optItem(L,o.v);if(!it)return '';
  if(L==='actions'&&!it.custom)return fillWho(lang==='en'?it.en:it.zt,who);
  return lang==='en'?itEn(it):itZh(it);
}
function checksVal(f,o,lang){
  if(!o)return [];const arr=(o.v||[]).map(k=>{const it=optItem(listOf(f),k);if(!it)return '';return lang==='en'?lf(itEn(it)):itZh(it)});
  const c=pick(o,lang);if(c)arr.push(c);return arr.filter(Boolean);
}
function soundAmb(o,lang){const a=((o&&o.parts&&o.parts.amb)||[]).map(k=>optItem('amb',k)).filter(Boolean);return a.map(it=>lang==='en'?lf(itEn(it)):itZh(it))}
function depthSent(o,lang){const a=checksVal({opts:'depth'},o,lang);if(!a.length)return '';return lang==='en'?sEn(joinList(a,'en')):sZh(a.join('，'))}
function soundSent(o,lang,who){
  if(!o||!o.v)return '';const it=byK('sound',o.v);let txt=pick(o,lang);
  if(o.v==='amb'||o.v==='nodlg'){const a=soundAmb(o,lang);if(a.length)txt=lang==='en'?cj([joinList(a,'en'),txt]):[a.join('、'),txt].filter(Boolean).join('，')}
  if(o.v==='room')return lang==='en'?it.en:it.zt;
  if(o.v==='nodlg'){const base=lang==='en'?it.en:it.zt;return txt?(lang==='en'?sEn(txt)+' '+base:sZh(txt)+base):base}
  if(o.v==='amb')return lang==='en'?sEn(txt):sZh(txt);
  if(o.v==='dlg'){if(!txt)return '';const w=byK('who',who)||KB.who[0];const q=txt.replace(/^["“'「]+|["”'」]+$/g,'');return lang==='en'?`${w.en} says "${q}".`:`${w.zh}说：“${q}”。`}
  return '';
}
function presEn(f,o,verb,tail){const items=(o&&o.v||[]).map(k=>{const it=optItem(listOf(f),k);return it?lf(itEn(it)):''}).filter(Boolean);const c=trim(o&&o.en)||trim(o&&o.zh);
  if(!items.length&&!c)return '';if(!items.length)return sEn(verb+' '+c+' exactly'+(tail?' '+tail:''));return `${verb} the exact ${joinList(items.concat(c?[c]:[]),'en')}${tail?' '+tail:''}.`}
function refTag(i,ff){return `<IMAGE_${i+(ff?1:0)}>`}

function defaults(mode){
  const d={};const cl=v=>JSON.parse(JSON.stringify(v));
  for(const f of MODES[mode].fields){
    if(f.type==='text2')d[f.id]={en:'',zh:''};
    else if(f.type==='select'||f.type==='seg')d[f.id]={v:f.def!==undefined?f.def:(f.id==='who'?'she':(f.none!==undefined?'':KB[f.opts][0].k)),en:'',zh:''};
    else if(f.type==='struct')d[f.id]={parts:{},en:'',zh:''};
    else if(f.type==='combo')d[f.id]={v:f.def!==undefined?cl(f.def):(f.kind==='many'?[]:''),en:'',zh:''};
    else if(f.type==='action')d[f.id]={v:'',en:'',zh:'',parts:{}};
    else if(f.type==='checks')d[f.id]={v:[],en:'',zh:''};
    else if(f.type==='toggle')d[f.id]=!!f.def;
    else if(f.type==='sound')d[f.id]={v:'',en:'',zh:'',parts:{}};
    else if(f.type==='beats')d[f.id]=[{v:'',en:'',zh:''}];
    else if(f.type==='refs')d[f.id]=[{role:'char',en:'',zh:''},{role:'cloth',en:'',zh:''}];
    else if(f.type==='aspects'){d.keep={m:{}};d.keepch={};for(const a of ASPECTS)d.keepch[a.k]={zh:'',en:''};d.keepd={}}
    else if(f.type==='frames'){d.tl=false;d.seg1=4;d.segs=[];d.keys=[];d.endf={on:false,zh:'',en:''}}
  }
  return d;
}
/* 旧版「文生图 / 文生视频」单一表单 → 人物表单 / 产品表单（不兼容内容并入「补充说明」） */
function convertOld(mode,d){
  if((mode!=='t2i'&&mode!=='t2v')||!d)return null;const sf=mode==='t2i'?'subject':'first';const n=d[sf];const P=n&&n.parts||{};const st=P.stype;
  if(!['person','dh','product'].includes(st))return null;
  const prod=st==='product';const key=mode+(prod?'_g':'_p');const nd=defaults(key);const left=[],leftE=[];const LP=(z,e)=>{if(trim(z)){left.push(z);leftE.push(e||'')}};const K=(o,ks)=>{const r={};ks.forEach(k=>{if(o[k]!==undefined)r[k]=o[k]});return r};
  nd[sf]=prod?{parts:K(P,['cat','material','color','place']),zh:n.zh||'',en:n.en||''}:{parts:Object.assign({ptype:st==='dh'?'dh':'real'},K(P,['gender','age','fic','hair','cloth','acc','pose'])),zh:n.zh||'',en:n.en||''};
  for(const id of ['framing','angle','lens','depth','who','beats','camera','throughout','continuity','sound'])if(d[id]!==undefined&&nd[id]!==undefined&&!(prod&&(id==='beats'||id==='continuity'||id==='who')))nd[id]=d[id];
  if(nd.setting&&d.setting)nd.setting=d.setting;else if(d.setting&&structHas(d.setting))LP(composeLead(null,d.setting,'zh'),composeLead(null,d.setting,'en'));
  const L=d.light;if(L&&structHas(L)){const lp=L.parts||{};const map=prod?{soft:'box',win:'win',sun:'sun'}:{win:'win',nat:'nat'};const np=K(lp,prod?['dir','hard']:['dir','hard','fill']);
    if(lp.src){if(map[lp.src])np.pat=map[lp.src];else{const it=optItem('lightSrc',lp.src);if(it)LP(it.zh,itEn(it))}}if(prod&&lp.fill){const it=optItem('lightFill',lp.fill);if(it)LP(it.zh,itEn(it))}
    nd.light={parts:np,zh:L.zh||'',en:L.en||''}}
  if(d.art&&structHas(d.art)){if(prod){nd.set.parts=Object.assign(nd.set.parts,K(d.art.parts||{},['props','surf']));if(trim(d.art.zh)||trim(d.art.en)){nd.set.zh=d.art.zh||'';nd.set.en=d.art.en||''}}else LP(composeStruct('art',d.art,'zh'),composeStruct('art',d.art,'en'))}
  if(d.color&&structHas(d.color)){const c=d.color.parts||{};if(prod){if(!nd[sf].parts.color&&(c.subj||[])[0])nd[sf].parts.color=c.subj[0];if((c.bg||[])[0])nd.set.parts.bgc=c.bg[0];if(trim(d.color.zh))LP(d.color.zh,d.color.en)}else LP(composeStruct('color',d.color,'zh'),composeStruct('color',d.color,'en'))}
  if(d.comp&&structHas(d.comp)){if(nd.comp)nd.comp=d.comp;else LP(composeStruct('comp',d.comp,'zh'),composeStruct('comp',d.comp,'en'))}
  if(prod&&mode==='t2v'){const bz=(d.beats||[]).map(b=>b.v==='_custom'?trim(b.zh):(optItem('actions',b.v)||{}).zh).filter(Boolean);if(bz.length)nd.motion.zh=bz.join('，');
    const cz=checksVal({list:'preserve'},d.continuity,'zh');if(cz.length)nd.preserve.zh=cz.join('、')}
  const lz=left.map(trim).filter(Boolean);const lE=leftE.map(trim).filter(Boolean);let origZh='',fullZh='';if(lz.length){const t=prod?nd.set:nd[sf];origZh=trim(t.zh);t.zh=[origZh].concat(lz).filter(Boolean).join('，');fullZh=t.zh}
  if(prod&&nd.set&&d.setting&&structHas(d.setting)){/* 已并入补充 */}
  return {mode:key,data:nd,moved:lz,leftEn:lE,origZh,fullZh};
}
/* 旧数据迁移：自由文本 → 结构化字段的「补充说明」；景别/角度拆分 */
function migrateData(mode,d){if(!d||!MODES[mode])return d;
  const ANGK=KB.angle.map(a=>a.k),SHOTK=KB.shot.map(a=>a.k);
  if(MODES[mode].fields.some(f=>f.id==='angle')){if(!d.angle||typeof d.angle!=='object')d.angle={v:'',en:'',zh:''};
    const v=d.framing&&d.framing.v;if(v&&ANGK.includes(v)){if(!d.angle.v)d.angle.v=v;d.framing.v=v==='front'?'ms':''}else if(v&&!SHOTK.includes(v))d.framing.v=''}
  /* 只适用于部分类别的选项（如过肩、全身）：在不适用的表单里清除，避免产品/场景出现人物措辞 */
  {const fm=MODES[mode].form||'person';for(const f of MODES[mode].fields)if(f.type==='seg'&&KB[f.opts]&&d[f.id]&&typeof d[f.id]==='object'){const it=KB[f.opts].find(x=>x.k===d[f.id].v);if(it&&it.only&&!it.only.includes(fm))d[f.id].v=''}}
  for(const f of MODES[mode].fields){const o=d[f.id];
    if(f.type==='struct'){if(!o||typeof o!=='object'||Array.isArray(o))d[f.id]={parts:{},en:'',zh:''};else{if(!o.parts||typeof o.parts!=='object')o.parts={};o.zh=o.zh||'';o.en=o.en||''}}
    else if(f.type==='combo'){if(!o||typeof o!=='object')d[f.id]={v:f.kind==='many'?[]:'',en:'',zh:''};else if(f.kind==='many'&&!Array.isArray(o.v))o.v=o.v?[o.v]:[];else if(f.kind!=='many'&&typeof o.v!=='string')o.v=''}
    else if((f.type==='action'||f.type==='sound')&&o&&typeof o==='object'&&!o.parts)o.parts={};}
  if(d.details&&(trim(d.details.zh)||trim(d.details.en))&&d.subject){const s=d.subject;s.zh=[trim(s.zh),trim(d.details.zh)].filter(Boolean).join('，');s.en=[trim(s.en),trim(d.details.en)].filter(Boolean).join(', ')}
  delete d.details;
  for(const f of MODES[mode].fields){if(f.type==='toggle'&&d[f.id]===undefined)d[f.id]=!!f.def;if(f.type==='struct'&&d[f.id])for(const pt of STRUCT[f.struct].parts)if(pt.lock)d[f.id].parts[pt.id]=true}
  return d}
const IDLOCK_EN='Preserve exact face, bone structure, and hairline',IDLOCK_ZH='保持脸部、骨相与发际线完全一致';
function subjField(M){return M.fields.find(f=>f.id==='subject'||f.id==='first')}
function leadOf(mode,d,lang,noSet){const M=MODES[mode];const f=subjField(M);if(!f)return '';const sf=M.fields.find(x=>x.id==='setting');return composeLead(d[f.id],noSet?null:d.setting,lang,STRUCT[f.struct],sf?STRUCT[sf.struct]:null)}
function sidSent(d,lang){if(!d.sid||!structHas(d.sid))return '';const t=composeLead(d.sid,null,lang,STRUCT.sid);if(!t)return '';return lang==='en'?sEn('The person is '+lowerFirst(t)):sZh('画面人物是'+t.replace(/^一位/,'一位'))}
/* v8：图生图「保持 / 修改」对照项；图生视频帧与时间轴 */
const ASPECTS=[{k:'id',zh:'人物身份与五官（或产品外形）',en:"the subject's identity and features"},{k:'cloth',zh:'服装',en:'the clothing'},{k:'pose',zh:'姿态',en:'the pose'},{k:'scene',zh:'背景与场景',en:'the background and scene'},{k:'light',zh:'光线',en:'the lighting'},{k:'comp',zh:'镜头与构图',en:'the framing and composition'},{k:'shape',zh:'产品外形与结构',en:"the product's shape and structure"},{k:'matc',zh:'材质与颜色',en:'the materials and colors'},{k:'logo',zh:'标志与文字',en:'the logo, label, and printed text'},{k:'subj',zh:'主体外观（毛色花纹 / 主要景物）',en:"the main subject's appearance"}];
function aspList(f,d){return typeof f.aspects==='function'?f.aspects(d):f.aspects}
const ASP_SHORT={id:'人物身份',cloth:'服装',pose:'姿态',scene:'场景',light:'光线',comp:'构图',shape:'外形结构',matc:'材质颜色',logo:'标志文字',subj:'主体外观'};
const ASP_COVERS={shape:['shape','prop'],logo:['label','logo'],matc:['mat','color'],light:['light'],comp:['angle'],scene:['bg'],pose:['pose'],cloth:['cloth'],subj:['fur','face'],id:['id']};
const CHG_ASP={bg:'scene',cloth:'cloth',light:'light',weather:'scene',place:'scene',color:'matc',mat:'matc',text:'logo',time:'light'};
function aspectSents(M,d){const f=M.fields.find(x=>x.type==='aspects');if(!f||!d.keep)return {kept:[],keepE:'',keepZ:'',chg:[]};const m=d.keep.m||{};const keepE=[],keepZ=[],chg=[];
  const AL=aspList(f,d);for(const a of ASPECTS){if(!AL.includes(a.k))continue;if(m[a.k]==='keep'){keepE.push(a.en);keepZ.push(a.zh)}else if(m[a.k]==='chg'){const c=(d.keepch||{})[a.k]||{};const e=pick(c,'en'),z=pick(c,'zh');if(e||z)chg.push([sEn('Change '+a.en+': '+lowerFirst(e.replace(/[.。]+$/,''))),sZh('修改'+a.zh+'：'+z)])}}
  const kept=AL.filter(k=>m[k]==='keep');
  return {kept,keepE:keepE.length?sEn('Keep '+joinList(keepE,'en')+' unchanged from the original image'):'',keepZ:keepZ.length?'保持原图的'+keepZ.join('、')+'不变。':'',chg}}
const fmtS=n=>String(Math.round(n*10)/10);
/* 产品 / 动物场景：用首帧主体称呼替换动作句里的泛称 */
function subjSwap(M,d){const se=pick(d.subj,'en').replace(/[.。]+$/,''),sz=trim(d.subj&&d.subj.zh||'').replace(/[。.]+$/,'');const the=x=>/^(the|a|an|this|that)\s/i.test(x)?x.replace(/^(a|an)\s/i,'the '):'the '+x;
  if(M.form==='product')return {e:t=>!se?t:cap(t.replace(/\bthe product\b/i,the(se)).replace(/\bthe surface\b/i,'the surface of '+the(se)).replace(/\baround it\b/i,'around '+the(se))),z:t=>!sz||!t?t:(t.includes(sz)?t:sz+'，'+t)};
  return {e:t=>!se?t:cap(t.replace(/\bthe animal\b/i,the(se))),z:t=>!sz?t:t.replace(/^动物/,sz)}}
function timeline(d,dur){if(!d.tl)return null;const segs=[{b:+d.seg1}].concat((d.segs||[]).map(s=>({b:+s.b})));let a=0;return segs.map((s,i)=>{const last=i===segs.length-1;const b=last?dur:Math.min(dur,s.b||dur);const r={a,b};a=b;return r})}
function build(mode,d,P){
  const M=MODES[mode];const bm=baseOf(mode);const fd=id=>M.fields.find(f=>f.id===id);const has=id=>!!fd(id);const out={en:[],zh:[]};
  const push=(e,z)=>{if(e)out.en.push(e);if(z)out.zh.push(z)};
  const who=d.who&&d.who.v;
  const dE=checksVal({opts:'depth'},d.depth,'en'),dZ=checksVal({opts:'depth'},d.depth,'zh');
  const camDepth=(c,cz)=>{push(sEn(cj([c].concat(dE))),sZh([cz].concat(dZ).filter(Boolean).join('，')))};
  const CS=(id,lang)=>has(id)&&fd(id).type==='struct'?composeStruct(fd(id).struct,d[id],lang):'';
  const sel=(id,lang)=>has(id)?selVal(fd(id),d[id],lang,who):'';
  const sty=lang=>has('style')?styleText(d.style,lang,!!M.spicy,/^(t2v|i2v|ref)/.test(M.base||mode)):'';
  const presLock=(verb,tail)=>{const f=fd('preserve');const o=d.preserve||{v:[]};const on=has('idlock')&&d.idlock;
    if(!on){const pz=checksVal(f,o,'zh');push(presEn(f,o,verb,tail),pz.length?(tail?'全程':'')+`保持${pz.join('、')}完全不变。`:'');return}
    const o2=Object.assign({},o,{v:(o.v||[]).filter(k=>k!=='face'&&k!=='bone')});const e=checksVal(f,o2,'en'),z=checksVal(f,o2,'zh');const [a,b]=lock(e.length?'the '+joinList(e,'en'):'',z.join('、'));push(a.replace(/\.$/,'')+(tail?' '+tail:'')+'.',(tail?'全程':'')+b)};
  const lock=(extraE,extraZ)=>{const on=has('idlock')&&d.idlock;if(on&&extraE)return [sEn(IDLOCK_EN+', and keep '+extraE+' consistent'),sZh(IDLOCK_ZH+'，并保持'+extraZ+'一致')];if(on)return [sEn(IDLOCK_EN),sZh(IDLOCK_ZH)];if(extraE)return [sEn('Preserve '+extraE),sZh('保持'+extraZ+'一致')];return ['','']};
  if(mode==='t2i'){
    push(sEn(composeLead(d.subject,d.setting,'en')),sZh(composeLead(d.subject,d.setting,'zh')));
    push(sEn(cj([sel('framing','en'),sel('angle','en'),sel('lens','en'),sty('en')])),sZh([sel('framing','zh'),sel('angle','zh'),sel('lens','zh'),sty('zh')].filter(Boolean).join('，')));
    push(sEn(cj([CS('art','en'),CS('color','en')])),sZh([CS('art','zh'),CS('color','zh')].filter(Boolean).join('，')));
    push(sEn(cj([CS('light','en'),CS('comp','en')].concat(dE))),sZh([CS('light','zh'),CS('comp','zh')].concat(dZ).filter(Boolean).join('，')));
  }else if(mode==='t2i_p'||mode==='t2i_ps'){
    push(sEn(leadOf(mode,d,'en')),sZh(leadOf(mode,d,'zh')));
    push(sEn(cj([sel('framing','en'),sel('angle','en'),sel('lens','en'),sty('en')])),sZh([sel('framing','zh'),sel('angle','zh'),sel('lens','zh'),sty('zh')].filter(Boolean).join('，')));
    push(sEn(cj([CS('light','en')].concat(dE))),sZh([CS('light','zh')].concat(dZ).filter(Boolean).join('，')));
    const [a,b]=lock();push(a,b);
  }else if(mode==='t2i_g'){
    push(sEn(leadOf(mode,d,'en')),sZh(leadOf(mode,d,'zh')));
    push(sEn(cj([sel('framing','en'),sel('angle','en'),sel('lens','en'),sty('en')])),sZh([sel('framing','zh'),sel('angle','zh'),sel('lens','zh'),sty('zh')].filter(Boolean).join('，')));
    push(sEn(CS('set','en')),sZh(CS('set','zh')));
    push(sEn(cj([CS('light','en'),CS('comp','en')].concat(dE))),sZh([CS('light','zh'),CS('comp','zh')].concat(dZ).filter(Boolean).join('，')));
  }else if(bm==='i2i'){
    push(sidSent(d,'en'),sidSent(d,'zh'));
    push(sEn(CS('change','en')),sZh(CS('change','zh')));
    const AS=aspectSents(M,d);AS.chg.forEach(([e,z])=>push(e,z));
    if(sty('en'))push(sEn('Convert the whole image to '+sty('en')),sZh('把整张画面转换为'+sty('zh')));
    push(AS.keepE,AS.keepZ);
    if(AS.kept.length&&d.preserve&&(d.preserve.v||[]).length){const cov=new Set(AS.kept.flatMap(k=>ASP_COVERS[k]||[]));d=Object.assign({},d,{preserve:Object.assign({},d.preserve,{v:d.preserve.v.filter(k=>!cov.has(k))})})}
    presLock('Keep','');
    if(d.matchLight)push(fd('matchLight').en,fd('matchLight').zt);
  }else if(bm==='i2v'){
    const sidE=d.sid&&structHas(d.sid)?composeLead(d.sid,null,'en',STRUCT.sid):'',sidZ=d.sid&&structHas(d.sid)?composeLead(d.sid,null,'zh',STRUCT.sid):'';let sidUsed=false;
    if(d.loop)push(fd('loop').en,fd('loop').zt);
    const AL=fd('action').list;let aE=actionText(d.action,'en',who,AL),aZ=actionText(d.action,'zh',who,AL);
    if(sidE){const w=byK('who',who)||KB.who[0];if(aE.startsWith(w.en+' ')&&aZ.startsWith(w.zh)){aE='The '+lowerFirst(sidE.replace(/^an?\s+/i,''))+aE.slice(w.en.length);aZ='这位'+sidZ.replace(/^一位/,'')+aZ.slice(w.zh.length);sidUsed=true}}
    else if(has('subj')&&pick(d.subj,'en')){const w=byK('who',who)||KB.who[0];const se=pick(d.subj,'en').replace(/[.。]+$/,''),sz=pick(d.subj,'zh').replace(/[.。]+$/,'');if(aE.startsWith(w.en+' ')){aE=cap(/^(the|a|an)\s/i.test(se)?se:'the '+se)+aE.slice(w.en.length)}if(aZ.startsWith(w.zh)&&sz)aZ=(/^(这位|那位|这个)/.test(sz)?sz:'这位'+sz.replace(/^一位/,''))+aZ.slice(w.zh.length)}
    if(M.form==='product'||M.form==='other'){const r=subjSwap(M,d);aE=r.e(aE);aZ=r.z(aZ)}
    if(!sidUsed)push(sEn(sidE&&('The person is '+lowerFirst(sidE))),sZh(sidZ&&('画面人物是'+sidZ)));
    const TL=has('fr')?timeline(d,+((P&&P.dur)||8)):null;
    if(TL&&TL.length>1){const SW2=M.form==='other'?{e:x=>x.replace(/\bthe animal\b/i,'it'),z:x=>x.replace(/^动物/,'它')}:{e:x=>x,z:x=>x};const xs=[[aE.replace(/[.。]+$/,''),aZ.replace(/[。.]+$/,'')]].concat((d.segs||[]).map(sg=>[SW2.e(actionText(sg,'en',who,AL)).replace(/[.。]+$/,''),SW2.z(actionText(sg,'zh',who,AL)).replace(/[。.]+$/,'')]));
      const pe=[],pz=[];xs.forEach(([e,z],i)=>{const r=TL[i];if(!r)return;const t=fmtS(r.a)+'–'+fmtS(r.b);if(e)pe.push((i?'then '+t+'s: '+lowerFirst(e):t+'s: '+e));if(z)pz.push((i?'然后 ':'')+t+' 秒：'+z)});
      push(sEn(pe.join('; ')),sZh(pz.join('；')))}
    else push(sEn(aE),sZh(aZ));
    push(sEn(CS('env','en')),sZh(CS('env','zh')));
    camDepth(sel('camera','en'),sel('camera','zh'));
    if(has('fr')){const ks=(d.keys||[]).filter(k=>pick(k,'en')||pick(k,'zh')).slice().sort((a,b)=>(+a.t)-(+b.t));
      if(ks.length)push(sEn('Keyframes: '+ks.map(k=>'at '+fmtS(+k.t)+'s, '+lowerFirst(pick(k,'en').replace(/[.。]+$/,''))).join('; ')),sZh('关键帧：'+ks.map(k=>fmtS(+k.t)+' 秒处，'+pick(k,'zh').replace(/[。.]+$/,'')).join('；')));
      if(d.endf&&d.endf.on&&!d.loop){const e=pick(d.endf,'en').replace(/[.。]+$/,''),z=pick(d.endf,'zh').replace(/[。.]+$/,'');push(sEn('End on the fixed last frame'+(e?': '+lowerFirst(e):'')),sZh('结尾落在固定尾帧'+(z?'：'+z:'')))}}
    presLock('Preserve','throughout');
    push(soundSent(d.sound,'en',who),soundSent(d.sound,'zh',who));
  }else if(bm==='t2v'){
    const fr=sel('framing','en'),frz=sel('framing','zh');
    const first=leadOf(mode,d,'en'),firstz=leadOf(mode,d,'zh');
    const an=sel('angle','en'),anz=sel('angle','zh');
    push(sEn(cj([fr&&first?fr+' of '+lowerFirst(first):(fr||first),an,sel('lens','en'),sty('en'),CS('set','en'),CS('light','en')])),sZh([frz&&firstz?frz+'，'+firstz:(frz||firstz),anz,sel('lens','zh'),sty('zh'),CS('set','zh'),CS('light','zh')].filter(Boolean).join('，')));
    const w=byK('who',who)||KB.who[0];const bE=[],bZ=[];
    if(has('beats'))(d.beats||[]).forEach(b=>{const e=selVal({opts:'actions'},b,'en',who),z=selVal({opts:'actions'},b,'zh',who);if(e)bE.push(e);if(z)bZ.push(z)});
    if(has('action')){const AL=fd('action').list;const e=actionText(d.action,'en',who,AL),z=actionText(d.action,'zh',who,AL);if(e)bE.push(e);if(z)bZ.push(z)}
    if(has('exprCh')){const e=exprText(d.exprCh,'en',who),z=exprText(d.exprCh,'zh',who);if(e)bE.push(e);if(z)bZ.push(z)}
    if(has('motion')){const it=checksVal(fd('motion'),d.motion,'en'),iz=checksVal(fd('motion'),d.motion,'zh');if(it.length)push(sEn(cj(it)),'');if(iz.length)push('',sZh(iz.join('，')))}
    if(bE.length){const rest=bE.slice(1).map(x=>{x=trim(x);return lowerFirst(x.startsWith(w.en+' ')?x.slice(w.en.length+1):x)});push(sEn([bE[0]].concat(rest).join(', then ')),'')}
    if(bZ.length){const rest=bZ.slice(1).map(x=>x.startsWith(w.zh)&&x[w.zh.length]!=='的'?x.slice(w.zh.length):x);push('',sZh([bZ[0]].concat(rest).join('，然后')))}
    const cam=sel('camera','en'),camz=sel('camera','zh');
    camDepth(cam?cam+(d.throughout?' throughout the clip':''):'',camz?camz+(d.throughout?'，贯穿全片':''):'');
    if(has('continuity')){const p=checksVal(fd('continuity'),d.continuity,'en'),pz=checksVal(fd('continuity'),d.continuity,'zh');const [a,b]=lock(p.length?joinList(p,'en'):'',pz.join('、'));push(a,b)}
    if(has('preserve')){const pz=checksVal(fd('preserve'),d.preserve,'zh');push(presEn(fd('preserve'),d.preserve,'Preserve','throughout'),pz.length?`全程保持${pz.join('、')}完全不变。`:'')}
    push(soundSent(d.sound,'en',who),soundSent(d.sound,'zh',who));
  }else if(mode==='ref'){
    push(sEn(pick(d.scene,'en')),sZh(pick(d.scene,'zh')));
    push(sEn(sty('en')),sZh(sty('zh')));
    camDepth(sel('camera','en'),sel('camera','zh'));
    push(soundSent(d.sound,'en','she'),soundSent(d.sound,'zh','she'));
  }
  return {en:out.en.join(' ').replace(/\s+/g,' ').trim(),zh:out.zh.join('').trim()};
}

function scan(text,re){re.lastIndex=0;const s=new Map();let m;while((m=re.exec(text))){const k=m[0].toLowerCase();if(!s.has(k))s.set(k,m[0]);if(m[0]==='')re.lastIndex++}return [...s.values()]}
const SPICY_RX={
  real:/\b(look-?alikes?|resembl\w+|looks? (just )?like|celebrity|celebrities|famous|real person|real people|actual photo|real photo|influencer|idol)\b|长得像|酷似|神似|撞脸|明星|名人|网红|真人照片|真实人物|偶像/i,
  young:/\b(chibi|kawaii|moe|loli\w*|shota\w*|petite|childlike|child-like|baby[- ]?face\w*|doll-?like|school ?girls?|school uniform|magical girl|super[- ]deformed|sd style)\b|萌系|萌妹|软萌|Q版|幼态|娃娃脸|童颜|萝莉|正太|学园|学生|魔法少女|三头身|二头身|小只|迷你身材/i,
  act:/\b(sex|sexual intercourse|intercourse|oral|penetrat\w*|masturbat\w*|orgasm\w*|genitals?|genitalia|porn\w*|explicit sex)\b|性交|做爱|口交|自慰|高潮|性器官|生殖器|色情片|性行为/i,
  nonc:/\b(asleep|sleeping|unconscious|passed out|drunk|drugged|intoxicated|against (her|his|their) will|reluctant|unwilling|struggling|forced|coerced|secretly)\b|睡着|熟睡|昏迷|醉酒|喝醉|迷晕|下药|被迫|不情愿|挣扎|强迫|胁迫|偷偷/i
};
/* 硬性检查（零容忍）。spicy=true 时更严格：年龄模糊、真实人物暗示、非同意暗示一律拦截 */
function hardCheck(all,spicy){const L=[];const add=(t,m,f)=>L.push({level:'block',title:t,msg:m,fix:f});
  for(const r of LEX.hard){const hits=scan(all,r.re);if(hits.length)add('硬性禁用词（'+r.cat+'）',hits.join('、'),'按手册属于零容忍内容，请删除相关内容。本工具不提供此类内容的改写，也不会帮助绕过平台限制。')}
  if(LEX.person.test(all)||spicy){const ages=[...all.matchAll(/\b(\d{1,2})[- ]year[- ]old\b|(\d{1,2})\s*岁/gi)].map(m=>+(m[1]||m[2])).filter(n=>n<18);const u=[...new Set(ages)];
    if(u.length)add('未成年年龄','检测到人物年龄 '+u.join('、')+' 岁','涉及未成年人的内容按手册零容忍，请删除。')}
  if(LEX.sexual.test(all)&&LEX.ageAmbig.test(all))add('年龄模糊词与性化词同时出现','属于零容忍风险组合','请删除该组合内容。');
  if(spicy){const a=all.match(LEX.ageAmbig);if(a&&!(LEX.sexual.test(all)))add('辣椒模式：年龄模糊',a[0],'辣椒模式只允许明确的虚构成年角色，请删除年龄模糊的写法');
    const r=all.match(SPICY_RX.real);if(r)add('辣椒模式：真实人物暗示',r[0],'辣椒模式不允许真实人物、明星或“长得像某人”的描述；只写虚构角色的可见特征');
    const n=all.match(SPICY_RX.nonc);if(n)add('辣椒模式：非同意暗示',n[0],'按手册零容忍：不允许任何非同意、失去意识或被迫的情境')
    const y=all.match(SPICY_RX.young);if(y)add('辣椒模式：幼态化 / 年龄模糊风格',y[0],'辣椒模式只允许明确成年的角色设定；不允许 Q版、萌系、幼态、校园等写法')
    const x=all.match(SPICY_RX.act);if(x)add('辣椒模式：露骨性行为 / 性器官描述',x[0],'本工具只支持服装状态 + 姿态 + 光线层面的成人向描述，不支持露骨性行为或性器官描述')}
  return L}
function has2(M,id){return M.fields.some(f=>f.id===id)}
function lint(mode,d,out,ctx){
  ctx=ctx||{};const L=[];const all=out.en+'\n'+out.zh;const M=MODES[mode];const bm=baseOf(mode);const spicy=!!(M.spicy||ctx.spicy);
  const add=(level,title,msg,fix)=>L.push({level,title,msg,fix});
  hardCheck(all,spicy).forEach(x=>L.push(x));
  if(M.spicy){for(const f of M.fields){if(f.type!=='struct')continue;const D=STRUCT[f.struct];const n=d[f.id]||{};for(const pt of D.parts)if(pt.req&&!(n.parts||{})[pt.id])add('block','辣椒模式：未选择明确的成年年龄','「'+f.label+'」的「'+pt.label.replace(/（.*）/,'')+'」必须选择','辣椒模式只适用于明确的虚构成年角色：在下拉中选择具体成年年龄（如 25岁、30多岁）')}}
  for(const r of LEX.risky){const hits=scan(all,r.re);if(hits.length)add('warn','易触发词（'+r.cat+'）',hits.join('、'),'建议：'+r.fix)}
  if(LEX.sexual.test(all)&&LEX.person.test(all)&&!LEX.adult.test(all))add('warn','未写明成年','涉及人物的成人向描述必须明确是虚构成年角色','写明 “fictional adult” 或具体年龄（如 in her late 20s）');
  if(spicy&&LEX.person.test(all)&&!LEX.adult.test(all))add('warn','辣椒模式：未写明虚构成年','辣椒模式仅适用于明确的虚构成年角色','在主体中写 “fictional adult woman/man” 或具体年龄');
  for(const r of LEX.weak){const hits=scan(all,r.re);if(hits.length)add('tip','低效词：'+hits.join('、'),r.why,'推荐：'+r.fix)}
  const negs=(out.en.match(/\b(no|not|without|don't|never)\b/gi)||[]).length;
  if(negs>=3)add('tip','负面描述偏多（'+negs+' 处）','长负面列表容易被忽略','正向描述想看到的内容；图生类用 Keep / Preserve 列表');
  for(const f of M.fields){if(!f.req)continue;let empty=false;const v=d[f.id];
    if(f.type==='text2')empty=!pick(v,'en');else if(f.type==='struct')empty=!structHas(v);else if(f.type==='select'||f.type==='action'||f.type==='combo')empty=!v||!v.v||(Array.isArray(v.v)&&!v.v.length)||(v.v==='_custom'&&!pick(v,'en'));
    if(empty)add('warn','缺少必填项：'+f.label,'',f.hint||'')}
  const firstField=pick(d.subject||d.first,'en');
  if(bm!=='ref'){for(const f of M.fields){if(f.type!=='struct')continue;const D=STRUCT[f.struct];const n=d[f.id];if(!n)continue;
    for(const p of D.parts){if(p.kind==='many'&&p.max&&Array.isArray(n.parts[p.id])&&n.parts[p.id].length>p.max)add('warn',f.label+' · '+p.label.replace(/（.*）/,'')+' 选了 '+n.parts[p.id].length+' 项','超过建议上限 '+p.max,'删减到 '+p.max+' 项以内')}}}
  if(bm==='i2i'&&d.change&&d.change.parts&&d.change.parts.target&&!d.change.parts.to&&d.change.parts.target!=='add')add('warn','改动目标未选择','已选「改动对象」但没选「改成」','在「改成」中下拉选择或添加自定义');
  if(trim(firstField)&&LEX.mood.test(trim(firstField)))add('warn','主体不在最前','主体句以氛围/质量词开头','把可拍摄的主体提到第一句最前面，如 “A fictional adult woman in a white shirt…”');
  else if(LEX.mood.test(out.en))add('warn','主体不在最前','提示词以氛围/质量词开头','第一句应是可拍摄的主体描述');
  if(M.video){
    const cams=LEX.camTerms.filter(([n,re])=>re.test(out.en)).map(([n])=>n);
    const isStatic=/static|locked shot|no camera movement/i.test(out.en);
    if(cams.length>1)add('warn','多个机位运动：'+cams.join(' + '),'一条提示只写一个机位','只保留一个，如 Slow push-in 或 Static locked shot');
    else if(cams.length===1&&isStatic)add('warn','机位冲突','同时写了静止机位与 '+cams[0],'二选一');
    else if(!cams.length&&!isStatic&&!/low angle|high angle|over-the-shoulder/i.test(out.en))add('warn','未指定机位','容易机位乱晃','加上 Static locked shot 或一个明确机位');
    if(has2(M,'fr')&&d.tl&&(d.segs||[]).length){}
    else if(M.fields.some(f=>f.id==='beats')){const n=(d.beats||[]).filter(b=>b.v&&(b.v!=='_custom'||pick(b,'en'))).length;
      if(n>3)add('warn','动作节拍过多（'+n+'）','节拍越多越不稳定','保留 1–2 个最重要的节拍');
      if(!n)add('warn','缺少动作','文生视频需要至少一个动作节拍','从下拉中选一个动作');}
    else{const vs=new Set(scan(out.en,LEX.mainVerbs).map(v=>v.toLowerCase().replace(/ .*/,'').replace(/s$/,'')));
      if(vs.size>=3)add('warn','多个动作叠加（'+[...vs].join(', ')+'）','手册：一次一个主要动作','只保留最重要的一个，如 She slowly turns her head toward the camera.');
      else if(vs.size===2)add('tip','包含两个动作（'+[...vs].join(', ')+'）','手册推荐一个主要动作','如不稳定，先只保留一个')}
  }
  const keepAny=d.keep&&Object.values(d.keep.m||{}).includes('keep');
  if(bm==='i2i'||bm==='i2v'){const p=d.preserve;if(!keepAny&&(!p||(!(p.v||[]).length&&!pick(p,'en'))))add('warn','未写保留列表','未写保留容易导致漂移（脸、背景等）','勾选要保留的部分，越具体越好')}
  const chS=bm==='i2i'?M.fields.find(f=>f.id==='change').struct:'change';
  if(bm==='i2i'&&d.preserve&&(d.preserve.v||[]).includes('bg')&&/background|背景/i.test(composeStruct(chS,d.change,'en')+composeStruct(chS,d.change,'zh')))add('warn','保留与修改冲突','要修改背景，但保留列表也勾了「背景」','取消勾选「背景」');
  if(bm==='i2v'&&d.env&&has2(M,'env')&&/\b(add|adds|new|appears?)\b/i.test(composeStruct(M.fields.find(f=>f.id==='env').struct,d.env,'en')))add('tip','环境响应可能在发明新物体','手册：不要发明新物体','只写已有元素的变化（雨、光、头发、蒸汽）');
  if(['t2i','t2v','i2v'].includes(bm)&&LEX.person.test(out.en)&&!/depth of field|foreground|layered|haze|atmospheric|blur|reflections?|defocus|soft background/i.test(out.en))add('tip','人物类缺少纵深','画面可能扁平','在「纵深」中加浅景深或前景元素');
  const sentences=(out.en.match(/[^.!?]+[.!?]+/g)||[]).filter(x=>x.trim().split(/\s+/).length>=3).length;
  if(sentences>5)add('warn','提示过长（'+sentences+' 句）','手册建议 2–5 句，重点在前','先用短版生成，再逐步加细节');
  if(out.en.length>900)add('tip','字符较多（'+out.en.length+'）','超长段落容易不稳定','删掉次要描述');
  if(/[\u4e00-\u9fff]/.test(out.en.replace(/"[^"]*"/g,'')))add('tip','英文提示词中还有中文','离线词表没能翻译全部内容','点「翻译成英文」用 EVA 模型翻译，或直接编辑英文（英文通常更稳定，未核实）');
  if(mode==='ref'){const ff=!!d.firstFrame;const refs=d.refs||[];const n=refs.length;
    const used=new Set([...all.matchAll(/<IMAGE_(\d+)>/g)].map(m=>+m[1]));const valid=new Set(refs.map((r,i)=>i+(ff?1:0)));
    for(const u of used){if(!valid.has(u))add('warn','引用不存在的 <IMAGE_'+u+'>',ff&&u===0?'<IMAGE_0> 被首帧占用，参考图从 <IMAGE_1> 开始':'超出参考图列表范围','按列表顺序'+(ff?'从 <IMAGE_1>':'从 <IMAGE_0>')+' 开始编号')}
    refs.forEach((r,i)=>{const t=i+(ff?1:0);if(!used.has(t))add('tip','参考图 <IMAGE_'+t+'> 未在描述中引用','','在描述中写明它承担的角色，如 “the shirt from <IMAGE_'+t+'>”')});
    if(n>14)add('warn','参考图超过 14 张','grok-imagine-video-1.5 最多 14 张','删减参考图');
    else if(n>7&&ctx.model==='old')add('warn','参考图超过 7 张','旧版 grok-imagine-video 最多 7 张','换用 1.5 或删减');
    if(refs.filter(r=>r.role==='char').length>3)add('tip','角色较多','手册：角色数量保持少','控制在 1–3 个角色');
    if(!n)add('warn','没有参考图','参考图生视频至少需要 1 张参考图','添加参考图');}
  if(d.who&&d.who.v){const txt=bm==='t2v'?leadOf(mode,d,'en',true):(d.sid?composeLead(d.sid,null,'en',STRUCT.sid):'');const male=/\b(man|men|boy|he|his|him|gentleman|guy)\b/i.test(txt),female=/\b(woman|women|girl|she|her|lady)\b/i.test(txt);
    if(d.who.v==='she'&&male&&!female)add('warn','称呼与主体不一致','人物写的是男性，主体称呼却是「她」','把「动作主体称呼」改为「他」');
    if(d.who.v==='he'&&female&&!male)add('warn','称呼与主体不一致','人物写的是女性，主体称呼却是「他」','把「动作主体称呼」改为「她」');}
  for(const f of M.fields){if(f.type==='checks'&&f.max&&d[f.id]&&(d[f.id].v||[]).length>f.max)add('warn',f.label.replace(/（.*）/,'')+'选了 '+d[f.id].v.length+' 项','手册建议纵深技巧精选 1–2 个，叠加过多会互相冲突','只保留最重要的 '+f.max+' 项')}
  if(M.video&&ctx.params){const P=ctx.params;
    if(mode==='ref'&&!capOf(P.model).ref)add('warn','模型与模式冲突',CAP_MODEL[P.model]+' 不支持参考图生视频','改用支持参考图的模型（如 grok-imagine-video-1.5）');
    if(P.res==='1080'&&(mode==='ref'||P.model==='old'))add('warn','分辨率超出上限',mode==='ref'?'参考图生视频输出最高 720p':'旧版最高 720p','改为 720p 或 480p');
    if(mode==='ref'&&P.model==='old'&&+P.dur>10)add('warn','时长超出上限','旧版参考图生视频最长 10 秒','把时长调到 10 秒以内');}
  if(M.spicy&&d.sound&&d.sound.v==='dlg'){const q=pick(d.sound,'en');if(q.split(/\s+/).length>12||trim(d.sound.zh).length>20)add('warn','辣椒模式：对白过长','手册：对白放引号、短句','缩短到一句短句（约 12 个英文词以内）')}
  if(M.spicy&&M.video&&d.camera&&d.camera.v==='_custom'&&!/static|locked|push-in|orbit|low angle|close-up/i.test(selVal({list:'spCam'},d.camera,'en')))add('warn','辣椒模式：镜头运动偏大','手册：一个机位、慢速','改为缓慢推进、缓慢环绕、低角度或近景特写');
  if(M.spicy&&bm==='t2v'&&has2(M,'action')&&d.action&&d.action.v==='_custom'){const vs=new Set(scan(pick(d.action,'en'),LEX.mainVerbs).map(v=>v.toLowerCase()));if(vs.size>=2)add('warn','辣椒模式：动作过多','一次一个主要动作，优先静态或微动','只保留一个微动作')}
  if(d.sound&&d.sound.v==='dlg'&&!pick(d.sound,'en'))add('tip','对白为空','已选择对白但没填内容','对白放引号内，短句效果更好');
  /* v8：图生图「保持 / 修改」 */
  if(has2(M,'keep')&&d.keep){const m=d.keep.m||{};const f=M.fields.find(x=>x.id==='keep');
    const AL=aspList(f,d);for(const a of ASPECTS){if(!AL.includes(a.k))continue;if(m[a.k]==='chg'){const c=(d.keepch||{})[a.k];if(!pick(c,'en')&&!pick(c,'zh'))add('warn','「'+ASP_SHORT[a.k]+'」选了修改但没写改成什么','','在该项下写明要改成什么，或改为「保持」')}}
    const tg=d.change&&d.change.parts&&d.change.parts.target;const ca=CHG_ASP[tg];if(ca&&m[ca]==='keep'&&AL.includes(ca))add('warn','保持与修改冲突','「要改什么」改的是'+ASP_SHORT[ca]+'，但对照项里「'+ASP_SHORT[ca]+'」选了保持','把「'+ASP_SHORT[ca]+'」改为「修改」或不指定');
    const nc=Object.values(m).filter(v=>v==='chg').length+(structHas(d.change)?1:0);if(nc>1)add('tip','同时修改 '+nc+' 处','手册：图生图一次只改一处更稳','分几次编辑，每次改一处')}
  /* v8：图生视频帧与时间轴 */
  if(has2(M,'fr')){const dur=+((ctx.params&&ctx.params.dur)||8);
    if(d.tl){const segs=[+d.seg1].concat((d.segs||[]).map(x=>+x.b));let prev=0;const n=1+(d.segs||[]).length;
      segs.slice(0,-1).forEach((b,i)=>{if(!(b>prev)||!(b<dur))add('warn','时间轴第 '+(i+1)+' 段结束时间不合理','应在 '+fmtS(prev)+'–'+dur+' 秒之间且递增','调整该段的结束秒数（总时长 '+dur+' 秒）');prev=b});
      if(n>3)add('warn','时间轴段数过多（'+n+'）','与文生视频节拍一致：最多 3 段，越多越不稳定','保留 1–2 段最重要的动作');
      (d.segs||[]).forEach((sg,i)=>{if(!sg.v||(sg.v==='_custom'&&!pick(sg,'en')))add('warn','时间轴第 '+(i+2)+' 段没有动作','','选择一个动作或删除该段')});
      if(n<2)add('tip','时间轴只有 1 段','只有一段时与不开时间轴相同','点「+ 添加一段」加入 then 动作')}
    const ks=d.keys||[];if(ks.length>4)add('warn','中间关键帧超过 4 个','grok-imagine-video-1.5 最多 4 个中间关键帧','删减关键帧');
    ks.forEach((k,i)=>{if(!(+k.t>0&&+k.t<dur))add('warn','关键帧 '+(i+1)+' 的时间点超出范围','时间点应在 0–'+dur+' 秒之间（不含首尾）','调整秒数')});
    if((ks.length||(d.endf&&d.endf.on))&&ctx.params&&ctx.params.model!=='v15')add('warn','当前模型不支持固定帧','固定尾帧 / 中间关键帧仅 grok-imagine-video-1.5 支持','把模型切到 grok-imagine-video-1.5，或去掉尾帧 / 关键帧');
    if(d.loop&&d.endf&&d.endf.on)add('tip','循环与固定尾帧冲突','无缝循环会把首帧同时设为尾帧，已忽略自定义尾帧','二选一')}
  /* v8：图片识别结果的安全提示（不识别身份，只看风险标记） */
  if(ctx.vis&&(ctx.vis.minor||ctx.vis.real)){const why=[ctx.vis.minor?'可能含未成年人':'',ctx.vis.real?'可能是真实可识别的公众人物':''].filter(Boolean).join('、');
    if(spicy)add('block','辣椒模式不可用：上传的图片'+why,'辣椒模式只适用于明确的虚构成年角色；按手册零容忍规则，已禁用复制与保存','换用虚构成年角色的图片，或关闭辣椒模式');
    else add('tip','图片识别提示：'+why,'该图片不能用于辣椒模式；涉及真实人物时请确认已获授权，不要做性化或冒充','')}
  const hasBlock=L.some(x=>x.level==='block'),hasWarn=L.some(x=>x.level==='warn');
  if(!L.length)add('ok','检查通过','符合检查清单：主体优先、正向描述、单一动作/机位、长度适中','');
  else if(!hasBlock&&!hasWarn)L.unshift({level:'ok',title:'无硬性问题',msg:'只有优化建议',fix:''});
  return L;
}

function capNoteDyn(k,mode){const c=capOf(k);
  if(mode==='ref')return c.ref?`参考图生视频最多${c.ref.max_images}张参考图、最长${c.ref.max_dur}秒、输出最高${c.ref.max_res}p`:'不支持参考图生视频';
  return `文生视频最高 ${c.t2v_max_res}p、图生视频最高 ${c.i2v_max_res}p；时长 1–${c.max_dur} 秒`+(c.frames?'；可固定首帧/尾帧':'')+(c.keyframes?`；最多 ${c.keyframes} 个中间关键帧`:'')+(c.voices?`；预设声音最多 ${c.voices} 个`:'')}
function paramNotes(key,d,P){
  const N=[];const m=KB.models.find(x=>x.k===P.model)||KB.models[0];const mode=baseOf(key);
  if(MODES[key]&&MODES[key].spicy)N.push(['🌶 推荐工作流：先在普通模式锁定干净的静态关键帧，再在辣椒模式做小幅度编辑或动画；被拦截时简化提示、明确虚构、逐步加细节。','']);
  if(CAPS_ACTIVE)N.push(['参数来源：已按 '+new Date((PUPD.updated||0)*1000).toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'})+'（北京时间）手动联网更新的官方文档字段；未取得的字段沿用内置值。','']);
  {const I=capsIssues(key,P,d);if(I.length)N.push(['⚠ 当前选择与参数不符（已保留你的选择，请手动调整）：'+I.join('；'),'w'])}
  if(!MODES[key].video){N.push(['图像生成：多图编辑最多合并 '+CAPS.image.edit_max_images+' 张源图片。','']);N.push(['工作流：先把静态关键帧做到完美，再用短提示做动画。','']);return N}
  const capNote={v15:mode==='ref'?'参考图生视频最多14张参考图、最长15秒、输出最高720p':'文生/图生视频原生最高 1080p；可固定首帧/尾帧及最多4个中间关键帧',lite:'720p 上采样至1080p；不支持参考图、预设声音、固定帧',old:mode==='ref'?'参考图生视频最多7张、最长10秒、720p':'最高720p；支持视频编辑（源视频≤8.7秒）与续写（每次2–10秒）'}[m.k];
  N.push([`${m.name}（${m.pos}）：${CAPS_ACTIVE?capNoteDyn(m.k,mode):capNote}`,'']);
  const C=capOf(P.model),LM=capLim(key,P);
  if(mode==='ref'){
    if(!C.ref)N.push([m.name+' 不支持参考图生视频，请改用支持参考图的模型。','w']);
    if(C.ref&&P.dur>LM.dur)N.push([m.name+' 参考图生视频最长 '+LM.dur+' 秒。','w']);
    if(+P.res>LM.maxRes)N.push(['参考图生视频输出最高 '+LM.maxRes+'p。','w']);
    if(d.firstFrame)N.push(['已设首帧 image：首帧占 <IMAGE_0>，参考图编号从 <IMAGE_1> 开始。','']);
  }
  if(!C.res.includes(P.res))N.push([m.name+' 最高 '+Math.max(...C.res.map(Number))+'p，不支持 '+P.res+'p。','w']);
  if(P.model==='lite'&&P.res==='1080')N.push(['1.5-lite 的 1080p 由 720p 上采样。','']);
  if(mode==='i2v'&&d.loop){if(C.frames)N.push(['API：可把同一张图同时设为首帧 image 与尾帧 last_frame 来做循环（官方文档）。',''])
    else N.push(['固定首尾帧仅 grok-imagine-video-1.5 支持；Grok App 内 loop 功能未核实，可后处理正反播放。','w'])}
  if(mode==='i2v'){N.push(['图生视频：上传的图片就是第 0 帧（首帧，API 参数 image），画幅自动匹配输入图片比例；时长 '+P.dur+' 秒（1–'+LM.dur+'）。','']);
    const nk=(d.keys||[]).length,ne=!!(d.endf&&d.endf.on);
    if(nk||ne){if(C.frames||C.keyframes>0)N.push(['固定帧：'+[ne?'尾帧用 last_frame':'',nk?'中间关键帧 '+nk+' 个（最多 '+keyMax()+' 个，按时间点固定画面）':''].filter(Boolean).join('；')+'。关键帧图建议先用图生图从首帧改出来，只改需要变化的部分。','']);else N.push(['固定尾帧 / 中间关键帧仅 grok-imagine-video-1.5 支持。','w'])}
    if(d.tl){const TL=timeline(d,+P.dur)||[];N.push(['时间轴：'+TL.map(r=>fmtS(r.a)+'–'+fmtS(r.b)+'s').join(' → ')+'（最后一段自动延续到结尾）',''])}}
  if(d.sound&&d.sound.v==='dlg')N.push(['原生音频默认开启（含口型同步）；1.5 可用 voice_id 预设声音，最多 '+capOf('v15').voices+' 个角色。','']);
  const price=capPrice(P.model,P.res);
  if(price!=null)N.push([`API 估算：${P.dur} 秒 × $${price.toFixed(2)}/秒 ≈ $${(P.dur*price).toFixed(2)}（${P.res}p；网页版/App 用订阅额度，另计）。`,'']);
  else N.push([`${m.name} 不支持 ${P.res}p，无法估价。`,'w']);
  if(P.res!=='480')N.push(['API 默认 480p：建议先用 480p 试动作，满意后再指定更高分辨率。','']);
  return N;
}

/* ================= 离线中→英词表（手册术语 + 常用画面词） ================= */
const GLOSS_RAW = `
静止机位=static locked shot|静止锁定机位=static locked shot|镜头不动=no camera movement|固定机位=static locked shot|缓慢推进=slow push-in|缓慢向前推进=slow push-in|推镜头=push-in|缓慢拉远=slow pull-out|拉远=pull-out|拉镜头=pull-out|缓慢左移=gentle pan left|缓慢右移=gentle pan right|左右平移=gentle pan|平移=pan|摇镜头=pan|侧向跟踪=slow tracking shot from the side|跟踪镜头=tracking shot|跟拍=tracking shot|环绕镜头=orbit shot|缓慢环绕=slow orbit|环绕=orbit|手持晃动=handheld sway|轻微手持晃动=subtle handheld sway|手持=handheld|升起俯拍=rising crane shot|升降镜头=crane shot|低角度仰拍=low angle looking up|仰拍=low angle shot|高角度俯拍=high angle looking down|俯拍=high angle shot|过肩镜头=over-the-shoulder shot|地平线锁定=locked horizon|贯穿全片=throughout the clip|全程=throughout
特写=close-up|大特写=extreme close-up|近景=close shot|中景=medium shot|中近景=medium close-up|中远景=medium-wide shot|全景=wide shot|远景=long shot|半身=half-body shot|全身=full-body shot|正面=front view|侧面=side view|背面=back view|四分之三视角=three-quarter view|45度=45-degree|微距=macro|俯视=top-down view|鸟瞰=aerial view|第一人称=first-person view|对称构图=symmetrical composition|居中构图=centered composition|三分法构图=rule-of-thirds composition|留白=negative space|裁切=cropped|画面中央=in the center of the frame|画面左侧=on the left side of the frame|画面右侧=on the right side of the frame
浅景深=shallow depth of field|景深=depth of field|背景虚化=background softly blurred|背景柔和虚化=background softly blurred|背景完全虚化=background completely blurred|前景虚化=blurred foreground|前景=foreground|中景位置=midground|背景=background|分层构图=layered composition|前中后景=foreground, midground and background|大气透视=atmospheric perspective|薄雾=haze|雾气=mist|焦点=focus|焦点在眼睛=eyes in sharp focus|清晰对焦=sharp focus|眼睛清晰=eyes sharp|反射=reflections|倒影=reflections|湿地面=wet pavement|湿地面反射=reflections on wet pavement
自然光=natural light|柔和自然光=soft natural light|柔光=soft light|硬光=hard light|窗光=window light|左侧柔和窗光=soft window light from the left|侧光=side lighting|柔和侧光=soft side lighting|逆光=backlight|轮廓光=rim light|顶光=top light|补光=fill light|柔和补光=soft fill|晨光=morning light|柔和晨光=soft morning light|午后阳光=afternoon sun|夕阳=sunset light|黄昏=dusk|黄金时刻=golden hour|蓝调时刻=blue hour|夜晚=at night|夜景=night scene|月光=moonlight|霓虹灯=neon lights|霓虹=neon|霓虹闪烁=neon-lit|烛光=candlelight|暖光=warm light|冷光=cool light|暖色调=warm tones|冷色调=cool tones|高对比=high contrast|低调光=low-key lighting|高调光=high-key lighting|电影感光线=cinematic lighting|摄影棚=studio|明亮的摄影棚=bright studio|影棚灯光=studio lighting|阴影=shadows|柔和阴影=soft shadows|光斑=bokeh|体积光=volumetric light|丁达尔光=god rays
红色=red|橙色=orange|黄色=yellow|绿色=green|青色=cyan|蓝色=blue|紫色=purple|粉色=pink|白色=white|黑色=black|灰色=grey|棕色=brown|米色=beige|金色=gold|银色=silver|银白色=silver-white|深祖母绿=deep emerald green|祖母绿=emerald green|鼠尾草绿=sage green|琥珀色=amber|深琥珀=dark amber|酒红色=burgundy|藏青色=navy blue|奶油色=cream|浅色=light-colored|深色=dark|哑光=matte|亮面=glossy|半透明=semi-transparent|透明=transparent|全息=holographic|全息蓝光=holographic blue light
陶瓷=ceramic|玻璃=glass|木质=wooden|木桌=wooden table|浅色木桌=pale wooden table|橡木=oak|浅橡木=pale oak|台面=counter|金属=metal|拉丝金属=brushed metal|不锈钢=stainless steel|皮革=leather|棕色皮革=brown leather|亚麻=linen|丝绸=silk|棉质=cotton|羊毛=wool|针织=knit|牛仔=denim|大理石=marble|混凝土=concrete|砖墙=brick wall|白色方砖=white square tile|瓷砖=tile|纸张=paper|塑料=plastic|水珠=water droplets|冷凝水珠=condensation beads|蒸汽=steam|烟雾=smoke|灰尘=dust|微尘=dust motes|花瓣=petals|树叶=leaves
女性=woman|男性=man|女人=woman|男人=man|成年女性=adult woman|成年男性=adult man|虚构成年女性=fictional adult woman|虚构成年男性=fictional adult man|虚构=fictional|成年=adult|东亚=East Asian|亚洲=Asian|欧洲=European|模特=model|数字人=digital human|角色=character|人物=the person|她=she|他=he|他们=they|她的=her|他的=his|一位=a|一个=a|一只=a|一张=a|两个=two|三个=three|20多岁=in her 20s|30多岁=in their 30s|25岁=25-year-old|长发=long hair|短发=short hair|黑色长发=long black hair|卷发=curly hair|马尾=ponytail|刘海=bangs|胡子=beard|眼镜=glasses|微笑=smile|表情=expression|脸=face|脸部=face|眼睛=eyes|嘴唇=lips|头发=hair|发型=hairstyle|手=hand|手部=hands|肩膀=shoulder|身份=identity|骨相=bone structure|发际线=hairline|姿势=pose|服装=clothing
衬衫=shirt|白色衬衫=white shirt|T恤=T-shirt|外套=jacket|夹克=jacket|风衣=trench coat|大衣=coat|西装=suit|连衣裙=dress|裙子=skirt|长裙=long dress|毛衣=sweater|卫衣=hoodie|雨衣=raincoat|红色雨衣=red raincoat|牛仔裤=jeans|裤子=trousers|运动鞋=sneakers|高跟鞋=high heels|靴子=boots|帽子=hat|围巾=scarf|领带=tie|手表=watch|表带=watch strap|项链=necklace|耳环=earrings|背包=backpack|手提包=handbag|雨伞=umbrella|睡袍=robe|薄纱睡袍=sheer robe|科技服装=tech clothing|制服=uniform|和服=kimono|汉服=hanfu|旗袍=qipao
城市=city|街道=street|街头=street|小街=side street|小巷=alley|东京=Tokyo|上海=Shanghai|香港=Hong Kong|雨夜=rainy night|下雨=raining|细雨=light rain|雨=rain|雪=snow|下雪=snowing|雾=fog|起雾=foggy|海边=seaside|海滩=beach|沙滩=beach|大海=sea|海浪=waves|湖边=lakeside|河边=riverside|森林=forest|草地=meadow|花园=garden|山顶=mountaintop|沙漠=desert|码头=pier|天台=rooftop|窗边=by a window|窗户=window|窗帘=curtains|房间=room|卧室=bedroom|客厅=living room|厨房=kitchen|咖啡馆=café|餐厅=restaurant|办公室=office|走廊=hallway|门框=door frame|楼梯=stairs|地铁=subway|车站=station|车内=inside a car|书店=bookstore|图书馆=library|教室=classroom|舞台=stage|赛博朋克=cyberpunk|未来感=futuristic|复古=vintage|极简=minimalist|奢华=luxurious|温馨=cozy|安静=quiet|宁静=serene|热闹=bustling
坐在=sitting|坐=sits|站在=standing|站着=standing|站=stands|走=walks|行走=walking|缓慢行走=walks slowly|走向镜头=walks toward the camera|缓慢走向镜头=walks slowly toward the camera|跑=runs|奔跑=running|跳舞=dancing|转身=turns around|转头=turns her head|缓慢转头=slowly turns her head|看向镜头=looks at the camera|看着镜头=looks at the camera|回头=looks back|回头看=looks back over her shoulder|低头=lowers her gaze|抬头=looks up|眨眼=blinks|偶尔眨眼=blinks occasionally|呼吸=breathes|自然呼吸=breathes naturally|轻轻呼吸=breathes gently|胸腔起伏=chest rising and falling|胸腔轻微起伏=chest rising and falling gently|挥手=waves|轻轻挥手=waves gently|抬手=raises her hand|点头=nods|轻轻微笑=smiles gently|缓慢微笑=slowly smiles|笑=laughs|看书=reading a book|读书=reading|喝咖啡=drinking coffee|拿着=holding|手持=holding|撑伞=holding an umbrella|撑起雨伞=opens an umbrella|整理头发=tucks her hair|把头发别到耳后=tucks her hair behind her ear|起身=stands up|缓慢起身=slowly stands up|坐下=sits down|伸手=reaches out|拥抱=hugs|摆动=sways|轻微摆动=slightly swaying|头发轻微摆动=hair slightly swaying|飘动=drifts|飘落=falls|落下=falls|滑下=slide down|缓慢滑下=slowly slide down|荡漾=ripple|流动=flows|闪烁=flickers|旋转=rotates|缓慢旋转=slowly rotates|微动=micro-movements|轻微头部微动=subtle head micro-movements|无缝循环=seamless loop|首尾帧一致=first frame matches last frame
缓慢=slowly|缓缓=slowly|轻轻=gently|轻微=subtle|慢慢=slowly|快速=quickly|突然=suddenly|然后=then|同时=while|并且=and|和=and|与=and|或=or|在=in|上=on|下=under|里=in|旁边=next to|前面=in front of|后面=behind|左侧=on the left|右侧=on the right|远处=in the distance|附近=nearby|周围=around|中间=in the middle|朝向=toward|看向=looks toward|穿着=wearing|穿=wearing|戴着=wearing|带着=with|拿=holding|放在=placed on|位于=located|只把=change only the|只改=change only|改成=to|换成=with|替换为=replace with|保留=keep|保持=keep|完全不变=exactly the same|不变=unchanged|添加=add|一个小=a small|匹配=match|自然=natural|干净轮廓=clean silhouette|轮廓=silhouette|产品摄影=product photography|微距产品摄影=macro product photography|肖像=portrait|自拍=selfie|照片=photo|电影=cinematic|纪录片=documentary|胶片感=film look|写实=photorealistic|插画=illustration|水彩=watercolor|油画=oil painting|动漫=anime|3D渲染=3D render
声音=sound|环境音=ambient sound|房间底噪=room tone|车流声=traffic noise|远处车流声=distant traffic|雨声=rain sounds|细雨声=soft rain|风声=wind|鸟鸣=birdsong|海浪声=sound of waves|音乐=music|轻音乐=soft music|钢琴=piano|无对白=no dialogue|说=says|欢迎回来=Welcome back|你好=Hello|谢谢=Thank you
缓慢转头看向镜头=slowly turns her head toward the camera|转向镜头=turns toward the camera|缓慢转向镜头=slowly turns toward the camera|穿上=wears|戴=wearing|草帽=straw hat|老=old|老人=elderly person|渔夫=fisherman|渔网=fishing net|补渔网=mending a fishing net|厨师=chef|医生=doctor|老师=teacher|学者=scholar|士兵=soldier|骑士=knight|机器人=robot|宇航员=astronaut|舞者=dancer|歌手=singer|女孩=young woman|男孩=young man|耳机=earbuds|无线耳机=wireless earbuds|无线耳机盒=wireless earbud case|耳机盒=earbud case|手机=phone|笔记本电脑=laptop|相机=camera|手冲滤杯=pour-over dripper|分享壶=carafe|咖啡=coffee|咖啡杯=coffee cup|茶杯=teacup|杯子=cup|杯身=glass|瓶子=bottle|瓶身=bottle|瓶身形状=bottle shape|标签=label|瓶内液体=liquid inside the bottle|液体=liquid|液体颜色=liquid color|香水=perfume|口红=lipstick|蛋糕=cake|松饼=pancakes|盘子=plate|花=flowers|花瓶=vase|蜡烛=candle|书=book|猫=cat|狗=dog|汽车=car|自行车=bicycle|毛巾=towel|亚麻毛巾=linen towel|价格牌=price tag|木质价格牌=wooden price tag|原图一切细节=every detail of the original photo|街道几何结构=the street geometry
`;
const GLOSS=(()=>{const m=new Map();for(const p of GLOSS_RAW.split(/[|\n]/)){const i=p.indexOf('=');if(i>0)m.set(p.slice(0,i).trim(),p.slice(i+1).trim())}return m})();
function glossAdd(zh,en){zh=trim(zh);en=trim(en);if(zh&&en&&!GLOSS.has(zh))GLOSS.set(zh,en)}
const GLOSS_DROP=new Set(['的','了','着','地','得','是','把','被','将','让','很','非常','十分','一些','这','那']);
let GLOSS_MAXLEN=0;
/* 返回 {text, missing[]}：最长匹配；未命中的中文保留并记入 missing */
function glossTranslate(zh){
  zh=trim(zh);if(!zh)return {text:'',missing:[]};
  if(GLOSS.has(zh))return {text:GLOSS.get(zh),missing:[]};
  zh=zh.replace(/(<IMAGE_\d+>)\s*(?:中的|里的|的)\s*/g,(m,tag,off,str)=>{
         if(!GLOSS_MAXLEN)for(const k of GLOSS.keys())GLOSS_MAXLEN=Math.max(GLOSS_MAXLEN,k.length);
         const rest=str.slice(off+m.length);for(let L=Math.min(GLOSS_MAXLEN,rest.length);L>=1;L--){const w=rest.slice(0,L);if(GLOSS.has(w))return '\u0001'+tag+'\u0002'+L+'\u0003'}
         return tag+' ';})
       .replace(/\u0001(<IMAGE_\d+>)\u0002(\d+)\u0003/g,(m,tag,L,off,str)=>m) ;
  zh=zh.replace(/\u0001(<IMAGE_\d+>)\u0002(\d+)\u0003/g,(m,tag,L,off,str)=>{const w=str.slice(off+m.length,off+m.length+(+L));return ' the '+w+' from '+tag+' \u0004'+L+'\u0005'});
  zh=zh.replace(/\u0004(\d+)\u0005/g,(m,L,off,str)=>m);
  { // 删除已移到前面的名词
    let out='';let i=0;while(i<zh.length){const m=zh.slice(i).match(/^\u0004(\d+)\u0005/);if(m){i+=m[0].length+(+m[1]);continue}out+=zh[i];i++}zh=out;}
  zh=zh.replace(/(\d{2})多岁/g,' $1-something ').replace(/(\d{1,3})\s*岁/g,' $1-year-old ')
       .replace(/(放在|在|位于)([^，。、]{1,12}?)上(?=[，。、]|$)/g,'$1$2');
  if(!GLOSS_MAXLEN)for(const k of GLOSS.keys())GLOSS_MAXLEN=Math.max(GLOSS_MAXLEN,k.length);
  const out=[];const missing=[];let i=0;let miss='';
  const flush=()=>{if(miss){missing.push(miss);out.push(miss);miss=''}};
  const punct={'，':', ','、':', ','。':'. ','；':'; ','：':': ','！':'! ','？':'? ','（':' (','）':') ','“':'"','”':'"','‘':"'",'’':"'",'「':'"','」':'"'};
  while(i<zh.length){
    const ch=zh[i];
    if(punct[ch]){flush();out.push(punct[ch]);i++;continue}
    if(!/[\u4e00-\u9fff]/.test(ch)){flush();let j=i;while(j<zh.length&&!/[\u4e00-\u9fff]/.test(zh[j])&&!punct[zh[j]])j++;out.push(' '+zh.slice(i,j)+' ');i=j;continue}
    let hit='';for(let L=Math.min(GLOSS_MAXLEN,zh.length-i);L>=1;L--){const s=zh.substr(i,L);if(GLOSS.has(s)){hit=s;break}}
    if(hit){flush();out.push(' '+GLOSS.get(hit)+' ');i+=hit.length;continue}
    let dropped=false;for(const d of ['非常','十分','一些','的','了','着','地','得','是','把','被','将','让','很','这','那']){if(zh.startsWith(d,i)){flush();i+=d.length;dropped=true;break}}
    if(dropped)continue;
    miss+=ch;i++;
  }
  flush();
  let text=out.join('').replace(/\s+/g,' ').replace(/\s+([,.;:!?)])/g,'$1').replace(/\(\s+/g,'(').replace(/\b(a) (a|an)\b/gi,'$1').trim();
  text=text.replace(/\ba ([aeiou])/gi,'an $1');
  return {text,missing};
}

/* ================= v95 参数能力层 =================
   CAPS_BUILTIN = 与内置手册一致的默认参数；手动「联网更新参数」后，EVA 后端从固定白名单的 docs.x.ai 页面
   用确定性表格解析取得字段，前端再次按白名单/取值范围校验后逐字段覆盖。页面内容只当数据，不执行、不写源码。
   本工具不调用生成接口：这些只用于参数提示、可选项与范围。 */
const CAP_RES=['480','720','1080'];
const CAPS_BUILTIN={video:{
  v15:{max_dur:15,res:['480','720','1080'],t2v_max_res:'1080',i2v_max_res:'1080',ref:{max_images:14,max_dur:15,max_res:'720'},keyframes:4,frames:true,voices:3,ratios:KB.ratios.slice(),i2v_ratio_auto:true,price:{480:0.08,720:0.14,1080:0.25}},
  lite:{max_dur:15,res:['480','720','1080'],t2v_max_res:'1080',i2v_max_res:'1080',ref:null,keyframes:0,frames:false,voices:0,ratios:KB.ratios.slice(),i2v_ratio_auto:true,price:{480:0.02,720:0.03,1080:0.14}},
  old:{max_dur:15,res:['480','720'],t2v_max_res:'720',i2v_max_res:'720',ref:{max_images:7,max_dur:10,max_res:'720'},keyframes:0,frames:false,voices:0,ratios:KB.ratios.slice(),i2v_ratio_auto:true,price:{480:0.05,720:0.07,1080:null}}},
  ref_max_res:'720',
  image:{ratios:KB.ratios.slice(),edit_max_images:5,resolutions:null}};
const CAP_RATIO_RE=/^(\d{1,2}(?:\.\d)?):(\d{1,2}(?:\.\d)?)$/;
const CAP_VFIELDS=['max_dur','res','ratios','t2v_max_res','i2v_max_res','i2v_ratio_auto','ref','keyframes','frames','voices','price'];
const CAP_LABEL={max_dur:'最长时长',res:'可选分辨率',ratios:'画幅比例',t2v_max_res:'文生视频最高分辨率',i2v_max_res:'图生视频最高分辨率',i2v_ratio_auto:'图生视频画幅跟随首帧',ref:'参考图生视频（张数/时长/分辨率）',keyframes:'中间关键帧上限',frames:'固定首帧/尾帧',voices:'预设声音上限',price:'每秒单价（USD）'};
const CAP_MODEL={v15:'grok-imagine-video-1.5',lite:'grok-imagine-video-1.5-lite',old:'grok-imagine-video'};
function capInt(v,a,b){return typeof v==='number'&&Number.isInteger(v)&&v>=a&&v<=b}
/* 与后端 _valid_field 同一白名单；未知字段一律忽略 */
function capValid(key,v){const p=String(key).split('.');
  if(key==='image.ratios')return Array.isArray(v)&&v.length>=1&&v.length<=24&&v.every(x=>typeof x==='string'&&(x==='auto'||CAP_RATIO_RE.test(x)));
  if(key==='image.resolutions')return Array.isArray(v)&&v.length>=1&&v.length<=4&&v.every(x=>['1k','2k','4k'].includes(x));
  if(key==='image.edit_max_images')return capInt(v,1,20);
  if(key==='video.ref.max_res')return CAP_RES.includes(v);
  if(p.length!==3||p[0]!=='video'||!CAP_MODEL[p[1]])return false;const f=p[2];
  if(f==='max_dur')return capInt(v,1,60);
  if(f==='res')return Array.isArray(v)&&v.length>=1&&v.length<=3&&v.every(x=>CAP_RES.includes(x))&&new Set(v).size===v.length;
  if(f==='ratios')return Array.isArray(v)&&v.length>=1&&v.length<=20&&v.every(x=>typeof x==='string'&&CAP_RATIO_RE.test(x));
  if(f==='t2v_max_res'||f==='i2v_max_res')return CAP_RES.includes(v);
  if(f==='i2v_ratio_auto'||f==='frames')return typeof v==='boolean';
  if(f==='keyframes')return capInt(v,0,12);
  if(f==='voices')return capInt(v,0,10);
  if(f==='ref')return v===null||(!!v&&typeof v==='object'&&Object.keys(v).sort().join()==='max_dur,max_images,max_res'&&capInt(v.max_images,1,50)&&capInt(v.max_dur,1,60)&&CAP_RES.includes(v.max_res));
  if(f==='price')return !!v&&typeof v==='object'&&Object.keys(v).sort().join()==='1080,480,720'&&CAP_RES.every(r=>v[r]===null||(typeof v[r]==='number'&&v[r]>0&&v[r]<5))&&CAP_RES.some(r=>v[r]!=null);
  return false}
function capClone(o){return JSON.parse(JSON.stringify(o))}
let CAPS=capClone(CAPS_BUILTIN);
/* PUPD：已取得的官方字段（只保存通过校验的字段）+ 来源；useBuiltin=true 时不应用 */
let PUPD={fields:{},sources:{},updated:0,useBuiltin:false};
let CAPS_ACTIVE=false;
function capsSanitize(src){const out={fields:{},sources:{},updated:0,useBuiltin:false};if(!src||typeof src!=='object')return out;
  for(const [k,f] of Object.entries(src.fields||{}))if(f&&typeof f==='object'&&capValid(k,f.value))out.fields[k]={value:capClone(f.value),ev:String(f.ev||'').slice(0,240),src:String(f.src||'').slice(0,40),at:+f.at||0};
  for(const [k,s] of Object.entries(src.sources||{}))if(s&&typeof s==='object'&&/^[a-z_]{3,30}$/.test(k))out.sources[k]={ok:!!s.ok,error:String(s.error||'').slice(0,160),fetched_at:+s.fetched_at||0,count:+s.count||0,url:/^https:\/\/docs\.x\.ai\//.test(s.url||'')?String(s.url):''};
  out.updated=+src.updated||0;out.useBuiltin=!!src.useBuiltin;return out}
function capsApply(){CAPS=capClone(CAPS_BUILTIN);CAPS_ACTIVE=false;if(PUPD.useBuiltin)return;
  for(const [k,f] of Object.entries(PUPD.fields)){if(!capValid(k,f.value))continue;const p=k.split('.');const v=capClone(f.value);
    if(k==='image.ratios')CAPS.image.ratios=v;else if(k==='image.resolutions')CAPS.image.resolutions=v;else if(k==='image.edit_max_images')CAPS.image.edit_max_images=v;
    else if(k==='video.ref.max_res')CAPS.ref_max_res=v;else CAPS.video[p[1]][p[2]]=v;CAPS_ACTIVE=true}}
function capOf(model){return CAPS.video[model]||CAPS.video.v15}
function capPrice(model,res){const p=capOf(model).price||{};return p[res]==null?null:p[res]}
function vidRatios(model){return capOf(model).ratios}
function imgRatios(){return CAPS.image.ratios}
function keyMax(){return capOf('v15').keyframes}
/* 当前模式/模型的范围（纯函数，便于测试） */
function capLim(mode,P){const c=capOf(P.model),b=baseOf(mode);
  if(b==='ref'){const r=c.ref;return {dur:r?r.max_dur:c.max_dur,maxRes:+(r?r.max_res:CAPS.ref_max_res),res:c.res,noRef:!r}}
  const mx=+(b==='i2v'?c.i2v_max_res:c.t2v_max_res)||Math.max(...c.res.map(Number));return {dur:c.max_dur,maxRes:mx,res:c.res,noRef:false}}
/* 更新后的参数不支持当前选择时：保留原值，只返回提示，不改用户选择 */
function capsIssues(mode,P,d){const I=[],b=baseOf(mode),M=MODES[mode];if(!M)return I;
  if(!M.video){const k=b==='t2i'?'iar':b==='i2i'?'i2iar':null;if(k&&P[k]&&P[k]!=='src'&&!imgRatios().includes(P[k]))I.push('画幅 '+P[k]+' 不在当前图片参数的比例列表中');return I}
  const lim=capLim(mode,P),c=capOf(P.model);
  if(b==='ref'&&lim.noRef)I.push(CAP_MODEL[P.model]+' 不支持参考图生视频');
  if(!c.res.includes(P.res))I.push(CAP_MODEL[P.model]+' 不支持 '+P.res+'p');else if(+P.res>lim.maxRes)I.push('当前模式最高 '+lim.maxRes+'p，已选 '+P.res+'p');
  if(+P.dur>lim.dur)I.push('时长 '+P.dur+' 秒超过上限 '+lim.dur+' 秒');
  const ak=b==='i2v'?'i2var':'ar';if(P[ak]&&P[ak]!=='src'&&!vidRatios(P.model).includes(P[ak]))I.push('画幅 '+P[ak]+' 不在 '+CAP_MODEL[P.model]+' 的比例列表中');
  if(b==='i2v'&&d){const nk=(d.keys||[]).length;if(nk>keyMax())I.push('中间关键帧 '+nk+' 个，超过上限 '+keyMax()+' 个')}
  if(b==='ref'&&d&&c.ref){const n=(d.refs||[]).length;if(n>c.ref.max_images)I.push('参考图 '+n+' 张，超过上限 '+c.ref.max_images+' 张')}
  return I}
function capFmt(k,v){const f=k.split('.').pop();if(v===undefined)return '—';
  if(f==='ref')return v===null?'不支持':v.max_images+' 张 / '+v.max_dur+' 秒 / '+v.max_res+'p';
  if(f==='price')return CAP_RES.map(r=>r+'p '+(v[r]==null?'—':'$'+(+v[r]).toFixed(2))).join('，');
  if(f==='max_dur')return v+' 秒';if(f==='keyframes'||f==='voices')return v===0?'不支持':v+' 个';if(f==='edit_max_images')return v+' 张';
  if(f==='t2v_max_res'||f==='i2v_max_res'||f==='max_res')return v+'p';if(f==='res')return v.map(x=>x+'p').join('、');
  if(typeof v==='boolean')return v?'支持':'不支持';if(Array.isArray(v))return v.join('、');return String(v)}
function capKeyLabel(k){const p=k.split('.');if(k==='image.ratios')return '图片 · 画幅比例';if(k==='image.resolutions')return '图片 · 分辨率';if(k==='image.edit_max_images')return '图片 · 多图编辑源图上限';
  if(k==='video.ref.max_res')return '参考图生视频 · 输出最高分辨率';return (CAP_MODEL[p[1]]||p[1])+' · '+(CAP_LABEL[p[2]]||p[2])}
function capBuiltinVal(k){const p=k.split('.');if(k==='image.ratios')return CAPS_BUILTIN.image.ratios;if(k==='image.resolutions')return undefined;if(k==='image.edit_max_images')return CAPS_BUILTIN.image.edit_max_images;
  if(k==='video.ref.max_res')return CAPS_BUILTIN.ref_max_res;const m=CAPS_BUILTIN.video[p[1]];return m?m[p[2]]:undefined}
/* 期望覆盖的全部字段（用于显示「未取得」） */
function capAllKeys(){const K=[];for(const m of Object.keys(CAP_MODEL))for(const f of CAP_VFIELDS)K.push('video.'+m+'.'+f);K.push('video.ref.max_res','image.ratios','image.edit_max_images','image.resolutions');return K}
try{if(typeof localStorage!=='undefined'){PUPD=capsSanitize(JSON.parse(localStorage.getItem('ips.params.v1')));capsApply()}}catch(_){}

/* ================= 共享管线（网页与 EVA「Grok提示词」技能共用；纯函数，不访问 DOM / 存储 / 网络） =================
   由中文表单派生英文 → 拼装 → 检查 → 参数建议。网页 ui.js 与技能 engine.js 都只调用这里，避免两套规则漂移。 */
const TC=new Map();/* 译文缓存 zh → {en,src}：网页从 localStorage 载入；技能每次调用为空表 + 预设 + 对话模型给的译文 */
const hasCJK=s=>/[\u4e00-\u9fff]/.test(s||'');
function enFor(zh){zh=trim(zh);if(!zh)return {text:'',missing:[],src:''};if(!hasCJK(zh))return {text:zh,missing:[],src:'raw'};
  const c=TC.get(zh);if(c)return {text:c.en,missing:[],src:c.src};const g=glossTranslate(zh);return {text:g.text,missing:g.missing,src:'gloss'}}
/* 预设与快捷词进入缓存 / 词表（启动时调用一次） */
let TC_SEEDED=false;
function tcSeed(){if(TC_SEEDED)return;TC_SEEDED=true;
  for(const p of PRESETS)(function walk(o){if(!o||typeof o!=='object')return;if(Array.isArray(o))return o.forEach(walk);if(typeof o.zh==='string'&&typeof o.en==='string'&&o.zh&&o.en&&!TC.has(o.zh.trim()))TC.set(o.zh.trim(),{en:o.en.trim(),src:'preset'});for(const k in o)walk(o[k])})(p.data);
  for(const m in MODES)for(const f of MODES[m].fields)(f.chips||[]).forEach(c=>glossAdd(c[1],c[0]));
  glossAdd('只把背景换成','Replace only the background with');glossAdd('只把','Change only the');glossAdd('添加一个小','Add a small')}
/* 由中文表单派生英文：每个 {zh} 节点补 en；记录未翻译片段 */
function derive(d){const miss=[];const pend=new Set();const srcs=new Set();
  const out=JSON.parse(JSON.stringify(d));
  (function walk(o){if(!o||typeof o!=='object')return;if(Array.isArray(o))return o.forEach(walk);
    if(typeof o.zh==='string'){const r=enFor(o.zh);o.en=r.text;if(r.src)srcs.add(r.src);r.missing.forEach(x=>miss.push(x));if(r.src==='gloss'&&hasCJK(o.zh))pend.add(trim(o.zh))}
    for(const k in o)if(k!=='zh'&&k!=='en')walk(o[k])})(out);
  const used=JSON.stringify(d);
  for(const arr of Object.values(USER_OPTS||{}))for(const o of arr)if(!trim(o.en)&&hasCJK(o.zh)){const c=TC.get(trim(o.zh));if(!c||c.src==='gloss'){pend.add(trim(o.zh));if(used.includes('"'+o.k+'"'))glossTranslate(o.zh).missing.forEach(x=>miss.push(x))}}
  return {d:out,missing:[...new Set(miss)],pending:[...pend],srcs};}
/* 画幅：t2i 用 iar，t2v / ref 用 ar，图生图 i2iar、图生视频 i2var（src = 跟随原图 / 首帧）。im = {w,h} 源图尺寸（可无） */
function ratioOf(w,h,list){if(!w||!h)return '';const r=w/h;let best='',bd=1e9;for(const k of (list||KB.ratios).filter(x=>x!=='auto')){const [a,b]=k.split(':').map(Number);const dd=Math.abs(Math.log(r/(a/b)));if(dd<bd){bd=dd;best=k}}return best}
function arInfoP(mode,P,im){const base=baseOf(mode);
  if(base==='i2v'||base==='i2i'){const key=base+'ar';const list=base==='i2v'?vidRatios(P.model):imgRatios();return {locked:false,key,v:P[key]||'src',src:im?ratioOf(im.w,im.h,list):'',im,list}}
  if(base==='t2i')return {locked:false,key:'iar',v:P.iar||'1:1',list:imgRatios()};
  return {locked:false,key:'ar',v:P.ar||'16:9',list:vidRatios(P.model)}}
function genSettingsP(mode,P,dRef,A){const M=MODES[mode],base=baseOf(mode);const T='生成端参数建议（本工具不直接生成）：';
  if(base==='i2i')return T+(A.v==='src'?'画幅跟随原图'+(A.src?' ≈ '+A.src:'')+'（不传 aspect_ratio）':`aspect_ratio="${A.v}"（与原图不同时可能重新构图）`);
  if(!M.video)return T+`aspect_ratio="${A.v}"`;
  const m=KB.models.find(x=>x.k===P.model)||KB.models[0];
  let t=T+`model=${m.name}, duration=${P.dur}, resolution="${P.res}p"`;
  if(base==='i2v'){if(A.v==='src'||A.v===A.src)t+='；画幅跟随首帧'+(A.src?' ≈ '+A.src:'（上传后显示）');else t+=`；目标画幅 ${A.v}；需先将首帧裁切或扩图到该比例再生成`}
  else{t+=`, aspect_ratio="${A.v}"`;if(base==='ref'&&dRef&&dRef.firstFrame)t+='（固定首帧时以生成端为准）'}
  return t}
/* 切换模式/模型时按限制调整参数；返回调整说明（P 原地修改） */
function normalizeParamsP(mode,P){const ch=[];if(!MODES[mode].video)return ch;
  if(baseOf(mode)==='ref'&&!capOf(P.model).ref&&capOf('v15').ref){const was=CAP_MODEL[P.model];P.model='v15';ch.push('模型改为 grok-imagine-video-1.5（'+was+' 不支持参考图）')}
  const lim=capLim(mode,P);
  if(+P.res>lim.maxRes){P.res=String(lim.maxRes);ch.push('分辨率改为 '+lim.maxRes+'p')}
  if(P.dur>lim.dur){P.dur=lim.dur;ch.push('时长改为 '+lim.dur+' 秒')}
  return ch}
function lintCtxP(mode,P,vis){return {spicy:!!MODES[mode].spicy,model:P.model,params:MODES[mode].video?P:null,vis:vis||{minor:false,real:false}}}
/* 一次完整生成：o = {ov,zov（用户手改的英文/中文，可无）, vis:{minor,real}} */
function runPipeline(mode,d,P,o){o=o||{};
  const info=derive(d);const dd=info.d;
  if(d.keepZhDlg&&dd.sound&&dd.sound.v==='dlg')dd.sound.en=trim(d.sound.zh);
  const gen=build(mode,dd,P);
  const out={en:typeof o.ov==='string'?o.ov:gen.en,zh:typeof o.zov==='string'?o.zov:gen.zh};
  const L=lint(mode,dd,out,lintCtxP(mode,P,o.vis));
  return {info,dd,gen,out,lint:L,blocked:L.some(x=>x.level==='block')}}
/* 历史记录（网页「保存到历史」/ 导出文件的条目）：清洗 + 旧版迁移，网页与技能共用 */
const HID_RE=/^[A-Za-z0-9_-]{1,40}$/;
function histSafe(v,depth){if(depth>8)return undefined;if(v==null||typeof v==='boolean')return v;if(typeof v==='number')return isFinite(v)?v:undefined;if(typeof v==='string')return v.slice(0,2000);
  if(Array.isArray(v))return v.slice(0,60).map(x=>histSafe(x,depth+1)).filter(x=>x!==undefined);
  if(typeof v==='object'){const o={};for(const k of Object.keys(v).slice(0,80)){if(k==='__proto__'||k==='constructor'||k==='prototype')continue;const x=histSafe(v[k],depth+1);if(x!==undefined)o[k]=x}return o}return undefined}
function histClean(x){if(!x||typeof x!=='object'||Array.isArray(x))return null;
  if(typeof x.id!=='string'||!HID_RE.test(x.id)||typeof x.mode!=='string'||!Object.prototype.hasOwnProperty.call(MODES,x.mode))return null;
  const en=typeof x.en==='string'?x.en.slice(0,6000):'';if(!trim(en))return null;const t=Date.parse(x.time);
  const data=x.data&&typeof x.data==='object'&&!Array.isArray(x.data)?histSafe(x.data,0):null;
  return {id:x.id,time:isNaN(t)?new Date(0).toISOString():new Date(t).toISOString(),mode:x.mode,title:typeof x.title==='string'&&trim(x.title)?x.title.slice(0,200):'（无标题）',data:data&&Object.keys(data).length?data:null,
    params:x.params&&typeof x.params==='object'&&!Array.isArray(x.params)?x.params:null,en,zh:typeof x.zh==='string'?x.zh.slice(0,6000):'',enEdited:x.enEdited===true,zhEdited:x.zhEdited===true}}
function histKey(x){if(!x.data)return x.mode;if(x.mode==='t2i'||x.mode==='t2v'){try{const c=convertOld(x.mode,migrateData(x.mode,Object.assign(defaults(x.mode),JSON.parse(JSON.stringify(x.data)))));if(c)return c.mode}catch(_){}}return x.mode}
function histParams(mode,p){const o={},b=baseOf(mode);if(!p||typeof p!=='object')return o;const R=v=>typeof v==='string'&&CAP_RATIO_RE.test(v);
  if(MODES[mode].video){if(CAP_MODEL[p.model])o.model=p.model;if(Number.isInteger(+p.dur)&&+p.dur>=1&&+p.dur<=60)o.dur=+p.dur;if(CAP_RES.includes(String(p.res)))o.res=String(p.res);
    if(b==='i2v'){if(p.i2var==='src'||R(p.i2var))o.i2var=p.i2var}else if(R(p.ar))o.ar=p.ar}
  else if(b==='t2i'){if(R(p.iar)||p.iar==='auto')o.iar=p.iar}else if(b==='i2i'){if(p.i2iar==='src'||p.i2iar==='auto'||R(p.i2iar))o.i2iar=p.i2iar}
  return o}
function migrateEntryP(mode,data){const d=migrateData(mode,Object.assign(defaults(mode),JSON.parse(JSON.stringify(data||{}))));const c=convertOld(mode,d);if(c)return {mode:c.mode,data:migrateData(c.mode,c.data),moved:c.moved,conv:c};return {mode,data:d,moved:[],conv:null}}
function regLeftP(c){if(c&&c.fullZh&&c.leftEn.length){const en=[c.origZh?enFor(c.origZh).text:''].concat(c.leftEn).filter(Boolean).join(', ');TC.set(c.fullZh,{en,src:'preset'});return true}return false}
/* 识图候选列表（发给 EVA 识图接口，把识别结果对应到选项 key） */
function visListsP(mode,base){const M=MODES[mode];const o={};const L=(n,k)=>(KB.o[n]||KB[n]||[]).concat(USER_OPTS[n]||[]).slice(0,60).map(x=>({k:x.k,zh:x.zh}));
  if(base==='i2v'){const al=M.fields.find(x=>x.id==='action').list;o.actions=L(al);const ef=M.fields.find(x=>x.id==='env');if(ef)o.env=L(STRUCT[ef.struct].parts[0].list)}
  o.refRole=L('refRoles');return o}

module.exports={IPS_BUILD,capValid,capsSanitize,capsApply,capLim,capsIssues,capOf,capPrice,getCaps:()=>CAPS,setPupd:(o)=>{PUPD=capsSanitize(o);capsApply()},CAPS_BUILTIN,ASPECTS,timeline,KB,LEX,MODES,PRESETS,build,lint,defaults,paramNotes,glossTranslate,migrateData,composeLead,composeStruct,actionText,STRUCT,optItem,hardCheck,convertOld,baseOf,resolveKey,BASES,FORMS,setUser:(o)=>{USER_OPTS=o},TC,tcSeed,enFor,derive,runPipeline,arInfoP,genSettingsP,normalizeParamsP,lintCtxP,ratioOf,paramNotes,spicyAllowed,STRUCT,ASPECTS,setOptEnHook:(f)=>{optEnHook=f},convertOldP:convertOld,histClean,histSafe,histParams,histKey,migrateEntryP,HID_RE,regLeftP,visListsP,setPupdRaw:(o)=>{PUPD=o},getPupd:()=>PUPD,capsSanitizeP:capsSanitize};
