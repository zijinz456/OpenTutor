"""Intent router with rule pre-matching + LLM fallback.

Borrows from:
- OpenAkita multi-layer routing: rules first, LLM for ambiguous cases
- OpenClaw binding router: keyword → agent mapping
- Spec Section 2: Intent Router with LEARN / ACTION / PREF classification

Enhancement over original: two-stage routing (regex → LLM) for robustness.
"""

import json
import re
import logging

from services.agent.state import AgentContext, IntentType
from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)

# ── Stage 1: Rule-based pre-matching (high confidence, zero latency) ──

INTENT_RULES: list[tuple[IntentType, re.Pattern, float]] = [
    # Layout actions (highest priority — direct UI control)
    (IntentType.LAYOUT, re.compile(
        r"(放大|缩小|全屏|布局|layout|resize|maximize|minimize|expand|collapse|"
        r"set_layout|换个布局)", re.IGNORECASE
    ), 0.95),

    # v3: Scene switch signals (high priority — goal/mode change)
    (IntentType.SCENE_SWITCH, re.compile(
        r"(准备考试|开始复习|考前冲刺|要考试了|有考试|prepare\s+for\s+exam|"
        r"exam\s+prep|start\s+review|做作业|写作业|这个作业|this\s+assignment|"
        r"homework\s+help|错题专练|复习错题|review\s+mistakes|"
        r"切换到|switch\s+to\s+.*(mode|模式)|整理笔记|organize\s+notes)", re.IGNORECASE
    ), 0.90),

    # Explicit preference changes
    (IntentType.PREFERENCE, re.compile(
        r"(太长了|太短了|换成|改成|我喜欢|我不喜欢|我偏好|prefer|switch\s+to|"
        r"change\s+to|too\s+(long|short|detailed|brief)|make\s+it)", re.IGNORECASE
    ), 0.90),

    # Quiz / Exercise
    (IntentType.QUIZ, re.compile(
        r"(出题|出几道|练习|quiz|exercise|test\s+me|给我出|做题|"
        r"generate\s+(quiz|question|questions|problem|practice\s+questions)|"
        r"generate\s+\d+\s+practice\s+questions|来道题)", re.IGNORECASE
    ), 0.90),

    # Study plan
    (IntentType.PLAN, re.compile(
        r"(学习计划|study\s+plan|复习计划|review\s+schedule|安排|plan\s+for|"
        r"how\s+should\s+I\s+study|帮我规划|study\s+schedule|schedule\s+for\s+finals|create\s+a\s+study\s+schedule)", re.IGNORECASE
    ), 0.90),

    # Error review / analysis
    (IntentType.REVIEW, re.compile(
        r"(错因|为什么错|wrong|mistake|error\s+analysis|错题|review\s+my|"
        r"what\s+did\s+I\s+get\s+wrong|哪里错了|错了什么|做错了什么)", re.IGNORECASE
    ), 0.85),

    # Code execution / programming (before LEARN to catch code-related queries first)
    (IntentType.CODE, re.compile(
        r"(运行|执行|run\s+(this|my|the)\s+code|debug|编程|代码|```python|"
        r"代码执行|code\s+execution|写个程序|write\s+a?\s*program|帮我跑|"
        r"这段代码|this\s+code|compile|编译)", re.IGNORECASE
    ), 0.90),

    # Course structure / curriculum analysis
    (IntentType.CURRICULUM, re.compile(
        r"(课程结构|知识图谱|大纲|syllabus|curriculum|前置知识|prerequisite|"
        r"知识点关系|topic\s+hierarchy|course\s+structure|章节|学习路径|"
        r"learning\s+path|依赖关系|dependency|这门课.*结构|课程.*结构)", re.IGNORECASE
    ), 0.85),

    # Learning assessment / progress report
    (IntentType.ASSESS, re.compile(
        r"(评估|assessment|我的进度|学习报告|progress\s+report|report|"
        r"薄弱|weak\s+area|学习情况|how\s+am\s+I\s+doing|考试准备度|"
        r"exam\s+readiness|掌握情况|mastery)", re.IGNORECASE
    ), 0.85),

    # Learning / knowledge questions (broadest, lowest priority)
    (IntentType.LEARN, re.compile(
        r"(什么是|解释|explain|what\s+is|how\s+does|why\s+does|define|概念|"
        r"tell\s+me\s+about|帮我理解|teach\s+me|不懂|不太明白|clarify)", re.IGNORECASE
    ), 0.80),
]


def rule_match(message: str) -> tuple[IntentType, float] | None:
    """Stage 1: Fast regex-based intent detection.

    Returns (intent, confidence) if a rule matches, else None.
    """
    for intent, pattern, confidence in INTENT_RULES:
        if pattern.search(message):
            return intent, confidence
    return None


# ── Stage 2: LLM classification (for ambiguous cases) ──

CLASSIFICATION_PROMPT = """Classify the student's message into ONE intent category.

Categories:
- learn: Knowledge question, explanation request, concept clarification
- quiz: Request to generate quiz, exercise, practice problems
- plan: Request for study plan, schedule, learning roadmap
- review: Review errors, analyze mistakes, wrong answer analysis
- preference: Change display settings, learning style preference
- layout: Change UI layout (panel sizes, fullscreen)
- scene_switch: Goal/mode change — preparing for exam, starting homework, switching to review mode, organizing notes
- code: Code execution, programming help, debugging, running code snippets
- curriculum: Course structure analysis, knowledge graph, prerequisites, syllabus
- assess: Learning assessment, progress report, mastery check, weak areas
- general: General chat, greeting, off-topic

Output JSON: {{"intent": "<category>", "confidence": <0.0-1.0>}}

Student message: {message}"""


async def llm_classify(message: str) -> tuple[IntentType, float]:
    """Stage 2: LLM-based classification for ambiguous messages."""
    client = get_llm_client()
    try:
        result, _ = await client.extract(
            "You are an intent classifier. Output only valid JSON.",
            CLASSIFICATION_PROMPT.format(message=message[:300]),
        )
        result = result.strip()
        if "```" in result:
            json_start = result.find("{")
            json_end = result.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                result = result[json_start:json_end]

        data = json.loads(result)
        intent_str = data.get("intent", "general")
        confidence = float(data.get("confidence", 0.5))

        try:
            intent = IntentType(intent_str)
        except ValueError:
            intent = IntentType.GENERAL
            confidence = 0.3

        return intent, confidence

    except Exception as e:
        logger.warning("LLM intent classification failed: %s", e)
        return IntentType.GENERAL, 0.3


async def classify_intent(ctx: AgentContext) -> AgentContext:
    """Two-stage intent classification: rules first, LLM fallback.

    Updates ctx.intent and ctx.intent_confidence in-place.
    """
    message = ctx.user_message

    # Stage 1: Rule matching (fast, high precision)
    rule_result = rule_match(message)
    if rule_result:
        intent, confidence = rule_result
        ctx.intent = intent
        ctx.intent_confidence = confidence
        logger.info(
            "Intent classified by RULE: %s (conf=%.2f) msg=%s",
            intent.value, confidence, message[:60],
        )
        return ctx

    # Stage 2: LLM classification (slower, handles ambiguity)
    intent, confidence = await llm_classify(message)
    ctx.intent = intent
    ctx.intent_confidence = confidence
    logger.info(
        "Intent classified by LLM: %s (conf=%.2f) msg=%s",
        intent.value, confidence, message[:60],
    )
    return ctx
