# -*- coding: utf-8 -*-
"""抓取模块：GitHub / HuggingFace / arXiv / 各大科技媒体 RSS"""

import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

import config


def _get(url, params=None, headers=None, retries=1):
    """带超时、浏览器 UA 与失败重试的 GET 请求，返回 text 或抛异常。"""
    h = dict(config.HEADERS)
    if headers:
        h.update(headers)
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, headers=h, timeout=config.FETCH_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(2)
    raise last_err


def _iso(dt):
    """统一转成 ISO 字符串（无时区则按 UTC 补齐）。"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _log_source_error(name, error):
    """把单源抓取失败原因追加写入当日日志文件，便于离线排查（不阻塞主流程）。"""
    try:
        os.makedirs(config.LOG_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        path = os.path.join(config.LOG_DIR, f"collect_{datetime.now().strftime('%Y-%m-%d')}.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] 数据源失败: {name} | {str(error)[:300]}\n")
    except Exception:
        pass


# ---------------------------------------------------------------- GitHub
def fetch_github():
    """搜索最近 N 天创建的 AI 相关仓库，按 star 排序。全部主题都失败时抛异常。"""
    items = []
    since = (datetime.utcnow() - timedelta(days=config.GITHUB_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    headers = {"Accept": "application/vnd.github+json"}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"

    errors = []
    for topic in config.GITHUB_TOPICS:
        try:
            text = _get(
                "https://api.github.com/search/repositories",
                params={"q": f"topic:{topic} created:>={since}",
                        "sort": "stars", "order": "desc", "per_page": 15},
                headers=headers,
            )
            data = json.loads(text)
            for repo in data.get("items", []):
                items.append({
                    "title": repo["full_name"],
                    "url": repo["html_url"],
                    "summary": repo.get("description") or "",
                    "source": "GitHub",
                    "source_type": "github",
                    "metrics": {"stars": repo.get("stargazers_count", 0)},
                    "published_at": _iso(_parse_dt(repo.get("created_at"))),
                    "lang": repo.get("language") or "",
                    "topic": topic,
                })
            time.sleep(2)  # 未认证搜索接口限流 10 次/分钟
        except Exception as e:
            errors.append(f"{topic}: {e}")
    if len(errors) == len(config.GITHUB_TOPICS):
        raise RuntimeError(f"GitHub 全部主题失败（{errors[0]}）")
    return items


# ---------------------------------------------------------------- HuggingFace
def fetch_hf(kind):
    """kind: hf_models 或 hf_spaces，按 trendingScore 拉热门；主站不通时走镜像。"""
    api = "models" if kind == "hf_models" else "spaces"
    text = None
    for host in config.HF_HOSTS:
        try:
            text = _get(f"{host}/api/{api}",
                        params={"sort": "trendingScore", "direction": -1,
                                "limit": config.MAX_ITEMS_PER_SOURCE},
                        retries=0)
            break
        except Exception as e:
            print(f"    [提示] {host} 不可用: {e}")
    if text is None:
        raise RuntimeError(f"HuggingFace {api} 所有通道（含镜像）均失败")
    entries = json.loads(text)

    items = []
    for ent in entries:
        obj_id = ent.get("modelId") or ent.get("id", "")
        if not obj_id or ent.get("private"):
            continue
        base = "https://huggingface.co/"
        url = base + obj_id if kind == "hf_models" else f"{base}spaces/{obj_id}"
        metrics = {}
        if kind == "hf_models":
            metrics = {"downloads": ent.get("downloads", 0), "likes": ent.get("likes", 0)}
        else:
            metrics = {"likes": ent.get("likes", 0)}
        items.append({
            "title": obj_id,
            "url": url,
            "summary": _pipeline_desc(ent, kind),
            "source": "HuggingFace",
            "source_type": kind,
            "metrics": metrics,
            "published_at": _iso(_parse_dt(ent.get("createdAt"))),
            "pipeline_tag": ent.get("pipeline_tag") or "",
        })
    return items


def _pipeline_desc(ent, kind):
    parts = []
    if kind == "hf_models":
        tag = ent.get("pipeline_tag")
        if tag:
            parts.append(f"任务类型: {tag}")
        dl = ent.get("downloads", 0)
        if dl:
            parts.append(f"近30天下载 {dl:,}")
    else:
        parts.append("Space 在线应用（可直接体验）")
    likes = ent.get("likes", 0)
    if likes:
        parts.append(f"👍 {likes}")
    return " · ".join(parts)


# ---------------------------------------------------------------- arXiv
ARXIV_NS = "{http://www.w3.org/2005/Atom}"

def fetch_arxiv(categories):
    cat_query = " OR ".join(f"cat:{c}" for c in categories)
    text = _get(
        "https://export.arxiv.org/api/query",
        params={"search_query": cat_query, "sortBy": "submittedDate",
                "sortOrder": "descending", "max_results": config.MAX_ITEMS_PER_SOURCE},
    )
    root = ET.fromstring(text)

    items = []
    for entry in root.findall(f"{ARXIV_NS}entry"):
        title = (entry.findtext(f"{ARXIV_NS}title") or "").strip().replace("\n", " ")
        link = entry.findtext(f"{ARXIV_NS}id") or ""
        summary = (entry.findtext(f"{ARXIV_NS}summary") or "").strip().replace("\n", " ")
        published = entry.findtext(f"{ARXIV_NS}published")
        authors = [a.findtext(f"{ARXIV_NS}name") for a in entry.findall(f"{ARXIV_NS}author")]
        items.append({
            "title": title,
            "url": link,
            "summary": summary,
            "source": "arXiv",
            "source_type": "arxiv",
            "metrics": {},
            "published_at": published,
            "authors": ", ".join(a for a in authors[:3] if a) + (" 等" if len(authors) > 3 else ""),
        })
    return items


# ---------------------------------------------------------------- RSS
def fetch_rss(name, url, ai_only=False):
    """通用 RSS/Atom 解析器，兼容两种格式；ai_only=True 时只保留 AI 相关内容。
    抓取或解析彻底失败时抛异常（由上层记录源健康状态）。"""
    text = _get(url)
    # 部分站点返回内容前带杂字符，去掉 XML 声明前的内容
    m = re.search(r"<(\?xml|rss|feed)", text)
    if m:
        text = text[m.start():]
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError:
        # 容错：转义未转义的裸 & 后重试（常见于不规范 feed）
        fixed = re.sub(r"&(?!#\d+;|#x[0-9a-fA-F]+;|\w+;)", "&amp;", text)
        root = ET.fromstring(fixed.encode("utf-8"))

    items, seen = [], set()
    rss_items = root.findall(".//item")          # RSS 2.0
    atom_entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")  # Atom

    def is_relevant(title, desc):
        if not ai_only:
            return True
        hay = f"{title} {desc}"
        for kw in config.RELEVANCE_KEYWORDS:
            if kw == "AI":
                # "AI" 用大小写敏感匹配，避免误命中 pair/air 等英文词
                if "AI" in title:
                    return True
            elif kw.lower() in hay.lower():
                return True
        return False

    def add(title, link, desc, pub):
        title = _clean(title)
        link = (link or "").strip()
        if not title or not link or link in seen:
            return
        clean_desc = _clean(desc)
        if name.startswith("Hacker News"):
            # hnrss 的 description 是模板化的链接与计数信息，清理成纯正文
            clean_desc = re.sub(r"(Article|Comments) URL:\s*\S+", "", clean_desc)
            clean_desc = re.sub(r"Points:\s*\d+\s*#\s*Comments:\s*\d+", "", clean_desc)
            clean_desc = re.sub(r"\s{2,}", " ", clean_desc).strip()
        if not is_relevant(title, clean_desc):
            return
        seen.add(link)
        items.append({
            "title": title,
            "url": link,
            "summary": clean_desc,
            "source": name,
            "source_type": "rss",
            "metrics": {},
            "published_at": _parse_pubdate(pub),
        })

    for it in rss_items:
        add(it.findtext("title"),
            it.findtext("link"),
            it.findtext("description") or it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded"),
            it.findtext("pubDate"))

    for en in atom_entries:
        link = ""
        for le in en.findall("{http://www.w3.org/2005/Atom}link"):
            rel = le.get("rel", "alternate")
            if rel == "alternate":
                link = le.get("href", "")
                break
            link = link or le.get("href", "")
        add(en.findtext("{http://www.w3.org/2005/Atom}title"),
            link,
            en.findtext("{http://www.w3.org/2005/Atom}summary") or en.findtext("{http://www.w3.org/2005/Atom}content"),
            en.findtext("{http://www.w3.org/2005/Atom}updated"))
    return items


# ---------------------------------------------------------------- AI Hot 聚合
def fetch_aihot(url="https://aihot.virxact.com"):
    """
    抓取 aihot.virxact.com（AI 热点精选聚合站）。
    该站为 Next.js 服务端渲染，精选条目内嵌在 RSC flight 数据的
    initialItems 数组中，含中文标题、提炼摘要、AI 标签与站点评分。
    """
    try:
        text = _get(url)
    except Exception as e:
        raise RuntimeError(f"页面请求失败: {e}")

    chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', text)
    if not chunks:
        raise RuntimeError("页面结构变化：未找到 flight 数据")
    payload = "".join(json.loads('"' + c + '"') for c in chunks)
    arr_text = _extract_json_array(payload, '"initialItems":')
    if not arr_text:
        raise RuntimeError("页面结构变化：未找到 initialItems")
    try:
        entries = json.loads(arr_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"数据解析失败: {e}")

    items, seen = [], set()
    for ent in entries:
        link = (ent.get("url") or "").strip()
        title = (ent.get("titleZh") or ent.get("title") or "").strip()
        if not link or not title or link in seen:
            continue
        seen.add(link)
        src = ent.get("source") or {}
        items.append({
            "title": title,
            "url": link,
            "summary": (ent.get("summaryZh") or "").strip(),
            "source": "AI Hot 精选",
            "source_type": "aihot",
            "metrics": {"site_score": ent.get("finalScore") or 0,
                        "origin": src.get("name", "")},
            "published_at": _iso(_parse_dt(ent.get("publishedAt"))),
            "tags": [t.get("tag", "") for t in ent.get("aiTags") or []],
        })
    return items


def _extract_json_array(text, marker):
    """定位 marker 后第一个括号平衡的 JSON 数组，返回其文本。"""
    i = text.find(marker)
    if i < 0:
        return None
    j = text.find("[", i)
    if j < 0:
        return None
    depth, in_str, esc = 0, False, False
    for k in range(j, len(text)):
        ch = text[k]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return text[j:k + 1]
    return None


# ---------------------------------------------------------------- 工具函数
def _clean(html_text, limit=400):
    """去除 HTML 标签、反转义实体并压缩空白。"""
    if not html_text:
        return ""
    s = re.sub(r"<[^>]+>", " ", html_text)
    s = html.unescape(re.sub(r"\s+", " ", s).strip())
    return s[:limit]


def _parse_dt(s):
    if not s:
        return None
    # 去掉毫秒部分，兼容 2026-08-23T14:13:31.000Z 与普通 ISO 格式
    s = re.sub(r"\.\d+", "", s)
    try:
        return datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_pubdate(s):
    if not s:
        return None
    try:
        return _iso(parsedate_to_datetime(s.strip()))
    except Exception:
        return None


# ---------------------------------------------------------------- 总入口
def collect_all():
    """
    按配置抓取全部数据源，返回 (条目列表, 逐源状态列表)。
    状态元素: {"name", "type", "ok": bool, "count": int, "error": str}
    """
    all_items, statuses = [], []
    for src in config.SOURCES:
        if not src.get("enabled", True):
            continue
        stype = src["type"]
        print(f"  -> 抓取: {src['name']} ...")
        try:
            if stype == "github":
                batch = fetch_github()
            elif stype in ("hf_models", "hf_spaces"):
                batch = fetch_hf(stype)
            elif stype == "arxiv":
                batch = fetch_arxiv(src.get("categories", ["cs.AI"]))
            elif stype == "rss":
                batch = fetch_rss(src["name"], src["url"],
                                  ai_only=src.get("ai_only", False))
            elif stype == "aihot":
                batch = fetch_aihot(src.get("url", "https://aihot.virxact.com"))
            else:
                batch = []
            batch = batch[: config.MAX_ITEMS_PER_SOURCE]
            statuses.append({"name": src["name"], "type": stype, "ok": True,
                             "count": len(batch), "error": ""})
            print(f"     获得 {len(batch)} 条")
        except Exception as e:
            batch = []
            _log_source_error(src["name"], e)
            statuses.append({"name": src["name"], "type": stype, "ok": False,
                             "count": 0, "error": str(e)[:150]})
            print(f"     [警告] 抓取失败: {str(e)[:150]}")
        all_items.extend(batch)
    return all_items, statuses
