# -*- coding: utf-8 -*-
"""AI 项目信息收集平台 - 全局配置"""

import os
import urllib.parse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------- 存储路径 ----------
DATA_DIR = os.path.join(BASE_DIR, "data")
REPORT_DIR = os.path.join(BASE_DIR, "reports")
LOG_DIR = os.path.join(BASE_DIR, "logs")
DB_PATH = os.path.join(DATA_DIR, "ai_news.db")

# ---------- 抓取设置 ----------
FETCH_TIMEOUT = 25          # 单个请求超时（秒）
MAX_ITEMS_PER_SOURCE = 40   # 每个数据源最多保留条数
GITHUB_LOOKBACK_DAYS = 7    # GitHub 只看最近 N 天创建的仓库
GITHUB_TOKEN = ""           # 可选：填写 GitHub Token 可提升 API 配额

# HuggingFace 主站与镜像（主站不通时自动切换，国内网络常用）
HF_HOSTS = ["https://huggingface.co", "https://hf-mirror.com"]

# 综合类信息源的「AI 相关」过滤词：标题/摘要至少命中一个才保留
RELEVANCE_KEYWORDS = [
    "AI", "人工智能", "大模型", "LLM", "GPT", "生成式", "智能体", "Agent",
    "机器学习", "深度学习", "神经网络", "OpenAI", "ChatGPT", "Claude",
    "Gemini", "文心", "通义", "豆包", "DeepSeek", "Kimi", "智谱", "混元",
    "算力", "英伟达", "NVIDIA", "Sora", "Midjourney", "AIGC", "多模态",
    "自动驾驶", "机器人", "Copilot", "Diffusion", "开源模型",
]

# 分类偏置：给特定来源的分类计分加权（如 arXiv 论文更倾向归入「研究前沿」）
SOURCE_CATEGORY_BIAS = {
    "arxiv": {"research": 1},
}

# 类目得分权重：免费/羊毛信息一旦命中就该归入「限时免费」，避免被
# 开源/行业等高频词压过（其余类目权重 1）
CATEGORY_WEIGHT = {"freebie": 2.0}

# ---------- 事件聚类 ----------
CLUSTER_SIMILARITY = 0.60   # 标题归一化后的相似度阈值（0~1，越高越严格）

# ---------- 数据源健康监控 ----------
SOURCE_FAIL_ALERT_STREAK = 3    # 连续失败达到该天数时在报告页脚告警

# ---------- 周报 ----------
WEEKLY_WINDOW_DAYS = 7      # 统计窗口
WEEKLY_TOP_N = 15           # 本周热门条数
WEEKLY_GH_GAIN_TOP = 10     # GitHub 周增星榜条数

# ---------- 英文自动翻译 ----------
# True: 将英文标题/摘要翻译为中文
# 后端自动降级（互为备份）：LLM（配置了 LLM_API_KEY 时）→ MyMemory → Google
TRANSLATE_ENABLED = True
TRANSLATE_MAX_PER_RUN = 300     # 单次运行最多翻译的文本条数（配合缓存分批完成）
TRANSLATE_MYMEMORY_EMAIL = ""   # 可选：填入邮箱将 MyMemory 免费配额从 5k 提升到 5w 字/日
TRANSLATE_CACHE = True          # 相同原文复用翻译结果（落库），避免重复打限流严重的免密钥接口

# 每日定时运行时间（--loop 模式使用，24 小时制）
DAILY_RUN_TIME = "08:30"

