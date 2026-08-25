# -*- coding: utf-8 -*-
"""报告生成：将当日条目渲染为独立单文件 HTML 日报（含样式、深色模式，无外部依赖）。"""

import html
import os
from datetime import datetime, timedelta

import config

CSS = """
:root {
  --bg: #f3f5f9; --card: #ffffff; --text: #1f2937; --muted: #6b7280;
  --border: #e5e7eb; --link: #1d4ed8; --chip-bg: #ffffff;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1420; --card: #171e2e; --text: #e5e7eb; --muted: #9ca3af;
    --border: #2a3447; --link: #8ab4ff; --chip-bg: #171e2e;
  }
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg); color: var(--text);
  font-family: -apple-system, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
  line-height: 1.65; padding-bottom: 60px;
}
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
.container { max-width: 1000px; margin: 0 auto; padding: 0 22px; }

/* ---------- 头部 ---------- */
.hero {
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 55%, #db2777 120%);
  color: #fff; padding: 44px 0 36px; margin-bottom: 18px;
}
.hero h1 { font-size: 30px; letter-spacing: .5px; }
.hero .sub { opacity: .92; margin-top: 6px; font-size: 15px; }
.stats { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 20px; }
.stat-chip {
  background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.25);
  border-radius: 10px; padding: 8px 16px; backdrop-filter: blur(4px);
}
.stat-chip b { font-size: 19px; margin-right: 6px; }
.stat-chip span { font-size: 13px; opacity: .9; }

/* ---------- 分类导航 ---------- */
nav.cats {
  position: sticky; top: 0; z-index: 10;
  background: var(--bg); padding: 12px 0; border-bottom: 1px solid var(--border);
}
/* 分类 chip 行与筛选工具条各占一行（避免工具条遮挡分类 chip）；
   工具条整体靠右，窄屏自动换行 */
.chips { display: flex; flex-wrap: nowrap; gap: 7px; overflow-x: auto; scrollbar-width: none; -ms-overflow-style: none; padding-bottom: 4px; }
.chips.wrap { flex-wrap: wrap; overflow: visible; }   /* 今日热词：换行完整显示，不被裁切 */
.chips::-webkit-scrollbar { display: none; }
.chip {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--chip-bg); border: 1px solid var(--border);
  border-radius: 999px; padding: 5px 12px; font-size: 13px; color: var(--text);
  white-space: nowrap; flex-shrink: 0;
}
.chip:hover { text-decoration: none; border-color: #6366f1; }
.chip .n { color: var(--muted); font-size: 12px; }
.chip.kw { cursor: pointer; }
.chip.kw:hover { border-color: #6366f1; color: #6366f1; }
.chip.kw.active { background: #6366f1; border-color: #6366f1; color: #fff; }
.chip.kw.active .n { color: #fff; }

/* ---------- 板块 ---------- */
section { margin-top: 34px; scroll-margin-top: 130px; }
.sec-head { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; cursor: pointer; user-select: none; }
.sec-head h2 { font-size: 21px; transition: color .15s ease; }
.sec-head:hover h2 { color: var(--link); }
.sec-head .toggle { font-size: 13px; color: var(--muted); transition: transform .15s ease; flex: none; }
section.collapsed .sec-head .toggle { transform: rotate(-90deg); }
section.collapsed .sec-head { margin-bottom: 0; }
section.collapsed > .container > *:not(.sec-head) { display: none; }
.sec-badge {
  font-size: 12.5px; color: #fff; border-radius: 999px; padding: 2px 11px;
}
.sec-line { flex: 1; height: 1px; background: var(--border); }

/* ---------- 卡片 ---------- */
.card {
  background: var(--card); border: 1px solid var(--border); border-radius: 14px;
  padding: 14px 18px; margin-bottom: 10px; transition: box-shadow .15s ease, transform .15s ease;
}
.card:hover { box-shadow: 0 6px 22px rgba(30,41,59,.12); transform: translateY(-1px); }
/* 超出封顶、默认隐藏的卡片：点「加载更多」移除 .beyond 后展开 */
.card.beyond { display: none; }
.more-btn {
  display: block; margin: 6px auto 14px; padding: 8px 18px; cursor: pointer;
  font-size: 13.5px; color: var(--link); background: var(--chip-bg);
  border: 1px solid var(--border); border-radius: 20px;
}
.more-btn:hover { border-color: var(--link); }
.card .title { font-size: 16.5px; font-weight: 600; }
.card .title a { color: var(--text); }
.card .title a:hover { color: var(--link); }
.card p.sum { color: var(--muted); font-size: 14px; margin-top: 6px; }
/* 亮点面板：一句话说明模型/智能体优势（不复述下载数，避免与 meta 重复） */
.hl-box { margin: 9px 0 2px; font-size: 13px; line-height: 1.6; color: var(--text);
          background: var(--bg); border: 1px solid var(--border);
          border-left: 3px solid var(--cat, var(--link));
          border-radius: 8px; padding: 6px 12px; }
.hl-box .hl-tag { color: var(--cat, var(--link)); font-weight: 700; margin-right: 7px; }
.meta { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; margin-top: 10px;
        font-size: 12.5px; color: var(--muted); }
.tag { color: #fff; border-radius: 6px; padding: 1px 9px; font-size: 12px; }
.score-wrap { display: inline-flex; align-items: center; gap: 6px; margin-left: auto; }
.bar { width: 64px; height: 5px; border-radius: 99px; background: var(--border); overflow: hidden; }
.bar i { display: block; height: 100%; border-radius: 99px;
         background: linear-gradient(90deg,#f97316,#ef4444); }
.score-num { color: #ef4444; font-weight: 700; }

/* ---------- 精选区 ---------- */
.top-item { display: flex; gap: 16px; }
.rank {
  flex: none; width: 40px; height: 40px; border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  font-weight: 800; font-size: 17px; color: #fff;
  background: linear-gradient(135deg, #f59e0b, #ef4444);
}
.rank.r2 { background: linear-gradient(135deg, #64748b, #94a3b8); }
.rank.r3 { background: linear-gradient(135deg, #b45309, #d97706); }

.note { color: var(--muted); font-size: 12.5px; margin: 4px 0 10px 2px; }
footer { margin-top: 48px; text-align: center; color: var(--muted); font-size: 12.5px; }
footer hr { border: none; border-top: 1px solid var(--border); margin-bottom: 14px; }

/* ---------- 报告索引页 ---------- */
.index-card { background: var(--card); border: 1px solid var(--border);
              border-radius: 12px; padding: 14px 20px; margin-bottom: 10px;
              display: flex; justify-content: space-between; align-items: center; }

/* ---------- 今日综述 / 热词 ---------- */
.brief-card { border-left: 4px solid #7c3aed; }
.brief-card p.body { margin-top: 10px; font-size: 14.5px; }

/* ---------- 相关报道折叠块 ---------- */
details.rel { margin-top: 8px; font-size: 13px; color: var(--muted); }
details.rel summary { cursor: pointer; user-select: none; }
details.rel ul { margin: 6px 0 2px 18px; }
details.rel li { margin-bottom: 4px; list-style: disc; }

.meta .gain { color: #f59e0b; font-weight: 600; }
.srclink { color: var(--muted); text-decoration: none; }
.srclink:hover { color: var(--link); text-decoration: underline; }

/* ---------- 工具栏：信源下拉筛选 / 关键词搜索 ---------- */
.toolbar { display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 8px 10px; padding: 8px 0 4px; flex: 0 0 100%; }
.sel, .qbox { flex: none; border: 1px solid var(--border); border-radius: 10px;
        background: var(--chip-bg); color: var(--text); padding: 6px 10px; font-size: 13px;
        font-family: inherit; outline: none; max-width: 240px; }
.qbox { width: 224px; flex: 1 1 224px; }
.sel:focus, .qbox:focus { border-color: #6366f1; }
#match-cnt { color: var(--muted); font-size: 12.5px; flex: none; }

/* ---------- 周报 ---------- */
.bars { display: flex; align-items: flex-end; gap: 10px; height: 130px;
        padding: 10px 4px 0; }
.bar-col { flex: 1; display: flex; flex-direction: column; align-items: center;
           gap: 6px; height: 100%; justify-content: flex-end; }
.bar-col i { display: block; width: 70%; max-width: 46px;
             background: linear-gradient(180deg,#6366f1,#8b5cf6);
             border-radius: 6px 6px 0 0; }
.bar-col .lbl { font-size: 11.5px; color: var(--muted); white-space: nowrap; }
.bar-col b { font-size: 12px; }
.wrow { display: flex; align-items: center; gap: 12px; padding: 9px 4px;
        border-bottom: 1px solid var(--border); font-size: 14px; }
.wrow:last-child { border-bottom: none; }
.wrow .rk { width: 26px; text-align: center; font-weight: 700;
            color: var(--muted); flex: none; }
.wrow .t { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis;
           white-space: nowrap; }
.wrow .sc { flex: none; color: #ef4444; font-weight: 700; font-size: 13px; }

/* ---------- 美化 1：卡片分类色条 + 悬浮高亮 ---------- */
.card { position: relative; overflow: hidden; }
.card::before {
  content: ""; position: absolute; left: 0; top: 9px; bottom: 9px; width: 4px;
  border-radius: 0 4px 4px 0; background: var(--cat, var(--border)); opacity: .8;
  transition: opacity .15s ease, box-shadow .15s ease;
}
.card:hover { border-color: var(--cat, var(--border)); }
.card:hover::before { opacity: 1; box-shadow: 0 0 10px var(--cat, var(--border)); }

/* ---------- 美化 6：渐变标题 ---------- */
.hero h1 {
  background: linear-gradient(90deg, #ffffff 0%, #dbeafe 52%, #fbcfe8 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}

/* ---------- 美化 5：空状态 ---------- */
#no-res {
  margin: 26px auto; max-width: 540px;
  background: var(--card); border: 1px dashed var(--border); border-radius: 14px;
}

/* ---------- 美化 4：热词词云悬浮 ---------- */
.chip.kw:hover { transform: translateY(-1px); }
.chip.kw:focus-visible { outline-offset: 3px; }

/* ---------- 美化 7：响应式 + 无障碍 ---------- */
:focus-visible { outline: 2px solid #6366f1; outline-offset: 2px; border-radius: 6px; }
@media (max-width: 640px) {
  .hero { padding: 30px 0 24px; }
  .hero h1 { font-size: 22px; }
  .card { padding: 12px 14px; }
  .sec-head h2 { font-size: 18px; }
  .toolbar { gap: 6px 8px; }
  .sel { flex: 1 1 auto; }
  .qbox { width: 100%; flex: 1 1 100%; }
}
@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: none !important; }
}
"""

