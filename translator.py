# -*- coding: utf-8 -*-
"""翻译层：将英文标题/摘要自动翻译为简体中文。

后端按顺序尝试，前一个不可用时自动降级：
  1. LLM 批量翻译（配置了 config.LLM_API_BASE 时）——质量最好
  2. MyMemory 免费接口（国内网络可达，匿名每日有配额，可填邮箱提升）
  3. 翻译 gTX 公开接口（海外网络可用）

全部失败时保留英文原文并在控制台明确提示，不影响主流程。
"""

import json
import re
import time

import requests

import config
import storage

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_ASCII_RE = re.compile(r"[A-Za-z]")
# 识别嵌在中文里的较长英文片段（中英文混用场景），命中即纳入翻译
_EN_RUN_RE = re.compile(r"[A-Za-z][A-Za-z0-9 .,!?;:'\"\-]{10,}[A-Za-z]")

# 离线术语表：高频英文技术词 -> 中文（无需联网，作为翻译兜底/补全，缓解中英文混用）
_GLOSSARY = {
    "image-text-to-text": "图文到文本",
    "text-to-image": "文生图",
    "text-to-video": "文生视频",
    "image-to-video": "图生视频",
    "video-to-video": "视频到视频",
    "image-to-text": "图生文",
    "image-to-3d": "图生3D",
    "text-to-3d": "文生3D",
    "text-generation": "文本生成",
    "text-generation-inference": "文本生成推理",
    "automatic-speech-recognition": "自动语音识别",
    "speech-to-text": "语音转文本",
    "text-to-speech": "文本转语音",
    "audio-to-audio": "音频到音频",
    "audio-classification": "音频分类",
    "image-classification": "图像分类",
    "image-segmentation": "图像分割",
    "object-detection": "目标检测",
    "video-classification": "视频分类",
    "visual-question-answering": "视觉问答",
    "document-question-answering": "文档问答",
    "table-question-answering": "表格问答",
    "zero-shot-classification": "零样本分类",
    "zero-shot-image-classification": "零样本图像分类",
    "fill-mask": "掩码填充",
    "token-classification": "词元分类",
    "feature-extraction": "特征提取",
    "sentence-similarity": "句子相似度",
    "tabular-classification": "表格分类",
    "tabular-regression": "表格回归",
    "conversational": "对话模型",
    "mask-generation": "掩码生成",
    "reinforcement-learning": "强化学习",
    "custom-code": "自定义代码",
    "question-answering": "问答",
    "summarization": "摘要生成",
    "translation": "翻译",
    "graph-ml": "图机器学习",
    "robotics": "机器人",
    # 补充的 HuggingFace pipeline tag
    "depth-estimation": "深度估计",
    "image-to-image": "图生图",
    "mask-fill": "掩码填充",
    "unconditional-image-generation": "无条件图像生成",
    "video-generation": "视频生成",
    "text-to-sql": "文本转 SQL",
    "table-to-text": "表生文",
    "multiple-choice": "多选问答",
    "code-generation": "代码生成",
    "optical-character-recognition": "光学字符识别",
    # 常见 AI 术语（英文摘要未翻译时也能本地化）
    "state-of-the-art": "最先进",
    "benchmark": "基准测试",
    "fine-tuning": "微调",
    "pre-training": "预训练",
    "post-training": "后训练",
    "inference": "推理",
    "transformer": "Transformer",
    "tokenizer": "分词器",
    "embedding": "嵌入",
    "retrieval-augmented-generation": "检索增强生成",
    "alignment": "对齐",
    "hallucination": "幻觉",
    "quantization": "量化",
    "distillation": "蒸馏",
    "multimodal": "多模态",
    "open-source": "开源",
    "open-weight": "开放权重",
    "open weight": "开放权重",
    "few-shot": "少样本",
    "long-context": "长上下文",
    "reasoning-model": "推理模型",
}
_GLOSSARY_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(_GLOSSARY, key=len, reverse=True)) + r")\b",
    re.I,
)


