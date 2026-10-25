# -*- coding: utf-8 -*-
"""数据源连续失败自动开/关 GitHub Issue。

在 GitHub Actions 里随每日任务运行（main.py --once 之后）：
  - 某源连续失败 >= config.SOURCE_ISSUE_STREAK 天：
      无对应 Issue  -> 开新 Issue（标签 source-health）
      已有对应 Issue -> 追加一条进度评论（记录最新失败日期与原因）
  - 某源恢复（fail_streak == 0）且存在未关闭的对应 Issue：自动关闭并评论已恢复。

本地运行（无 GITHUB_TOKEN）时为 dry-run：只打印将执行的动作，不调用 API。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

import config

LABEL = "source-health"
TITLE_PREFIX = "📡 数据源失败："
API = "https://api.github.com"


# ---------------------------------------------------------------- 决策逻辑（纯函数，可单测）
def plan_actions(health, open_issues):
    """根据健康表与当前未关闭 Issue，计算要执行的动作。

    health: [{source, fail_streak, last_fail, last_error}, ...]
    open_issues: [{number, title}, ...]   # 已带 LABEL 的未关闭 Issue
    返回 {"open": [...], "comment": [...], "close": [...]}
    """
    threshold = getattr(config, "SOURCE_ISSUE_STREAK", 2)
    by_title = {}
    for it in open_issues:
        for h in health:
            if it["title"].startswith(f"{TITLE_PREFIX}{h['source']}"):
                by_title[h["source"]] = it
                break

    plan = {"open": [], "comment": [], "close": []}
    for h in health:
        name = h["source"]
        issue = by_title.get(name)
        if h["fail_streak"] >= threshold:
            target = {"source": name, "fail_streak": h["fail_streak"],
                      "last_fail": h.get("last_fail") or "",
                      "last_error": (h.get("last_error") or "")[:300]}
            if issue:
                plan["comment"].append({"issue": issue["number"], **target})
            else:
                plan["open"].append(target)
        elif h["fail_streak"] == 0 and issue:
            plan["close"].append({"issue": issue["number"], "source": name})
    return plan


def issue_title(source):
    return f"{TITLE_PREFIX}{source}"


def issue_body(target):
    lines = [
        f"## 📡 数据源连续失败",
        "",
        f"| 项 | 值 |",
        f"|---|---|",
        f"| 信源 | **{target['source']}** |",
        f"| 连续失败 | {target['fail_streak']} 天 |",
        f"| 最近失败日期 | {target['last_fail'] or '未知'} |",
        "",
        "### 最近错误",
        "```",
        target["last_error"] or "（无错误信息）",
        "```",
        "",
        f"- 今日报告：https://lavie-purple.github.io/Ai-news/",
        f"- 该源内容在报告里已缺失；恢复后本 Issue 会自动关闭。",
        f"- 由 `tools/source_issues.py` 自动创建（阈值：连续失败 ≥ {getattr(config, 'SOURCE_ISSUE_STREAK', 2)} 天）。",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- API 封装
class GitHub:
    def __init__(self, token, repo):
        self.token = token
        self.repo = repo
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        })

    def _url(self, path):
        return f"{API}/repos/{self.repo}/{path}"

    def list_open_issues(self, label):
        r = self.session.get(self._url("issues"),
                             params={"labels": label, "state": "open", "per_page": 100},
                             timeout=20)
        r.raise_for_status()
        return [{"number": x["number"], "title": x["title"]} for x in r.json()
                if "pull_request" not in x]

    def create_issue(self, title, body):
        r = self.session.post(self._url("issues"),
                              json={"title": title, "body": body, "labels": [LABEL]},
                              timeout=20)
        r.raise_for_status()
        return r.json()["number"]

    def comment(self, number, body):
        r = self.session.post(self._url(f"issues/{number}/comments"),
                              json={"body": body}, timeout=20)
        r.raise_for_status()

    def close_issue(self, number, comment):
        self.comment(number, comment)
        r = self.session.patch(self._url(f"issues/{number}"),
                               json={"state": "closed"}, timeout=20)
        r.raise_for_status()


def comment_body(target):
    return (f"仍持续失败：连续 **{target['fail_streak']} 天**"
            f"（最近失败 {target['last_fail'] or '未知'}）\n\n"
            f"```\n{target['last_error'] or '（无错误信息）'}\n```")


# ---------------------------------------------------------------- 主流程
def read_health():
    """从 DB 读健康表。"""
    import sqlite3
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT source, fail_streak, last_fail, last_error FROM source_health"
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def main():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    repo = os.environ.get("GITHUB_REPOSITORY") or os.environ.get("GH_REPO") or ""
    health = read_health()
    threshold = getattr(config, "SOURCE_ISSUE_STREAK", 2)
    if not threshold:
        print("  [Issue] SOURCE_ISSUE_STREAK=0，功能关闭")
        return

    if not token or not repo:
        failing = [h for h in health if h["fail_streak"] >= threshold]
        print(f"  [Issue] 无 GITHUB_TOKEN，dry-run："
              f"连续失败≥{threshold}天 {len(failing)} 个源"
              + (f" -> {', '.join(h['source'] for h in failing)}" if failing else ""))
        return

    gh = GitHub(token, repo)
    open_issues = gh.list_open_issues(LABEL)
    plan = plan_actions(health, open_issues)

    for t in plan["open"]:
        n = gh.create_issue(issue_title(t["source"]), issue_body(t))
        print(f"  [Issue] 已创建 #{n}: {issue_title(t['source'])}"
              f"（连续失败 {t['fail_streak']} 天）")
    for t in plan["comment"]:
        gh.comment(t["issue"], comment_body(t))
        print(f"  [Issue] 已评论 #{t['issue']}: {t['source']} 仍失败"
              f"（{t['fail_streak']} 天）")
    for t in plan["close"]:
        gh.close_issue(t["issue"], f"✅ 信源「{t['source']}」已恢复，自动关闭。")
        print(f"  [Issue] 已关闭 #{t['issue']}: {t['source']} 已恢复")
    if not (plan["open"] or plan["comment"] or plan["close"]):
        print("  [Issue] 所有信源健康，无需处理")


if __name__ == "__main__":
    main()