TOP_N = 8          # 今日精选条数
PER_CATEGORY_CAP = 30   # 每个分类最多渲染条数


def _esc(s):
    return html.escape(str(s or ""), quote=True)


def fmt_num(n):
    n = int(n or 0)
    if n >= 10000:
        return f"{n / 10000:.1f}w"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def fmt_time(iso):
    if not iso:
        return ""
    try:
        return datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").strftime("%m-%d %H:%M")
    except ValueError:
        return iso[:10]


def metrics_text(item):
    m = item.get("metrics") or {}
    parts = []
    if m.get("stars"):
        star_str = f"⭐ {fmt_num(m['stars'])}"
        if m.get("stars_gain"):
            star_str += (f' <span class="gain">+{fmt_num(m["stars_gain"])}星/日</span>')
        parts.append(star_str)
    if m.get("downloads"):
        parts.append(f"⬇ {fmt_num(m['downloads'])} 近30天")
    if m.get("likes"):
        parts.append(f"👍 {fmt_num(m['likes'])}")
    if item.get("lang"):
        parts.append(_esc(item["lang"]))
    return " · ".join(parts)


def _rel_html(item):
    """同一事件的相关报道折叠块。"""
    rel = item.get("related") or []
    if not rel:
        return ""
    lis = "".join(
        f'<li><a href="{_esc(r["url"])}" target="_blank" rel="noopener">{_esc(r["title"])}</a>'
        f' <span>— {_esc(r["source"])}</span></li>'
        for r in rel
    )
    return (f'<details class="rel"><summary>📎 相关报道（{len(rel)}）</summary>'
            f'<ul>{lis}</ul></details>')


