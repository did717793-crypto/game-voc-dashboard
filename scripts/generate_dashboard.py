#!/usr/bin/env python3
"""
VOC 대시보드 HTML 생성기 v2.0
- 주요 이슈: 공지사항/업데이트 게시판
- 유저 동향: 카테고리(게임관련/버그제보/건의/기타) × 제목+링크 테이블
- 키워드 클라우드 제거
"""

import json, re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST      = timezone(timedelta(hours=9))
GIT_DIR  = Path(__file__).parent.parent
DATA_DIR = GIT_DIR / "data" / "DKR"
OUTPUT   = GIT_DIR / "index.html"

# ── 카테고리 분류 키워드 ──────────────────────────────────────
CAT_RULES = [
    ("버그·오류", ["버그", "오류", "에러", "error", "제보", "크래시", "튕김", "다운", "오작동",
                  "안됨", "안되는", "먹통", "끊김", "렉", "팅김"]),
    ("건의·요청", ["건의", "요청", "개선", "추가해", "넣어줘", "바꿔", "수정", "해주세요",
                  "해주시면", "원합니다", "바랍니다", "개편"]),
    ("게임 관련", ["공략", "팁", "가이드", "정보", "공유", "방법", "추천", "캐릭터", "아이템",
                  "장비", "스킬", "빌드", "던전", "보스", "레이드", "이벤트", "업데이트",
                  "패치", "시스템", "콘텐츠"]),
]

def categorize(title: str, body: str = "") -> str:
    text = (title + " " + body[:200]).lower()
    for cat, keywords in CAT_RULES:
        if any(k in text for k in keywords):
            return cat
    return "기타"


# ── 날짜 로드 ────────────────────────────────────────────────
def available_dates() -> list[str]:
    return sorted([f.stem for f in DATA_DIR.glob("*.json")], reverse=True)

def load(date_str: str) -> dict | None:
    p = DATA_DIR / f"{date_str}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ── 주요 이슈 HTML ───────────────────────────────────────────
def build_major_issues(official_posts: list[dict]) -> str:
    if not official_posts:
        return "<p class='empty'>해당 기간 공지·업데이트 없음</p>"

    rows = ""
    for p in official_posts:
        board = p.get("board_name", "")
        title = p.get("title", "")[:80]
        url   = p.get("url", "#")
        date  = (p.get("created_at", "") or "")[:10]
        badge_cls = "badge-notice" if "공지" in board else "badge-update"
        rows += f"""
        <li>
          <span class="issue-badge {badge_cls}">{board}</span>
          <a href="{url}" target="_blank" class="issue-link">{title}</a>
          <span class="issue-date">{date}</span>
        </li>"""

    return f"<ul class='issue-list'>{rows}</ul>"


