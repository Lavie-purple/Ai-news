# -*- coding: utf-8 -*-
"""事件聚类：将标题高度相似（同一事件的多家报道）的条目合并为一组。

主条目保留热度最高者，其余以 related 列表挂在主条目上，
由报告层渲染为「相关报道」折叠块。纯内存计算，不落库，
每次渲染日报时基于当日全量数据重新计算，保证多次运行结果一致。
"""

import re
from difflib import SequenceMatcher

import config

_NORM_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+")
_MAX_RELATED = 5          # 每组最多展示的相关报道数
_MIN_TITLE_LEN = 8        # 归一化后短于此的标题不参与聚类（太短易误合）
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")


def _norm(title):
    return _NORM_RE.sub("", (title or "").lower())


def _tokens(s):
    """英文按词、中文按字切分，用于词集重合度判断。"""
    return set(_TOKEN_RE.findall((s or "").lower()))


def _token_sim(a, b):
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _similar(a, b, threshold):
    """归一化标题相似判断：长度差预筛 + 综合「序列相似度 / 词集重合度」取高值。

    词集重合能兜住「同一事件、不同媒体换种说法/调换语序」的场景
    （如 “OpenAI 发布 GPT-5” 与 “GPT-5 由 OpenAI 推出”），单靠序列相似易漏合。
    """
    if abs(len(a) - len(b)) > max(len(a), len(b)) * 0.5:
        return False
    seq = SequenceMatcher(None, a, b).ratio()
    tok = _token_sim(a, b)
    return max(seq, tok) >= threshold


def merge_related(items, threshold=None):
    """
    就地给 items 中的主条目挂上 related 列表。
    items 需已按热度降序排列（保证组内主条目是热度最高者）。
    返回合并出的多成员事件组数。
    """
    thr = threshold if threshold is not None else config.CLUSTER_SIMILARITY
    reps = []           # 各事件组的代表：{"norm": str, "item": 主条目}
    multi_groups = 0
    for it in items:
        norm = _norm(it.get("title"))
        if len(norm) < _MIN_TITLE_LEN:
            continue
        target = None
        for rep in reps:
            if _similar(rep["norm"], norm, thr):
                target = rep
                break
        if target is None:
            reps.append({"norm": norm, "item": it})
            continue
        related = target["item"].setdefault("related", [])
        if not related:
            multi_groups += 1
        if len(related) < _MAX_RELATED:
            related.append({
                "title": it.get("title", ""),
                "url": it.get("url", ""),
                "source": it.get("source", ""),
            })
    return multi_groups