def _hl_html(item):
    """卡片亮点面板：一句话说明该模型/智能体的优势特点（不复述下载数）。"""
    hl = (item.get("highlight") or "").strip()
    if not hl:
        return ""
    return (f'<div class="hl-box"><span class="hl-tag">💡 优势</span>'
            f'{_esc(hl)}</div>')


def _origin_span(item):
    """AI Hot 等聚合条目显示其原始信源。"""
    origin = (item.get("metrics") or {}).get("origin")
    return f"<span>↳ {_esc(origin)}</span>" if origin else ""


def _clean_summary(item):
    """卡片摘要展示：HuggingFace 元数据摘要自带「近30天下载 / 👍」，与下方 meta
    的 metrics_text 完全重复，渲染时只保留任务类型等摘要独有信息，避免同一数据
    出现两次（今日热词点击筛选的数据-text 仍用原始 summary，不受影响）。"""
    s = item.get("summary", "") or ""
    if "近30天下载" in s:
        s = s.split("近30天下载", 1)[0].rstrip(" ·")
    return _esc(s)


def _card(item, hidden=False):
    cat = config.CATEGORIES[item["category"]]
    score = int(item.get("score", 0))
    summary = _clean_summary(item)
    extra = ""
    if item["source_type"] == "arxiv" and item.get("authors"):
        extra = f" · {_esc(item['authors'])}"
    # data-src / data-text 供前端「信源筛选 + 关键词搜索」使用
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    cls = "card" + (" beyond" if hidden else "")
    # data-beyond 标记「默认隐藏、需加载更多/筛选命中才展开」，
    # 用于清除筛选时把它们重新藏回（区别于已手动展开的卡片）。
    attr = ' data-beyond="1"' if hidden else ""
    return f"""
    <div class="{cls}"{attr} style="--cat:{cat['color']}" data-cat="{_esc(item['category'])}" data-src="{_esc(item['source'])}" data-text="{_esc(text)}">
      <div class="title">🔗 <a href="{_esc(item['url'])}" target="_blank" rel="noopener">{_esc(item['title'])}</a></div>
      {f'<p class="sum">{summary}</p>' if summary else ''}
      {_hl_html(item)}
      <div class="meta">
        <span class="tag" style="background:{cat['color']}">{cat['emoji']} {cat['name']}</span>
        <a class="srclink" href="{_esc(item['url'])}" target="_blank" rel="noopener">📡 {_esc(item['source'])}</a>
        {_origin_span(item)}
        {f'<span>🕐 {fmt_time(item.get("published_at"))}</span>' if item.get('published_at') else ''}
        <span>{metrics_text(item)}{extra}</span>
        <span class="score-wrap"><span class="bar"><i style="width:{score}%"></i></span><span class="score-num">{score}</span></span>
      </div>
      {_rel_html(item)}
    </div>"""