# ── 유저 동향 테이블 HTML ────────────────────────────────────
def build_voc_table(posts: list[dict]) -> str:
    if not posts:
        return "<p class='empty'>수집된 게시물 없음</p>"

    # 카테고리별 분류
    cat_map: dict[str, list[dict]] = defaultdict(list)
    for p in posts:
        cat = categorize(p.get("title",""), p.get("body",""))
        cat_map[cat].append(p)

    cat_order = ["게임 관련", "버그·오류", "건의·요청", "기타"]

    rows = ""
    for cat in cat_order:
        items = cat_map.get(cat, [])
        if not items:
            continue

        # 카테고리 행 헤더 (rowspan)
        first = True
        for p in items:
            title = p.get("title","")[:60]
            url   = p.get("url","#")
            cmt   = p.get("comment_count",0)
            views = p.get("view_count",0)
            cmt_badge = f'<span class="cmt-badge">💬{cmt}</span>' if cmt else ""

            if first:
                rows += f"""
        <tr>
          <td class="cat-cell" rowspan="{len(items)}">{cat}</td>
          <td class="content-cell">
            <a href="{url}" target="_blank" class="post-link">{title}</a>{cmt_badge}
          </td>
          <td class="views-cell">{views:,}</td>
        </tr>"""
                first = False
            else:
                rows += f"""
        <tr>
          <td class="content-cell">
            <a href="{url}" target="_blank" class="post-link">{title}</a>{cmt_badge}
          </td>
          <td class="views-cell">{views:,}</td>
        </tr>"""

    return f"""
    <table class="voc-table">
      <thead>
        <tr><th style="width:90px">항목</th><th>내용</th><th style="width:60px">조회</th></tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


# ── 통계 카드 HTML ───────────────────────────────────────────
def build_stats(posts: list[dict], official: list[dict]) -> str:
    total    = len(posts)
    comments = sum(len(p.get("comments",[])) for p in posts)
    bugs     = sum(1 for p in posts if categorize(p.get("title",""), p.get("body","")) == "버그·오류")
    suggests = sum(1 for p in posts if categorize(p.get("title",""), p.get("body","")) == "건의·요청")

    return f"""
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-num">{total}</div>
        <div class="stat-label">유저 게시물</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{comments}</div>
        <div class="stat-label">댓글</div>
      </div>
      <div class="stat-card neg-card">
        <div class="stat-num">{bugs}</div>
        <div class="stat-label">버그·오류</div>
      </div>
      <div class="stat-card warn-card">
        <div class="stat-num">{suggests}</div>
        <div class="stat-label">건의·요청</div>
      </div>
    </div>"""


# ── 메인 생성 ────────────────────────────────────────────────
def generate():
    dates = available_dates()
    now   = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    if not dates:
        latest_date = (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")
        body = f"<p class='empty'>아직 수집된 데이터 없음 (기대 파일: data/DKR/{latest_date}.json)</p>"
    else:
        # 일간: 최신 1일
        daily_data    = load(dates[0])
        daily_posts   = daily_data.get("posts", []) if daily_data else []
        daily_official = daily_data.get("official_posts", []) if daily_data else []

        # 주간: 최근 7일
        weekly_dates   = dates[:7]
        weekly_posts   = []
        weekly_official = []
        for d in weekly_dates:
            wd = load(d)
            if wd:
                weekly_posts.extend(wd.get("posts", []))
                weekly_official.extend(wd.get("official_posts", []))

        weekly_range = f"{weekly_dates[-1]} ~ {weekly_dates[0]}" if len(weekly_dates)>1 else weekly_dates[0]

        body = f"""
    <div class="subtab-nav">
      <button class="subtab-btn active" onclick="switchSub('daily', this)">
        📅 일간 <span class="sbadge">{dates[0]}</span>
      </button>
      <button class="subtab-btn" onclick="switchSub('weekly', this)">
        📆 주간 <span class="sbadge">{len(weekly_dates)}일</span>
      </button>
    </div>

    <!-- 일간 -->
    <div id="sub-daily" class="subtab-content active">
      <div class="section-title">📢 주요 이슈</div>
      {build_major_issues(daily_official)}

      <div class="section-title">👥 유저 동향</div>
      {build_stats(daily_posts, daily_official)}
      {build_voc_table(daily_posts)}
    </div>

    <!-- 주간 -->
    <div id="sub-weekly" class="subtab-content">
      <div class="period-bar">📊 {weekly_range}</div>
      <div class="section-title">📢 주요 이슈</div>
      {build_major_issues(weekly_official)}
      <div class="section-title">👥 유저 동향</div>
      {build_stats(weekly_posts, weekly_official)}
      {build_voc_table(weekly_posts)}
    </div>

    <div class="updated-at">마지막 업데이트: {now}</div>
"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NTRANCE VOC 대시보드 — DKR</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Malgun Gothic","Apple SD Gothic Neo",sans-serif;background:#f0f2f5;color:#1a1a2e;min-height:100vh}}