def localize_terms(text):
    """把文本中已知的英文技术术语替换为中文（离线，安全幂等）。"""
    if not text:
        return text
    return _GLOSSARY_RE.sub(lambda m: _GLOSSARY[m.group(0).lower()], text)

# 不翻译的标题模式：仓库名 / 模型名（org/name 形式的标识符）
_REPO_TITLE_RE = re.compile(r"^[\w.-]+/[\w.-]+$")

_MAX_QUERY_LEN = 450   # MyMemory 单次查询长度上限约 500 字节
_TRANSLATE_TIMEOUT = 10  # 单条翻译请求超时（秒）
_TRANSLATE_BUDGET = 45    # 免费后端总耗时上限（秒），超时即放弃以免卡死


def is_mostly_english(text):
    """判断文本是否以英文为主（中文字符占比过低）。"""
    if not text:
        return False
    letters = len(_ASCII_RE.findall(text))
    cjk = len(_CJK_RE.findall(text))
    return letters >= 20 and cjk < letters * 0.15


def needs_translation(item):
    """GitHub/HF 的标题是标识符（org/repo），只译摘要；其余源标题摘要都判断。"""
    out = []
    if not _REPO_TITLE_RE.match(item.get("title", "")) and is_mostly_english(item.get("title", "")):
        out.append("title")
    # 优先检查 summary_final，若不存在（DB 加载）则回退检查 summary
    summary_text = item.get("summary_final") or item.get("summary", "")
    if is_mostly_english(summary_text) or _EN_RUN_RE.search(summary_text):
        out.append("summary")
    return out


def translate_items(items, max_texts=None):
    """
    就地翻译 items 中英文标题与摘要（按热度从高到低安排翻译优先级）。
    LLM（若配置）与免密钥后端（MyMemory/Google）互为备份：前一个不可用自动降级。
    相同原文优先走翻译缓存（落库），避免重复打限流严重的免密钥接口。
    返回实际翻译成功的条数。
    """
    if not config.TRANSLATE_ENABLED or not items:
        return 0
    tasks = []
    for it in sorted(items, key=lambda x: x.get("score", 0), reverse=True):
        for field in needs_translation(it):
            tasks.append((it, field, it[field]))
    if max_texts:
        tasks = tasks[:max_texts]
    if not tasks:
        return 0

    texts = [t[2][:_MAX_QUERY_LEN] for t in tasks]
    results = [None] * len(texts)
    pending = set(range(len(texts)))

    # 1) 翻译缓存命中（相同原文直接复用，省配额）
    if config.TRANSLATE_CACHE:
        try:
            cache = storage.get_translation_cache(texts)
            for i, t in enumerate(texts):
                if t in cache and cache[t] and cache[t] != t:
                    results[i] = cache[t]
                    pending.discard(i)
        except Exception:
            cache = {}

    # 2) 后端翻译：LLM（若配置）→ MyMemory → Google，互为备份
    backends = []
    if config.LLM_API_BASE and config.LLM_API_KEY:
        backends.append(("LLM", _translate_llm))
    backends.append(("MyMemory", _translate_mymemory))
    backends.append(("Google", _translate_google))

    deadline = time.time() + _TRANSLATE_BUDGET
    for name, fn in backends:
        if not pending:
            break
        idx = sorted(pending)
        try:
            out = fn([texts[i] for i in idx], deadline)
        except Exception as e:
            print(f"    [提示] 翻译后端 {name} 不可用: {str(e)[:110]}")
            continue
        new_pairs = []
        for i, t in zip(idx, out):
            if t and t != texts[i]:
                results[i] = t
                pending.discard(i)
                new_pairs.append((texts[i], t))
        if new_pairs and config.TRANSLATE_CACHE:
            try:
                storage.save_translation_cache(new_pairs)
            except Exception:
                pass

    # 3) 写回条目；摘要同步到 summary_final，避免渲染时被回滚成原文
    done = 0
    for (it, field, original), translated in zip(tasks, results):
        if translated:
            it[field] = translated
            if field == "summary":
                it["summary_final"] = translated
            done += 1
    failed = len(tasks) - done
    print(f"  翻译英文条目：成功 {done} / 共 {len(tasks)}"
          + (f"，{failed} 条失败保留原文" if failed else ""))
    if done == 0:
        print("    [提示] 全部翻译失败——建议在 config.py 配置 LLM_API_KEY 以获得稳定中文翻译")
    return done