# 日报交互脚本：信源下拉筛选 + 关键词搜索
VIEW_JS = """
<script>
(function () {
  // 板块折叠：点击标题在展开/折叠间切换
  document.querySelectorAll("[data-sec] .sec-head").forEach(function (h) {
    h.addEventListener("click", function () {
      var sec = h.closest("section");
      if (sec) sec.classList.toggle("collapsed");
    });
  });
  // 点导航 chip 时展开对应分类；若正有热词/搜索/信源筛选，则一并清空，
  // 避免某分类被筛选隐藏后「点不开」
  document.querySelectorAll('nav.cats a.chip[href^="#"]').forEach(function (a) {
    a.addEventListener("click", function () {
      src = ""; q = ""; kw = "";
      var sel = document.getElementById("srcsel"); if (sel) sel.value = "";
      var qbox = document.getElementById("q"); if (qbox) qbox.value = "";
      document.querySelectorAll(".chip.kw.active").forEach(function (c) { c.classList.remove("active"); });
      var id = a.getAttribute("href").slice(1);
      var sec = document.getElementById(id);
      if (sec) {
        sec.classList.toggle("collapsed");            // 点击类目按钮折叠/展开
        if (!sec.classList.contains("collapsed")) {
          sec.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      }
      apply();
    });
  });

  var src = "";   // 选中的信源，空 = 全部
  var q = "";     // 搜索关键词（小写）
  var kw = "";    // 今日热词筛选（小写）
  // 规范化：与后端热词计数同一套规则（去空格/连字符/标点，保留字母数字与中文），
  // 让 "Claude5" 也能命中卡片里的 "Claude 5"，且热词条数 = 实际筛出卡片数
  function _norm(s) { return (s || "").toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]/g, ""); }
  function matches(c) {
    if (src && c.getAttribute("data-src") !== src) return false;
    var raw = (c.getAttribute("data-text") || "");
    if (q) {
      var nq = _norm(q), ntq = _norm(raw);
      if (nq && ntq.indexOf(nq) === -1) return false;
    }
    if (kw) {
      var nk = _norm(kw), ntk = _norm(raw);
      if (nk && ntk.indexOf(nk) === -1) return false;
    }
    return true;
  }
  function apply() {
    var filtering = !!(src || q || kw);
    var n = 0, firstVisible = null;
    var catCounts = {};   // 各分类「筛选后命中数」
    document.querySelectorAll(".card[data-src]").forEach(function (c) {
      var ok = matches(c);
      if (!ok) {
        c.style.display = "none";
        return;
      }
      if (filtering) {
        // 筛选命中：真正移除 .beyond（空 inline display 无法覆盖 CSS 的
        // .card.beyond{display:none}），隐藏卡片才能显现
        c.classList.remove("beyond");
        c.style.display = "";
      } else if (c.hasAttribute("data-beyond")) {
        // 无筛选：恢复「加载更多」之前的隐藏状态
        c.classList.add("beyond");
        c.style.display = "none";
      } else {
        c.style.display = "";
      }
      n++; if (!firstVisible) firstVisible = c;
      var cat = c.getAttribute("data-cat");
      if (cat) catCounts[cat] = (catCounts[cat] || 0) + 1;
    });
    // 更新分类数字：导航 chip 与板块徽标显示「筛选后命中数」，其求和 = 热词 ×N；
    // 无筛选时恢复各分类总数。导航 chip 命中为 0 时隐藏，避免干扰。
    document.querySelectorAll("[data-cat][data-total]").forEach(function (el) {
      var cat = el.getAttribute("data-cat");
      var total = el.getAttribute("data-total") || "0";
      var span = el.querySelector(".n") || el;
      if (filtering) {
        var v = catCounts[cat] || 0;
        if (el.classList.contains("chip")) el.style.display = v ? "" : "none";
        span.textContent = v;
      } else {
        if (el.classList.contains("chip")) el.style.display = "";
        span.textContent = total;
      }
    });
    // 没有可见卡片的分类板块整体隐藏
    document.querySelectorAll("[data-sec]").forEach(function (sec) {
      var cards = sec.querySelectorAll(".card[data-src]");
      var any = Array.prototype.some.call(cards, function (c) {
        return c.style.display !== "none";
      });
      sec.style.display = any ? "" : "none";
    });
    var nr = document.getElementById("no-res");
    if (nr) nr.hidden = n > 0;
    var cnt = document.getElementById("match-cnt");
    if (cnt) cnt.textContent = (src || q || kw) ? ("匹配 " + n + " 条") : "";
    // 筛选后把视口移到第一条命中结果：避免当前板块被隐藏后「以为没筛选」
    if (filtering && firstVisible) {
      var r = firstVisible.getBoundingClientRect();
      var vh = window.innerHeight || document.documentElement.clientHeight;
      if (r.top < 0 || r.top > vh) {
        firstVisible.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
  }
  // 「加载更多」：展开该板块超出封顶、默认隐藏的卡片（移除 beyond 类与标记，永久展开）
  document.querySelectorAll(".more-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var sec = document.getElementById(btn.getAttribute("data-sec"));
      if (sec) sec.querySelectorAll(".card.beyond").forEach(function (c) {
        c.classList.remove("beyond");
        c.removeAttribute("data-beyond");
        c.style.display = "";
      });
      btn.style.display = "none";
    });
  });
  var sel = document.getElementById("srcsel");
  if (sel) sel.addEventListener("change", function () {
    src = sel.value;
    apply();
  });
  var qbox = document.getElementById("q");
  if (qbox) qbox.addEventListener("input", function () {
    q = qbox.value.trim().toLowerCase();
    kw = "";                                   // 手动搜索时清除热词高亮
    document.querySelectorAll(".chip.kw.active").forEach(function (c) { c.classList.remove("active"); });
    apply();
  });
  // 点击「今日热词」：筛选包含该词的条目，再次点击取消
  document.querySelectorAll(".chip.kw").forEach(function (chip) {
    chip.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); chip.click(); }
    });
    chip.addEventListener("click", function () {
      var k = (chip.getAttribute("data-kw") || "").toLowerCase();
      if (!k) return;
      if (kw === k) {
        kw = "";
        chip.classList.remove("active");
      } else {
        kw = k;
        document.querySelectorAll(".chip.kw.active").forEach(function (c) { c.classList.remove("active"); });
        chip.classList.add("active");
      }
      apply();
    });
  });
  apply();
})();
</script>
"""