/* 헤더 */
.header{{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);color:#fff;padding:18px 28px;display:flex;align-items:center;justify-content:space-between;box-shadow:0 2px 12px rgba(0,0,0,.3)}}
.header h1{{font-size:19px;font-weight:700}}
.header .sub{{font-size:12px;color:#8892b0;margin-top:3px}}
.header .ts{{font-size:11px;color:#8892b0}}

/* 게임 탭 */
.main{{max-width:1000px;margin:0 auto;padding:20px 14px}}
.tab-nav{{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}}
.tab-btn{{padding:9px 18px;border:2px solid #dde1e7;border-radius:7px;background:#fff;cursor:pointer;font-size:13px;font-weight:600;color:#5f6368;transition:all .2s;display:flex;align-items:center;gap:7px}}
.tab-btn:hover{{border-color:#1a73e8;color:#1a73e8}}
.tab-btn.active{{background:#1a73e8;border-color:#1a73e8;color:#fff}}
.tab-dot{{width:8px;height:8px;border-radius:50%}}
.tab-panel{{display:none}}.tab-panel.active{{display:block}}

/* 카드 */
.panel-card{{background:#fff;border-radius:12px;padding:22px;box-shadow:0 1px 6px rgba(0,0,0,.08)}}

/* 서브탭 */
.subtab-nav{{display:flex;gap:6px;margin-bottom:18px}}
.subtab-btn{{padding:7px 16px;border:1.5px solid #dde1e7;border-radius:6px;background:#fff;cursor:pointer;font-size:12px;font-weight:600;color:#5f6368;transition:all .2s}}
.subtab-btn.active{{background:#e8f0fe;border-color:#1a73e8;color:#1a73e8}}
.subtab-content{{display:none}}.subtab-content.active{{display:block}}
.sbadge{{background:#e8f0fe;color:#1a73e8;font-size:10px;padding:2px 5px;border-radius:3px;margin-left:3px}}
.subtab-btn.active .sbadge{{background:#fff}}

/* 섹션 타이틀 */
.section-title{{font-size:13px;font-weight:700;color:#3c4043;margin:20px 0 10px;padding-left:8px;border-left:3px solid #1a73e8}}

/* 주요 이슈 */
.issue-list{{list-style:none;display:flex;flex-direction:column;gap:7px;padding:2px 0}}
.issue-list li{{display:flex;align-items:center;gap:8px;font-size:13px}}
.issue-badge{{font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;white-space:nowrap;flex-shrink:0}}
.badge-notice{{background:#e3f2fd;color:#1565c0}}
.badge-update{{background:#e8f5e9;color:#2e7d32}}
.issue-link{{color:#1a1a2e;text-decoration:none;flex:1}}
.issue-link:hover{{color:#1a73e8;text-decoration:underline}}
.issue-date{{font-size:11px;color:#9aa0a6;white-space:nowrap;flex-shrink:0}}

/* 통계 카드 */
.stats-row{{display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap}}
.stat-card{{flex:1;min-width:90px;background:#f8f9fa;border-radius:9px;padding:14px;text-align:center;border:1.5px solid #e8eaed}}
.stat-card.neg-card{{border-color:#fce8e6;background:#fef9f9}}
.stat-card.warn-card{{border-color:#fef3cd;background:#fffdf0}}
.stat-num{{font-size:24px;font-weight:800;color:#1a73e8}}
.neg-card .stat-num{{color:#d93025}}
.warn-card .stat-num{{color:#f57c00}}
.stat-label{{font-size:11px;color:#5f6368;margin-top:3px}}

/* VOC 테이블 */
.voc-table{{width:100%;border-collapse:collapse;font-size:12.5px}}
.voc-table th{{background:#f1f3f4;padding:8px 10px;text-align:left;font-size:11px;color:#5f6368;border-bottom:1.5px solid #e8eaed;font-weight:600}}
.voc-table td{{padding:8px 10px;border-bottom:1px solid #f1f3f4;vertical-align:middle}}
.voc-table tr:hover td{{background:#f8f9fa}}
.cat-cell{{font-weight:700;font-size:12px;color:#3c4043;background:#fafafa;border-right:2px solid #e8eaed;text-align:center;white-space:nowrap}}
.content-cell{{line-height:1.5}}
.views-cell{{text-align:right;color:#9aa0a6;font-size:11px;white-space:nowrap}}
.post-link{{color:#1a1a2e;text-decoration:none}}
.post-link:hover{{color:#1a73e8;text-decoration:underline}}
.cmt-badge{{font-size:10px;color:#5f6368;margin-left:5px;background:#f1f3f4;padding:1px 5px;border-radius:3px}}

/* 기타 */
.period-bar{{font-size:12px;color:#5f6368;background:#f8f9fa;padding:7px 12px;border-radius:5px;margin-bottom:14px}}
.updated-at{{font-size:11px;color:#9aa0a6;text-align:right;margin-top:18px}}
.empty{{color:#9aa0a6;font-size:13px;padding:20px;text-align:center}}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>📊 NTRANCE VOC 대시보드</h1>
    <div class="sub">네이버 라운지 유저 동향 자동 수집</div>
  </div>
  <div class="ts">생성: {now}</div>
</div>

<div class="main">
  <!-- 게임 탭 -->
  <div class="tab-nav">
    <button class="tab-btn active" onclick="switchTab('DKR',this)">
      <span class="tab-dot" style="background:#1a73e8"></span>DK모바일:리본
    </button>
    <!-- 추후: COCW, 베르시온 -->
  </div>

  <div class="panel-card">
    <div id="tab-DKR" class="tab-panel active">
      {body}
    </div>
  </div>
</div>

<script>
function switchTab(key, btn) {{
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tab-'+key).classList.add('active');
}}
function switchSub(sub, btn) {{
  const panel = btn.closest('.tab-panel');
  panel.querySelectorAll('.subtab-btn').forEach(b=>b.classList.remove('active'));
  panel.querySelectorAll('.subtab-content').forEach(c=>c.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('sub-'+sub).classList.add('active');
}}
</script>
</body>
</html>"""

    OUTPUT.write_text(html, encoding="utf-8")
    print(f"[DONE] 대시보드 생성: {OUTPUT}")


if __name__ == "__main__":
    generate()
