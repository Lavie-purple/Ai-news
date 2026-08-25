# -*- coding: utf-8 -*-
"""分类与评分：关键词自动分类、热度打分、摘要提取、可选大模型润色。"""

import json
import math
import re
import time
import urllib.request
from datetime import datetime, timedelta

import config


# ---------------------------------------------------------------- 分类
def classify(item):
    """按中英文关键词计分（叠加来源偏置），返回得分最高的分类 key；无命中时用数据源兜底。"""
    tags = " ".join(item.get("tags") or [])
    text = f"{item['title']} {item.get('summary', '')} {tags}".lower()
    bias = config.SOURCE_CATEGORY_BIAS.get(item["source_type"], {})
    best_key, best_score = None, 0
    for key in config.CATEGORY_PRIORITY:
        score = sum(1 for kw in config.KEYWORDS[key] if kw.lower() in text)
        score += bias.get(key, 0)
        if score > best_score:
            best_key, best_score = key, score
    if best_key:
        return best_key
    return config.DEFAULT_CATEGORY_BY_TYPE.get(item["source_type"], "industry")


# ---------------------------------------------------------------- 热度评分
def raw_score(item):
    """原始热度分：社区指标(对数) + 新鲜度加成 + 数据源权重。"""
    m = item.get("metrics") or {}
    s = 0.0
    if m.get("stars"):
        s += math.log10(m["stars"] + 1) * 3.0
    if m.get("downloads"):
        s += math.log10(m["downloads"] + 1) * 2.2
    if m.get("likes"):
        s += math.log10(m["likes"] + 1) * 2.5
    # AI Hot 精选站的编辑/模型评分（约 50~90 分区间），线性折算为加分
    if m.get("site_score"):
        s += m["site_score"] * 0.04

    published = item.get("published_at")
    if published:
        try:
            age_h = (datetime.utcnow() -
                     datetime.strptime(published[:19], "%Y-%m-%dT%H:%M:%S")).total_seconds() / 3600
            if age_h < 24:
                s += 3.0
            elif age_h < 72:
                s += 1.5
            elif age_h < 24 * 7:
                s += 0.6
        except ValueError:
            pass

    weight = {"github": 1.5, "hf_models": 1.4, "hf_spaces": 1.2,
              "arxiv": 1.2, "rss": 1.3, "aihot": 1.6}.get(item["source_type"], 1.0)
    return s * weight


def normalize_scores(items):
    """将原始分映射到 20~100 的展示分数。"""
    if not items:
        return
    scores = [raw_score(it) for it in items]
    lo, hi = min(scores), max(scores)
    for it, sc in zip(items, scores):
        it["score_raw"] = round(sc, 2)
        if hi - lo < 1e-9:
            it["score"] = 60
        else:
            it["score"] = int(round(20 + 80 * (sc - lo) / (hi - lo)))


# ---------------------------------------------------------------- 摘要
_TAG_RE = re.compile(r"<[^>]+>")

def extract_summary(text, limit=180):
    """规则版摘要：清洗 HTML、压缩空白、截断到句子边界。"""
    if not text:
        return ""
    s = _TAG_RE.sub(" ", text)
    s = re.sub(r"\s+", " ", s).strip()
    # arXiv 摘要去掉常见前缀
    s = re.sub(r"^(Abstract|摘要)[:：\s]*", "", s, flags=re.I)
    if len(s) <= limit:
        return s
    cut = s[:limit]
    for sep in ["。", ". ", "！", "! ", "？", "? ", "；", "; "]:
        pos = cut.rfind(sep)
        if pos > limit // 2:
            return cut[: pos + 1].strip()
    return cut.rstrip() + "…"