def build_daily_html(date_str, items, stats, db_total,
                     brief=None, hot_words=None, merged_groups=0, source_alerts=None):
    """生成某天的完整日报 HTML 字符串。"""
    weekday = "一二三四五六日"[datetime.strptime(date_str, "%Y-%m-%d").weekday()]
    gen_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    top = items[:TOP_N]
    used_urls = {it["url"] for it in top}
    source_alerts = source_alerts or []
    # 实际会渲染成「可筛选卡片」的条目集合（与前端 .card[data-src] 一一对应）。
    # 热词计数必须基于它，否则热词条数会和「筛选出的条子数」对不上。
    # 注意：TOP 精选与超出封顶数的分类卡片都渲染进 DOM（默认隐藏），
    # 同样可参与前端筛选，因此计数须覆盖「全部可筛选卡片」（TOP + 分类）。
    rendered_items = list(top)
    for key in config.CATEGORY_PRIORITY:
        cat_items = [it for it in items
                     if it["category"] == key and it["url"] not in used_urls]
        rendered_items.extend(cat_items)

    # ---- 头部统计
    merged_chip = (f'<div class="stat-chip"><b>{merged_groups}</b><span>合并重复事件</span></div>'
                   if merged_groups else "")
    hero = f"""
  <div class="hero"><div class="container">
    <h1>🛰️ AI 项目情报站 · 每日精选</h1>
    <div class="sub">{date_str} 星期{weekday} ｜ 自动抓取国内外大模型与 AI 项目动态</div>
    <div class="stats">
      <div class="stat-chip"><b>{stats['total']}</b><span>今日收录</span></div>
      <div class="stat-chip"><b>{len([v for v in stats['by_category'].values() if v])}</b><span>涉及分类</span></div>
      <div class="stat-chip"><b>{len(stats['by_source'])}</b><span>数据源</span></div>
      <div class="stat-chip"><b>{min(TOP_N, len(items))}</b><span>今日精选</span></div>
      {merged_chip}
    </div>
  </div></div>"""

    # ---- 分类导航 + 工具栏（信源下拉筛选 / 关键词搜索）
    chips = []
    for key in config.CATEGORY_PRIORITY:
        cnt = stats["by_category"].get(key, 0)
        if not cnt:
            continue
        c = config.CATEGORIES[key]
        chips.append(f'<a class="chip" href="#cat-{key}" data-cat="{key}" data-total="{cnt}">'
                     f'{c["emoji"]} {c["name"]} <span class="n">{cnt}</span></a>')
    src_opts = ['<option value="">📡 全部信源</option>']
    for name, cnt in sorted(stats["by_source"].items(), key=lambda x: -x[1]):
        src_opts.append(f'<option value="{_esc(name)}">{_esc(name)}（{cnt}）</option>')
    toolbar = f"""
<div class="toolbar">
  <select id="srcsel" class="sel" title="按信源筛选">{"".join(src_opts)}</select>
  <input id="q" class="qbox" type="search" placeholder="🔍 搜索标题 / 摘要">
  <span id="match-cnt"></span>
</div>"""
    chips_row = (f'<div class="chips wrap">{"".join(chips)}</div>' if chips else "")
    nav = f'<nav class="cats"><div class="container">{chips_row}{toolbar}</div></nav>'

    body_parts = [hero, nav]

    # ---- 今日综述（LLM 生成）或热词兜底
    if brief:
        body_parts.append(f"""
  <section id="brief"><div class="container">
    <div class="card brief-card">
      <div class="sec-head" style="margin-bottom:0"><span class="toggle">▾</span><h2>📝 今日综述</h2><div class="sec-line"></div></div>
      <p class="body">{_esc(brief)}</p>
      <p class="note" style="margin-top:10px">由大模型基于今日热度最高的条目自动生成，仅供参考</p>
    </div>
  </div></section>""")
    elif hot_words:
        # 用「实际渲染的可筛选卡片」重算热词计数，保证 热词条数 == 筛选出的条子数
        try:
            from classifier import hot_words as _compute_hot_words
            hw = _compute_hot_words(rendered_items, top_n=8)
        except Exception:
            hw = list(hot_words)
        chips = "".join(
            f'<span class="chip kw" data-kw="{_esc(w)}" tabindex="0" role="button" '
            f'aria-label="筛选包含 {_esc(w)} 的条目" '
            f'title="点击筛选包含「{_esc(w)}」的条目">{_esc(w)} '
            f'<span class="n">×{c}</span></span>'
            for w, c in hw)
        body_parts.append(f"""
  <section id="hotwords"><div class="container">
    <div class="sec-head"><span class="toggle">▾</span><h2>🔥 今日热词</h2><div class="sec-line"></div></div>
    <div class="chips wrap">{chips}</div>
  </div></section>""")

    # ---- 今日精选
    if top:
        rank_cards = []
        for i, it in enumerate(top):
            cls = "rank" if i == 0 else f"rank r{min(i + 1, 3)}"
            cat = config.CATEGORIES[it["category"]]
            score = int(it.get("score", 0))
            summary = _clean_summary(it)
            mt = metrics_text(it)
            ttext = f"{it.get('title', '')} {it.get('summary', '')}".lower()
            rank_cards.append(f"""
      <div class="card" style="--cat:{cat['color']}" data-cat="{_esc(it['category'])}" data-src="{_esc(it['source'])}" data-text="{_esc(ttext)}">
        <div class="top-item">
          <div class="{cls}">{i + 1}</div>
          <div style="flex:1">
            <div class="title"><a href="{_esc(it['url'])}" target="_blank" rel="noopener">{_esc(it['title'])}</a></div>
            {f'<p class="sum">{summary}</p>' if summary else ''}
            {_hl_html(it)}
            <div class="meta">
              <span class="tag" style="background:{cat['color']}">{cat['emoji']} {cat['name']}</span>
              <a class="srclink" href="{_esc(it['url'])}" target="_blank" rel="noopener">📡 {_esc(it['source'])}</a>
              {_origin_span(it)}
              {f'<span>{mt}</span>' if mt else ''}
              <span class="score-wrap"><span class="bar"><i style="width:{score}%"></i></span><span class="score-num">{score}</span></span>
            </div>
            {_rel_html(it)}
          </div>
        </div>
      </div>""")
        body_parts.append(
            f'<section id="top" data-sec><div class="container"><div class="sec-head"><span class="toggle">▾</span><h2>🔥 今日精选 TOP{min(TOP_N, len(top))}</h2>'
            f'<div class="sec-line"></div></div>{"".join(rank_cards)}</div></section>')

    # ---- 各分类板块（全部渲染，超出封顶的默认隐藏，可「加载更多」展开）
    for key in config.CATEGORY_PRIORITY:
        cat_items = [it for it in items if it["category"] == key and it["url"] not in used_urls]
        if not cat_items:
            continue
        c = config.CATEGORIES[key]
        cards = "".join(
            _card(it, hidden=(i >= PER_CATEGORY_CAP))
            for i, it in enumerate(cat_items)
        )
        more = ""
        if len(cat_items) > PER_CATEGORY_CAP:
            more = (f'<button type="button" class="more-btn" data-sec="cat-{key}">'
                    f'展开其余 {len(cat_items) - PER_CATEGORY_CAP} 条 ▾</button>')
        body_parts.append(
            f'<section id="cat-{key}" data-sec class="collapsed"><div class="container">'
            f'<div class="sec-head">'
            f'<span class="toggle">▾</span>'
            f'<h2>{c["emoji"]} {c["name"]}</h2>'
            f'<span class="sec-badge" style="background:{c["color"]}" '
            f'data-cat="{key}" data-total="{len(cat_items)}">{len(cat_items)}</span>'
            f'<div class="sec-line"></div></div>{cards}{more}'
            f'</div></section>')
    body_parts.append('<p class="note" id="no-res" hidden '
                      'style="text-align:center;padding:34px 0">🫙 没有匹配的条目——试试更换信源或关键词</p>')

    src_detail = "、".join(f"{k}({v})" for k, v in sorted(stats["by_source"].items(), key=lambda x: -x[1]))
    alert_line = ""
    if source_alerts:
        parts = []
        for n, d, reason in source_alerts:
            r = (reason or "")[:60]
            parts.append(f"{n}({d}天" + (f"：{r}" if r else "") + ")")
        alert_line = (f'<p style="color:#ef4444">⚠️ 数据源异常（连续失败），已自动容错：'
                      f'{", ".join(parts)}</p>')
    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🛰️</text></svg>">