# 请求头：部分站点会拦截默认 UA，统一伪装成浏览器
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# ---------- 数据源 ----------
# type: github | hf_models | hf_spaces | arxiv | rss
SOURCES = [
    {"name": "GitHub 热门新项目", "type": "github", "enabled": True},
    {"name": "HuggingFace 热门模型", "type": "hf_models", "enabled": True},
    {"name": "HuggingFace 热门应用", "type": "hf_spaces", "enabled": True},
    {"name": "arXiv 最新论文", "type": "arxiv", "enabled": True,
     "categories": ["cs.CL", "cs.AI", "cs.LG"]},
    # 综合类国内源：开启 ai_only 过滤，只保留 AI 相关内容
    {"name": "IT之家", "type": "rss", "enabled": True, "ai_only": True,
     "url": "https://www.ithome.com/rss/"},
    {"name": "爱范儿", "type": "rss", "enabled": True, "ai_only": True,
     "url": "https://www.ifanr.com/feed"},
    {"name": "TechCrunch AI", "type": "rss", "enabled": True,
     "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
    {"name": "The Verge AI", "type": "rss", "enabled": True,
     "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},
    {"name": "Hacker News (高赞 AI)", "type": "rss", "enabled": True,
     "url": "https://hnrss.org/newest?q=LLM+OR+%22AI+agent%22+OR+GPT&points=80"},
    # 限时免费线报：HN 上关于免费额度/试用/免费档的讨论（ai_only 过滤非 AI 内容）
    {"name": "HN 免费/额度线报", "type": "rss", "enabled": True, "ai_only": True,
     "url": "https://hnrss.org/newest?q=%22free+credits%22+OR+%22free+trial%22+OR+%22free+tier%22&points=20"},
    # 限时免费线报：Reddit r/LocalLLaMA 社区的免费访问/额度/试用帖（引号短语精准过滤）
    {"name": "Reddit 免费线报", "type": "rss", "enabled": True,
     "url": "https://www.reddit.com/r/LocalLLaMA/search.rss?"
            "q=%22free+credits%22+OR+%22free+trial%22+OR+%22free+access%22+OR+%22free+tier%22+OR+%22unlimited+access%22"
            "&restrict_sr=1&sort=new&t=week"},
    # 中文 AI 媒体：厂商免费活动（如限时免费无限制访问）多由其报道
    {"name": "量子位", "type": "rss", "enabled": True,
     "url": "https://www.qbitai.com/feed"},
    # 限时免费线报：Bing 新闻主动搜索（多词 AND，命中厂商免费活动报道）
    {"name": "Bing 中文免费线报", "type": "rss", "enabled": True,
     "url": "https://www.bing.com/news/search?q=" +
            urllib.parse.quote("大模型 免费") + "&format=RSS"},
    {"name": "Bing 英文免费线报", "type": "rss", "enabled": True,
     "url": "https://www.bing.com/news/search?q=" +
            urllib.parse.quote("LLM free credits") + "&format=RSS"},
    # 放在最后：该源已做内容提炼与精选，同一 URL 会覆盖前面源的原始摘要
    {"name": "AI Hot 每日精选", "type": "aihot", "enabled": True,
     "url": "https://aihot.virxact.com"},
]

# GitHub 搜索的主题词（按 star 排序的新建仓库）
GITHUB_TOPICS = ["llm", "ai-agents", "rag", "text-to-image", "machine-learning"]

# ---------- 分类体系 ----------
# key: 英文标识(用于锚点), name: 中文显示, color: 主题色, emoji: 图标
CATEGORIES = {
    "foundation": {"name": "大模型发布", "color": "#6366f1", "emoji": "🧠"},
    "agents":     {"name": "智能体与应用", "color": "#10b981", "emoji": "🤖"},
    "multimodal": {"name": "多模态生成", "color": "#f59e0b", "emoji": "🎨"},
    "opensource": {"name": "开源项目与工具", "color": "#0ea5e9", "emoji": "🛠️"},
    "freebie":    {"name": "限时免费", "color": "#ec4899", "emoji": "🎁"},
    "research":   {"name": "研究前沿", "color": "#8b5cf6", "emoji": "🔬"},
    "policy":     {"name": "政策与安全", "color": "#ef4444", "emoji": "⚖️"},
    "industry":   {"name": "行业动态", "color": "#64748b", "emoji": "📈"},
}

# 各数据源无关键词命中时的兜底分类
DEFAULT_CATEGORY_BY_TYPE = {
    "github": "opensource",
    "hf_models": "foundation",
    "hf_spaces": "opensource",
    "arxiv": "research",
    "rss": "industry",
    "aihot": "industry",
}

# 中英文关键词（子串匹配，不区分大小写，命中数最多者获胜）
KEYWORDS = {
    "foundation": [
        "大模型", "基座模型", "预训练", "LLM", "Large Language Model",
        "Foundation Model", "GPT", "Claude", "Gemini", "Llama",
        "通义千问", "Qwen", "文心一言", "ERNIE", "混元", "豆包",
        "DeepSeek", "Kimi", "GLM", "智谱", "MiniMax", "百川", "Mistral",
        "Grok", "开源权重", "模型发布", "参数量", "MoE", "推理模型",
    ],
    "agents": [
        "Agent", "智能体", "多智能体", "Multi-Agent", "工作流", "Workflow",
        "Copilot", "AutoGPT", "Manus", "数字员工", "编程助手", "代码助手",
        "Coding Agent", "任务规划", "工具调用", "Function Call", "Computer Use",
    ],
    "multimodal": [
        "多模态", "Multimodal", "图像生成", "视频生成", "文生图", "文生视频",
        "Text-to-Image", "Text-to-Video", "Diffusion", "扩散模型",
        "Stable Diffusion", "Midjourney", "Sora", "可灵", "即梦",
        "语音识别", "语音合成", "Speech", "TTS", "ASR", "数字人",
        "3D生成", "音乐生成", "视觉语言", "VLM", "OCR",
    ],
    "opensource": [
        "开源", "Open Source", "Open-Source", "GitHub", "框架", "Framework",
        "微调", "Fine-tune", "LoRA", "RAG", "检索增强", "向量数据库",
        "推理加速", "量化", "Quantization", "部署", "Inference", "vLLM",
        "算力", "GPU", "CUDA", "工具链", "SDK", "本地部署", "端侧",
    ],
    "freebie": [
        # 限时免费 / 短期免费服务：API 额度、token、试用 key、羊毛线报
        "限时免费", "免费额度", "免费试用", "试用资格", "试用密钥", "试用key", "试用 Key",
        "免费领", "免费送", "白嫖", "免费token", "免费 Token", "免费tokens",
        "免费API", "免费 API", "限量免费", "限时开放", "免费开放", "赠送额度",
        "免费无限制", "不限量", "免费畅享", "免费访问", "限免",
        "free credits", "free credit", "free trial", "free tier", "free tokens",
        "limited-time free", "limited time free", "free for a limited",
        "free unlimited", "unlimited free", "no usage limits",
        "for free", "free access",
        "giveaway", "promo code", "redeem code", "free API key",
    ],
    "research": [
        "论文", "Paper", "arXiv", "研究", "Research", "突破", "Benchmark",
        "基准测试", "评测", "NeurIPS", "ICML", "ICLR", "强化学习",
        "Reinforcement Learning", "RLHF", "对齐", "Alignment", "可解释",
        "Scaling Law", "思维链", "Chain-of-Thought", "Reasoning", "推理能力",
        "世界模型", "具身智能", "Embodied",
    ],
    "policy": [
        "监管", "政策", "法规", "合规", "安全", "Safety", "隐私",
        "版权", "诉讼", "伦理", "备案", "深度伪造", "Deepfake",
        "滥用", "风险", "立法", "法案", "数据跨境", "开源协议",
    ],
    "industry": [
        "融资", "投资", "估值", "收购", "上市", "财报", "营收",
        "商业化", "合作", "发布会", "裁员", "招聘", "市场", "产业",
        "独角兽", "OpenAI", "Anthropic", "谷歌", "Google", "微软",
        "Microsoft", "Meta", "百度", "阿里", "腾讯", "字节", "华为",
        "英伟达", "NVIDIA", "苹果", "Apple", "小米",
    ],
}

# 分类优先级：决定导航条与卡片分区的展示顺序
CATEGORY_PRIORITY = ["foundation", "multimodal", "agents", "freebie",
                     "opensource", "industry", "research", "policy"]

# ---------- 可选增强：接入大模型改写摘要 ----------
# 填写 OpenAI 兼容接口后自动启用（例如 https://api.openai.com/v1）；
# 留空则使用本地规则提取摘要，完全离线可用。
LLM_API_BASE = ""       # 例: https://api.openai.com/v1
LLM_API_KEY = ""        # 例: sk-xxx
LLM_MODEL = "gpt-4o-mini"

# 环境变量优先：GitHub Actions 里用 Secrets 注入密钥，避免把 Key 写进仓库
LLM_API_BASE = os.environ.get("LLM_API_BASE", LLM_API_BASE)
LLM_API_KEY = os.environ.get("LLM_API_KEY", LLM_API_KEY)
LLM_MODEL = os.environ.get("LLM_MODEL", LLM_MODEL)