# ---------------------------------------------------------------- LLM 后端
def _translate_llm(texts, deadline=0):
    from classifier import _chat  # 复用 OpenAI 兼容接口封装

    results, batch_size = [], 20
    for i in range(0, len(texts), batch_size):
        chunk = texts[i: i + batch_size]
        numbered = "\n".join(f"{j+1}. {t.replace(chr(10), ' ')}" for j, t in enumerate(chunk))
        prompt = (
            "将以下 AI 领域资讯文本逐条翻译成简体中文。要求：保留专有名词/产品名/公司名的"
            "通用写法（如 GPT、Claude、RAG、LoRA 可保留英文），数字和百分比不变。"
            f"输出 JSON 数组，元素为字符串，顺序与输入一致，共 {len(chunk)} 条。\n\n{numbered}"
        )
        content = _chat(prompt).strip()
        content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.M).strip()
        arr = json.loads(content)
        if not isinstance(arr, list) or len(arr) != len(chunk):
            raise RuntimeError("LLM 翻译返回数量不匹配")
        results.extend(str(x) for x in arr)
        time.sleep(0.5)
    return results


# ---------------------------------------------------------------- MyMemory 后端
_MYMEMORY_URL = "https://api.mymemory.translated.net/get"


def _http_get(url, params=None, headers=None, retries=1):
    """带超时与单次重试的 GET（配额类 RuntimeError 立即上抛，不重试）。"""
    h = dict(config.HEADERS)
    if headers:
        h.update(headers)
    last = None
    for _ in range(retries + 1):
        try:
            resp = requests.get(url, params=params, headers=h,
                                timeout=_TRANSLATE_TIMEOUT)
            resp.raise_for_status()
            return resp
        except RuntimeError:
            raise
        except Exception as e:
            last = e
            time.sleep(0.5)
    raise last


def _mymemory_one(text):
    params = {"q": text, "langpair": "en|zh-CN"}
    if config.TRANSLATE_MYMEMORY_EMAIL:
        params["de"] = config.TRANSLATE_MYMEMORY_EMAIL
    resp = _http_get(_MYMEMORY_URL, params=params)
    data = resp.json()
    t = (data.get("responseData") or {}).get("translatedText") or ""
    status = str(data.get("responseStatus", ""))
    if "MYMEMORY WARNING" in t or status == "403":
        raise RuntimeError("MyMemory 当日配额已用尽（可配置 LLM 或填写 "
                           "TRANSLATE_MYMEMORY_EMAIL 提升配额）")
    if not t or t.upper().startswith("INVALID") or t == text:
        return None
    return t


def _translate_mymemory(texts, deadline=0):
    results = []
    for t in texts:
        if deadline and time.time() > deadline:
            results.append(None)
            continue
        try:
            results.append(_mymemory_one(t))
        except RuntimeError:
            raise           # 配额问题直接中止该后端
        except Exception:
            results.append(None)
        time.sleep(0.12)
    return results


# ---------------------------------------------------------------- Google 后端
_GTX_URL = "https://translate.googleapis.com/translate_a/single"


def _google_one(text):
    resp = _http_get(
        _GTX_URL,
        params={"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": text},
    )
    segs = resp.json()[0] or []
    return "".join(s[0] for s in segs if s and s[0])


def _translate_google(texts, deadline=0):
    results = []
    for t in texts:
        if deadline and time.time() > deadline:
            results.append(None)
            continue
        try:
            results.append(_google_one(t))
        except Exception:
            results.append(None)
        time.sleep(0.12)
    return results