<title>AI 每日精选 · {date_str}</title>
<style>{CSS}</style>
</head>
<body>
{''.join(body_parts)}
<footer><div class="container"><hr>
{alert_line}
<p>报告生成时间：{gen_time} ｜ 数据库累计收录 {db_total} 条</p>
<p>来源分布：{_esc(src_detail)}</p>
<p>本报告由 AI 项目信息收集平台自动抓取公开数据源生成，内容版权归原作者所有。</p>
<p><a href="weekly.html">📊 查看近 7 天周报</a> ｜ <a href="index.html">← 返回历史报告列表</a></p>
</div></footer>
{VIEW_JS}
</body>
</html>"""
    return page


def build_index_html(dates_desc):
    """历史报告索引页（含周报固定入口）。"""
    rows = ['<div class="index-card"><div>📊 <a href="weekly.html">近 7 天周报</a></div>'
            '<span class="note">每次运行自动更新</span></div>']
    for d, cnt in dates_desc:
        rows.append(
            f'<div class="index-card"><div>📰 <a href="daily_{d}.html">{d} AI 每日精选</a></div>'
            f'<span class="note">{cnt} 条</span></div>')
    empty = '<p class="note">暂无历史报告</p>'
    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI 情报站 · 历史报告</title><style>{CSS}</style></head>
<body><div class="hero"><div class="container">
<h1>🛰️ AI 项目情报站</h1><div class="sub">历史每日精选报告</div></div></div>
<div class="container">{''.join(rows) or empty}</div>
</body></html>"""
    return page