# ---------------------------------------------------------------- 可选：LLM 润色
def _chat(prompt, timeout=60):
    """调用 OpenAI 兼容接口，返回回复文本。未配置时抛 RuntimeError。"""
    if not (config.LLM_API_BASE and config.LLM_API_KEY):
        raise RuntimeError("LLM 未配置")
    body = json.dumps({
        "model": config.LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{config.LLM_API_BASE.rstrip('/')}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {config.LLM_API_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def llm_polish(items, batch_size=8, max_batches=4):
    """
    若配置了 OpenAI 兼容接口，则对热度最高的前若干条批量改写中文摘要。
    失败时静默回退到本地提取的摘要，不影响主流程。
    """
    done = 0
    top_items = sorted(items, key=lambda x: x.get("score", 0), reverse=True)
    for i in range(0, min(len(top_items), batch_size * max_batches), batch_size):
        chunk = top_items[i: i + batch_size]
        lines = [f"{j+1}. [{it['source']}] {it['title']}\n   原始信息: {extract_summary(it.get('summary',''), 300)}"
                 for j, it in enumerate(chunk)]
        prompt = (
            "以下是今日 AI 领域资讯条目。请为每条生成一句不超过60字的简体中文摘要，"
            "突出它是什么、为什么重要。输出 JSON 数组，元素为字符串，顺序与输入一致。\n\n"
            + "\n".join(lines)
        )
        try:
            content = _chat(prompt).strip()
            content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.M).strip()
            summaries = json.loads(content)
            for it, sm in zip(chunk, summaries):
                if isinstance(sm, str) and sm.strip():
                    it["summary_final"] = sm.strip()
                    done += 1
        except Exception as e:
            print(f"    [提示] LLM 摘要批次失败（已回退本地摘要）: {e}")
        time.sleep(1)
    return done


def llm_daily_brief(top_items):
    """
    基于当日热度最高的条目生成一段编辑视角的中文综述。
    未配置 LLM 或调用失败时返回 None（由调用方回退热词展示）。
    """
    if not top_items:
        return None
    date_str = datetime.now().strftime("%Y-%m-%d")
    lines = [f"- {it['title']}｜{extract_summary(it.get('summary', ''), 80)}"
             for it in top_items]
    prompt = (
        f"以下是 {date_str} 抓取到的 AI 领域热门资讯（按热度排序）。"
        "请以科技编辑的视角写一段 280 字以内的简体中文综述：提炼当天最重要的 "
        "3~5 个动态或趋势，说明它们之间的关联与值得关注的理由。"
        "要求：直接输出正文，不要标题、列表和客套话；语气专业克制。\n\n"
        + "\n".join(lines)
    )
    try:
        brief = _chat(prompt).strip()
        return re.sub(r"^```(?:markdown)?|```$", "", brief, flags=re.M).strip() or None
    except Exception as e:
        print(f"    [提示] 今日综述生成失败（回退热词模式）: {e}")
        return None


# 可作为「今日热词」的具体模型品牌（按长度降序排列，长名优先匹配）
_MODEL_BRANDS = [
    "StableDiffusion", "Qwen", "DeepSeek", "MiniMax", "Mistral", "Midjourney",
    "Llama", "Kimi", "Hunyuan", "Gemma", "GLM", "Groq", "Grok", "Gemini",
    "Ernie", "Doubao", "Claude", "Baichuan", "Whisper", "SenseNova", "Sora",
    "Phi", "GPT", "Yi", "Step", "Abab", "Command",
]
# 品牌 (捕获组1) + 可选版本/参数量 (捕获组2)：
#   \d...        紧跟数字，如 3.8-27B / 405B
#   [.\-]X...    连字符/点 + 字母或数字，如 -H3 / -4o / .5
#   " 数字...    空格 + 数字，如 Claude 3.5 / Llama 3.1
_MODEL_RE = re.compile(
    r"(?<![A-Za-z])(" + "|".join(re.escape(b) for b in _MODEL_BRANDS) + r")"
    r"(\d[\w.\-]*|[.\-][A-Za-z0-9][\w.\-]*| [0-9][\w.\-]*)?",
    re.I,
)
# 中文机构 / 产品名（剔除已覆盖的英文品牌，避免重复计数）
_BRAND_CN = ["小米", "华为", "阿里", "腾讯", "字节", "百度", "智谱", "通义", "文心",
             "豆包", "混元", "月之暗面", "阶跃星辰", "商汤", "讯飞", "昆仑万维",
             "百川", "零一万物"]
# 品牌小写 -> 规范写法（统一大小写，避免 MiniMax 与 minimax 被拆成两条）
_BRAND_CANON = {b.lower(): b for b in _MODEL_BRANDS}


def _version_display(v):
    """把版本片段规整为展示用字符串：保留空格分隔（Claude 3.5），截断尾部描述性小写词，
    字母开头的粘连版本补连字符（Kimi-K3）。"""
    if not v:
        return ""
    raw = v
    s = v.strip()
    if not s:
        return ""
    if raw[0] == " ":                          # 空格分隔版本（Claude 3.5）
        return s
    lead = ""
    if raw[0] in ".-":                         # 连字符/点开头的版本，去掉前导符稍后补回
        s = s[1:]
        lead = "-"
    parts = s.split("-")
    kept = [parts[0]]
    for p in parts[1:]:
        if re.search(r"\d", p) or (p and p[0].isupper()):
            kept.append(p)
        else:
            break                              # 遇 ultra/fast 等描述词即截断
    joined = "-".join(kept)
    if joined and joined[0].isalpha():
        joined = joined[0].upper() + joined[1:]   # h3 -> H3
    if lead == "" and joined and joined[0].isalpha():
        lead = "-"                            # 字母开头的粘连版本补连字符
    return lead + joined


def hot_words(items, top_n=8):
    """无 LLM 时的兜底热词：优先识别具体模型名（如 Qwen3.8-27B），其次中文机构名。
    返回的「次数」= 点选该热词后实际筛出的卡片数（与日报前端筛选逻辑一致），不再用提及频次。"""
    text = " ".join(it.get("title", "") for it in items)
    low = text.lower()

    brand_total = {}        # 品牌(小写) -> 总出现次数
    brand_display = {}      # 品牌(小写) -> 规范展示名（取首个出现的写法）
    brand_versions = {}     # 品牌(小写) -> {带版本的具体型号: 次数}
    for m in _MODEL_RE.finditer(text):
        low_brand = m.group(1).lower()
        canon = _BRAND_CANON.get(low_brand, m.group(1))
        ver = _version_display(m.group(2))
        disp = canon + ver
        brand_total[low_brand] = brand_total.get(low_brand, 0) + 1
        brand_display.setdefault(low_brand, disp)
        if ver and re.search(r"\d", disp) and len(disp) > len(canon):
            brand_versions.setdefault(low_brand, {})
            brand_versions[low_brand][disp] = brand_versions[low_brand].get(disp, 0) + 1

    cand = {}  # 展示词 -> 用于匹配的原文关键词
    for low_brand, cnt in brand_total.items():
        if cnt < 2:
            continue
        # 展示时用该品牌下最常见的具体型号，否则退化为品牌名
        ex = brand_versions.get(low_brand)
        name = max(ex, key=ex.get) if ex else brand_display[low_brand]
        cand[name] = name

    # 中文机构 / 产品名（整词命中）
    for b in _BRAND_CN:
        if low.count(b.lower()) >= 2:
            cand[b] = b

    # 以「点选后实际筛出的卡片数」作为热词计数：与前端筛选逻辑保持一致，
    # 规范化（去空格/连字符/标点，保留字母数字与中文）后做包含匹配，
    # 使 "Claude5" 也能命中标题里的 "Claude 5"。
    def _norm(s):
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", s.lower())

    freq = {}
    for name, kw in cand.items():
        nk = _norm(kw)
        if not nk:
            continue
        c = sum(1 for it in items
                if nk in _norm(it.get("title", "") + " " + it.get("summary", "")))
        if c >= 1:                       # 仅保留确实能筛出卡片的热词
            freq[name] = c
    return sorted(freq.items(), key=lambda x: -x[1])[:top_n]


# ---------------------------------------------------------------- 优势/亮点提炼
# 规则版「一句话亮点」：从标题+摘要中识别评测超越、SOTA、首个、参数量、开源水平等信号，
# 无 LLM 时也能给模型/智能体卡片补充「特殊点或优势点」补充说明。
_BEAT_RE = re.compile(r"(超越|超过|击败|力压|优于|领先于|打败)\s*([A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9.\-\u4e00-\u9fff]{0,15})", re.I)
_PACE_RE = re.compile(r"(媲美|比肩|接近|持平)\s*([A-Za-z0-9][A-Za-z0-9.\-]{0,15})", re.I)
_IMPROVE_RE = re.compile(r"(提升|提高|增加|增强|降低|减少|下降|缩短|压缩)\s*(\d+(?:\.\d+)?\s*%)", re.I)
_FAST_RE = re.compile(r"比\s*([A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9.\-\u4e00-\u9fff]{0,15}?)\s*(更快|快|强|高|领先)\s*(\d+(?:\.\d+)?\s*倍)?", re.I)
_PARAM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[Bb]\b")
_SOTA_RE = re.compile(r"(登顶|问鼎|刷新|打破|SOTA|世界第一|业界第一|全球第一|开源第一)", re.I)
_FIRST_RE = re.compile(r"首个|业界首款|全球首款")
_OPEN_RE = re.compile(r"(开源 SOTA|开源最强|开源达到|开源权重|开源模型|可商用|开放权重)", re.I)

# 英文优势信号（与中文规则并列，让 GitHub / arXiv 等英文条目也能提炼亮点）
_EN_BEAT_RE = re.compile(
    r"(outperform(?:s|ed|ing)?|beats?|surpass(?:es|ed)?|exceeds?|better than|"
    r"superior to|wins? over)\s+([A-Za-z0-9][A-Za-z0-9.\-]{0,20})", re.I)
_EN_IMPROVE_RE = re.compile(
    r"(cut|cuts|reduce|reduces|reduced|lower|lowers|improves?|increased?|boosts?|"
    r"speeds?\s*up|shrinks?|drops?)\w*\s+([A-Za-z\-]{1,14})\s+(?:by\s+)?"
    r"(\d+(?:\.\d+)?\s*%)", re.I)
_METRIC_CN = {
    "failures": "失败率", "failure": "失败率", "errors": "错误率", "error": "错误率",
    "cost": "成本", "costs": "成本", "latency": "延迟", "time": "耗时",
    "runtime": "耗时", "size": "体积", "memory": "显存", "params": "参数量",
    "loss": "损失", "risk": "风险", "price": "价格",
}
_EN_ALT_RE = re.compile(
    r"(alternative|replacement|substitute|successor)\s+(?:to|for)\s+"
    r"([A-Za-z0-9][A-Za-z0-9.\-]{0,20})", re.I)
_EN_FAST_RE = re.compile(
    r"(faster|lighter|smaller|cheaper|more accurate)\s+(?:than|vs\.?)\s+"
    r"([A-Za-z0-9][A-Za-z0-9.\-]{0,20})", re.I)
_EN_SOTA_RE = re.compile(r"\b(SOTA|state[- ]of[- ]the[- ]art)\b", re.I)
_EN_FIRST_RE = re.compile(r"\b(first open[- ]source|world'?s first|first-of-its-kind|novel)\b", re.I)
_EN_LOCAL_RE = re.compile(
    r"\b(fully local|100% local|on-device|local-first|runs? locally|"
    r"privacy[- ]preserving|zero (?:data )?leaving)\b", re.I)
_EN_IMPROVE_LABEL = {
    "cut": "降低", "reduce": "降低", "lower": "降低", "drop": "降低",
    "improve": "提升", "increase": "提升", "boost": "提升", "speed up": "加速",
    "shrink": "缩减",
}
_EN_FAST_LABEL = {
    "faster": "更快", "lighter": "更轻", "smaller": "更小",
    "cheaper": "更省", "more accurate": "更准",
}


def _fmt_num(n):
    n = int(n or 0)
    if n >= 10000:
        return f"{n / 10000:.0f}w"
    if n >= 1000:
        return f"{n / 1000:.0f}k"
    return str(n)


def extract_highlight(item):
    """返回该条目的一句话亮点（带前缀 emoji），突出「为何选它 / 比现有模型强在哪」。
    中英文信号都识别：无 LLM 也能给模型 / 智能体卡片补充「特殊点或优势点」说明。"""
    t = f"{item.get('title', '')} {item.get('summary', '')}"
    low = t.lower()
    # --- 性能超越（中 / 英） ---
    m = _BEAT_RE.search(t)
    if m and m.group(2).strip():
        return f"⚡ 性能超越 {m.group(2).strip()}（领先同类）"
    m = _EN_BEAT_RE.search(t)
    if m:
        tg = m.group(2).strip().rstrip(".,")
        if tg:
            return f"⚡ 性能超越 {tg}（领先同类）"
    # --- 指标提升（中 / 英） ---
    m = _IMPROVE_RE.search(t)
    if m:
        return f"📈 {m.group(1)}{m.group(2).replace(' ', '')}"
    m = _EN_IMPROVE_RE.search(t)
    if m:
        verb = m.group(1).lower()
        pct = m.group(3).replace(" ", "")
        metric = m.group(2).strip().lower()
        label = _EN_IMPROVE_LABEL.get(verb, "提升")
        cn = _METRIC_CN.get(metric, metric)
        if cn and len(cn) <= 6:
            return f"📉 {cn}{label} {pct}"
        return f"📈 效果{label} {pct}"
    # --- 比 X 更快 / 更轻（中 / 英） ---
    m = _FAST_RE.search(t)
    if m:
        tail = f" {m.group(3).replace(' ', '')}" if m.group(3) else ""
        return f"⚡ 比 {m.group(1).strip()} {m.group(2)}{tail}"
    m = _EN_FAST_RE.search(t)
    if m:
        tg = m.group(2).strip().rstrip(".,")
        if tg:
            return f"⚡ 比 {tg} {_EN_FAST_LABEL.get(m.group(1).lower(), '更强')}"
    # --- 开源替代 X（英文） ---
    m = _EN_ALT_RE.search(t)
    if m:
        tg = m.group(2).strip().rstrip(".,")
        if tg:
            return f"🛠 开源替代 {tg}"
    # --- 媲美（中文） ---
    m = _PACE_RE.search(t)
    if m:
        return f"⚡ 媲美 {m.group(2).strip()}"
    # --- SOTA / 首个（中 / 英） ---
    if _SOTA_RE.search(t) or _EN_SOTA_RE.search(t):
        return "🏆 登顶 / 刷新评测纪录"
    if _FIRST_RE.search(t) or _EN_FIRST_RE.search(t):
        return "🌟 业界首个（或首创方向）"
    # --- 指标对比：用下载量 / 星标做「热度领先」式对比（回答「为何选它」）---
    # 放在参数量之前：对开源模型，「海量下载 / 高星标」比单纯参数规模更能说明优势。
    mtex = item.get("metrics") or {}
    dl = mtex.get("downloads") or 0
    st = mtex.get("stars") or 0
    if dl and dl >= 1_000_000:
        return f"🔥 近30天下载 {_fmt_num(dl)}，开源热度领先"
    if st and st >= 10_000:
        return f"⭐ {_fmt_num(st)} 星标，社区关注度第一梯队"
    if dl and dl >= 500_000:
        return f"🔥 近30天下载 {_fmt_num(dl)}，开源人气靠前"
    if st and st >= 1000:
        return f"⭐ {_fmt_num(st)} 星标，社区热度高"
    # --- 参数量 ---
    m = _PARAM_RE.search(t)
    if m:
        return f"🔢 {m.group(1)}B 参数规模"
    # --- 完全本地 / 隐私优先（英文项目常见卖点） ---
    if _EN_LOCAL_RE.search(t):
        return "🔒 完全本地运行，隐私优先"
    if _OPEN_RE.search(t):
        return "🛠 开源，可商用 / 可部署"
    if "开源" in t or "open-source" in low or "open source" in low:
        return "🛠 开源项目"
    return ""


def build_highlights(items):
    """为每条目计算并挂上 highlight 字段（就地修改）。"""
    for it in items:
        it["highlight"] = extract_highlight(it)
    return items


# ---------------------------------------------------------------- 组装处理管线
def process(items):
    """分类 -> 打分 -> 归一化 -> 摘要 -> LLM 润色(可选）。"""
    now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    seen_urls, seen_titles = set(), set()
    unique = []
    for it in items:
        url = re.sub(r"[?#].*$", "", it["url"].strip())
        title_key = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", it["title"].lower())[:60]
        if url in seen_urls or (title_key and title_key in seen_titles):
            continue
        seen_urls.add(url)
        seen_titles.add(title_key)

        it["url"] = url
        it["category"] = classify(it)
        it["summary_final"] = extract_summary(it.get("summary", ""))
        it["fetched_at"] = now_iso
        unique.append(it)

    normalize_scores(unique)

    # 英文标题/摘要翻译为中文（放在分类评分之后，不影响关键词命中；失败保留原文）
    try:
        import translator
        n_tr = translator.translate_items(unique, max_texts=config.TRANSLATE_MAX_PER_RUN)
        if n_tr:
            print(f"  翻译英文条目 {n_tr} 条")
    except Exception as e:
        print(f"    [提示] 翻译环节跳过: {e}")

    polished = llm_polish(unique)
    if polished:
        print(f"  LLM 润色摘要 {polished} 条")
    return unique


def stats_of(items):
    """统计各分类条数与来源分布。"""
    by_cat = {k: 0 for k in config.CATEGORIES}
    by_src = {}
    for it in items:
        by_cat[it["category"]] = by_cat.get(it["category"], 0) + 1
        by_src[it["source"]] = by_src.get(it["source"], 0) + 1
    return {"total": len(items), "by_category": by_cat, "by_source": by_src}
