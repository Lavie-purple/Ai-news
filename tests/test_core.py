# -*- coding: utf-8 -*-
"""核心模块单元测试（纯逻辑，无需联网）。

运行:
  python -m unittest discover -s tests -t .
"""

import os
import sys
import unittest

# 把项目根目录加入导入路径（discover 默认只把 tests 目录加入 sys.path）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import translator
import classifier
import cluster
import report
import config


def _item(title, summary="", category="foundation", source="GitHub",
          source_type="github", score=10, metrics=None, url=None):
    return {
        "title": title,
        "summary": summary,
        "category": category,
        "source": source,
        "source_type": source_type,
        "score": score,
        "metrics": metrics or {},
        "url": url or ("https://example.com/" + str(abs(hash(title)) % 10**8)),
        "published_at": "2026-08-24T00:00:00",
    }


class TestTranslator(unittest.TestCase):
    def test_needs_translation_repo_title_excluded(self):
        it = _item("org/repo-name", "Some english description here that is long enough")
        fields = translator.needs_translation(it)
        self.assertNotIn("title", fields)          # 仓库标识符不译
        self.assertIn("summary", fields)

    def test_needs_translation_english_title(self):
        it = _item("OpenAI releases a new large language model today")
        self.assertIn("title", translator.needs_translation(it))

    def test_needs_translation_chinese_skipped(self):
        it = _item("国产大模型今日发布新版本", "这是一段中文摘要不需要翻译的内容")
        self.assertEqual(translator.needs_translation(it), [])

    def test_is_mostly_english(self):
        self.assertTrue(translator.is_mostly_english("This is a fully english sentence about AI models"))
        self.assertFalse(translator.is_mostly_english("这是中文为主的内容 English mix"))

    def test_localize_terms_glossary(self):
        out = translator.localize_terms("A new image-text-to-text pipeline model")
        self.assertIn("图文到文本", out)
        self.assertNotIn("image-text-to-text", out)


class TestClassifier(unittest.TestCase):
    def test_extract_highlight_beats(self):
        hl = classifier.extract_highlight(_item("x", "Our model beats GPT-4 by 45% on the benchmark"))
        self.assertIn("超越", hl)

    def test_extract_highlight_downloads(self):
        hl = classifier.extract_highlight(_item("x", "y", metrics={"downloads": 2_358_347}))
        self.assertIn("下载", hl)
        self.assertIn("开源热度", hl)

    def test_extract_highlight_param(self):
        hl = classifier.extract_highlight(_item("Qwen3.8-27B released", "a 27B parameter model"))
        self.assertIn("参数规模", hl)

    def test_extract_highlight_local(self):
        hl = classifier.extract_highlight(_item("x", "Runs locally with no cloud dependency"))
        self.assertIn("本地", hl)

    def test_hot_words_count(self):
        items = [_item("Qwen3.8 model A", "about Qwen3.8"),
                 _item("Qwen3.8 model B", "mentions Qwen3.8 again"),
                 _item("Claude release", "something else")]
        hw = classifier.hot_words(items, top_n=5)
        d = dict(hw)
        self.assertEqual(d.get("Qwen3.8"), 2)   # 出现 ≥2 次的模型名才进热词


class TestCluster(unittest.TestCase):
    def test_merge_reorder_wording(self):
        items = [
            _item("OpenAI 发布 GPT-5 旗舰模型", category="x", score=90),
            _item("OpenAI 发布 GPT-5 新旗舰模型", category="x", score=80),
            _item("完全不相关的另一则科技新闻", category="x", score=70),
        ]
        groups = cluster.merge_related(items)
        self.assertEqual(groups, 1)               # 前两则同一事件被合并
        self.assertEqual(len(items[0].get("related", [])), 1)

    def test_norm_strips_punct(self):
        self.assertEqual(cluster._norm("Claude 5!"), cluster._norm("claude-5"))


class TestReport(unittest.TestCase):
    def _build(self, items):
        stats = classifier.stats_of(items)
        return report.build_daily_html(
            "2026-08-24", items, stats, 999,
            brief=None, hot_words=[("Qwen3.8", 2)],
            merged_groups=0, source_alerts=[("AI Hot 每日精选", 4, "HTTP 429")])

    def test_top_cards_are_filterable(self):
        items = [_item(f"Top item {i}", f"summary {i}", score=100 - i) for i in range(8)]
        html = self._build(items)
        # TOP 区块的卡片应带 data-src / data-text（可参与前端筛选）
        self.assertIn('id="top"', html)
        self.assertIn('data-text', html)

    def test_load_more_for_capped_category(self):
        # TOP 8 用别的分类占位，避免占掉 foundation 的条目导致不到封顶数
        top_items = [_item(f"Policy item {i}", category="policy", score=200 - i)
                     for i in range(8)]
        found = [_item(f"Found model {i}", f"desc {i}", category="foundation", score=50 - i)
                 for i in range(35)]   # 超过 PER_CATEGORY_CAP(30)
        html = self._build(top_items + found)
        self.assertIn('class="card beyond"', html)     # 超出封顶的默认隐藏
        self.assertIn('data-beyond="1"', html)         # 标记可被筛选命中后展开
        self.assertIn('class="more-btn"', html)        # 提供「加载更多」

    def test_alert_reason_shown(self):
        html = self._build([_item("x")])
        self.assertIn("HTTP 429", html)                # 数据源失败原因展示在页脚


if __name__ == "__main__":
    unittest.main()