def write_reports(date_str, items, stats, db_total,
                  brief=None, hot_words=None, merged_groups=0, source_alerts=None):
    """写出当日日报并刷新索引页。返回文件路径。"""
    os.makedirs(config.REPORT_DIR, exist_ok=True)
    daily_path = os.path.join(config.REPORT_DIR, f"daily_{date_str}.html")
    with open(daily_path, "w", encoding="utf-8") as f:
        f.write(build_daily_html(date_str, items, stats, db_total,
                                 brief=brief, hot_words=hot_words,
                                 merged_groups=merged_groups,
                                 source_alerts=source_alerts))

    # 扫描已有报告生成索引（按日期倒序）
    reports = []
    for fn in os.listdir(config.REPORT_DIR):
        if fn.startswith("daily_") and fn.endswith(".html"):
            d = fn[len("daily_"):-len(".html")]
            try:
                datetime.strptime(d, "%Y-%m-%d")
                reports.append(d)
            except ValueError:
                pass
    counts = {}
    for it in items:
        counts[date_str] = counts.get(date_str, 0) + 1
    dates_desc = []
    for d in sorted(reports, reverse=True):
        if d == date_str:
            dates_desc.append((d, stats["total"]))
        else:
            dates_desc.append((d, ""))
    index_path = os.path.join(config.REPORT_DIR, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(build_index_html(dates_desc))
    return daily_path, index_path


# ---------------------------------------------------------------- 周报
def build_weekly_html(start_date, end_date, counts, week_items, gh_gains):
    """生成滚动 7 天周报 HTML。counts: {date: n}; gh_gains: [{title,url,gain,stars}]"""
    gen_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    total = sum(counts.values())
    days = []
    d0 = datetime.strptime(start_date, "%Y-%m-%d")
    d1 = datetime.strptime(end_date, "%Y-%m-%d")
    all_dates = [(d0 + timedelta(days=i)).strftime("%Y-%m-%d")
                 for i in range((d1 - d0).days + 1)]
    max_cnt = max([counts.get(d, 0) for d in all_dates] + [1])

    # ---- 每日收录柱状图
    bar_cols = []
    for d in all_dates:
        c = counts.get(d, 0)
        h = int(90 * c / max_cnt) if c else 2
        lbl = d[5:].replace("-", "/")
        bar_cols.append(f'<div class="bar-col"><b>{c}</b>'
                        f'<i style="height:{h}px"></i><span class="lbl">{lbl}</span></div>')
    bars_html = f'<div class="bars">{"".join(bar_cols)}</div>'

    # ---- 本周热门
    top = week_items[: config.WEEKLY_TOP_N]
    rows = []
    for i, it in enumerate(top):
        cat = config.CATEGORIES[it["category"]]
        score = int(it.get("score", 0))
        rows.append(f"""
      <div class="wrow"><span class="rk">{i + 1}</span>
        <span class="tag" style="background:{cat['color']};flex:none">{cat['emoji']} {cat['name']}</span>
        <span class="t"><a href="{_esc(it['url'])}" target="_blank" rel="noopener">{_esc(it['title'])}</a></span>
        <span class="sc">{score}</span>
      </div>""")
    top_html = f'<div>{"".join(rows)}</div>' if rows else '<p class="note">暂无数据</p>'

    # ---- GitHub 周增星榜
    gh_rows = []
    for i, g in enumerate(gh_gains[: config.WEEKLY_GH_GAIN_TOP]):
        title = g.get("title") or g["url"]
        gh_rows.append(f"""
      <div class="wrow"><span class="rk">{i + 1}</span>
        <span class="t"><a href="{_esc(g['url'])}" target="_blank" rel="noopener">{_esc(title)}</a></span>
        <span class="gain" style="flex:none">+{fmt_num(g["gain"])} 星</span>
        <span style="flex:none;color:var(--muted)">现 {_esc(fmt_num(g["stars"] or 0))}</span>
      </div>""")
    gh_html = (f'<div>{"".join(gh_rows)}</div>' if gh_rows
               else '<p class="note">快照数据积累中——首次运行只记录基线，'
                    '从第二次运行起开始统计日增/周增星</p>')

    # ---- 分类分布
    cat_count = {}
    for it in week_items:
        cat_count[it["category"]] = cat_count.get(it["category"], 0) + 1
    chips = "".join(
        f'<span class="chip">{c["emoji"]} {c["name"]} <span class="n">{cat_count[k]}</span></span>'
        for k, c in config.CATEGORIES.items() if cat_count.get(k))

    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI 情报站 · 周报 {start_date} ~ {end_date}</title>
<style>{CSS}</style>
</head>
<body>
<div class="hero"><div class="container">
  <h1>📊 AI 情报站 · 近 7 天周报</h1>
  <div class="sub">{start_date} ~ {end_date} ｜ 累计收录 <b>{total}</b> 条（每次运行自动刷新）</div>
</div></div>
<div class="container">
  <section id="w-daily"><div class="sec-head"><h2>📅 每日收录趋势</h2><div class="sec-line"></div></div>{bars_html}</section>
  <section id="w-top"><div class="sec-head"><h2>🔥 本周热门 TOP{min(config.WEEKLY_TOP_N, len(top))}</h2><div class="sec-line"></div></div>{top_html}</section>
  <section id="w-gh"><div class="sec-head"><h2>🚀 GitHub 周增星榜</h2><div class="sec-line"></div></div>{gh_html}</section>
  <section id="w-cat"><div class="sec-head"><h2>🗂 分类分布</h2><div class="sec-line"></div></div><div class="chips">{chips}</div></section>
</div>
<footer><div class="container"><hr>
<p>报告生成时间：{gen_time} ｜ 统计窗口：最近 {len(all_dates)} 天</p>
<p><a href="index.html">← 返回历史报告列表</a></p>
</div></footer>
</body>
</html>"""
    return page


def write_weekly(start_date, end_date, counts, week_items, gh_gains):
    """写出周报文件，返回路径。"""
    os.makedirs(config.REPORT_DIR, exist_ok=True)
    path = os.path.join(config.REPORT_DIR, "weekly.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_weekly_html(start_date, end_date, counts, week_items, gh_gains))
    return path
