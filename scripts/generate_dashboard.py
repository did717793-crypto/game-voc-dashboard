#!/usr/bin/env python3
"""
VOC 대시보드 HTML 생성기 v4.0
- analyzed.json 기반 Claude 분석 결과 렌더링
- 7일 트렌드 스택 바 차트 (Chart.js)
- VOC 인라인 펼치기 (아코디언)
- ▷ 중복 제거 (CSS ::before 제거)
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST      = timezone(timedelta(hours=9))
GIT_DIR  = Path(__file__).parent.parent
DATA_DIR = GIT_DIR / "data" / "DKR"
OUTPUT   = GIT_DIR / "index.html"


# ── 로드 ─────────────────────────────────────────────────────
def available_dates() -> list[str]:
    return sorted(
        [f.stem for f in DATA_DIR.glob("*.json") if not f.stem.endswith(".analyzed")],
        reverse=True,
    )


def load_raw(date_str: str) -> dict | None:
    p = DATA_DIR / f"{date_str}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def load_analyzed(date_str: str) -> dict | None:
    p = DATA_DIR / f"{date_str}.analyzed.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def build_raw_map(dates: list[str]) -> dict:
    """feed_id → post dict 매핑 (여러 날짜 합산)"""
    result = {}
    for d in dates:
        raw = load_raw(d)
        if raw:
            for p in raw.get("posts", []):
                fid = str(p.get("feed_id", ""))
                if fid:
                    result[fid] = p
    return result


# ── 7일 트렌드 차트 ───────────────────────────────────────────
def build_trend_chart(ref_date_str: str, chart_id: str) -> str:
    end = datetime.strptime(ref_date_str, "%Y-%m-%d")
    chart_dates = [
        (end - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)
    ]
    labels = [d[5:] for d in chart_dates]  # MM-DD

    game_d, bug_d, sug_d, other_d = [], [], [], []
    for d in chart_dates:
        ad = load_analyzed(d)
        if ad:
            voc = ad.get("voc_groups", [])
            game_d.append(sum(g.get("count", 1) for g in voc if g.get("category") == "게임 관련"))
            bug_d.append(sum(g.get("count", 1) for g in voc if g.get("category") == "버그·오류"))
            sug_d.append(sum(g.get("count", 1) for g in voc if g.get("category") == "건의·요청"))
            other_d.append(sum(g.get("count", 1) for g in voc if g.get("category") == "기타"))
        else:
            game_d.append(0); bug_d.append(0); sug_d.append(0); other_d.append(0)

    # 오늘 요약 미니 통계
    cur = load_analyzed(ref_date_str) or {}
    voc = cur.get("voc_groups", [])
    total   = sum(g.get("count", 1) for g in voc)
    bugs    = sum(g.get("count", 1) for g in voc if g.get("category") == "버그·오류")
    sugg    = sum(g.get("count", 1) for g in voc if g.get("category") == "건의·요청")
    iss_cnt = len(cur.get("major_issues", []))

    return f"""
    <div class="trend-area">
      <div class="mini-stats">
        <div class="mstat"><div class="mstat-n">{iss_cnt}</div><div class="mstat-l">공지/업데이트</div></div>
        <div class="mstat"><div class="mstat-n">{total}</div><div class="mstat-l">유저 게시물</div></div>
        <div class="mstat neg"><div class="mstat-n">{bugs}</div><div class="mstat-l">버그·오류</div></div>
        <div class="mstat warn"><div class="mstat-n">{sugg}</div><div class="mstat-l">건의·요청</div></div>
      </div>
      <div class="chart-wrap">
        <canvas id="chart-{chart_id}" height="110"></canvas>
      </div>
    </div>
    <script>
    (function(){{
      const ctx = document.getElementById('chart-{chart_id}');
      if (!ctx || ctx._done) return; ctx._done = true;
      new Chart(ctx, {{
        type: 'bar',
        data: {{
          labels: {json.dumps(labels, ensure_ascii=False)},
          datasets: [
            {{label:'게임 관련', data:{json.dumps(game_d)}, backgroundColor:'rgba(66,133,244,0.8)', stack:'s'}},
            {{label:'버그·오류',  data:{json.dumps(bug_d)},  backgroundColor:'rgba(234,67,53,0.8)',  stack:'s'}},
            {{label:'건의·요청', data:{json.dumps(sug_d)},  backgroundColor:'rgba(251,188,4,0.85)', stack:'s'}},
            {{label:'기타',      data:{json.dumps(other_d)},backgroundColor:'rgba(154,160,166,0.7)',stack:'s'}},
          ]
        }},
        options: {{
          responsive: true, maintainAspectRatio: true,
          plugins: {{
            legend: {{position:'top', labels:{{font:{{size:11}}, boxWidth:12, padding:10}}}},
            tooltip: {{mode:'index', intersect:false}}
          }},
          scales: {{
            x: {{stacked:true, ticks:{{font:{{size:11}}}}, grid:{{display:false}}}},
            y: {{stacked:true, beginAtZero:true, ticks:{{stepSize:1, font:{{size:11}}}}, grid:{{color:'#f0f0f0'}}}}
          }}
        }}
      }});
    }})();
    </script>"""


# ── 주요 이슈 HTML ────────────────────────────────────────────
def build_major_issues(issues: list[dict]) -> str:
    if not issues:
        return "<p class='empty'>해당 기간 공지·업데이트 없음</p>"
    rows = ""
    for item in issues:
        board   = item.get("board_name", "")
        title   = item.get("title", "")
        url     = item.get("url", "#")
        summary = item.get("summary", "")
        bullets = item.get("bullets", [])
        badge_cls = "badge-notice" if "공지" in board else "badge-update"

        bullet_html = "".join(f"<li>{b}</li>" for b in bullets)
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


# ── VOC 카드 (아코디언) ───────────────────────────────────────
CAT_COLORS = {
    "게임 관련": "#4285f4",
    "버그·오류":  "#ea4335",
    "건의·요청": "#fbbc04",
    "기타":      "#9aa0a6",
}
CAT_ORDER = ["게임 관련", "버그·오류", "건의·요청", "기타"]


def build_voc(voc_groups: list[dict], raw_map: dict, id_prefix: str = "v") -> str:
    if not voc_groups:
        return "<p class='empty'>수집된 VOC 없음</p>"

    by_cat: dict[str, list] = {c: [] for c in CAT_ORDER}
    for g in voc_groups:
        cat = g.get("category", "기타")
        by_cat.setdefault(cat, []).append(g)

    html = '<div class="voc-wrap">'
    idx  = 0

    for cat in CAT_ORDER:
        items = by_cat.get(cat, [])
        if not items:
            continue
        color = CAT_COLORS.get(cat, "#9aa0a6")
        html += f'<div class="voc-group" style="border-left-color:{color}">'
        html += f'<div class="voc-cat" style="color:{color}">{cat}</div>'

        for item in items:
            summary  = item.get("summary", "")
            count    = item.get("count", 1)
            url      = item.get("representative_url", "#")
            feed_ids = [str(fid) for fid in item.get("feed_ids", [])]
            cnt_txt  = f'<span class="cnt">({count}건)</span>' if count > 1 else ""

            # 아코디언 상세 내용 빌드
            detail_parts = []
            for fid in feed_ids:
                post = raw_map.get(fid)
                if not post:
                    continue
                ptitle = post.get("title", "")
                pbody  = (post.get("body") or "").strip()
                if len(pbody) > 250:
                    pbody = pbody[:250] + "…"
                purl   = post.get("url", "#")
                body_html = f'<div class="det-body">{pbody}</div>' if pbody else ""
                detail_parts.append(
                    f'<div class="det-item">'
                    f'<a href="{purl}" target="_blank" class="det-title">{ptitle}</a>'
                    f'{body_html}'
                    f'</div>'
                )

            vid = f"{id_prefix}{idx}"
            has_expand = bool(detail_parts)
            arrow_html = f'<span id="ar-{vid}" class="voc-arr">▸</span>' if has_expand else \
                         '<span class="voc-arr-ph"></span>'
            onclick_attr = f' onclick="toggleVoc(\'{vid}\')"' if has_expand else ""
            expand_div   = (
                f'<div id="{vid}" class="voc-detail" style="display:none">'
                + "".join(detail_parts)
                + "</div>"
            ) if has_expand else ""

            html += f"""<div class="voc-item"{onclick_attr}>
              <div class="voc-main">
                {arrow_html}<span class="voc-sum">- {summary}</span>{cnt_txt}
              </div>
              <a href="{url}" target="_blank" class="voc-link" onclick="event.stopPropagation()">[링크]</a>
            </div>
            {expand_div}"""
            idx += 1

        html += "</div>"

    html += "</div>"
    return html


# ── 패널 전체 빌드 ────────────────────────────────────────────
def build_panel(dates: list[str]) -> str:
    if not dates:
        sample = (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")
        return f"<p class='empty'>아직 수집된 데이터 없음 (기대 파일: data/DKR/{sample}.json)</p>"

    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    latest = dates[0]

    # 일간
    daily_ad  = load_analyzed(latest) or {"date": latest, "major_issues": [], "voc_groups": [],
                                           "_note": "analyzed.json 없음 — 09:00 스케줄 후 생성"}
    daily_map = build_raw_map([latest])

    # 주간 (최근 7일 병합)
    weekly_dates = dates[:7]
    weekly_ad   = {"date": "weekly", "major_issues": [], "voc_groups": []}
    for d in weekly_dates:
        ad = load_analyzed(d)
        if ad:
            weekly_ad["major_issues"].extend(ad.get("major_issues", []))
            weekly_ad["voc_groups"].extend(ad.get("voc_groups", []))
    weekly_map   = build_raw_map(weekly_dates)
    weekly_range = f"{weekly_dates[-1]} ~ {weekly_dates[0]}" if len(weekly_dates) > 1 else weekly_dates[0]

    chart_html = build_trend_chart(latest, latest.replace("-", ""))

    return f"""
    {chart_html}

    <div class="subtab-nav" style="margin-top:18px">
      <button class="subtab-btn active" onclick="switchSub('daily',this)">
        📅 일간 <span class="sbadge">{latest}</span>
      </button>
      <button class="subtab-btn" onclick="switchSub('weekly',this)">
        📆 주간 <span class="sbadge">{len(weekly_dates)}일</span>
      </button>
    </div>

    <!-- 일간 -->
    <div id="sub-daily" class="subtab-content active">
      <div class="section-title">📢 주요 이슈</div>
      {build_major_issues(daily_ad.get("major_issues", []))}

      <div class="section-title">👥 공식 라운지 유저 동향</div>
      {build_voc(daily_ad.get("voc_groups", []), daily_map, id_prefix="d")}
    </div>

    <!-- 주간 -->
    <div id="sub-weekly" class="subtab-content">
      <div class="period-bar">📊 수집 기간: {weekly_range}</div>

      <div class="section-title">📢 주요 이슈</div>
      {build_major_issues(weekly_ad.get("major_issues", []))}

      <div class="section-title">👥 공식 라운지 유저 동향</div>
      {build_voc(weekly_ad.get("voc_groups", []), weekly_map, id_prefix="w")}
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
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
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

