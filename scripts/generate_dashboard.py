#!/usr/bin/env python3
"""
VOC 대시보드 HTML 생성기 v3.0
- analyzed.json 우선 사용 (Claude 분석 결과)
- 없으면 raw JSON 기반 폴백 렌더링
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST     = timezone(timedelta(hours=9))
GIT_DIR = Path(__file__).parent.parent
DATA_DIR = GIT_DIR / "data" / "DKR"
OUTPUT   = GIT_DIR / "index.html"


# ── 로드 ─────────────────────────────────────────────────────
def available_dates() -> list[str]:
    return sorted([f.stem for f in DATA_DIR.glob("*.json")
                   if not f.stem.endswith(".analyzed")], reverse=True)

def load_raw(date_str: str) -> dict | None:
    p = DATA_DIR / f"{date_str}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

def load_analyzed(date_str: str) -> dict | None:
    p = DATA_DIR / f"{date_str}.analyzed.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ── 주요 이슈 HTML ────────────────────────────────────────────
def build_major_issues_analyzed(issues: list[dict]) -> str:
    if not issues:
        return "<p class='empty'>해당 기간 공지·업데이트 없음</p>"
    rows = ""
    for item in issues:
        board    = item.get("board_name", "")
        title    = item.get("title", "")
        url      = item.get("url", "#")
        summary  = item.get("summary", "")
        bullets  = item.get("bullets", [])
        badge_cls = "badge-notice" if "공지" in board else "badge-update"

        bullet_html = "".join(
            f"<li>{b}</li>" for b in bullets
        )
        rows += f"""
        <div class="issue-item">
          <div class="issue-head">
            <span class="issue-badge {badge_cls}">{board}</span>
            <a href="{url}" target="_blank" class="issue-title-link">{title}</a>
          </div>
          {f'<p class="issue-summary">{summary}</p>' if summary else ''}
          {f'<ul class="issue-bullets">{bullet_html}</ul>' if bullet_html else ''}
        </div>"""
    return rows


# ── 유저 동향 VOC HTML ────────────────────────────────────────
def build_voc_analyzed(voc_groups: list[dict]) -> str:
    if not voc_groups:
        return "<p class='empty'>수집된 VOC 없음</p>"

    # 카테고리 순서
    order = ["게임 관련", "버그·오류", "건의·요청", "기타"]
    groups_by_cat: dict[str, list] = {c: [] for c in order}
    for g in voc_groups:
        cat = g.get("category", "기타")
        if cat not in groups_by_cat:
            groups_by_cat[cat] = []
        groups_by_cat[cat].append(g)

    rows = ""
    for cat in order:
        items = groups_by_cat.get(cat, [])
        if not items:
            continue
        first = True
        for item in items:
            summary  = item.get("summary", "")
            count    = item.get("count", 1)
            url      = item.get("representative_url", "#")
            count_txt = f"({count}건)" if count > 1 else ""

            if first:
                rows += f"""
        <tr>
          <td class="cat-cell" rowspan="{len(items)}">{cat}</td>
          <td class="content-cell">
            - <a href="{url}" target="_blank" class="post-link">{summary}</a>
            <span class="count-badge">{count_txt}</span>
          </td>
          <td class="ref-cell"><a href="{url}" target="_blank" class="link-btn">[링크]</a></td>
        </tr>"""
                first = False
            else:
                rows += f"""
        <tr>
          <td class="content-cell">
            - <a href="{url}" target="_blank" class="post-link">{summary}</a>
            <span class="count-badge">{count_txt}</span>
          </td>
          <td class="ref-cell"><a href="{url}" target="_blank" class="link-btn">[링크]</a></td>
        </tr>"""

    return f"""
    <table class="voc-table">
      <thead>
        <tr><th style="width:90px">항목</th><th>내용</th><th style="width:60px">비고</th></tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


# ── 통계 카드 ─────────────────────────────────────────────────
def build_stats(analyzed: dict) -> str:
    voc  = analyzed.get("voc_groups", [])
    total = sum(g.get("count", 1) for g in voc)
    bugs  = sum(g.get("count", 1) for g in voc if g.get("category") == "버그·오류")
    sugg  = sum(g.get("count", 1) for g in voc if g.get("category") == "건의·요청")
    issue_cnt = len(analyzed.get("major_issues", []))

    return f"""
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-num">{issue_cnt}</div>
        <div class="stat-label">공지/업데이트</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{total}</div>
        <div class="stat-label">유저 게시물</div>
      </div>
      <div class="stat-card neg-card">
        <div class="stat-num">{bugs}</div>
        <div class="stat-label">버그·오류</div>
      </div>
      <div class="stat-card warn-card">
        <div class="stat-num">{sugg}</div>
        <div class="stat-label">건의·요청</div>
      </div>
    </div>"""


