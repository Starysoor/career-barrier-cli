#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生涯闯关自动刷

用法:
    python 刷生涯闯关.py            交互式运行（首次会引导配置，之后回车即可）
    python 刷生涯闯关.py --fresh    忽略已保存配置，重新配置
    python 刷生涯闯关.py --dry      离线自检（不联网，只验证答案生成功能）

流程: 登录 https://zgs.chsi.com.cn → F12 → Network(网络) → 刷新页面 →
      点任意一条 api.zgs.chsi.com.cn 请求 → 请求标头 → 复制 Authorization 的值
      （形如 Bearer eyJhbGci...）→ 粘贴到本脚本提示处 → 回车开始。

协议参考: ScriptCat MIT 开源脚本「职业规划大赛闯关助手」(作者 毫厘/proudly)。
仅供完成学校要求的练习任务，请勿用于参赛。风险自负，仅供学习交流。
"""

import base64
import json
import os
import random
import re
import socket
import struct
import subprocess
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API = "https://api.zgs.chsi.com.cn"
ORIGIN = "https://zgs.chsi.com.cn"
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# ---------------------------------------------------------------
# 控制台中文输出
# ---------------------------------------------------------------
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DEFAULT_CONFIG = {
    "token": "",
    "mode": "template",  # template=内置模板 ai=AI生成 random=快速随机
    "ai": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key": "",
        "model": "glm-4-flash",
    },
    "profile": {
        "name": "", "school": "", "major": "", "grade": "",
        "job1": "", "job2": "", "interests": "", "highlights": "",
        "role_models": "", "extra_prompt": "",
    },
    "overrides": {},
    "bound_uid": "",
}

AI_PRESETS = [
    ("智谱GLM glm-4-flash（免费，推荐）", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
    ("智谱GLM glm-4.6", "https://open.bigmodel.cn/api/paas/v4", "glm-4.6"),
    ("DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat"),
    ("Kimi 月之暗面", "https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    ("通义千问（阿里云百炼）", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    ("硅基流动 SiliconFlow", "https://api.siliconflow.cn/v1", "deepseek-ai/DeepSeek-V3"),
    ("OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("自定义 / 本地Ollama", "http://localhost:11434/v1", "qwen2.5:7b"),
]

ROLE_MODEL_PRESETS = [
    {"name": "黄大年", "position": "战略科学家", "unit": "吉林大学"},
    {"name": "屠呦呦", "position": "研究员", "unit": "中医科学院"},
    {"name": "王坚", "position": "工程院院士", "unit": "阿里巴巴"},
    {"name": "雷军", "position": "创始人", "unit": "小米集团"},
    {"name": "张桂梅", "position": "校长", "unit": "华坪女高"},
]
MAJOR_PRESETS = ["计算机科学与技术", "电子信息工程", "数据科学与大数据技术", "材料科学与工程", "经济学类专业"]
JOB_PRESETS = ["软件研发工程师", "数据分析师", "算法工程师", "产品经理", "市场策划专员", "人力资源专员"]
SHORT_JOB_PRESETS = ["算法工程师", "产品经理", "数据分析师", "研发工程师", "市场策划师", "咨询顾问师"]
EVENT_NAME_PRESETS = [
    "参加学院组织的专业技术分享会并做主题报告",
    "报名参加校级学科竞赛并完成团队项目的答辩环节",
    "参与校企联合实训项目并顺利完成结题验收工作",
    "申报大学生创新创业训练计划项目并顺利完成立项",
    "参加暑期社会实践调研活动并撰写实践调研报告",
    "参与职业技能提升工作坊培训并完成最终结业考核",
]

BOOK_PRESETS = [
    ("《你的降落伞是什么颜色》", "书中的花朵练习帮我系统梳理了技能与价值观"),
    ("《远见》", "三大职业阶段的划分让我对长线规划有了框架"),
    ("《职业锚》", "我据此判断自己的职业锚点是技术职能型"),
    ("《刻意练习》", "我按书中方法设计了技能提升的练习闭环"),
]

CFG = json.loads(json.dumps(DEFAULT_CONFIG))
TOKEN = ""  # 运行期全局Token（供校验函数使用）
TOKEN_SOURCE = ""  # 账号来源说明


# ===============================================================
# 零依赖中文 PDF 生成器（引用标准 CID 字体 STSong-Light/Adobe-GB1，
# 文件极小，Edge/Chrome/WPS/福昕/Adobe(含亚洲字体包) 均可正常打开）
# ===============================================================
def _pdf_hex_text(s):
    """文本 -> UTF-16BE 十六进制字符串（仅保留BMP字符，生僻字/emoji降级为'□'的省略处理）"""
    chars = []
    for ch in s:
        cp = ord(ch)
        if 0x20 <= cp <= 0xFFFF and not (0xD800 <= cp <= 0xDFFF):
            chars.append(ch)
        elif cp > 0xFFFF:
            continue  # 跳过增补平面字符
    return ("".join(chars)).encode("utf-16-be", "replace").hex().upper()


def _pdf_escape_literal(s):
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _pdf_wrap(text, width_units):
    """按显示宽度折行：CJK字符宽1，ASCII宽0.55"""
    lines, cur, w = [], [], 0.0
    for ch in text:
        cw = 0.55 if ord(ch) < 128 else 1.0
        if ch == "\n":
            lines.append("".join(cur))
            cur, w = [], 0.0
            continue
        if w + cw > width_units and cur:
            lines.append("".join(cur))
            cur, w = [], 0.0
            if ch in "，。、；：）】》\"' " and not cur:
                pass
        cur.append(ch)
        w += cw
    if cur:
        lines.append("".join(cur))
    return lines


def make_pdf(blocks):
    """
    生成 A4 中文 PDF。
    blocks: [(style, text), ...]，style: 'h1' 标题 / 'h2' 小标题 / 'meta' 元信息 / 'p' 正文
    返回 PDF bytes。
    """
    PAGE_W, PAGE_H = 595.0, 842.0          # A4 pt
    MARGIN = 64.0
    USABLE_W = PAGE_W - MARGIN * 2

    sizes = {"h1": 18, "h2": 14, "meta": 10.5, "p": 12}
    lead = {"h1": 30, "h2": 24, "meta": 18, "p": 20}
    space_before = {"h1": 0, "h2": 14, "meta": 10, "p": 8}

    pages = []          # 每页: list[ (x, y_baseline, fontsize, hex_text, gray) ]
    cur_lines = []
    y = PAGE_H - MARGIN

    for style, text in (blocks or []):
        fs = sizes.get(style, 12)
        width_units = USABLE_W / fs
        for ln in _pdf_wrap(text or "", width_units):
            if y - lead[style] < MARGIN:
                pages.append(cur_lines)
                cur_lines = []
                y = PAGE_H - MARGIN
            y -= lead[style]
            gray = 0.25 if style in ("h1", "h2") else (0.45 if style == "meta" else 0)
            cur_lines.append((MARGIN, y, fs, _pdf_hex_text(ln), gray))
        y -= space_before.get(style, 6) * 0.5
    if cur_lines:
        pages.append(cur_lines)
    if not pages:
        pages = [[]]

    # ---- 组装 PDF 对象 ----
    objs = {}

    def add(num, body):
        objs[num] = body

    n_pages = len(pages)
    # 1 catalog, 2 pages树, 3 font(type0), 4 descendant CIDFont, 5 font metrics,
    # 之后每页2个对象: page dict + content stream
    add(1, "<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join("%d 0 R" % (6 + i * 2) for i in range(n_pages))
    add(2, "<< /Type /Pages /Count %d /Kids [%s] >>" % (n_pages, kids))
    add(3, ("<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light "
            "/Encoding /UniGB-UCS2-H /DescendantFonts [4 0 R] >>"))
    add(4, ("<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light "
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 2 >> "
            "/FontDescriptor 5 0 R /DW 1000 >>"))
    add(5, ("<< /Type /FontDescriptor /FontName /STSong-Light /Flags 4 /FontBBox "
            "[-25 -254 1000 880] /ItalicAngle 0 /Ascent 880 /Descent -254 "
            "/CapHeight 880 /StemV 93 >>"))

    first_page = 6
    for i, lines in enumerate(pages):
        num_page = first_page + i * 2
        num_content = num_page + 1
        parts = []
        for (x, yb, fs, hexs, gray) in lines:
            g = ("%g g " % gray) if gray else ""
            parts.append("BT %s/F1 %g Tf 1 0 0 1 %.1f %.1f Tm <%s> Tj ET" % (g, fs, x, yb, hexs))
        stream = "\n".join(parts).encode("latin-1", "ignore")
        add(num_page, ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %g %g] "
                       "/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>"
                       % (PAGE_W, PAGE_H, num_content)))
        add(num_content, b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))

    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num
        body = objs[num]
        out += body if isinstance(body, bytes) else body.encode("latin-1", "ignore")
        out += b"\nendobj\n"
    xref_pos = len(out)
    maxnum = max(objs)
    out += b"xref\n0 %d\n" % (maxnum + 1)
    out += b"0000000000 65535 f \n"
    for n in range(1, maxnum + 1):
        out += b"%010d 00000 n \n" % offsets.get(n, 0)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (maxnum + 1, xref_pos)
    return bytes(out)


class ApiError(Exception):
    pass


class TokenError(Exception):
    pass


# ===============================================================
# HTTP
# ===============================================================
def http_json(method, url, token, data=None, timeout=25, retries=2):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, method=method, headers={
                "Authorization": token,
                "Content-Type": "application/json",
                "X-Client-Type": "pc",
                "Accept": "application/json, text/plain, */*",
                "Origin": ORIGIN,
                "Referer": ORIGIN + "/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode("utf-8"))
            except Exception:
                payload = {}
            # 兼容 dict 与 list(yii2 校验错误返回 [{field,message},...]) 两种格式
            if isinstance(payload, list):
                parts = []
                for item in payload:
                    if isinstance(item, dict):
                        f, m2 = item.get("field"), item.get("message")
                        parts.append(("%s: %s" % (f, m2)) if f and m2 else str(item))
                    else:
                        parts.append(str(item))
                msg = "; ".join(parts) or ("HTTP %d" % e.code)
            else:
                msg = (payload.get("message") or payload.get("msg") or ("HTTP %d" % e.code))
                msg = str(msg).strip()
            if e.code == 401 or "token" in msg.lower() or "登录" in msg:
                raise TokenError(msg)
            raise ApiError(msg)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if attempt < retries:
                time.sleep(1 + attempt)
                continue
    raise ApiError("网络错误: %s" % last)


IGNORABLE = ["请勿重复点击", "已存在", "已有分析数据", "请勿重复提交", "重复"]


def api(method, path, token, data=None, ignore=False):
    try:
        return http_json(method, API + path, token, data)
    except ApiError as e:
        if ignore and any(p in str(e) for p in IGNORABLE):
            log("  - [提示] %s，已自动忽略。" % e)
            return None
        raise


# ===============================================================
# 文本生成引擎
# ===============================================================
GENERIC = [
    "通过这次系统性的生涯探索，我对自己的兴趣、能力和价值观有了更加清晰的认识，也更加明确了未来的努力方向。",
    "职业规划不是一次性的任务，而是一个持续迭代的过程，需要根据环境变化和自我成长不断调整优化。",
    "在完成这一阶段的任务后，我深刻体会到理论与实践结合的重要性，也认识到自身还有许多需要提升的地方。",
    "这段经历让我意识到，只有把个人发展与时代需求结合起来，才能走出一条真正适合自己的道路。",
    "老师同学的反馈和测评工具的结果相互印证，帮助我更客观地看待自己的优势与不足。",
    "我会保持开放的心态，积极尝试新的领域，在实践中检验并修正自己的职业假设。",
    "生涯发展的每一步都需要脚踏实地的积累，任何捷径最终都会变成弯路。",
    "感谢这次机会让我停下脚步认真思考未来，我相信清晰的规划是行动成功的一半。",
]

TEMPLATES = {
    "b1.intro": [
        "这位职业榜样在自己的领域深耕多年，取得了令人敬佩的成就。从基层做起，凭借扎实的专业功底和持续的钻研精神，逐步成长为行业内的骨干力量。其职业轨迹清晰而坚定，展现了长期主义者的耐心与专注。研究其经历后，我发现成功并非偶然，而是源于对目标的清晰认知和对行动的严格执行。",
        "我选择的职业榜样是行业内公认的优秀代表。他不仅专业技能过硬，更难得的是始终保持学习的热情，在技术变革的浪潮中不断更新自己的知识体系。其对待工作的严谨态度和对后辈的提携精神，都让我看到了优秀职业人的品格底色。",
    ],
    "b1.reason": [
        "选择这位榜样，是因为他的发展路径与我期望的方向高度契合。他没有依赖运气，而是通过持续的学习和一次次的实践积累，把每一步都走得扎实。面对困难时展现出的韧性和解决问题的思路，正是我最需要学习的品质。他的经历告诉我，职业发展是一场马拉松，比的是耐力和方向感。",
        "我以他为学习对象，是因为他在专业深度和视野广度之间找到了很好的平衡。既能在自己的领域做到精通，又能跳出圈外理解行业的整体趋势。这种复合型能力结构是我努力的方向，他的成长故事为我提供了可参照的路线图。",
    ],
    "b1.inspired": [
        "从榜样身上，我获得的最大启发是：与其焦虑未来，不如专注当下的每一步积累。他把大目标拆解成可执行的小任务，用完成的确定性对抗未知的不确定性。同时我认识到，人脉和口碑是在真诚利他的过程中自然形成的，而不是刻意经营的结果。",
        "榜样的经历让我明白，职业早期阶段最重要的不是薪资和头衔，而是成长速度和平台的质量。要敢于走出舒适区，主动承担有挑战的任务，在实战中锤炼能力。同时保持阅读和复盘的习惯，让经验沉淀为方法论。",
    ],
    "b1.retrospect": [
        "回顾这段生涯探索的旅程，我从一个对未来充满迷茫的新生，逐渐成长为一个对自己有清晰认知、对方向有初步规划的人。通过新知学习、榜样分析和自我反思，我理解了生涯愿景不是空中楼阁，而是建立在充分自我认知基础上的行动纲领。我看到了自己的热情所在，也正视了自己的短板。未来的路上，我会把愿景转化为一个个具体的里程碑，用行动去填平理想与现实之间的差距。我相信，只要方向正确、步伐坚定，时间会给我答案。",
        "完成这一关的探索后，我对生涯愿景有了更深的理解：它不是一句口号，而是由榜样参照、自我评估和阶段性反思共同构筑的动态蓝图。写作和梳理的过程本身就是一次深度对话，让我把模糊的期待变成了清晰的画面。我认识到职业选择的本质是价值交换和自我实现的双赢，既要考虑市场需要什么，也要思考自己能提供什么独特价值。接下来，我会以此愿景为灯塔，在实践中不断校准航向。",
    ],
    "b2.major_course": [
        "本专业的课程体系由通识教育、学科基础、专业核心和实践教学四个模块构成。低年级重点学习高等数学、线性代数、概率统计等基础课程，锻炼数理逻辑功底；进入专业阶段后，系统学习本专业的核心理论与方法课程，涵盖原理、分析与设计等多个层次；高年级通过方向选修课和综合项目，把知识串联成解决实际问题的能力。整体课程由浅入深、环环相扣，既保证了理论的系统性，也预留了个性化发展的空间。",
        "从课程设置来看，本专业强调厚基础、重实践。基础课程夯实数理与语言能力，专业课程围绕行业核心知识展开，从概论到进阶逐步深入。实验课和课程设计贯穿始终，让我们在做中学。此外，学院还引入了企业导师讲座和行业前沿选修，帮助我们把课本知识与产业实践对接。通过这些课程的学习，我逐步建立起本专业的知识框架，也找到了自己感兴趣的方向。",
    ],
    "b2.tunnel": [
        "本专业的发展路径总体清晰，毕业生主要有几类去向：一是进入对口行业企业，从初级岗位做起，沿着从助理到资深再到专家的路线深耕技术；二是继续深造，攻读硕士后进入研发或高校；三是通过跨界学习，转向相邻领域。行业内普遍看重项目经验和证书资质，工作三到五年是能力分化的关键期。随着数字化浪潮推进，本专业与新技术结合的复合型岗位需求增长明显，为毕业生提供了更宽的赛道。",
        "就发展通道而言，本专业毕业生既可以选择技术路线，成为独当一面的专业人才；也可以选择管理路线，向项目经理、部门主管方向发展；还可以利用专业背景进入咨询、教育等知识服务行业。就业面较宽，但竞争同样激烈，唯有尽早规划、突出差异化优势，才能在关键节点上掌握主动权。",
    ],
    "b2.interviewer": [
        "在与本专业从业者交流的过程中，我收获了许多书本上没有的信息。前辈们普遍提到，学校学的是工具箱，真正上手还需要在企业场景中打磨一两年。他们建议我在校期间多参加项目实训和实习，提前熟悉行业的工作节奏与协作方式；同时强调持续学习的重要性，因为行业知识更新很快，固守旧知很快会被淘汰。这次访谈让我对未来的工作状态有了更真实的预期，也缓解了一些焦虑。",
        "通过访谈从业者，我对本专业的真实生态有了更立体的认识。他们分享了很多实际案例：如何处理工期与质量的矛盾，如何在团队中表达观点，如何在重复性工作中保持成长。最触动我的一句话是把简单的事情做好就是不简单。他们还提醒我关注行业报告和趋势动态，培养从宏观视角理解自身岗位价值的能力。这些经验之谈为我的规划提供了重要参照。",
    ],
    "b2.practice_mode": [
        "本专业的实践环节设计得比较完整，从课程实验、课程设计，到学期综合实训、企业实习，再到毕业设计，层层递进。实验课验证理论，课程设计模拟真实小项目，实训阶段则以团队形式完成接近生产级的任务。学校还与多家企业建立了实习基地，寒暑假可以申请进入真实项目组。这种渐进式的实践训练，让知识在应用中得到检验和内化。",
        "实践教学方面，我们专业采用课内实验、课外项目与企业实习三位一体的模式。课内实验配合理论教学即时巩固；课外可以通过学科竞赛、大创项目和开放实验室锻炼综合能力；大三以后有机会进入企业顶岗实习，接触真实业务。老师们鼓励我们把实践中的问题带回课堂讨论，形成学习闭环。这种模式有效提升了我的动手能力和团队协作意识。",
    ],
    "b2.identity_change": [
        "学习本专业以来，我最大的变化是从被动接受者转变为主动探索者。刚入学时，我习惯于等待老师安排任务；如今，我会主动查阅资料、提出问题、规划学习路径。看世界的眼光也不一样了——开始用专业的视角去分析身边的现象，把课堂知识和社会观察联系起来。身份认同感在一次次实践成果中慢慢建立，我逐渐意识到自己正在成为这个领域的一名准从业者。",
        "专业学习带给我的是一次认知升级。最初我以为大学就是学知识点，后来发现真正要学会的是如何像专业人士一样思考：定义问题、拆解问题、寻找证据、得出结论并反思修正。这种思维方式的转变让我在其他方面也受益匪浅。同时，和优秀同学的交流让我看到了差距，也激发了我的进取心，从关注分数转向关注真实能力的成长。",
    ],
    "b2.favorite_major": [
        "在本专业的诸多方向中，我最喜欢的是与实际应用结合最紧密的那个方向。它既有理论的深度，又能直接看到学习成果转化为真实产品的过程，这种即时反馈让我充满动力。为了深入这个方向，我旁听了相关高年级课程，自学了配套工具，还参加了相关竞赛。未来我希望在这个方向上继续深造或就业，把它发展成自己的核心竞争力。",
        "我最感兴趣的是专业中偏综合应用的模块，因为它需要调动多方面知识协同解决问题，过程充满挑战也充满乐趣。在相关课程项目中，我从需求分析做到方案落地，第一次体会到完整交付的成就感。这段经历让我确认了自己的兴趣所在，也让我明白：喜欢不是一时的冲动，而是投入之后获得正向反馈的循环。",
    ],
    "b3.profession": [
        "目标职业是连接个人价值与社会需求的重要桥梁。从行业环境看，该职业处于稳步发展期，市场需求稳定且随数字化转型持续扩容。从业要求包括：扎实的专业知识、熟练的实操技能、良好的沟通协作能力和持续学习的习惯。工作内容以分析、设计与执行为主，需要与多方协作推进。职业发展遵循从执行者到决策者的进阶路径，越往上越考验综合判断和资源整合能力。总体而言，这是一个既有技术含量又有成长空间的职业。",
        "对该职业的系统了解让我认识到：它并非外界想象的那样单一，而是融合了专业技能、工具应用与人际协作的复合型岗位。入行门槛是相关专业背景和基础技能，但走远的门票是项目经验、方法论和行业理解。薪资随能力和城市差异较大，成长速度与学习投入正相关。当前行业对复合型人才的需求上升，若能辅以第二技能，竞争力会显著增强。",
    ],
    "b3.interviewer": [
        "本次职业访谈我联系了一位从业五年的前辈。他详细介绍了岗位的一天：上午处理核心业务，下午参加会议和评审，晚上复盘整理。谈到职业门槛，他说学历是敲门砖，真正决定发展的是解决问题的心态和方法。他建议在校生尽早实习，把简历上的了解变成做过。这次访谈让抽象的职业变得具体可感，也让我制定了一个九十天的技能补强计划。",
        "访谈过程中，前辈坦诚地分享了行业的光鲜与压力。他提到这份职业最有成就感的时刻是作品被认可，最煎熬的时刻是项目节点前的赶工。他给我的建议是：第一，打牢基础，不要追逐浮于表面的技巧；第二，建立自己的作品集，用事实说话；第三，保持身体健康和心态平稳，职业是长跑。这些建议朴素而中肯，我都记在了规划笔记里。",
    ],
    "b4.report": [
        "兴趣测评的结果与我的自我感知基本一致。测评显示我对动手实践和创意实现类活动兴趣浓厚，对研究分析也有中等偏好，这解释了为什么我在项目实践中总是干劲十足。结合兴趣类型分析，我的兴趣组合指向需要创造力与执行力并重的职业环境。同时测评也提醒我：对常规事务性工作的兴趣偏低，未来选择岗位时要尽量避开纯流程型工作，扬长避短。",
        "通过兴趣揭秘环节，我更客观地看待了自己的兴趣图谱。我最突出的兴趣维度是探索与创造，其次是社会型倾向——喜欢与人协作并把成果分享出去。这种组合说明我适合既有独立钻研空间又有团队互动的工作。测评不是给自己贴标签，而是提供一面镜子：它确认了我的热情方向，也提示我需要有意识地补足耐心和细节管理。",
    ],
    "b4.choose": [
        "基于兴趣测评结果，我对职业选择有了更清晰的优先级。首先，我确认了自己对创造与协作并重型岗位的偏好，这类岗位能同时满足我的成就动机和社交需求。其次，我意识到兴趣只是维度之一，还需要结合能力胜任度和市场需求综合判断。接下来的计划是：通过实习和项目验证兴趣的真实性，用作品积累能力证据，在动态尝试中收敛目标。",
        "这次探索让我明白，职业选择的本质是我喜欢、我擅长、社会需要三圆交集的寻找过程。兴趣测评帮我划定了喜欢的大致区域，但要真正落到具体职业上，还需要实践的检验。我打算利用假期做两件事：一是深度访谈三位不同方向的前辈，二是争取一次短期实习。用一手信息代替想象，让选择建立在事实而非滤镜之上。",
    ],
    "b5.new_know": [
        "完成目标锚定后，我最大的收获是把想做什么变成了要做什么、怎么做。通过岗位调研和信息整理，我发现理想职业与自我认知之间存在几处偏差，比如我高估了自己对某些工作内容的耐受度。锚定不是一次性动作，而是一个假设、验证、修正的循环。我为自己设定了短期可衡量的目标，也预留了调整的弹性空间，让规划真正落地。",
        "这一阶段的领悟是：目标不清晰的本质往往是信息不足。当我把岗位要求、能力差距、发展通道等信息逐项整理清楚后，焦虑感明显下降，因为不确定变成了可管理的任务清单。我还学会了用平衡表权衡取舍——没有完美的选择，只有当下最优且可修正的选择。接下来我会按季度复盘目标完成度，让锚定随认知升级而迭代。",
    ],
    "b6.comprehension": [
        "能力盘点像一次全面的自我体检，让我看清了三件事：我的优势区在哪里、短板是什么、以及它们对目标岗位意味着什么。对照岗位要求，我的专业基础和学习能力是加分项，但项目经验和跨部门沟通是明显缺口。为此我制定了针对性的提升计划：以项目为载体补实践经验，以社团和课程展示练表达。盘点不是给自己打分定级，而是为了把有限的精力投到杠杆最大的地方。",
    ],
    "b7.comprehension": [
        "技能提升部分的探索让我建立了技能组合的意识：单一技能的边际价值有限，稀缺的是几项技能的独特组合。我梳理了自己的知识技能、可迁移技能和自我管理技能三个清单，发现真正的竞争力来自交叉处。制定提升计划时，我学会了用行为、结果、时间三要素定义一个可检验的目标，而不是空喊口号。技能的习得没有捷径，唯有刻意练习加及时反馈，我会用每周复盘来保证执行不打折。",
    ],
    "ach.situation": [
        "大二上学期，学院组织了为期六周的课程综合实训，要求团队在限定时间内完成一个完整的课题任务。当时我们小组共五人，成员水平参差，前期进度严重滞后，中途还因为方案分歧发生过激烈争论。作为组长，我面对的第一个挑战就是如何在时间和质量的双重压力下，把团队重新凝聚起来。",
        "去年秋天，我报名参加了校级学科竞赛。备赛期间正值多门课程考试密集期，时间冲突非常明显。团队三个人中有一个人临时退出，剩下的任务量骤增，方案的核心部分还没有打通。情况紧迫，我必须迅速调整分工并稳住大家的情绪。",
    ],
    "ach.task_target": [
        "我的任务目标非常明确：四周内完成方案设计、中期评审和最终答辩三个里程碑，并争取进入校级前十。具体拆解为：第一周完成资料调研和需求界定；第二三周迭代方案原型；最后一周打磨文档和答辩展示。同时我给自己额外定了个人目标——把项目过程整理成可复用的方法笔记。",
        "摆在面前的目标是限期完成作品并参加评审。我们把总目标拆成了五个可验收的子任务，每个子任务指定责任人和截止时间。我个人的任务重点是核心模块的方案设计与跨组资源协调，同时负责把每次讨论沉淀成会议纪要，确保信息不遗漏。",
    ],
    "ach.action_attitude": [
        "我采取了先对齐再冲刺的策略：先组织一次坦诚的复盘会，把分歧摆到桌面上，用投票方式确定技术路线，让大家重新回到同一频道。随后我把任务拆成两天一个的小颗粒，每天站会同步进度、暴露问题。我自己则坚持最早到最晚走，遇到卡点主动查资料请教老师，用行动带动团队节奏。整个过程中我始终保持耐心倾听，不否定任何提议，而是引导大家聚焦怎样做更好。",
        "面对时间紧人手少的局面，我主动承担了最难的模块，并重新规划了所有人的任务优先级。我每天列出三件最重要的事，完成之后才做其他工作；晚上坚持复盘二十分钟，记录当天的收获与问题。遇到不懂的地方，我先自查文档，再带着具体问题去请教老师和学长，绝不把问题过夜。",
    ],
    "ach.result": [
        "最终我们的项目在校级评审中获得了二等奖，排名进入前八，超出了预期目标。更让我欣慰的是团队氛围的转变：从最初互相埋怨到后来主动补位，大家都说这次经历让他们学会了如何高效协作。我个人整理的方法笔记被老师推荐给了下一届同学，成了实训课的参考资料之一。这段经历让我确信，组织能力和执行力是可以刻意练习出来的。",
        "项目按期交付，评审获得良好等第，指导老师在总结会上专门肯定了我们的过程管理。我把全部文档归档并做了复盘报告，梳理出四个可以复用的模板。后来有低年级同学来取经，我给他们做了两次分享。这次经历沉淀下来的不仅是奖项，更是一套遇事不慌、拆解推进的工作方法。",
    ],
    "ach.major_skill": [
        "这个项目充分运用了课堂所学的专业理论：需求界定阶段用到了调研分析方法，方案设计阶段运用了专业课程中的建模思想，文档撰写则锻炼了学术表达能力。为了解决一个技术难点，我还自学了一个新工具，并把它成功应用到项目中。把课本知识迁移到真实任务的过程，加深了我对理论适用边界的理解。",
        "我在项目中系统运用了本学期的专业核心知识，包括基础分析方法、标准流程规范和相关工具软件的操作。特别是在关键决策环节，我用课程中学到的评估框架对三个候选方案做了打分比较，让团队的选择有理有据。老师评价说我们的方案专业味很浓，这是对我知识运用能力的最好肯定。",
    ],
    "ach.migrate_skill": [
        "项目极大地锻炼了我的可迁移技能：沟通协调方面，我学会了在不同意见间寻找共同点，用事实和数据推动共识；信息管理方面，我建立了统一的文档协作规范，让五个人不再是五个信息孤岛；抗压与时间管理方面，我把大目标拆解成日清单的方法被证明非常有效。这些能力不依赖具体专业，将来无论做什么工作都用得上。",
        "整个过程中我的组织协调、公开表达和快速学习能力都得到了实战检验。我主持了十余次小组会议，学会了控制议程和聚焦决策；答辩环节我主讲，锻炼了结构化表达和临场应变。此外，遇到知识盲区时快速检索、筛选、验证信息的能力，是我这次最大的隐性收获。",
    ],
    "ach.self_skill": [
        "在自我管理层面，我建立了自己的节奏系统：每天早上十分钟规划当日，晚上十分钟复盘打卡；情绪管理上，我学会了在争执中先处理心情再处理事情。坚持六周的时间管理实践让我发现自己可以持续输出而不透支，关键在于保证睡眠和运动。这些习惯一直保持到今天，成为我状态稳定的基础。",
        "这段经历检验并强化了我的自我管理技能：我能够抵御手机干扰，保持每天三小时的深度专注；能够在压力下维持情绪稳定，不被一时的挫折带偏节奏；还能够诚实面对自己的拖延，用公开承诺倒逼执行。队友评价我稳，我想这份稳就是自我管理的最好成果。",
    ],
    "b7.behavior": [
        "计划通过每周固定投入加项目实战的方式提升该技能：每周安排固定的时间进行专项学习，从经典教材和优质网课入手建立系统认知；每两周完成一次小练习并公开记录，寻求反馈；学期末参与一次完整的综合项目，把学到的技能在真实场景中验证。同时加入相关学习社群，用同伴压力保持进度不脱落。",
        "我准备采用刻意练习的路径：先花两周梳理该技能的知识框架，明确关键概念和常见误区；然后以周为单位进行专项训练，每次训练都设定可量化的完成标准；每月做一次阶段测试，对比一个月前的自己；并主动向有经验的前辈请教，校准练习方向，避免在错误路径上越走越远。",
    ],
    "b7.expect_result": [
        "预期通过一个学期的持续投入，达到能够独立完成中等难度任务的水平：可以在无指导情况下搭建基本方案，正确率或完成质量达到课程良好以上；能够用该技能在团队项目中承担核心模块；并形成一套自己的练习笔记和方法总结，为下一阶段的进阶打下地基。",
        "目标是三个月内从了解进阶到会做：能独立解决日常场景中的常见问题，遇到复杂问题知道如何拆解和求助；产出至少三份可以放进简历的成果证明；在小组中能够指导初步者，用输出倒逼输入，让技能真正长在自己身上。",
    ],
    "b7.need_resource": [
        "需要准备的主要资源包括：一本评价较好的系统教材和一到两门配套网课；可用于练习的软件环境或工具套装；每周至少八小时的固定可支配时间；以及一个可以请教问题的学习社群或导师渠道。预算方面主要是教材和可能的数据服务费用，预计控制在合理范围内，学生身份可享的优惠也会加以利用。",
        "资源清单：图书馆的参考书目若干、开放课程平台的进阶课程、一台满足要求的个人电脑、用于记录的电子笔记系统，以及找到的同方向学习伙伴两到三人。时间资源上，我计划把每周日晚固定为复盘时段，工作日利用碎片时间做小练习，周末安排整块时间攻坚难点。",
    ],
    "b8.plan": [
        "求职行动计划围绕信息、能力、证据、渠道四条线展开：信息线，每周精读行业报告，跟踪目标岗位的招聘动态；能力线，对照岗位要求逐项补齐技能差距；证据线，持续积累作品、证书和实习经历，形成有说服力的简历素材；渠道线，维护好校招信息源和人脉网络，把握关键时间节点。计划按月检查、按季度调整，确保毕业时手里有粮、心中不慌。",
    ],
}

SKILL_WORDS_CS = ["Python编程", "Java开发", "数据结构", "算法设计", "数据库SQL", "Linux操作",
                  "Git协作", "前端开发", "调试排错", "英语文献阅读", "需求分析", "单元测试",
                  "时间管理", "团队协作", "演讲表达", "技术文档写作"]
SKILL_WORDS_COMMON = ["沟通表达", "团队协作", "时间管理", "Office办公", "信息检索", "数据分析",
                      "公文写作", "逻辑思维", "计划执行", "英语应用", "组织协调", "快速学习",
                      "问题解决", "批判性思维", "演讲展示", "会议纪要总结"]

_filler_i = [0]


def filler_sentence():
    s = GENERIC[_filler_i[0] % len(GENERIC)]
    _filler_i[0] += 1
    return s


def fit_text(t, min_, max_):
    """截断/补写，使 len(t) 落在 [min_, max_] 内（优先在句末标点截断）"""
    t = re.sub(r"\s+", " ", (t or "").strip())
    if len(t) > max_:
        cut = -1
        for i in range(max_, min_ - 1, -1):
            if i < 8:
                break
            if t[i - 1] in "。！？!?；;\n":
                cut = i
                break
        t = t[:cut if cut > 0 else max_]
        t = re.sub(r"[，,、:：]$", "。", t)
    guard = 0
    while len(re.sub(r"。$", "", t)) < min_ and guard < 50:
        guard += 1
        room = max_ - len(t)
        if room <= 2:
            break
        s = filler_sentence()
        base = re.sub(r"。$", "", t)
        if len(s) + 1 <= room:
            t = base + "。" + s
        else:
            t = base + "，" + s[:room - 2] + "。"
        if len(t) > max_:
            t = fit_text(t, min_, max_)
    return t


def shuffle(lst):
    a = list(lst)
    random.shuffle(a)
    return a


def random_target(min_, max_):
    return random.randint(min_, max_)


def template_text(key, min_, max_):
    pool = TEMPLATES.get(key)
    target = random_target(min_, max_)
    t = random.choice(pool) if pool else ""
    for s in shuffle(GENERIC):
        if len(re.sub(r"。$", "", t)) < target:
            t += s
    return fit_text(t, min_, max_)


def random_text(min_, max_):
    chars = ("大学生涯规划探索实践能力素养成长发展目标行动反思总结提升沟通协作创新思维学习积累未来职业方向"
             "兴趣价值匹配评估调整优化坚持努力收获体验认知视野格局心态方法路径资源沉淀迭代突破蜕变承诺担当"
             "使命愿景蓝图基石阶梯征程启航锚定盘点揭秘瞭望笃行领悟新知")
    return "".join(random.choice(chars) for _ in range(random_target(min_, max_)))


def clean_ai_output(out):
    t = (out or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
    t = re.sub(r"```\s*$", "", t)
    t = re.sub(r"^(好的|当然|没问题|明白了)[，,]\s*", "", t)
    lines = t.split("\n")
    if len(lines) > 1 and len(lines[0].strip()) <= 30 and lines[0].strip().endswith(("：", ":")):
        lines = lines[1:]
    t = "\n".join(lines).strip()
    if len(t) >= 2 and ((t[0] == "「" and t[-1] == "」") or (t[0] == '"' and t[-1] == '"')):
        t = t[1:-1].strip()
    return t


def build_system_prompt():
    p = CFG["profile"]
    lines = ["你是一名中国普通大学的在校大学生，正在完成学校要求人人参与的「职业规划大赛-生涯闯关」练习作业（非参赛作品）。请以第一人称撰写内容。"]
    info = []
    for label, v in [("专业", p["major"]), ("年级", p["grade"]), ("学校", p["school"]), ("姓名", p["name"]),
                     ("兴趣爱好", p["interests"]), ("个人经历/亮点", p["highlights"])]:
        if v:
            info.append("%s：%s" % (label, v))
    if p["job1"]:
        info.append("目标职业方向：%s%s" % (p["job1"], (" / " + p["job2"]) if p["job2"] else ""))
    if info:
        lines.append("我的个人背景信息如下（写内容时务必贴合这些信息，做到真实具体）：\n" + "\n".join(info))
    if p["extra_prompt"]:
        lines.append("补充要求：" + p["extra_prompt"])
    lines.append("写作要求：语气真诚朴实、像一个真实的大学生写的；内容具体、有细节，避免空话套话；绝对不要提及你是AI、助手或模型。")
    return "\n".join(lines)


def ai_call(prompt, max_tokens):
    ai = CFG["ai"]
    url = ai["base_url"].rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": ai["model"],
        "messages": [
            {"role": "system", "content": build_system_prompt()},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.8,
        "max_tokens": max(800, int(max_tokens * 2.5)),
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + ai["api_key"],
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    if data.get("choices") and data["choices"][0].get("message"):
        return data["choices"][0]["message"]["content"].strip()
    raise ApiError("AI响应格式异常: %s" % str(data)[:120])


_ai_cache = {}


def ai_text(key, prompt, min_, max_, cache_key=None):
    ck = cache_key or key
    if ck in _ai_cache:
        return _ai_cache[ck]
    target = random_target(min(min_ + 10, max_), max_)
    min_accept = int(min_ * 0.6)
    text, last_err = None, None
    for attempt in range(2):
        try:
            ask = ("%s\n\n输出要求：直接输出正文，不要标题、不要解释、不要引号；字数约%d字（必须在%d到%d字之间）。"
                   % (prompt, target, min_, max_))
            if attempt == 1:
                ask = ("你上一次的回答太短（不足%d字），请重新回答：\n%s\n\n直接输出正文，长度必须在%d到%d个汉字之间，约%d字。"
                       % (min_, prompt, min_, max_, target))
            out = clean_ai_output(ai_call(ask, max_))
            if len(out) >= min_accept:
                text = out
                break
            last_err = ApiError("AI输出过短(%d字，要求>=%d)" % (len(out), min_))
        except (ApiError, urllib.error.HTTPError, OSError, KeyError) as e:
            last_err = e
    if text is None:
        raise last_err or ApiError("AI生成失败")
    fitted = fit_text(text, min_, max_)
    _ai_cache[ck] = fitted
    return fitted


def gen(key, prompt, min_, max_, cache_key=None, no_random=False):
    """统一生成入口：手动覆盖 > AI > 模板 > 随机"""
    ov = CFG.get("overrides", {}).get(key)
    if ov and str(ov).strip():
        log("  - [%s] 使用自定义答案" % key)
        return fit_text(str(ov).strip(), min_, max_)
    if CFG["mode"] == "ai" and CFG["ai"]["api_key"]:
        try:
            t = ai_text(key, prompt, min_, max_, cache_key)
            log("  - [%s] AI生成完成 (%d字)" % (key, len(t)))
            return t
        except Exception as e:
            log("  - [%s] AI失败: %s，回退内置模板" % (key, e), warn=True)
    if CFG["mode"] == "random" and not no_random:
        log("  - [%s] 随机生成" % key)
        return random_text(min_, max_)
    log("  - [%s] 内置模板生成" % key)
    return template_text(key, min_, max_)


# ---------------------------------------------------------------
# 结构化字段
# ---------------------------------------------------------------
def pick(lst):
    return random.choice(lst)


def get_major_name():
    m = (CFG["profile"]["major"] or "").strip()
    if m:
        if 5 <= len(m) <= 10:
            return m
        if len(m) < 5:
            return (m + "类专业")[:10]
        return m[:10]
    return pick(MAJOR_PRESETS)


def get_role_models(n):
    custom = []
    for line in (CFG["profile"]["role_models"] or "").replace("；", ";").split(";"):
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"[,，|]", line)
        parts = [x.strip() for x in parts]
        custom.append({
            "name": (parts[0] if len(parts) > 0 and parts[0] else "职业榜样")[:10],
            "position": (parts[1] if len(parts) > 1 and parts[1] else "行业专家")[:10],
            "unit": (parts[2] if len(parts) > 2 and parts[2] else "知名单位")[:10],
        })
    return (custom + ROLE_MODEL_PRESETS)[:n]


def get_target_jobs(n):
    custom = [x.strip() for x in (CFG["profile"]["job1"], CFG["profile"]["job2"]) if x and x.strip()]
    return (custom + JOB_PRESETS)[:n]


def skill_words():
    m = (CFG["profile"]["major"] or "") + (CFG["profile"]["job1"] or "")
    return SKILL_WORDS_CS if re.search(r"计算机|软件|网络|数据|信息|电子|人工智能|智能|自动化|程序", m) else SKILL_WORDS_COMMON


def gen_skill_text():
    words = shuffle(skill_words())
    target = random_target(20, 80)
    out, length = [], 0
    for w in words:
        if length + len(w) + 1 > min(target, 95):
            break
        out.append(w)
        length += len(w) + 1
        if length >= target:
            break
    while len(",".join(out)) < 15:
        out.append(pick(skill_words()))
    return ",".join(out)


# ===============================================================
# OSS 上传（按题目内容生成真PDF并上传）
# ===============================================================
def build_multipart(oss, filename, pdf_bytes):
    boundary = "----zgs" + uuid.uuid4().hex
    fields = [
        ("key", oss["dir"] + oss["name"] + ".pdf"),
        ("name", filename),
        ("policy", oss["policy"]),
        ("OSSAccessKeyId", oss["accessid"]),
        ("success_action_status", "200"),
        ("callback", oss["callback"]),
        ("x-oss-forbid-overwrite", "true"),
        ("signature", oss["signature"]),
        ("x-oss-signature", oss["signature"]),
        ("x-oss-signature-version", oss["x_oss_signature_version"]),
        ("x-oss-credential", oss["x_oss_credential"]),
        ("x-oss-date", oss["x_oss_date"]),
    ]
    parts = []
    for k, v in fields:
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, k, v)).encode("utf-8"))
    parts.append(('--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\nContent-Type: application/pdf\r\n\r\n'
                  % (boundary, filename)).encode("utf-8"))
    parts.append(pdf_bytes)
    parts.append(b"\r\n")
    parts.append(("--%s--\r\n" % boundary).encode("utf-8"))
    return b"".join(parts), "multipart/form-data; boundary=" + boundary


def upload_pdf(token, filename, oss_type=11, blocks=None):
    """上传PDF；blocks 给定时按内容生成真PDF，否则用通用报告模板"""
    if blocks is None:
        blocks = [("h1", filename.replace(".pdf", "").replace("_", " ")), ("p", "本文档为生涯闯关任务配套材料。")]
    log("  - 生成并上传PDF: %s" % filename)
    pdf_bytes = make_pdf(blocks)
    oss = http_json("GET", "%s/osses/token?type=%d&upload_type=pdf&upload_max_filesize=52428800" % (API, oss_type), token)
    body, ctype = build_multipart(oss, filename, pdf_bytes)
    req = urllib.request.Request(oss["host"], data=body, method="POST", headers={
        "Content-Type": ctype,
        "Accept": "application/json, text/plain, */*",
        "Origin": ORIGIN,
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read().decode("utf-8"))
    log("  - 上传成功(%d字节): %s" % (len(pdf_bytes), resp.get("file", "?")))
    return {"name": filename, "url": resp["file"]}


# ===============================================================
# 题目配套真PDF内容（招聘简章/访谈报告/实习报告/求职计划书）
# ===============================================================
def pdf_blocks_zhaopin(job, major):
    return [
        ("h1", "%s岗位招聘简章" % job),
        ("meta", "来源平台：BOSS直聘 ｜ 招聘单位：某互联网科技有限公司 ｜ 工作地点：贵阳/一线城市建设 ｜ 截止时间：本学年校招季"),
        ("h2", "一、公司简介"),
        ("p", "公司成立于2015年，专注于企业数字化与人工智能应用落地，现有员工300余人，研发人员占比超过60%，服务客户覆盖金融、教育、零售等行业，曾多次获得省级专精特新企业称号。"),
        ("h2", "二、招聘岗位"),
        ("p", "岗位名称：%s；招聘人数：5人；学历要求：本科及以上；专业要求：%s等相关专业均可报名。" % (job, major)),
        ("h2", "三、岗位职责"),
        ("p", "1. 参与公司核心业务系统的设计与开发，编写规范的技术文档；\n2. 参与需求评审与技术方案讨论，配合测试完成功能交付；\n3. 关注行业新技术动态，参与人工智能相关模块的开发与优化；\n4. 完成上级交办的其他研发任务。"),
        ("h2", "四、任职要求"),
        ("p", "1. 扎实掌握至少一门主流编程语言（Python/Java/C++），具备良好的编码习惯；\n2. 熟悉常用数据结构与算法，了解数据库与网络基础知识；\n3. 具备良好的学习能力、沟通表达能力与团队协作精神；\n4. 对人工智能、大模型应用有浓厚兴趣，有相关项目或竞赛经历者优先。"),
        ("h2", "五、薪资福利"),
        ("p", "综合月薪8000-15000元，十四薪；入职缴纳五险一金，享受带薪年假、节日福利、年度体检；公司提供完善的导师带教体系与晋升双通道。"),
        ("h2", "六、投递方式"),
        ("p", "请在BOSS直聘内搜索岗位名称直接沟通投递，或将简历发送至公司校招邮箱，邮件标题注明“姓名-学校-%s应聘”。" % job),
    ]


def pdf_blocks_interview(idx, job):
    return [
        ("h1", "职业生涯人物访谈报告（%d）" % idx),
        ("meta", "访谈对象：%s 从业者（从业约6年）｜ 访谈方式：线上视频访谈 ｜ 访谈时长：约40分钟 ｜ 访谈人：本人" % job),
        ("h2", "一、访谈目的"),
        ("p", "通过对%s岗位一线从业者的深入访谈，了解该职业的真实工作内容、能力要求、发展路径与行业现状，检验并修正我此前的职业认知，为个人职业规划提供一手参考。" % job),
        ("h2", "二、访谈提纲与记录"),
        ("p", "问题1：您日常的主要工作内容是什么？\n答：日常以需求分析、功能开发、代码评审为主，大约一半时间在与产品、测试沟通对齐，另一半时间在写代码和做技术方案。"),
        ("p", "问题2：这份工作最需要什么样的能力和素质？\n答：最重要的是解决问题的能力和持续学习的习惯，技术更新很快；其次是沟通表达，很多工作需要跨团队协作推进。"),
        ("p", "问题3：您觉得这个职业的发展路径是怎样的？\n答：一般从初级工程师开始，三到五年成长为高级工程师，之后走技术专家或管理两条路线，越往上越考验综合能力。"),
        ("p", "问题4：您对我这样在校生的建议是什么？\n答：把基础打牢，多动手做完整的项目；尽早实习，把简历上的“了解”变成“做过”；同时注意写作和表达能力，会做还要会讲。"),
        ("p", "问题5：行业未来的发展趋势如何？\n答：人工智能正在重塑开发方式，简单重复的编码会逐步被工具替代，但懂业务、会驾驭新工具的复合型人才会更抢手。"),
        ("h2", "三、访谈总结与感悟"),
        ("p", "本次访谈让抽象的职业变得具体可感。我认识到学历只是敲门砖，真正决定发展的是解决问题的方法和持续学习的习惯。结合自身情况，我计划在下一阶段重点补强编程基础与项目经验，并争取一次企业实习机会，把访谈中的建议落实到行动上。"),
    ]


def pdf_blocks_practice():
    return [
        ("h1", "专业实践记录报告"),
        ("meta", "实践方式：课程综合实训与企业见习 ｜ 实践周期：一学期 ｜ 报告人：本人"),
        ("h2", "一、实践目的"),
        ("p", "将课堂所学专业知识应用于真实任务，检验自身技能掌握情况，锻炼团队协作与解决实际问题的能力，为后续职业发展积累实践经验。"),
        ("h2", "二、实践内容"),
        ("p", "本学期参加了学院组织的课程综合实训，以小组形式完成一个完整课题：从需求调研、方案设计、开发实现到结题答辩，全流程参与。实践期间还利用假期进入本地一家科技企业见习，观摩并参与日常项目工作，了解企业真实的工作流程与协作规范。"),
        ("h2", "三、实践过程"),
        ("p", "实训阶段：小组五人分工协作，我主要承担方案设计与部分开发工作，过程中经历了方案分歧与进度压力，通过组织复盘会议和任务拆解，最终按期完成课题并获得良好评价。\n见习阶段：跟随企业导师参与晨会、需求评审与代码走查，记录并整理了企业开发的规范流程，完成了导师交办的学习任务。"),
        ("h2", "四、实践收获与反思"),
        ("p", "通过实践，我把课本知识迁移到了真实任务中，加深了对理论适用边界的理解；沟通协调、时间管理和公开表达能力得到实战检验。同时也发现自己在项目经验与跨部门沟通上仍有短板，下一步将针对这些不足制定提升计划。"),
    ]


def pdf_blocks_jobplan(profile, job1, job2):
    return [
        ("h1", "个人求职行动计划书"),
        ("meta", "姓名：%s ｜ 学校：%s ｜ 专业：%s ｜ 年级：%s" % (
            profile.get("name") or "本人", profile.get("school") or "——", profile.get("major") or "——", profile.get("grade") or "——")),
        ("h2", "一、自我分析"),
        ("p", "通过生涯测评与实践探索，我对自己的兴趣、能力与价值观有了较清晰的认识。我对%s方向有浓厚兴趣%s，具备一定的专业基础与学习能力，短板在于项目经验与跨团队沟通，需要在后续学习中重点补足。" % (
            job1 or "目标职业", ("，并喜欢%s" % profile["interests"]) if profile.get("interests") else "")),
        ("h2", "二、目标职业与岗位"),
        ("p", "目标职业一：%s；目标职业二：%s。结合行业调研，该类岗位需求稳定、成长通道清晰，与我的专业背景和兴趣匹配度较高。" % (job1 or "——", job2 or "——")),
        ("h2", "三、分阶段行动计划"),
        ("p", "第一阶段（本学期）：夯实专业核心课程，完成至少一个完整的课程项目，形成可展示的作品。\n第二阶段（下一学年）：争取一次与目标岗位相关的实习，考取相关技能证书，持续积累项目作品集。\n第三阶段（毕业学年）：系统准备校招，完善简历与面试表达，通过模拟面试查漏补缺，拿到目标岗位录用。"),
        ("h2", "四、评估与调整机制"),
        ("p", "每月对计划完成情况进行一次复盘，每学期结合实践反馈对目标做一次校准；若行业环境或个人认知发生较大变化，及时调整方向，保持规划的弹性与可持续性。"),
    ]


# ===============================================================
# 浏览器自动登录（CDP 调试协议：弹窗登录官网，脚本自动读取 Token cookie）
# ===============================================================
BROWSER_PATHS = [
    r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
]


class MiniWS(object):
    """最小 WebSocket 客户端（纯标准库实现，供 CDP 调试协议使用）"""

    def __init__(self, host, port, path, timeout=15):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, host, port, key))
        self.sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise OSError("WS握手失败: 连接断开")
            resp += chunk
        status = resp.split(b"\r\n")[0].decode(errors="ignore")
        if " 101 " not in status:
            raise OSError("WS握手失败: %s" % status)

    def _send_frame(self, opcode, payload):
        header = bytearray([0x80 | opcode])
        n = len(payload)
        mask = os.urandom(4)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise OSError("连接断开")
            buf += chunk
        return buf

    def _recv_frame(self):
        b1, b2 = self._recv_exact(2)
        fin, opcode = b1 & 0x80, b1 & 0x0F
        masked, length = b2 & 0x80, b2 & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else None
        data = self._recv_exact(length)
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        return fin, opcode, data

    def send_text(self, text):
        self._send_frame(1, text.encode("utf-8"))

    def recv_message(self):
        buf = b""
        while True:
            fin, opcode, data = self._recv_frame()
            if opcode == 9:  # ping -> pong
                self._send_frame(10, data)
                continue
            if opcode == 8:
                raise OSError("WS已关闭")
            if opcode in (1, 0):
                buf += data
                if fin:
                    return buf.decode("utf-8", errors="replace")

    def close(self):
        try:
            self._send_frame(8, b"")
            self.sock.close()
        except OSError:
            pass


def _cdp_http(port, path, method="GET", timeout=5):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _with_bearer(token):
    token = (token or "").strip()
    if token and not token.lower().startswith("bearer"):
        token = "Bearer " + token
    return token


def _find_browser():
    for p in BROWSER_PATHS:
        if os.path.exists(p):
            return p
    for name in ("msedge", "chrome"):
        w = shutil.which(name)
        if w:
            return w
    return None


def _read_token_via_cdp(port):
    """从调试端口读取大赛平台页面里的 token cookie。返回 (token, note)"""
    try:
        targets = _cdp_http(port, "/json")
    except Exception:
        return None, "调试端口未响应"
    pages = [t for t in targets
             if t.get("type") == "page" and "chsi.com.cn" in (t.get("url") or "")]
    if not pages:
        return None, "浏览器里还没有大赛平台的页面"
    for t in pages:
        ws = None
        try:
            path = "/" + t["webSocketDebuggerUrl"].split("127.0.0.1:%d" % port + "/")[1]
            ws = MiniWS("127.0.0.1", port, path)
            expr = "decodeURIComponent((document.cookie.match(/(?:^|;\\s*)token=([^;]+)/i)||[])[1]||'')"
            ws.send_text(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                     "params": {"expression": expr, "returnByValue": True}}))
            deadline = time.time() + 8
            while time.time() < deadline:
                r = json.loads(ws.recv_message())
                if r.get("id") == 1:
                    val = (r.get("result", {}).get("result", {}) or {}).get("value") or ""
                    if len(val) >= 20:
                        return val, None
                    return None, None  # 页面在但还没登录（没有token cookie）
            return None, None
        except Exception:
            continue
        finally:
            if ws:
                try:
                    ws.close()
                except Exception:
                    pass
    return None, None


def _verify_token(token):
    """用 /users/login-user-info 验证 token 是否有效"""
    try:
        req = urllib.request.Request(API + "/users/login-user-info", headers={
            "Authorization": token, "X-Client-Type": "pc",
            "Accept": "application/json, text/plain, */*",
            "Origin": ORIGIN, "Referer": ORIGIN + "/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36",
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            if r.status == 200:
                data = json.loads(r.read().decode("utf-8"))
                name = (data.get("data") or {}).get("name") if isinstance(data, dict) else None
                return True, name
    except Exception:
        pass
    return False, None


def browser_login_cdp(preferred_port=9222, wait_seconds=600):
    """
    浏览器自动登录：
    1. 优先探测是否已有本脚本打开的浏览器窗口（已登录则直接复用，零操作）
    2. 否则启动一个独立的浏览器窗口直接打开大赛官网【登录界面】
    3. 你在窗口里用任意官方方式登录（微信扫码/支付宝/账密均可）
    4. 登录成功后官网前端会把 TOKEN 写入 cookie，脚本通过调试协议自动读取并验证
    返回带 Bearer 的 token；失败返回 None。
    """
    # 0. 先探测是否已有本脚本打开的浏览器（上次运行留下的窗口）
    for p in range(preferred_port, preferred_port + 9):
        try:
            _cdp_http(p, "/json/version")
        except Exception:
            continue
        print("[*] 检测到之前打开的浏览器窗口(端口%d)，尝试直接读取登录态..." % p)
        t, _ = _read_token_via_cdp(p)
        if t:
            cand = _with_bearer(t)
            ok, name = _verify_token(cand)
            if ok:
                print("[OK] 该窗口已登录%s，直接复用！无需再登录。" % (("（%s）" % name) if name else ""))
                return cand
        print("[*] 该窗口登录态不可用，将打开新的登录窗口。")
        break

    exe = _find_browser()
    if not exe:
        print("[!!] 未找到 Edge/Chrome 浏览器，无法自动登录。请改用手动粘贴Token。")
        return None

    port = None
    for p in range(preferred_port, preferred_port + 9):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("127.0.0.1", p))
            port = p
            s.close()
            break
        except OSError:
            continue
    if port is None:
        print("[!!] 没有可用的本地调试端口")
        return None

    profile = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".browser_profile")
    print("\n----- 浏览器自动登录 -----")
    print("即将弹出一个新的浏览器窗口，直接打开大赛官网的【登录界面】。")
    print("请在弹出的窗口里用任意方式登录学信网账号（微信扫码 / 支付宝 / 账号密码）。")
    print("登录成功后，Token 会自动回到本脚本，无需任何其他操作。")
    print("(登录态保存在本脚本的独立浏览器配置里，之后重新获取Token时免登录)")

    proc = subprocess.Popen(
        [exe, "--remote-debugging-port=%d" % port, "--user-data-dir=" + profile,
         "--no-first-run", "--no-default-browser-check",
         "https://zgs.chsi.com.cn/login"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ready = False
    for _ in range(30):
        try:
            _cdp_http(port, "/json/version")
            ready = True
            break
        except Exception:
            time.sleep(0.5)
    if not ready:
        print("[!!] 浏览器调试端口未就绪（可能浏览器启动失败）")
        return None

    print("已打开浏览器窗口，等待你登录...（最多等 %d 秒，每几秒自动检测一次）" % wait_seconds)

    deadline = time.time() + wait_seconds
    start = time.time()
    last_hint = 0
    token = None
    while time.time() < deadline:
        token, note = _read_token_via_cdp(port)
        if token:
            break
        time.sleep(3)
        elapsed = int(time.time() - start)
        if elapsed - last_hint >= 60:
            last_hint = elapsed
            extra = ("（检测到大赛平台页面但还没有登录Cookie，请在弹出的窗口里完成登录）" if note is None
                     else "（%s）" % note)
            c = ask("  ...已等待%d秒%s。回车继续等待，输入 m=改用手动粘贴Token，输入 q=放弃: " % (elapsed, extra))
            c = (c or "").strip().lower()
            if c == "q":
                break
            if c == "m":
                t = ask("粘贴Token（Bearer eyJ... 或裸token均可）: ")
                if len(t.replace("Bearer ", "").strip()) >= 20:
                    token = t if t.lower().startswith("bearer") else "Bearer " + t.strip()
                    break

    if token:
        cand = _with_bearer(token)
        ok, name = _verify_token(cand)
        if ok:
            print("[OK] 检测到登录Token%s！弹出的浏览器窗口可以关掉了。" % (("（%s）" % name) if name else ""))
            return cand
        print("[!!] 读到的Token已失效，继续等待新登录...")
        token = None
        # 回到等待循环逻辑：直接走手动提示兜底
        t = ask("回车=重新打开登录窗口，输入 m=手动粘贴Token，输入 q=放弃: ")
        c = (t or "").strip().lower()
        if c == "q":
            return None
        if c == "m":
            t2 = ask("粘贴Token: ")
            if len(t2.replace("Bearer ", "").strip()) >= 20:
                return _with_bearer(t2.strip())
        return browser_login_cdp(preferred_port, wait_seconds=wait_seconds)

    print("[!!] 未能自动获取Token。")
    print("     备选：在你已登录大赛官网的浏览器里按 F12 → 网络/Network → 刷新页面 →")
    print("     点任意一条 api.zgs.chsi.com.cn 请求 → 复制请求头 Authorization 的值，选手动粘贴。")
    return None


# ===============================================================
# 八个关卡
# ===============================================================
def barrier1(token):
    p = "[关卡1·生涯愿景]"
    log(p + " 新知学习...")
    api("POST", "/barrier-firsts/new-knowledge", token, {}, ignore=True)

    log(p + " 笃行-添加职业榜样...")
    models = http_json("GET", API + "/barrier-firsts/role-model-list", token)
    if len(models) < 2:
        add = get_role_models(2 - len(models))
        log("  - 添加榜样: " + "、".join(m["name"] for m in add))
        api("POST", "/barrier-firsts/create-role-model", token,
            {"data": add, "del_ids": []})
    models = http_json("GET", API + "/barrier-firsts/role-model-list", token)
    to_analyze = next((m for m in models if m.get("barrierRoleModelAnalyze") is None), None)
    if to_analyze:
        log(p + " 笃行-分析榜样「%s」..." % to_analyze.get("name", ""))
        payload = {
            "intro": gen("b1.intro", "介绍一下你的职业榜样「%s」（职位：%s）的成就与影响力"
                         % (to_analyze.get("name", "他"), to_analyze.get("position", "行业专家")), 100, 300,
                         cache_key="b1.intro.%s" % to_analyze["id"]),
            "reason": gen("b1.reason", "说明你为什么选择这位人物作为职业榜样", 100, 300,
                          cache_key="b1.reason.%s" % to_analyze["id"]),
            "inspired": gen("b1.inspired", "谈谈这位职业榜样带给你的职业启发", 100, 300,
                            cache_key="b1.inspired.%s" % to_analyze["id"]),
        }
        api("POST", "/barrier-firsts/create-role-model-analyze/%s" % to_analyze["id"], token, payload, ignore=True)
    else:
        log("  - 所有榜样均已分析，跳过。")

    log(p + " 领悟-生涯回顾...")
    content = gen("b1.retrospect", "写一段生涯回顾与感悟：通过本阶段生涯愿景的探索（新知学习、榜样分析）有什么收获，对自己的未来有什么展望", 100, 500)
    api("POST", "/barrier-firsts/create-career-retrospect", token, {"content": content}, ignore=True)


def barrier2(token):
    p = "[关卡2·专业探索]"
    major = get_major_name()
    log(p + " 新知学习...")
    api("POST", "/barrier-seconds/new-knowledge", token, {}, ignore=True)

    log(p + " 笃行-专业认知（专业: %s）..." % major)
    payload = {
        "major_name": major,
        "major_course": gen("b2.major_course", "介绍%s专业的核心课程设置与学习内容" % major, 210, 300),
        "tunnel": gen("b2.tunnel", "描述%s专业的发展路径与就业方向" % major, 210, 300),
        "interviewer": gen("b2.interviewer", "记述一次与%s专业从业者访谈的经历与收获" % major, 210, 300),
        "practice_mode": gen("b2.practice_mode", "说明%s专业的实践教学环节与你的实践体会" % major, 210, 300),
    }
    api("POST", "/barrier-seconds/create-major", token, payload)
    api("POST", "/barrier-seconds/create-major-explore", token, {}, ignore=True)

    log(p + " 领悟...")
    api("POST", "/barrier-seconds/create-comprehend", token, {
        "identity_change": gen("b2.identity_change", "写专业学习给你带来的身份认知变化", 210, 300),
        "favorite_major": gen("b2.favorite_major", "写你最喜欢的%s专业方向及原因" % major, 210, 300),
    })


def barrier3(token):
    p = "[关卡3·职业瞭望]"
    jobs = get_target_jobs(2)
    major = get_major_name()
    log(p + " 新知学习...")
    api("POST", "/barrier-thirds/new-knowledge", token, {}, ignore=True)

    log(p + " 笃行-职业认知（目标: %s）..." % jobs[0])
    payload = {
        "job": fit_text(jobs[0], 5, 20),
        "major": fit_text(major, 5, 20),
        "profession": gen("b3.profession", "对目标职业「%s」进行专业认知分析：行业环境、从业要求、发展通道" % jobs[0], 80, 95),
        "interviewer": gen("b3.interviewer", "记录一次对「%s」从业者的访谈内容与感悟" % jobs[0], 110, 150),
    }
    api("POST", "/barrier-thirds/create-profession", token, payload)
    api("POST", "/barrier-thirds/create-profession-explore", token, {}, ignore=True)

    log(p + " 领悟-意向职业...")
    try:
        api("POST", "/barrier-thirds/create-comprehend", token,
            {"data": [{"profession_name": j} for j in shuffle(SHORT_JOB_PRESETS)[:2]], "del_ids": []})
    except ApiError as e:
        # 首次提交2份必然合法；报份数校验错说明之前已提交过 → 视为已完成
        if "最少填写2份" in str(e) or "最多5份" in str(e):
            log("  - [提示] 意向职业此前已提交过，跳过。")
        else:
            raise


def barrier4(token):
    p = "[关卡4·兴趣揭秘]"
    log(p + " 新知学习...")
    api("POST", "/barrier-fifths/new-knowledge", token, {}, ignore=True)

    log(p + " 笃行-兴趣测评...")
    types = http_json("GET", API + "/barrier-fifths/career-interest-type-entry-list", token)
    if not types:
        raise ApiError("未能获取兴趣选项")
    # 与官网交互一致：只选 3 个真实类型（sort 1-3），其余 3 位为空占位
    data = []
    for i, t in enumerate(shuffle(types)[:3]):
        entries = t.get("barrierWorkValueEntry")
        if not entries:
            continue
        entry = pick(entries)
        data.append({"type_id": t["id"], "entry_id": [entry["id"]], "sort": len(data) + 1})
    while len(data) < 6:
        data.append({"type_id": "", "entry_id": []})
    api("POST", "/barrier-fifths/create-career-interest", token, {"data": data})

    explore = http_json("GET", API + "/barrier-fifths/career-interest-explore-list", token)
    if explore:
        log("  - 生成%d条兴趣与职业关联分析..." % len(explore))
        payload = []
        for i, item in enumerate(explore):
            payload.append({
                "profession_comprehend_id": item["id"],
                "interest_factor": gen("b4.factor", "分析这类职业吸引你的兴趣因素（与你的兴趣爱好结合）", 50, 100,
                                       cache_key="b4.factor.%s" % item["id"]),
                "sort": i + 1,
            })
        api("POST", "/barrier-fifths/create-career-interest-explore", token, {"data": payload})

    log(p + " 领悟...")
    api("POST", "/barrier-fifths/create-comprehend", token, {
        "interest_analyze_report": gen("b4.report", "写你的兴趣测评结果分析与解读（你的兴趣类型、特点）", 100, 300),
        "job_choose": gen("b4.choose", "写基于兴趣测评的职业选择思考", 100, 300),
    })


def barrier5(token):
    p = "[关卡5·目标锚定]"
    jobs = get_target_jobs(2)
    log(p + " 锚定目标岗位...")
    job_names = []
    for j in jobs:
        job_names.append({"job_name": gen("b5.job_name", "基于职业方向「%s」，写出一个具体的目标岗位名称（如XX方向的XX工程师）" % j,
                                          10, 20, cache_key="b5.job_name." + j, no_random=True)})
    api("POST", "/barrier-sixths/create-anchored-job-direction", token, {"data": job_names})

    log(p + " 笃行-1 职业探索（招聘简章）...")
    job_ad = upload_pdf(token, "zhaopinjianzhang.pdf", blocks=pdf_blocks_zhaopin(jobs[0], CFG["profile"].get("major") or get_major_name()))
    book_name, _ = pick(BOOK_PRESETS)
    api("POST", "/barrier-sixths/create-job-explore", token, {
        "platform_info": fit_text(pick(["前程无忧", "智联招聘", "BOSS直聘", "猎聘", "实习僧"]), 5, 15),
        "file": [{"name": job_ad["name"], "url": job_ad["url"], "uid": int(time.time() * 1000)}],
        "book": {"data": [{"name": book_name,
                           "experience": gen("b5.book_exp", "阅读《%s》这本书的收获与体验" % book_name.strip("《》"), 20, 50,
                                             cache_key="b5.book_exp." + book_name)}],
                 "del_ids": []},
    })

    log(p + " 笃行-2 访谈报告...")
    interviews = http_json("GET", API + "/barrier-sixths/interview-report-list", token)
    if not isinstance(interviews, list) or len(interviews) < 2:
        raise ApiError("未获取到足够的访谈报告条目，请先在官网打开一次「目标锚定」关卡再重跑")
    f1 = upload_pdf(token, "fangtanbaogao_1.pdf", blocks=pdf_blocks_interview(1, interviews[0].get("job_name") or jobs[0]))
    f2 = upload_pdf(token, "fangtanbaogao_2.pdf", blocks=pdf_blocks_interview(2, interviews[1].get("job_name") or jobs[0]))
    api("POST", "/barrier-sixths/create-interview-report", token, {
        "data": [
            {"id": interviews[0]["id"], "job_name": interviews[0]["job_name"], "job_file": f1},
            {"id": interviews[1]["id"], "job_name": interviews[1]["job_name"], "job_file": f2},
        ]
    })

    log(p + " 笃行-3 实践记录...")
    practice = upload_pdf(token, "shixibaogao.pdf", blocks=pdf_blocks_practice())
    api("POST", "/barrier-sixths/create-practice-record", token, {
        "data": [{
            "practice_mode": gen("b5.practice_mode", "写一种你参与的实践方式名称与简述（如企业实习/课程实训/社会调研）", 10, 20),
            "practice_report": practice,
            "practice_add_material": [],
        }],
        "del_ids": [],
    })

    log(p + " 笃行-4 岗位信息整理...")
    tidy_list = http_json("GET", API + "/barrier-sixths/job-info-tidy-list", token)
    if not isinstance(tidy_list, list) or len(tidy_list) < 2:
        raise ApiError("未获取到足够的信息整理条目")
    tidy_fields = [
        ("interest_meet", "该岗位与你的兴趣匹配情况"), ("job_environment", "该岗位的工作环境特点"),
        ("job_reward", "该岗位的薪酬回报情况"), ("job_lift_balance", "该岗位的工作生活平衡情况"),
        ("channel_chance", "进入该岗位的渠道与机会"), ("qualification_prepare", "该岗位需要的资质与准备"),
        ("remark", "对该岗位的其他备注"), ("short_term_target", "进入该岗位的短期目标"), ("other", "其他补充信息"),
    ]
    tidy_data = []
    for item in tidy_list:
        row = {"anchored_job_id": item["id"], "id": None}
        for field, desc in tidy_fields:
            row[field] = gen("b5.tidy." + field, "针对目标岗位「%s」：%s（简短一句话）" % (item.get("job_name") or jobs[0], desc),
                             10, 30, cache_key="b5.tidy." + field)
        tidy_data.append(row)
    api("POST", "/barrier-sixths/create-job-info-tidy", token, {"data": tidy_data})

    log(p + " 领悟...")
    api("POST", "/barrier-sixths/create-comprehend", token,
        {"new_know": gen("b5.new_know", "写本阶段（目标锚定）的领悟与新认识", 110, 250)})


def barrier6(token):
    """能力盘点：一次跑一个子任务，返回 True 表示还有剩余"""
    p = "[关卡6·能力盘点]"
    log(p + " 新知学习...")
    api("POST", "/barrier-sevenths/new-knowledge", token, {}, ignore=True)

    log(p + " 笃行-技能盘点...")
    skill = http_json("GET", API + "/barrier-sevenths/skill-explore-list", token)
    items = [x for x in (skill.get("major") or []) + (skill.get("profession") or []) if x.get("is_checked") == "0"]
    total = len(skill.get("major") or []) + len(skill.get("profession") or [])
    done = total - len(items)

    if items:
        it = items[0]
        type_name = "专业" if it.get("type", {}).get("key") == 1 else "职业"
        log("  - 提交%s技能「%s」(%d/%d)..." % (type_name, it.get("name", ""), done + 1, total))
        suffix = it.get("name") or it.get("explore_id")
        api("POST", "/barrier-sevenths/create-skill-explore", token, {
            "knowledge_skill": gen("b6.skill.knowledge", "围绕「%s」，列出你具备的专业知识技能（逗号分隔的词条，不要长句）" % it.get("name", ""), 15, 95,
                                   cache_key="b6.skill.knowledge." + str(suffix)),
            "migrate_skill": gen("b6.skill.migrate", "围绕「%s」，列出你具备的可迁移技能（逗号分隔的词条）" % it.get("name", ""), 15, 95,
                                 cache_key="b6.skill.migrate." + str(suffix)),
            "self_manage_skill": gen("b6.skill.self", "围绕「%s」，列出你具备的自我管理技能（逗号分隔的词条）" % it.get("name", ""), 15, 95,
                                     cache_key="b6.skill.self." + str(suffix)),
            "type": it["type"]["key"],
            "explore_id": it["explore_id"],
        })
        return True

    log("  - 全部技能条目已完成。")
    skill = http_json("GET", API + "/barrier-sevenths/skill-explore-list", token)
    summary = (skill.get("summary") or [{}])[0]
    if summary.get("is_checked") == "0":
        log("  - 提交技能汇总...")
        view = http_json("GET", API + "/barrier-sevenths/skill-explore-view/0", token)
        payload = dict(view)
        payload["type"] = 3
        payload.pop("id", None)
        api("POST", "/barrier-sevenths/create-skill-explore", token, payload)
    api("POST", "/barrier-sevenths/commit-skill-explore", token, {}, ignore=True)

    log(p + " 笃行-成就故事...")
    ach = http_json("GET", API + "/barrier-sevenths/achievement-store-list", token)
    if len(ach) == 0:
        ctx = (CFG["profile"]["highlights"] or "一次团队项目经历")[:60]
        api("POST", "/barrier-sevenths/create-achievement-store", token, {
            "situation": gen("ach.situation", "用STAR法则写一个你的成就故事（背景：%s）——情境部分" % ctx, 55, 95, cache_key="ach.situation"),
            "task_target": gen("ach.task_target", "上述成就故事的目标/任务部分", 55, 95, cache_key="ach.task_target"),
            "action_attitude": gen("ach.action_attitude", "上述成就故事的行动与态度部分", 55, 95, cache_key="ach.action_attitude"),
            "result": gen("ach.result", "上述成就故事的结果部分", 55, 95, cache_key="ach.result"),
            "show_major_knowledge_skill": gen("ach.major_skill", "这个成就故事展现了你哪些专业知识技能", 55, 95, cache_key="ach.major_skill"),
            "show_migrate_skill": gen("ach.migrate_skill", "这个成就故事展现了你哪些可迁移技能", 55, 95, cache_key="ach.migrate_skill"),
            "show_self_manage_skill": gen("ach.self_skill", "这个成就故事展现了你哪些自我管理技能", 55, 95, cache_key="ach.self_skill"),
        })
    api("POST", "/barrier-sevenths/commit-achievement-store", token, {}, ignore=True)

    log(p + " 领悟...")
    view = http_json("GET", API + "/barrier-sevenths/comprehend-view", token)
    comp = view.get("comprehension") or ""
    if len(comp) < 10:
        view["comprehension"] = gen("b6.comprehension", "写能力盘点阶段的总领悟", 100, 490)
    elif len(comp) > 490:
        view["comprehension"] = comp[:490]
    api("POST", "/barrier-sevenths/create-comprehend", token, view)
    return False


def barrier7(token):
    """技能提升：一次创建一条提升途径，返回 True 表示还有剩余"""
    p = "[关卡7·技能提升]"
    log(p + " 新知学习...")
    api("POST", "/barrier-eighths/new-knowledge", token, {}, ignore=True)

    log(p + " 笃行-技能提升途径...")
    all_types = http_json("GET", API + "/barrier-eighths/skill-type-list", token)
    try:
        existing = http_json("GET", API + "/barrier-eighths/skill-promote-way-list", token)
    except ApiError as e:
        # 该接口 500 表示服务端此账号的关卡7数据异常（页面同样空白），无法通过接口修复
        raise ApiError("关卡7服务端数据异常（%s）。官网该页也会空白，需联系客服清理该关数据或稍后重试" % e)
    existing_keys = [w["type"]["key"] for w in existing if isinstance(w, dict) and w.get("type")]
    needed = next((t for t in all_types if t["key"] not in existing_keys), None)

    if needed:
        log("  - 创建「%s」提升途径 (%d/%d)..." % (needed["name"], len(existing_keys) + 1, len(all_types)))
        times = http_json("GET", API + "/barrier-eighths/expect-time-list", token)
        events = http_json("GET", API + "/barrier-eighths/event-list", token)
        t = pick(times) if times else {"key": "7"}
        # 事件名必须简短有意义（用模板句会污染公共事件库，之前正是这么把接口写坏的）
        evt = pick(events) if events else None
        if evt and isinstance(evt, dict) and evt.get("id"):
            event_payload = {"id": evt["id"], "name": evt["name"]}
        else:
            ev_name = pick(EVENT_NAME_PRESETS)
            if len(ev_name) < 20:
                ev_name = (ev_name + "，并在结束后整理形成个人技能提升实践总结")[:50]
            event_payload = {"name": ev_name}
        api("POST", "/barrier-eighths/create-skill-promote-way", token, {
            "type": needed["key"],
            "name": fit_text(needed["name"] + "提升计划", 5, 10),
            "behavior": gen("b7.behavior", "为提升「%s」，写下你的具体学习行为计划" % needed["name"], 100, 150,
                            cache_key="b7.behavior.%s" % needed["key"]),
            "expect_result": gen("b7.expect_result", "提升「%s」的预期成果" % needed["name"], 100, 150,
                                 cache_key="b7.expect.%s" % needed["key"]),
            "expect_time_id": t["key"],
            "need_resource": gen("b7.need_resource", "提升「%s」需要的资源支持" % needed["name"], 100, 150,
                                 cache_key="b7.resource.%s" % needed["key"]),
            "event": event_payload,
        })
        return True

    log("  - 全部提升途径已创建。")
    api("POST", "/barrier-eighths/commit-skill-promote-way", token, {}, ignore=True)

    log(p + " 领悟...")
    api("POST", "/barrier-eighths/create-comprehend", token,
        {"comprehension": gen("b7.comprehension", "写技能提升阶段的总领悟", 100, 490)})
    return False


def barrier8(token):
    p = "[关卡8·生涯启航]"
    log(p + " 新知学习...")
    api("POST", "/barrier-ninths/new-knowledge", token, {}, ignore=True)

    log(p + " 笃行-生涯成长档案...")
    grow = http_json("GET", API + "/barrier-ninths/career-explore-grow-view", token)
    api("POST", "/barrier-ninths/create-career-explore-grow", token, grow)

    log(p + " 领悟-求职计划书...")
    plan = upload_pdf(token, "qiuzhijihuashu.pdf", oss_type=10,
                      blocks=pdf_blocks_jobplan(CFG["profile"], CFG["profile"].get("job1") or "", CFG["profile"].get("job2") or ""))
    api("POST", "/barrier-ninths/create-comprehend", token,
        {"job_plan_name": plan["name"], "job_plan_url": plan["url"]})


BARRIERS = [
    ("1", "生涯愿景", barrier1),
    ("2", "专业探索", barrier2),
    ("3", "职业瞭望", barrier3),
    ("4", "兴趣揭秘", barrier4),
    ("5", "目标锚定", barrier5),
    ("6", "能力盘点", barrier6),
    ("7", "技能提升", barrier7),
    ("8", "生涯启航", barrier8),
]

# ===============================================================
# 覆盖重刷（把已提交的内容按当前模式重新生成并覆盖）
# 说明：官网仅对部分数据开放了覆盖/更新通道；未开放的子项会如实跳过。
# ===============================================================
def _ow_step(name, fn, results):
    log("\n----- %s -----" % name)
    try:
        fn()
        results.append((name, True, ""))
        log("[OK] %s 完成" % name)
    except Exception as e:
        results.append((name, False, str(e)))
        log("[!!] %s 失败: %s（不影响后续）" % (name, e))


def _ow_b1(results):
    def fn():
        log("  生涯回顾重写（覆盖式）...")
        content = gen("b1.retrospect", "写一段生涯回顾与感悟：通过生涯愿景探索的收获与展望（结合个人兴趣与目标职业）", 100, 500, cache_key="ow.b1.retrospect")
        api("POST", "/barrier-firsts/create-career-retrospect", TOKEN, {"content": content}, ignore=True)
        log("  [说明] 榜样分析官网限制只能提交一次，无法覆盖，保留原内容。")
    _ow_step("关卡1 生涯回顾", fn, results)


def _ow_b2(results):
    def fn():
        major = get_major_name()
        log("  重写专业认知（专业: %s）..." % major)
        post = lambda p, d, ig=False: api("POST", p, TOKEN, d, ignore=ig)
        post("/barrier-seconds/create-major", {
            "major_name": major,
            "major_course": gen("b2.major_course", "介绍%s专业的核心课程设置与学习内容" % major, 210, 300, "ow.b2.mc"),
            "tunnel": gen("b2.tunnel", "描述%s专业的发展路径与就业方向" % major, 210, 300, "ow.b2.tu"),
            "interviewer": gen("b2.interviewer", "记述一次与%s专业从业者访谈的经历与收获" % major, 210, 300, "ow.b2.iv"),
            "practice_mode": gen("b2.practice_mode", "说明%s专业的实践教学环节与你的实践体会" % major, 210, 300, "ow.b2.pm"),
        })
        post("/barrier-seconds/create-major-explore", {}, True)
        post("/barrier-seconds/create-comprehend", {
            "identity_change": gen("b2.identity_change", "写专业学习给你带来的身份认知变化", 210, 300, "ow.b2.ic"),
            "favorite_major": gen("b2.favorite_major", "写你最喜欢的%s专业方向及原因" % major, 210, 300, "ow.b2.fm"),
        })
    _ow_step("关卡2 专业探索", fn, results)


def _ow_b3(results):
    def fn():
        jobs = get_target_jobs(2)
        old = http_json("GET", API + "/barrier-thirds/comprehend-list", TOKEN)
        old_ids = [x["id"] for x in old if isinstance(x, dict) and x.get("id")] if isinstance(old, list) else []
        log("  重建意向职业（清旧%d条 → AI新2条: %s）..." % (len(old_ids), "、".join(jobs[:2])))
        api("POST", "/barrier-thirds/create-comprehend", TOKEN,
            {"data": [{"profession_name": j} for j in jobs[:2]], "del_ids": old_ids})
        log("  [说明] 职业探索(profession)官网为追加式且未开放删除，跳过以避免堆积。")
    _ow_step("关卡3 意向职业", fn, results)


def _ow_b4(results):
    def fn():
        post = lambda p, d, ig=False: api("POST", p, TOKEN, d, ignore=ig)
        types = http_json("GET", API + "/barrier-fifths/career-interest-type-entry-list", TOKEN)
        data = []
        for t in (shuffle(types) if isinstance(types, list) else [])[:3]:
            entries = t.get("barrierWorkValueEntry")
            if not entries:
                continue
            entry = pick(entries)
            data.append({"type_id": t["id"], "entry_id": [entry["id"]], "sort": len(data) + 1})
        while len(data) < 6:
            data.append({"type_id": "", "entry_id": []})
        post("/barrier-fifths/create-career-interest", {"data": data}, True)
        explore = http_json("GET", API + "/barrier-fifths/career-interest-explore-list", TOKEN)
        if isinstance(explore, list) and explore:
            post("/barrier-fifths/create-career-interest-explore", {"data": [
                {"profession_comprehend_id": it["id"],
                 "interest_factor": gen("b4.factor", "分析这类职业吸引你的兴趣因素", 50, 100, "ow.b4.f." + str(it["id"])),
                 "sort": i + 1} for i, it in enumerate(explore)]}, True)
        post("/barrier-fifths/create-comprehend", {
            "interest_analyze_report": gen("b4.report", "写你的兴趣测评结果分析与解读", 100, 300, "ow.b4.rp"),
            "job_choose": gen("b4.choose", "写基于兴趣测评的职业选择思考", 100, 300, "ow.b4.ch"),
        })
    _ow_step("关卡4 兴趣揭秘", fn, results)


def _ow_b5(results):
    def fn():
        jobs = get_target_jobs(2)
        post = lambda p, d, ig=False: api("POST", p, TOKEN, d, ignore=ig)
        old_anchor = http_json("GET", API + "/barrier-sixths/anchored-job-direction-list", TOKEN)
        old_ids = [x["id"] for x in old_anchor if isinstance(x, dict) and x.get("id")] if isinstance(old_anchor, list) else []
        post("/barrier-sixths/create-anchored-job-direction", {
            "data": [{"job_name": gen("b5.job_name", "基于职业方向「%s」写具体目标岗位名称" % j, 10, 20, "ow.b5.jn." + j, no_random=True)} for j in jobs[:2]],
            "del_ids": old_ids}, True)
        job_ad = upload_pdf(TOKEN, "zhaopinjianzhang.pdf", blocks=pdf_blocks_zhaopin(jobs[0], CFG["profile"].get("major") or get_major_name()))
        book_name, _ = pick(BOOK_PRESETS)
        post("/barrier-sixths/create-job-explore", {
            "platform_info": fit_text(pick(["BOSS直聘", "智联招聘", "前程无忧"]), 5, 15),
            "file": [{"name": job_ad["name"], "url": job_ad["url"], "uid": int(time.time() * 1000)}],
            "book": {"data": [{"name": book_name,
                               "experience": gen("b5.book_exp", "阅读《%s》的收获" % book_name.strip("《》"), 20, 50, "ow.b5.bk")}],
                     "del_ids": []}}, True)
        interviews = http_json("GET", API + "/barrier-sixths/interview-report-list", TOKEN)
        if isinstance(interviews, list) and interviews:
            files = []
            for i, it in enumerate(interviews[:2]):
                f = upload_pdf(TOKEN, "fangtanbaogao_%d.pdf" % (i + 1), blocks=pdf_blocks_interview(i + 1, it.get("job_name") or jobs[0]))
                files.append({"id": it["id"], "job_name": it.get("job_name") or jobs[0], "job_file": f})
            post("/barrier-sixths/create-interview-report", {"data": files})
        practice = upload_pdf(TOKEN, "shixibaogao.pdf", blocks=pdf_blocks_practice())
        old_pr = http_json("GET", API + "/barrier-sixths/practice-record-list", TOKEN)
        old_pr_ids = [x["id"] for x in old_pr if isinstance(x, dict) and x.get("id")] if isinstance(old_pr, list) else []
        post("/barrier-sixths/create-practice-record", {
            "data": [{"practice_mode": gen("b5.practice_mode", "写一种你参与的实践方式名称", 10, 20, "ow.b5.pmd"),
                      "practice_report": practice, "practice_add_material": []}],
            "del_ids": old_pr_ids}, True)
        tidy_list = http_json("GET", API + "/barrier-sixths/job-info-tidy-list", TOKEN)
        if isinstance(tidy_list, list) and tidy_list:
            fields = [("interest_meet", "该岗位与你的兴趣匹配情况"), ("job_environment", "该岗位的工作环境特点"),
                      ("job_reward", "该岗位的薪酬回报情况"), ("job_lift_balance", "该岗位的工作生活平衡"),
                      ("channel_chance", "进入该岗位的渠道与机会"), ("qualification_prepare", "该岗位需要的资质与准备"),
                      ("remark", "对该岗位的其他备注"), ("short_term_target", "进入该岗位的短期目标"), ("other", "其他补充信息")]
            tidy_data = []
            for item in tidy_list:
                row = {"anchored_job_id": item["id"], "id": (item.get("jobInfoTidy") or {}).get("id")}
                for fld, desc in fields:
                    row[fld] = gen("b5.tidy." + fld, "针对目标岗位「%s」：%s（一句话）" % (item.get("job_name") or jobs[0], desc), 10, 30, "ow.b5.td." + fld)
                tidy_data.append(row)
            post("/barrier-sixths/create-job-info-tidy", {"data": tidy_data}, True)
        post("/barrier-sixths/create-comprehend", {"new_know": gen("b5.new_know", "写目标锚定阶段的领悟与新认识", 110, 250, "ow.b5.nk")}, True)
    _ow_step("关卡5 目标锚定", fn, results)


def _ow_b6(results):
    def fn():
        post = lambda p, d, ig=False: api("POST", p, TOKEN, d, ignore=ig)
        view = http_json("GET", API + "/barrier-sevenths/comprehend-view", TOKEN)
        payload = view if isinstance(view, dict) else {}
        payload["comprehension"] = gen("b6.comprehension", "写能力盘点阶段的总领悟", 100, 490, "ow.b6.cp")
        post("/barrier-sevenths/create-comprehend", payload, True)
        log("  [说明] 技能盘点与成就故事官网未开放更新/删除接口，无法覆盖，保留原内容。")
    _ow_step("关卡6 能力盘点(领悟)", fn, results)


def _ow_b7(results):
    def fn():
        post = lambda p, d, ig=False: api("POST", p, TOKEN, d, ignore=ig)
        post("/barrier-eighths/create-comprehend", {"comprehension": gen("b7.comprehension", "写技能提升阶段的总领悟", 100, 490, "ow.b7.cp")}, True)
        log("  [说明] 提升途径官网未开放删除接口（同一类型也不允许重复创建），无法覆盖，保留原内容。")
    _ow_step("关卡7 技能提升(领悟)", fn, results)


def _ow_b8(results):
    def fn():
        post = lambda p, d, ig=False: api("POST", p, TOKEN, d, ignore=ig)
        grow = http_json("GET", API + "/barrier-ninths/career-explore-grow-view", TOKEN)
        if isinstance(grow, dict):
            post("/barrier-ninths/create-career-explore-grow", grow, True)
        plan = upload_pdf(TOKEN, "qiuzhijihuashu.pdf", oss_type=10,
                          blocks=pdf_blocks_jobplan(CFG["profile"], CFG["profile"].get("job1") or "", CFG["profile"].get("job2") or ""))
        view = http_json("GET", API + "/barrier-ninths/comprehend-view", TOKEN)
        payload = {"job_plan_name": plan["name"], "job_plan_url": plan["url"]}
        if isinstance(view, dict) and view.get("id"):
            payload["id"] = view["id"]
        post("/barrier-ninths/create-comprehend", payload, True)
    _ow_step("关卡8 生涯启航", fn, results)


def run_overwrite():
    global TOKEN
    TOKEN = (CFG.get("token") or "").strip()
    if len(TOKEN) < 20:
        log("❌ Token未获取，请先完成登录", "error")
        return
    print("\n=== 覆盖重刷（用当前答案模式重新生成全部内容） ===")
    print("说明：官网开放了覆盖通道的部分会重写；未开放的（榜样分析、技能盘点、\n      成就故事、提升途径）会保留原内容并如实提示。")
    results = []
    for fn in (_ow_b1, _ow_b2, _ow_b3, _ow_b4, _ow_b5, _ow_b6, _ow_b7, _ow_b8):
        fn(results)
        time.sleep(1.2)
    okk = [n for n, s, _ in results if s]
    badd = [(n, e) for n, s, e in results if not s]
    print("\n" + "=" * 56)
    print("覆盖完成 %d/%d 项，去官网刷新查看新内容。" % (len(okk), len(results)))
    for n, e in badd:
        print("  失败: %s -> %s" % (n, e[:80]))
    print("=" * 56)


# ===============================================================
# 交互配置
# ===============================================================
def log(msg, warn=False):
    print(msg, flush=True)


def ask(prompt, default=""):
    try:
        s = input(prompt).strip()
    except EOFError:
        s = default
    return s or default


def load_config():
    global CFG
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for k in DEFAULT_CONFIG:
                if k == "ai":
                    DEFAULT_CONFIG["ai"].update(saved.get("ai") or {})
                elif k == "profile":
                    DEFAULT_CONFIG["profile"].update(saved.get("profile") or {})
                else:
                    DEFAULT_CONFIG[k] = saved.get(k, DEFAULT_CONFIG[k])
            CFG = DEFAULT_CONFIG
            return True
        except Exception:
            pass
    return False


def save_config():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(CFG, f, ensure_ascii=False, indent=2)


def setup():
    """首次引导 / 修改配置。返回 None。"""
    global CFG
    mode_names = {"template": "内置模板", "ai": "AI生成", "random": "快速随机"}
    if CFG["token"]:
        print("\n检测到已保存的配置：")
        print("  模式: %s%s" % (mode_names.get(CFG["mode"], CFG["mode"]),
                                ("（%s）" % CFG["ai"]["model"]) if CFG["mode"] == "ai" else ""))
        print("  专业: %s | 目标职业: %s" % (CFG["profile"]["major"] or "未填", CFG["profile"]["job1"] or "未填"))
        print("  Token: ..." + (CFG["token"][-12:] if len(CFG["token"]) > 12 else ""))
        c = ask("直接回车使用以上配置，输入 r 重新配置: ")
        if c.lower() != "r":
            return
        CFG = json.loads(json.dumps(DEFAULT_CONFIG))

    print("\n========== 首次配置（所有问题都可以直接回车跳过/用默认） ==========")
    # 模式
    print("\n答案模式：\n  1) 内置模板（默认，零配置，速度最快）\n  2) AI生成（内容更真实，需要一个大模型API Key）\n  3) 快速随机（最省事但内容一看就是刷的）")
    c = ask("选择 [1/2/3]，回车=1: ", "1")
    CFG["mode"] = {"1": "template", "2": "ai", "3": "random"}.get(c, "template")

    if CFG["mode"] == "ai":
        print("\nAI平台（推荐智谱GLM-4-Flash，免费：open.bigmodel.cn 注册后在「API密钥」页创建）：")
        for i, (name, _, _) in enumerate(AI_PRESETS, 1):
            print("  %d) %s" % (i, name))
        c = ask("选择 [1-%d]，回车=1: " % len(AI_PRESETS), "1")
        try:
            idx = int(c) - 1
            if 0 <= idx < len(AI_PRESETS):
                CFG["ai"]["base_url"], CFG["ai"]["model"] = AI_PRESETS[idx][1], AI_PRESETS[idx][2]
        except ValueError:
            pass
        print("当前: %s | 模型 %s" % (CFG["ai"]["base_url"], CFG["ai"]["model"]))
        key = ask("粘贴 AI API Key（回车=沿用已保存的Key）: ")
        if key:
            CFG["ai"]["api_key"] = key
        if CFG["ai"]["api_key"]:
            print("正在测试AI连接...")
            try:
                out = ai_call("请只回复两个字：成功", 20)
                print("[OK] AI连接成功，返回: " + out[:30])
            except Exception as e:
                print("[!!] AI连接失败: %s" % e)
                print("     将回退到内置模板模式继续跑，也可以之后修好Key再跑。")
                CFG["mode"] = "template"
        else:
            print("未填Key，自动改用内置模板模式。")
            CFG["mode"] = "template"

    # 个人资料（影响生成内容的质量）
    p = CFG["profile"]
    print("\n个人资料（回车跳过；填了内容会更贴合你，尤其推荐填「专业」和「目标职业」）：")
    p["major"] = ask("  专业: ", p["major"])
    p["grade"] = ask("  年级（如大二）: ", p["grade"])
    p["job1"] = ask("  目标职业1（如 前端开发工程师）: ", p["job1"])
    p["job2"] = ask("  目标职业2: ", p["job2"])
    p["interests"] = ask("  兴趣爱好（逗号分隔）: ", p["interests"])
    p["highlights"] = ask("  个人经历/亮点（竞赛、实习、社团等，成就故事会从这里取材）: ", p["highlights"])

    # Token：优先官方扫码登录
    print('\n最后一步 —— 获取登录Token：')
    print('  1) 官方扫码登录（推荐：自动打开学信网官方登录页，微信/支付宝/学信网App扫码或账密均可，全自动取Token）')
    print('  2) 手动粘贴Token（F12 → Network → api.zgs.chsi.com.cn 请求头里的 Authorization 值）')
    c = ask("选择 [1/2]，回车=1: ", "1")
    if c == "2":
        while True:
            t = ask("粘贴Token: ")
            if len(t) >= 20:
                CFG["token"] = t
                break
            print("[!!] 看起来不像Token（太短），请重新粘贴。")
    else:
        token = browser_login_cdp()
        while token is None:
            c2 = ask("扫码未成功。回车=重试扫码，输入 m=改用手动粘贴，输入 q=退出: ", "r")
            if c2.lower() == "m":
                while True:
                    t = ask("粘贴Token: ")
                    if len(t) >= 20:
                        CFG["token"] = t
                        break
                    print("[!!] 太短，请重新粘贴。")
                break
            if c2.lower() == "q":
                print("已退出。下次运行可继续。")
                sys.exit(0)
            token = browser_login_cdp()
        # 关键：本次扫码/登录得到的新 Token 必须覆盖旧缓存，否则会继续用上一个账号
        CFG["token"] = token

    save_config()
    print("\n[OK] 配置已保存到 config.json，下次运行直接回车即可。\n")


# ===============================================================
# 服务端回读校验（防止"假成功"：只有服务端真的存下了才算完成）
# ===============================================================
def _safe_get(path):
    try:
        return http_json("GET", API + path, TOKEN)
    except Exception:
        return None


# UI序号(1-8) -> 接口关卡id(1,2,3,5,6,7,8,9，接口没有4)
API_BARRIER_ID = {1: 1, 2: 2, 3: 3, 4: 5, 5: 6, 6: 7, 7: 8, 8: 9}


def verify_barrier(bid):
    """只读回读该关的真实状态（bid 传 UI 序号 1-8）。返回 (是否真完成, 说明)"""
    bid = API_BARRIER_ID.get(bid, bid)
    try:
        if bid == 1:
            models = _safe_get("/barrier-firsts/role-model-list") or []
            analyzed = [x for x in models if isinstance(x, dict) and x.get("barrierRoleModelAnalyze")]
            retro = _safe_get("/barrier-firsts/career-retrospect-view") or {}
            has_retro = bool(isinstance(retro, dict) and (retro.get("content") or "").strip())
            return (len(analyzed) >= 1 and has_retro,
                    "榜样分析 %d 个｜生涯回顾%s" % (len(analyzed), "已提交" if has_retro else "未提交"))
        if bid == 2:
            c = _safe_get("/barrier-seconds/comprehend-view") or {}
            ok = isinstance(c, dict) and (c.get("identity_change") or "").strip() and (c.get("favorite_major") or "").strip()
            return (bool(ok), "专业领悟%s" % ("已提交" if ok else "未提交"))
        if bid == 3:
            lst = _safe_get("/barrier-thirds/comprehend-list") or []
            n = len(lst) if isinstance(lst, list) else 0
            return (n >= 2, "意向职业 %d 条（需≥2）" % n)
        if bid == 5:
            c = _safe_get("/barrier-fifths/comprehend-view") or {}
            ok = isinstance(c, dict) and (c.get("interest_analyze_report") or "").strip()
            return (bool(ok), "兴趣领悟%s" % ("已提交" if ok else "未提交"))
        if bid == 6:
            anchor = _safe_get("/barrier-sixths/anchored-job-direction-list") or []
            iv = _safe_get("/barrier-sixths/interview-report-list") or []
            pr = _safe_get("/barrier-sixths/practice-record-list") or []
            tidy = _safe_get("/barrier-sixths/job-info-tidy-list") or []
            filled_iv = [x for x in iv if isinstance(x, dict) and (x.get("job_file") or {}).get("url")]
            filled_pr = [x for x in pr if isinstance(x, dict) and (x.get("practice_report") or {}).get("url")]
            filled_tidy = [x for x in tidy if isinstance(x, dict) and (x.get("jobInfoTidy") or {}).get("interest_meet")]
            ok = len(anchor) >= 2 and len(filled_iv) >= 2 and len(filled_pr) >= 1 and len(filled_tidy) >= 2
            return (ok, "岗位%d｜访谈PDF %d/2｜实习PDF %d｜信息整理 %d"
                    % (len(anchor), len(filled_iv), len(filled_pr), len(filled_tidy)))
        if bid == 7:
            sk = _safe_get("/barrier-sevenths/skill-explore-list") or {}
            items = [x for x in (sk.get("major") or []) + (sk.get("profession") or [])]
            done = [x for x in items if x.get("is_checked") == "1"]
            summary = (sk.get("summary") or [{}])[0]
            ach = _safe_get("/barrier-sevenths/achievement-store-list") or []
            ok = (len(items) > 0 and len(done) == len(items) and summary.get("is_checked") == "1" and len(ach) > 0)
            return (ok, "技能 %d/%d｜汇总%s｜成就故事%d"
                    % (len(done), len(items), "已完成" if summary.get("is_checked") == "1" else "未完成", len(ach)))
        if bid == 8:
            ways = _safe_get("/barrier-eighths/skill-promote-way-list") or []
            types_filled = set()
            for w in ways:
                t = (w.get("type") or {}).get("key")
                if t is not None:
                    types_filled.add(str(t))
            ok = len(types_filled) >= 3
            return (ok, "提升途径覆盖 %d 类（需≥3）" % len(types_filled))
        if bid == 9:
            c = _safe_get("/barrier-ninths/comprehend-view") or {}
            ok = isinstance(c, dict) and (c.get("job_plan_url") or "").strip()
            return (bool(ok), "求职计划书%s" % ("已上传" if ok else "未上传"))
    except Exception as e:
        return (False, "校验异常: %s" % e)
    return (False, "未知关卡")


# ===============================================================
# 账号身份确认（防止把内容写进别人的账号）
# ===============================================================
def fetch_account():
    """取当前Token对应的账号信息"""
    try:
        info = http_json("GET", API + "/users/login-user-info", TOKEN)
        if isinstance(info, dict):
            return info
    except Exception:
        pass
    return None


def mask_phone(p):
    p = str(p or "")
    return p[:3] + "****" + p[-4:] if len(p) >= 7 else p


def browser_current_token():
    """如果本脚本的浏览器窗口正开着，返回它当前登录的 Token（以浏览器登录态为准）"""
    for p in range(9222, 9231):
        try:
            _cdp_http(p, "/json/version")
        except Exception:
            continue
        t, _ = _read_token_via_cdp(p)
        if t:
            return _with_bearer(t)
        return None
    return None


def switch_account(old_token="", wait_seconds=480):
    """
    切换账号：在现有浏览器里清空登录态(cookie)并跳转登录页，等待新账号登录。
    不删除 profile 目录，避免 Windows 文件占用错误。
    """
    exe = _find_browser()
    if not exe:
        print("[!!] 未找到 Edge/Chrome")
        return None

    # 找到（或启动）本脚本的调试浏览器
    port = None
    for p in range(9222, 9231):
        try:
            _cdp_http(p, "/json/version")
            port = p
            break
        except Exception:
            continue
    if port is None:
        profile = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".browser_profile")
        print("[i] 正在打开浏览器窗口...")
        subprocess.Popen([exe, "--remote-debugging-port=9222", "--user-data-dir=" + profile,
                          "--no-first-run", "--no-default-browser-check",
                          "https://zgs.chsi.com.cn/login"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(40):
            try:
                _cdp_http(9222, "/json/version")
                port = 9222
                break
            except Exception:
                time.sleep(0.5)
    if port is None:
        print("[!!] 浏览器调试端口未就绪")
        return None

    # 用 CDP 清空 cookie（等价于退出登录），再打开登录页
    targets = _cdp_http(port, "/json")
    page = next((t for t in targets if t.get("type") == "page"), None)
    if not page:
        print("[!!] 浏览器里没有可用页面")
        return None
    path = "/" + page["webSocketDebuggerUrl"].split("127.0.0.1:%d/" % port)[1]
    try:
        ws = MiniWS("127.0.0.1", port, path)
    except Exception as e:
        print("[!!] 连接浏览器失败: %s" % e)
        return None
    mid = [0]

    def cmd(method, params=None):
        mid[0] += 1
        i = mid[0]
        ws.send_text(json.dumps({"id": i, "method": method, "params": params or {}}))
        dl = time.time() + 20
        while time.time() < dl:
            r = json.loads(ws.recv_message())
            if r.get("id") == i:
                return r.get("result", {})

    try:
        cmd("Network.enable")
        cmd("Network.clearBrowserCookies")
        cmd("Page.navigate", {"url": "https://zgs.chsi.com.cn/login"})
        print("[OK] 已退出当前账号，请在浏览器窗口里登录要刷的账号。")
    except Exception as e:
        print("[!!] 清空登录态失败: %s" % e)
        ws.close()
        return None
    finally:
        try:
            ws.close()
        except Exception:
            pass

    old = (old_token or "").strip()
    deadline = time.time() + wait_seconds
    start = time.time()
    last_hint = 0
    while time.time() < deadline:
        if int(time.time() - start) - last_hint >= 20:
            last_hint = int(time.time() - start)
            print("  ...等待新账号登录（已等%d秒）" % last_hint)
        t, _ = _read_token_via_cdp(port)
        if t and t != old:
            print()
            print("[OK] 检测到新账号的登录态")
            return _with_bearer(t)
        time.sleep(3)
    print()
    print("[!!] 等待超时，未检测到新账号登录")
    return None


def confirm_account():
    """
    显示当前 Token 对应的账号，并允许切换。
    支持多账号场景：帮同学刷时，直接切到他的号即可。
    返回 True=可以继续。
    """
    info = fetch_account()
    if not info:
        print("[!!] 无法读取账号信息（Token可能无效，或浏览器里的登录态已过期）")
        return False
    name = info.get("name") or "未知"
    phone = mask_phone(info.get("mobile"))
    uid = str(info.get("uid") or "")

    print()
    print("=" * 56)
    print("  本次使用的账号：%s  （手机 %s，uid %s）" % (name, phone, uid))
    print("  账号来源：%s" % (TOKEN_SOURCE or "缓存Token"))
    print("=" * 56)

    last = str(CFG.get("last_uid") or "")
    if last and last != uid:
        print("（提示：上一次运行用的是 uid=%s，这次换成了 uid=%s —— 如果是有意换号，忽略即可）" % (last, uid))
    elif last == uid:
        print("（和上次是同一个账号）")

    print("  本次所有内容都会写进这个账号。")
    print("  · 回车    = 就用这个账号开刷")
    print("  · 输入 s  = 切换账号（清空浏览器登录态，重新登录，可帮别人刷）")

    c = (ask("选择: ") or "").strip().lower()
    if c == "s":
        new_token = switch_account(CFG.get("token") or "")
        if not new_token:
            print("[!!] 切换账号未完成")
            return False
        CFG["token"] = new_token
        save_config()
        global TOKEN
        TOKEN = new_token
        return confirm_account()  # 重新展示新账号

    CFG["last_uid"] = uid
    save_config()
    return True


# ===============================================================
# 运行
# ===============================================================
def run_all(token, only=None):
    global TOKEN
    TOKEN = token
    ok, fail = [], []
    verify_rows = []
    for idx, (sid, name, func) in enumerate(BARRIERS, 1):
        if only and idx not in only:
            continue
        print("\n========== [%d/8] %s ==========" % (idx, name), flush=True)
        try:
            if func in (barrier6, barrier7):  # 多子任务关卡：循环到完成
                for loop in range(30):
                    if not func(token):
                        break
                    time.sleep(1.5)
                else:
                    raise ApiError("子任务循环超过30次，中止")
            else:
                func(token)
        except TokenError as e:
            print("\n[!!] Token失效: %s" % e)
            print("  回车=重新自动登录（推荐） | 输入 m=手动粘贴Token | 输入 q=退出")
            c = ask("选择: ", "r")
            if c.lower() == "q":
                fail.append(name)
                verify_rows.append((name, False, "Token失效"))
                break
            if c.lower() == "m":
                t = ask("粘贴新Token（回车=放弃）: ")
            else:
                print("正在打开浏览器窗口...")
                t = browser_login_cdp() or ""
            if len(t) >= 20:
                CFG["token"] = t
                save_config()
                return run_all(t)
            fail.append(name)
            verify_rows.append((name, False, "Token失效"))
            break
        except ApiError as e:
            print("[!!] %s 失败: %s" % (name, e))
            c = ask("     回车=跳过该关继续跑后面的关卡，输入 r=停止并退出（之后可重跑续刷）: ")
            fail.append(name)
            verify_rows.append((name, False, str(e)[:40]))
            if (c or "").strip().lower() == "r":
                print("     已停止。重新运行即可续刷。")
                break
            time.sleep(1.2)
            continue

        # ★ 关键：不信任"没报错"，回读服务端验证是否真的完成
        time.sleep(0.8)
        real_ok, detail = verify_barrier(int(sid))
        verify_rows.append((name, real_ok, detail))
        if real_ok:
            ok.append(name)
            print("[OK] %s 完成（已回读校验）" % name, flush=True)
        else:
            fail.append(name)
            print("[!!] %s 未真正完成 → %s" % (name, detail), flush=True)
        time.sleep(1.2)

    # 汇总：以服务端回读为准
    print("\n" + "=" * 56)
    print("服务端回读校验结果：")
    for nm, r_ok, detail in verify_rows:
        print("  %s %-6s  %s" % ("✅" if r_ok else "❌", nm, detail))
    truly_done = [nm for nm, r, _ in verify_rows if r]
    truly_fail = [nm for nm, r, _ in verify_rows if not r]
    print("-" * 56)
    print("真正完成 %d/8 关" % len(truly_done))
    if truly_fail:
        print("未完成/需处理: %s" % "、".join(truly_fail))
        if len(truly_done) == 0:
            print("\n⚠ 一关都没真正完成，常见原因：")
            print("   1) 账号不对（内容写进了别的账号）——见上方账号确认")
            print("   2) 还没有点「报名参赛」——先去官网报名入口完成报名")
            print("   3) Token 已过期——重新运行会自动重新登录")
    print("=" * 56)
    return ok, fail


def dry_run():
    """离线自检：验证所有字段的生成长度合规"""
    print("== 离线自检：验证答案生成引擎（不联网） ==\n")
    specs = [
        ("b1.intro", 100, 300), ("b1.retrospect", 100, 500),
        ("b2.major_course", 210, 300), ("b2.identity_change", 210, 300),
        ("b3.profession", 80, 95), ("b3.interviewer", 110, 150),
        ("b4.factor", 50, 100), ("b4.report", 100, 300),
        ("b5.job_name", 10, 20), ("b5.tidy.interest_meet", 10, 30), ("b5.new_know", 110, 250),
        ("b6.skill.knowledge", 15, 95), ("ach.situation", 55, 95), ("b6.comprehension", 100, 490),
        ("b7.behavior", 100, 150), ("b7.comprehension", 100, 490),
    ]
    bad = 0
    for key, mn, mx in specs:
        t = template_text(key, mn, mx)
        ok = mn <= len(t) <= mx
        bad += 0 if ok else 1
        print("  %s [%s] %s (len=%d)" % ("[OK]" if ok else "[!!]", key, mode_name(), len(t)))
    s = gen_skill_text()
    ok = 15 <= len(s) <= 95
    bad += 0 if ok else 1
    print("  %s [技能词条] %s (len=%d)" % ("[OK]" if ok else "[!!]", s[:40] + "...", len(s)))
    print("\n" + ("[OK] 全部通过，可以正式运行: python 刷生涯闯关.py" if bad == 0 else "[!!] %d 项异常" % bad))
    return bad == 0


def mode_name():
    return {"template": "模板", "ai": "AI", "random": "随机"}.get(CFG["mode"], CFG["mode"])


def main():
    global CFG
    args = [a for a in sys.argv[1:]]
    fresh = "--fresh" in args
    if "--switch-account" in args:
        load_config()
        t = switch_account(CFG.get("token") or "")
        if t:
            CFG["token"] = t
            save_config()
            print("[OK] 已切换到新账号，下次运行会用它。")
            sys.exit(0)
        sys.exit(1)

    if "--dry" in args:
        load_config()
        ok = dry_run()
        sys.exit(0 if ok else 1)

    print("=" * 56)
    print("   生涯闯关自动刷 · Python")
    print("=" * 56)

    load_config()
    if fresh:
        CFG = json.loads(json.dumps(DEFAULT_CONFIG))
    setup()

    # ★ 以浏览器当前登录为准：弹窗里登了谁的号，就刷谁的号
    global TOKEN, TOKEN_SOURCE
    bt = browser_current_token()
    TOKEN_SOURCE = "缓存Token"
    if bt:
        if bt != CFG.get("token"):
            print("[i] 浏览器里登录的账号与缓存的不同，已按浏览器登录态为准。")
        CFG["token"] = bt
        TOKEN_SOURCE = "浏览器实时登录态"
        save_config()

    TOKEN = (CFG.get("token") or "").strip()
    if len(TOKEN) < 20:
        print("[!!] 未获取到Token")
        return
    if not confirm_account():
        return

    print("\n当前模式: " + mode_name())
    overwrite = "--overwrite" in args
    if not overwrite:
        c = ask("\n选择执行方式（回车=常规刷/续刷）：\n"
                "  1) 常规刷（自动跳过官网已完成的关卡）\n"
                "  2) 覆盖重刷（用当前模式重新生成全部可覆盖的内容，适合想替换之前模板/AI答案）\n"
                "选择 [1/2]，回车=1: ", "1")
        overwrite = c.strip() == "2"

    if overwrite:
        run_overwrite()
    else:
        print("开始闯关，过程中请勿关闭本窗口...\n")
        only = None
        if "--only" in args:
            try:
                only = {int(x) for x in args[args.index("--only") + 1].split(",")}
                print("只执行关卡: %s" % sorted(only))
            except Exception:
                print("[!!] --only 参数格式应为 --only 1,3,5")
        ok, fail = run_all(CFG["token"], only=only)
        print("\n" + "=" * 56)
        if not fail:
            print("[OK] 全部 8 关执行完毕！去官网刷新页面查看结果。")
            print("     如果官网某格显示未完成，重新运行本脚本即可补跑。")
        else:
            print("已完成: %s" % ("、".join(ok) if ok else "无"))
            print("失败于: %s（按上方提示处理后重新运行，会自动续跑）" % "、".join(fail))
        print("=" * 56)
    try:
        input("\n按回车键退出...")
    except EOFError:
        pass


if __name__ == "__main__":
    main()