/* 트렌드 차트 */
.trend-area{{display:flex;gap:14px;align-items:flex-start;margin-bottom:4px}}
.mini-stats{{display:flex;flex-direction:column;gap:8px;min-width:100px}}
.mstat{{background:#f8f9fa;border-radius:8px;padding:10px 12px;text-align:center;border:1.5px solid #e8eaed;min-width:90px}}
.mstat.neg{{border-color:#fce8e6;background:#fef9f9}}.mstat.warn{{border-color:#fef3cd;background:#fffdf0}}
.mstat-n{{font-size:20px;font-weight:800;color:#1a73e8}}.mstat.neg .mstat-n{{color:#d93025}}.mstat.warn .mstat-n{{color:#f57c00}}
.mstat-l{{font-size:10px;color:#5f6368;margin-top:2px}}
.chart-wrap{{flex:1;min-width:0}}

.subtab-nav{{display:flex;gap:6px}}
.subtab-btn{{padding:7px 15px;border:1.5px solid #dde1e7;border-radius:6px;background:#fff;cursor:pointer;font-size:12px;font-weight:600;color:#5f6368;transition:all .2s}}
.subtab-btn.active{{background:#e8f0fe;border-color:#1a73e8;color:#1a73e8}}
.subtab-content{{display:none}}.subtab-content.active{{display:block}}
.sbadge{{background:#e8f0fe;color:#1a73e8;font-size:10px;padding:2px 5px;border-radius:3px;margin-left:3px}}
.subtab-btn.active .sbadge{{background:#fff}}

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
.issue-bullets li{{font-size:12px;color:#3c4043;padding:3px 0 3px 4px;line-height:1.5}}

/* VOC 카드 */
.voc-wrap{{display:flex;flex-direction:column;gap:10px}}
.voc-group{{border-left:3px solid #e8eaed;padding:0 0 4px 12px}}
.voc-cat{{font-size:11px;font-weight:700;margin-bottom:6px;letter-spacing:.3px}}
.voc-item{{display:flex;align-items:flex-start;justify-content:space-between;padding:7px 10px;background:#fafafa;border-radius:6px;margin-bottom:4px;transition:background .15s;user-select:none}}
.voc-item[onclick]{{cursor:pointer}}.voc-item[onclick]:hover{{background:#f0f4ff}}
.voc-main{{display:flex;align-items:center;gap:5px;flex:1;min-width:0;flex-wrap:wrap}}
.voc-arr{{font-size:11px;color:#1a73e8;flex-shrink:0;transition:transform .15s;width:14px}}
.voc-arr-ph{{width:14px;flex-shrink:0}}
.voc-sum{{font-size:12px;color:#3c4043;line-height:1.5}}
.cnt{{font-size:11px;color:#9aa0a6;margin-left:3px}}
.voc-link{{font-size:11px;color:#1a73e8;text-decoration:none;font-weight:600;white-space:nowrap;margin-left:8px;flex-shrink:0}}
.voc-link:hover{{text-decoration:underline}}
.voc-detail{{background:#f0f4ff;border-radius:6px;padding:10px 12px;margin-bottom:4px}}
.det-item{{padding:6px 0;border-bottom:1px solid #e8eaed}}
.det-item:last-child{{border-bottom:none;padding-bottom:0}}
.det-title{{font-size:12px;font-weight:600;color:#1a1a2e;text-decoration:none;display:block;margin-bottom:3px}}
.det-title:hover{{color:#1a73e8;text-decoration:underline}}
.det-body{{font-size:11px;color:#5f6368;line-height:1.6;padding-left:4px}}

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
function switchTab(k,b){{
  document.querySelectorAll('.tab-btn').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');
  document.getElementById('tab-'+k).classList.add('active');
}}
function switchSub(s,b){{
  const p=b.closest('.tab-panel');
  p.querySelectorAll('.subtab-btn').forEach(x=>x.classList.remove('active'));
  p.querySelectorAll('.subtab-content').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');
  document.getElementById('sub-'+s).classList.add('active');
}}
function toggleVoc(id){{
  const d=document.getElementById(id);
  const a=document.getElementById('ar-'+id);
  if(!d)return;
  const open=d.style.display!=='none';
  d.style.display=open?'none':'block';
  if(a)a.textContent=open?'▸':'▾';
}}
</script>
</body>
</html>"""

    OUTPUT.write_text(html, encoding="utf-8")
    print(f"[DONE] 대시보드 생성: {OUTPUT}")


if __name__ == "__main__":
    generate()