# ── 패널 전체 빌드 ────────────────────────────────────────────
def build_panel(dates: list[str]) -> str:
    if not dates:
        sample = (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")
        return f"<p class='empty'>아직 수집된 데이터 없음 (기대 파일: data/DKR/{sample}.json)</p>"

    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    # 일간
    daily_analyzed = load_analyzed(dates[0])
    if not daily_analyzed:
        daily_analyzed = {"date": dates[0], "major_issues": [], "voc_groups": [],
                          "_note": "analyzed.json 없음 — 오늘 09:00 스케줄 실행 후 생성"}

    # 주간 (최근 7일 analyzed 병합)
    weekly_analyzed = {"date": "weekly", "major_issues": [], "voc_groups": []}
    weekly_dates = dates[:7]
    for d in weekly_dates:
        ad = load_analyzed(d)
        if ad:
            weekly_analyzed["major_issues"].extend(ad.get("major_issues", []))
            weekly_analyzed["voc_groups"].extend(ad.get("voc_groups", []))
    weekly_range = f"{weekly_dates[-1]} ~ {weekly_dates[0]}" if len(weekly_dates) > 1 else weekly_dates[0]

    return f"""
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
      {build_stats(daily_analyzed)}

      <div class="section-title">📢 주요 이슈</div>
      {build_major_issues_analyzed(daily_analyzed.get("major_issues", []))}

      <div class="section-title">👥 공식 라운지 유저 동향</div>
      {build_voc_analyzed(daily_analyzed.get("voc_groups", []))}
    </div>

    <!-- 주간 -->
    <div id="sub-weekly" class="subtab-content">
      <div class="period-bar">📊 수집 기간: {weekly_range}</div>
      {build_stats(weekly_analyzed)}

      <div class="section-title">📢 주요 이슈</div>
      {build_major_issues_analyzed(weekly_analyzed.get("major_issues", []))}

      <div class="section-title">👥 공식 라운지 유저 동향</div>
      {build_voc_analyzed(weekly_analyzed.get("voc_groups", []))}
    </div>

    <div class="updated-at">마지막 업데이트: {now}</div>"""


# ── HTML 전체 ─────────────────────────────────────────────────
def generate():
    dates = available_dates()
    now   = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    panel = build_panel(dates)

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>NTRANCE VOC 대시보드</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Malgun Gothic","Apple SD Gothic Neo",sans-serif;background:#f0f2f5;color:#1a1a2e;min-height:100vh;font-size:13px}}

.header{{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:16px 28px;display:flex;align-items:center;justify-content:space-between;box-shadow:0 2px 12px rgba(0,0,0,.3)}}
.header h1{{font-size:18px;font-weight:700}}.header .sub{{font-size:11px;color:#8892b0;margin-top:3px}}.header .ts{{font-size:11px;color:#8892b0}}

.main{{max-width:1000px;margin:0 auto;padding:20px 14px}}
.tab-nav{{display:flex;gap:8px;margin-bottom:14px}}
.tab-btn{{padding:8px 16px;border:2px solid #dde1e7;border-radius:7px;background:#fff;cursor:pointer;font-size:13px;font-weight:600;color:#5f6368;transition:all .2s;display:flex;align-items:center;gap:7px}}
.tab-btn:hover{{border-color:#1a73e8;color:#1a73e8}}.tab-btn.active{{background:#1a73e8;border-color:#1a73e8;color:#fff}}
.tab-dot{{width:8px;height:8px;border-radius:50%}}
.tab-panel{{display:none}}.tab-panel.active{{display:block}}

.panel-card{{background:#fff;border-radius:12px;padding:22px;box-shadow:0 1px 6px rgba(0,0,0,.08)}}

.subtab-nav{{display:flex;gap:6px;margin-bottom:18px}}
.subtab-btn{{padding:7px 15px;border:1.5px solid #dde1e7;border-radius:6px;background:#fff;cursor:pointer;font-size:12px;font-weight:600;color:#5f6368;transition:all .2s}}
.subtab-btn.active{{background:#e8f0fe;border-color:#1a73e8;color:#1a73e8}}
.subtab-content{{display:none}}.subtab-content.active{{display:block}}
.sbadge{{background:#e8f0fe;color:#1a73e8;font-size:10px;padding:2px 5px;border-radius:3px;margin-left:3px}}
.subtab-btn.active .sbadge{{background:#fff}}

.stats-row{{display:flex;gap:10px;margin-bottom:18px;flex-wrap:wrap}}
.stat-card{{flex:1;min-width:90px;background:#f8f9fa;border-radius:9px;padding:12px;text-align:center;border:1.5px solid #e8eaed}}
.neg-card{{border-color:#fce8e6;background:#fef9f9}}.warn-card{{border-color:#fef3cd;background:#fffdf0}}
.stat-num{{font-size:22px;font-weight:800;color:#1a73e8}}.neg-card .stat-num{{color:#d93025}}.warn-card .stat-num{{color:#f57c00}}
.stat-label{{font-size:11px;color:#5f6368;margin-top:3px}}

.section-title{{font-size:13px;font-weight:700;color:#3c4043;margin:20px 0 10px;padding-left:8px;border-left:3px solid #1a73e8}}

/* 주요 이슈 */
.issue-item{{margin-bottom:14px;padding:12px 14px;background:#f8f9fa;border-radius:8px;border-left:3px solid #1a73e8}}
.issue-head{{display:flex;align-items:center;gap:8px;margin-bottom:6px}}
.issue-badge{{font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;white-space:nowrap}}
.badge-notice{{background:#e3f2fd;color:#1565c0}}.badge-update{{background:#e8f5e9;color:#2e7d32}}
.issue-title-link{{font-weight:600;color:#1a1a2e;text-decoration:none;font-size:13px}}
.issue-title-link:hover{{color:#1a73e8;text-decoration:underline}}
.issue-summary{{font-size:12px;color:#5f6368;margin:4px 0 6px;padding-left:2px}}
.issue-bullets{{list-style:none;padding:0}}
.issue-bullets li{{font-size:12px;color:#3c4043;padding:2px 0 2px 12px;position:relative}}
.issue-bullets li::before{{content:"▷";position:absolute;left:0;color:#1a73e8;font-size:10px}}

/* VOC 테이블 */
.voc-table{{width:100%;border-collapse:collapse}}
.voc-table th{{background:#f1f3f4;padding:8px 10px;text-align:left;font-size:11px;color:#5f6368;border-bottom:1.5px solid #e8eaed;font-weight:600}}
.voc-table td{{padding:8px 10px;border-bottom:1px solid #f1f3f4;vertical-align:middle}}
.voc-table tr:hover td{{background:#f8f9fa}}
.cat-cell{{font-weight:700;font-size:12px;color:#3c4043;background:#fafafa;border-right:2px solid #e8eaed;text-align:center;white-space:nowrap}}
.content-cell{{line-height:1.6;color:#3c4043}}
.post-link{{color:#1a1a2e;text-decoration:none}}.post-link:hover{{color:#1a73e8;text-decoration:underline}}
.count-badge{{font-size:11px;color:#9aa0a6;margin-left:4px}}
.ref-cell{{text-align:center}}
.link-btn{{color:#1a73e8;font-size:11px;text-decoration:none;font-weight:600}}
.link-btn:hover{{text-decoration:underline}}

.period-bar{{font-size:12px;color:#5f6368;background:#f8f9fa;padding:7px 12px;border-radius:5px;margin-bottom:14px}}
.updated-at{{font-size:11px;color:#9aa0a6;text-align:right;margin-top:18px}}
.empty{{color:#9aa0a6;font-size:13px;padding:20px;text-align:center}}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>📊 NTRANCE VOC 대시보드</h1>
    <div class="sub">네이버 라운지 유저 동향 자동 수집·분석</div>
  </div>
  <div class="ts">생성: {now}</div>
</div>
<div class="main">
  <div class="tab-nav">
    <button class="tab-btn active" onclick="switchTab('DKR',this)">
      <span class="tab-dot" style="background:#1a73e8"></span>DK모바일:리본
    </button>
  </div>
  <div class="panel-card">
    <div id="tab-DKR" class="tab-panel active">{panel}</div>
  </div>
</div>
<script>
function switchTab(k,b){{document.querySelectorAll('.tab-btn').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.tab-panel').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.getElementById('tab-'+k).classList.add('active');}}
function switchSub(s,b){{const p=b.closest('.tab-panel');p.querySelectorAll('.subtab-btn').forEach(x=>x.classList.remove('active'));p.querySelectorAll('.subtab-content').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.getElementById('sub-'+s).classList.add('active');}}
</script>
</body>
</html>"""

    OUTPUT.write_text(html, encoding="utf-8")
    print(f"[DONE] 대시보드 생성: {OUTPUT}")


if __name__ == "__main__":
    generate()
