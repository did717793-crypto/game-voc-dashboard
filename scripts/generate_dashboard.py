#!/usr/bin/env python3
"""
VOC 대시보드 HTML 생성기 v5.0
- 리포트 양식 (01 주요 이슈 / 02 커뮤니티 지표 / 03 공식 라운지 동향)
- 날짜 선택 드롭다운
- 일간/주간 토글 → 탭 우측 배치
- VOC 테이블 + 인라인 아코디언
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST      = timezone(timedelta(hours=9))
GIT_DIR  = Path(__file__).parent.parent
DATA_DIR = GIT_DIR / "data" / "DKR"
OUTPUT   = GIT_DIR / "index.html"


# ── 데이터 로드 ───────────────────────────────────────────────
def available_dates() -> list[str]:
    return sorted(
        [f.stem for f in DATA_DIR.glob("*.json") if not f.stem.endswith(".analyzed")],
        reverse=True,
    )

def load_raw(d: str) -> dict | None:
    p = DATA_DIR / f"{d}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

def load_analyzed(d: str) -> dict | None:
    p = DATA_DIR / f"{d}.analyzed.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

def build_raw_map(dates: list[str]) -> dict:
    m = {}
    for d in dates:
        raw = load_raw(d)
        if raw:
            for p in raw.get("posts", []):
                fid = str(p.get("feed_id", ""))
                if fid:
                    m[fid] = p
    return m

def merge_analyzed(dates: list[str]) -> dict:
    out = {"major_issues": [], "voc_groups": []}
    for d in dates:
        ad = load_analyzed(d)
        if ad:
            out["major_issues"].extend(ad.get("major_issues", []))
            out["voc_groups"].extend(ad.get("voc_groups", []))
    return out


# ── 01 주요 이슈 ──────────────────────────────────────────────
def build_section_issues(analyzed: dict) -> str:
    items = []
    for iss in analyzed.get("major_issues", []):
        board   = iss.get("board_name", "")
        summary = iss.get("summary", "")
        url     = iss.get("url", "#")
        tag     = "공지" if "공지" in board else "업데이트"
        cls     = "tg-notice" if tag == "공지" else "tg-update"
        items.append(
            f'<li><span class="tg {cls}">{tag}</span>'
            f' <a href="{url}" target="_blank" class="iss-link">{summary}</a></li>'
        )
    for voc in analyzed.get("voc_groups", []):
        cat   = voc.get("category", "")
        cnt   = voc.get("count", 1)
        summ  = voc.get("summary", "")
        url   = voc.get("representative_url", "#")
        if cnt >= 2 or cat == "버그·오류":
            cnt_s = f' <span class="cnt-s">({cnt}건)</span>' if cnt > 1 else ""
            cls_map = {"버그·오류": "tg-bug", "건의·요청": "tg-sug",
                       "게임 관련": "tg-game", "기타": "tg-etc"}
            cls = cls_map.get(cat, "tg-etc")
            items.append(
                f'<li><span class="tg {cls}">{cat}</span>'
                f' <a href="{url}" target="_blank" class="iss-link">{summ}</a>{cnt_s}</li>'
            )
    if not items:
        return "<p class='empty-s'>수집된 주요 이슈 없음</p>"
    return f'<ul class="iss-list">{"".join(items)}</ul>'


# ── 02 커뮤니티 지표 차트 ─────────────────────────────────────
def build_section_chart(chart_dates: list[str], chart_id: str) -> str:
    labels = [d[5:] for d in chart_dates]   # MM-DD
    gd, bd, sd, od = [], [], [], []
    for d in chart_dates:
        ad = load_analyzed(d)
        if ad:
            voc = ad.get("voc_groups", [])
            gd.append(sum(x.get("count",1) for x in voc if x.get("category")=="게임 관련"))
            bd.append(sum(x.get("count",1) for x in voc if x.get("category")=="버그·오류"))
            sd.append(sum(x.get("count",1) for x in voc if x.get("category")=="건의·요청"))
            od.append(sum(x.get("count",1) for x in voc if x.get("category")=="기타"))
        else:
            gd.append(0); bd.append(0); sd.append(0); od.append(0)

    return f"""
    <p class="chart-label">커뮤니티 현황 (유저 게시물 추이 — 최근 7일)</p>
    <div style="max-height:200px"><canvas id="ch-{chart_id}" height="160"></canvas></div>
    <script>
    (function(){{
      const c=document.getElementById('ch-{chart_id}');
      if(!c||c._ok)return;c._ok=true;
      new Chart(c,{{
        type:'bar',
        data:{{
          labels:{json.dumps(labels, ensure_ascii=False)},
          datasets:[
            {{label:'게임 관련',data:{json.dumps(gd)},backgroundColor:'rgba(66,133,244,.8)',stack:'s'}},
            {{label:'버그·오류', data:{json.dumps(bd)},backgroundColor:'rgba(234,67,53,.8)', stack:'s'}},
            {{label:'건의·요청',data:{json.dumps(sd)},backgroundColor:'rgba(251,188,4,.85)',stack:'s'}},
            {{label:'기타',     data:{json.dumps(od)},backgroundColor:'rgba(154,160,166,.7)',stack:'s'}},
          ]
        }},
        options:{{
          responsive:true,maintainAspectRatio:false,
          plugins:{{
            legend:{{position:'top',labels:{{font:{{size:11}},boxWidth:12,padding:8}}}},
            tooltip:{{mode:'index',intersect:false}}
          }},
          scales:{{
            x:{{stacked:true,ticks:{{font:{{size:11}}}},grid:{{display:false}}}},
            y:{{stacked:true,beginAtZero:true,ticks:{{stepSize:1,font:{{size:11}}}},grid:{{color:'#eee'}}}}
          }}
        }}
      }});
    }})();
    </script>"""


# ── 03 공식 라운지 동향 ───────────────────────────────────────
CAT_ORDER  = ["게임 관련", "버그·오류", "건의·요청", "기타"]
CAT_COLORS = {"게임 관련":"#4285f4","버그·오류":"#ea4335","건의·요청":"#e37400","기타":"#9aa0a6"}

def build_section_voc(voc_groups: list[dict], raw_map: dict, pfx: str = "v") -> str:
    if not voc_groups:
        return "<p class='empty-s'>수집된 VOC 없음</p>"

    by_cat: dict[str, list] = {c: [] for c in CAT_ORDER}
    for g in voc_groups:
        cat = g.get("category", "기타")
        by_cat.setdefault(cat, []).append(g)

    rows = ""
    idx  = 0
    for cat in CAT_ORDER:
        items = by_cat.get(cat, [])
        if not items:
            continue
        total_cnt = sum(x.get("count", 1) for x in items)
        color     = CAT_COLORS.get(cat, "#9aa0a6")

        content = ""
        for item in items:
            summ     = item.get("summary", "")
            cnt      = item.get("count", 1)
            url      = item.get("representative_url", "#")
            feed_ids = [str(f) for f in item.get("feed_ids", [])]
            cnt_txt  = f'<span class="cnt-s">({cnt}건)</span>' if cnt > 1 else ""

            # 아코디언 상세
            det_parts = []
            for fid in feed_ids:
                post = raw_map.get(fid)
                if not post:
                    continue
                ptitle = post.get("title", "")
                pbody  = (post.get("body") or "").strip()
                if len(pbody) > 250:
                    pbody = pbody[:250] + "…"
                purl   = post.get("url", "#")
                bhtml  = f'<div class="det-body">{pbody}</div>' if pbody else ""
                det_parts.append(
                    f'<div class="det-item">'
                    f'<a href="{purl}" target="_blank" class="det-title">{ptitle}</a>{bhtml}'
                    f'</div>'
                )

            vid      = f"{pfx}{idx}"
            has_exp  = bool(det_parts)
            arr      = f'<span id="ar-{vid}" class="arr">▸</span>' if has_exp else '<span class="arr-ph"></span>'
            oc_attr  = f' onclick="toggleVoc(\'{vid}\')" style="cursor:pointer"' if has_exp else ''
            exp_div  = (
                f'<div id="{vid}" class="det-group" style="display:none">{"".join(det_parts)}</div>'
            ) if has_exp else ""

            content += f"""
              <div class="voc-row-item"{oc_attr}>
                <div class="voc-item-main">
                  {arr}<a href="{url}" target="_blank" class="vitem-link"
                     onclick="event.stopPropagation()">- {summ}</a>{cnt_txt}
                </div>
                <a href="{url}" target="_blank" class="link-btn"
                   onclick="event.stopPropagation()">[링크]</a>
              </div>
              {exp_div}"""
            idx += 1

        rows += f"""
        <tr>
          <td class="cat-td" style="border-left:3px solid {color}">{cat}</td>
          <td class="content-td">{content}</td>
          <td class="ref-td">{total_cnt}건</td>
        </tr>"""

    return f"""
    <table class="voc-tbl">
      <thead>
        <tr>
          <th style="width:76px">항목</th>
          <th>내용</th>
          <th style="width:52px">비고</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


# ── 리포트 패널 빌드 ──────────────────────────────────────────
def sec(num: str, title: str, body: str) -> str:
    return f"""
    <div class="rpt-section">
      <div class="rpt-sec-hd"><span class="sec-num">{num}</span>{title}</div>
      <div class="rpt-sec-body">{body}</div>
    </div>"""


def build_report(date_str: str, period: str, all_dates: list[str]) -> str:
    if period == "daily":
        analyzed = load_analyzed(date_str) or {"major_issues": [], "voc_groups": []}
        raw_map  = build_raw_map([date_str])

        end = datetime.strptime(date_str, "%Y-%m-%d")
        chart_dates = [(end - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]

        label  = f"{date_str} 일일 서비스 현황"
        chart_id = f"D{date_str.replace('-','')}"

        return (
            f'<div class="rpt-header"><span class="rpt-game">DK모바일:리본</span>'
            f'<span class="rpt-title">{label}</span>'
            f'<span class="rpt-ts">조회: {datetime.now(KST).strftime("%Y-%m-%d %H:%M")}</span></div>'
            + sec("01", "주요 이슈",         build_section_issues(analyzed))
            + sec("02", "커뮤니티 지표",     build_section_chart(chart_dates, chart_id))
            + sec("03", "공식 라운지 동향",  build_section_voc(analyzed.get("voc_groups",[]), raw_map, pfx=f"D{date_str.replace('-','')}_"))
        )
    else:  # weekly
        idx = all_dates.index(date_str) if date_str in all_dates else 0
        week_dates = all_dates[idx: idx + 7]
        analyzed = merge_analyzed(week_dates)
        raw_map  = build_raw_map(week_dates)
        wrange   = f"{week_dates[-1]} ~ {week_dates[0]}" if len(week_dates) > 1 else week_dates[0]
        chart_id = f"W{date_str.replace('-','')}"
        sorted_wd = sorted(week_dates)

        return (
            f'<div class="rpt-header"><span class="rpt-game">DK모바일:리본</span>'
            f'<span class="rpt-title">주간 서비스 현황</span>'
            f'<span class="rpt-ts">집계기간: {wrange}</span></div>'
            + sec("01", "주간 주요 이슈",    build_section_issues(analyzed))
            + sec("02", "커뮤니티 지표",     build_section_chart(sorted_wd, chart_id))
            + sec("03", "공식 라운지 동향",  build_section_voc(analyzed.get("voc_groups",[]), raw_map, pfx=f"W{date_str.replace('-','')}_"))
        )


# ── HTML 전체 생성 ────────────────────────────────────────────
def generate():
    dates = available_dates()
    now   = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    latest = dates[0] if dates else ""

    # 날짜 옵션
    date_opts = ""
    for i, d in enumerate(dates):
        sel = " selected" if i == 0 else ""
        date_opts += f'<option value="{d}"{sel}>{d}</option>\n'

    # 모든 패널 사전 렌더링 (날짜 × 기간)
    panels_html = ""
    for date_str in dates:
        is_first = (date_str == latest)
        daily_html  = build_report(date_str, "daily",  dates)
        weekly_html = build_report(date_str, "weekly", dates)
        panels_html += f"""
        <div id="panel-{date_str}" class="date-panel" style="display:{'block' if is_first else 'none'}">
          <div id="D-{date_str}" class="period-panel" style="display:block">{daily_html}</div>
          <div id="W-{date_str}" class="period-panel" style="display:none">{weekly_html}</div>
        </div>"""

    if not panels_html:
        panels_html = "<p class='empty-s'>데이터 없음 — 내일 09:00 스케줄 실행 후 생성됩니다</p>"

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>NTRANCE VOC 대시보드</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Malgun Gothic","Apple SD Gothic Neo",sans-serif;
      background:#eef0f3;color:#1a1a2e;font-size:13px;min-height:100vh}}

/* ── 상단 네비 ── */
.top-nav{{background:#1a1a2e;padding:0 20px;display:flex;align-items:center;
          justify-content:space-between;height:48px;box-shadow:0 2px 8px rgba(0,0,0,.3)}}
.nav-left{{display:flex;align-items:center;gap:10px}}
.brand{{color:#fff;font-size:15px;font-weight:700;letter-spacing:-.3px}}
.brand-sub{{color:#8892b0;font-size:11px}}
.nav-right{{display:flex;align-items:center;gap:8px}}

/* 게임 탭 */
.tab-bar{{background:#fff;border-bottom:2px solid #e8eaed;padding:0 20px;
          display:flex;align-items:center;justify-content:space-between;height:44px}}
.game-tabs{{display:flex;gap:4px}}
.tab-btn{{padding:8px 16px;border:none;border-bottom:3px solid transparent;background:none;
          cursor:pointer;font-size:13px;font-weight:600;color:#5f6368;
          display:flex;align-items:center;gap:6px;transition:all .2s}}
.tab-btn.active{{color:#1a73e8;border-bottom-color:#1a73e8}}
.tab-dot{{width:8px;height:8px;border-radius:50%;background:#1a73e8}}

/* 날짜 선택 + 기간 토글 (우측) */
.right-controls{{display:flex;align-items:center;gap:8px}}
.date-select{{padding:5px 10px;border:1.5px solid #dde1e7;border-radius:6px;
              font-size:12px;color:#3c4043;background:#fff;cursor:pointer;outline:none}}
.date-select:focus{{border-color:#1a73e8}}
.period-toggle{{display:flex;border:1.5px solid #dde1e7;border-radius:6px;overflow:hidden}}
.ptgl{{padding:5px 12px;border:none;background:#fff;font-size:12px;font-weight:600;
       color:#5f6368;cursor:pointer;transition:all .15s}}
.ptgl.active{{background:#1a73e8;color:#fff}}
.ptgl:not(:last-child){{border-right:1px solid #dde1e7}}

/* ── 본문 ── */
.main{{max-width:980px;margin:20px auto;padding:0 14px 40px}}

/* 리포트 카드 */
.rpt-card{{background:#fff;border-radius:10px;overflow:hidden;
           box-shadow:0 1px 6px rgba(0,0,0,.09)}}

/* 리포트 헤더 */
.rpt-header{{display:flex;align-items:center;gap:12px;padding:14px 20px;
             background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;flex-wrap:wrap}}
.rpt-game{{font-size:13px;font-weight:700;background:rgba(255,255,255,.15);
           padding:3px 10px;border-radius:4px}}
.rpt-title{{flex:1;font-size:15px;font-weight:700;letter-spacing:-.2px}}
.rpt-ts{{font-size:11px;color:#8892b0;white-space:nowrap}}

/* 섹션 */
.rpt-section{{border-top:1px solid #f0f2f5}}
.rpt-section:first-of-type{{border-top:none}}
.rpt-sec-hd{{display:flex;align-items:center;gap:10px;padding:12px 20px 10px;
             background:#f8f9fa;border-bottom:1px solid #e8eaed}}
.sec-num{{background:#1a73e8;color:#fff;font-size:11px;font-weight:800;
          padding:2px 7px;border-radius:3px;letter-spacing:.5px}}
.rpt-sec-hd{{font-size:13px;font-weight:700;color:#3c4043}}
.rpt-sec-body{{padding:16px 20px}}

/* 주요 이슈 리스트 */
.iss-list{{list-style:none;display:flex;flex-direction:column;gap:7px}}
.iss-list li{{display:flex;align-items:flex-start;gap:8px;font-size:12.5px;line-height:1.5}}
.tg{{font-size:10px;font-weight:700;padding:2px 6px;border-radius:3px;white-space:nowrap;flex-shrink:0;margin-top:1px}}
.tg-notice{{background:#e3f2fd;color:#1565c0}}
.tg-update{{background:#e8f5e9;color:#2e7d32}}
.tg-bug{{background:#fce8e6;color:#c62828}}
.tg-sug{{background:#fff3cd;color:#b45309}}
.tg-game{{background:#e8f0fe;color:#1a73e8}}
.tg-etc{{background:#f1f3f4;color:#5f6368}}
.iss-link{{color:#1a1a2e;text-decoration:none;font-weight:500}}
.iss-link:hover{{color:#1a73e8;text-decoration:underline}}
.cnt-s{{font-size:11px;color:#9aa0a6;margin-left:2px}}

/* 차트 */
.chart-label{{font-size:12px;color:#5f6368;font-weight:600;margin-bottom:10px}}

/* VOC 테이블 */
.voc-tbl{{width:100%;border-collapse:collapse}}
.voc-tbl th{{background:#f1f3f4;padding:8px 10px;text-align:left;font-size:11px;
             color:#5f6368;border-bottom:1.5px solid #e8eaed;font-weight:600}}
.voc-tbl td{{padding:0;border-bottom:1px solid #f1f3f4;vertical-align:top}}
.cat-td{{padding:12px 10px;font-weight:700;font-size:12px;color:#3c4043;
         vertical-align:middle;white-space:nowrap;width:76px}}
.content-td{{padding:6px 0}}
.ref-td{{padding:12px 8px;text-align:center;font-size:11px;color:#9aa0a6;
         vertical-align:middle;white-space:nowrap;width:52px}}

/* VOC 아이템 */
.voc-row-item{{display:flex;align-items:flex-start;justify-content:space-between;
               padding:6px 10px;gap:8px;transition:background .15s;border-radius:4px}}
.voc-row-item:hover{{background:#f8f9fa}}
.voc-item-main{{display:flex;align-items:flex-start;gap:4px;flex:1;min-width:0;flex-wrap:wrap}}
.arr{{font-size:11px;color:#1a73e8;flex-shrink:0;width:13px;margin-top:1px;transition:transform .15s}}
.arr-ph{{width:13px;flex-shrink:0}}
.vitem-link{{font-size:12.5px;color:#3c4043;text-decoration:none;line-height:1.5;flex:1}}
.vitem-link:hover{{color:#1a73e8}}
.link-btn{{font-size:11px;color:#1a73e8;text-decoration:none;font-weight:600;
           white-space:nowrap;flex-shrink:0;padding:2px 0}}
.link-btn:hover{{text-decoration:underline}}

/* 아코디언 상세 */
.det-group{{background:#f0f4ff;border-radius:6px;margin:4px 8px 8px;padding:10px 12px}}
.det-item{{padding:6px 0;border-bottom:1px solid #dde6ff}}
.det-item:last-child{{border-bottom:none;padding-bottom:0}}
.det-title{{font-size:12px;font-weight:600;color:#1a1a2e;text-decoration:none;display:block;margin-bottom:3px}}
.det-title:hover{{color:#1a73e8;text-decoration:underline}}
.det-body{{font-size:11px;color:#5f6368;line-height:1.6;padding-left:4px;margin-top:2px}}

.period-bar{{font-size:12px;color:#5f6368;background:#f8f9fa;padding:6px 12px;
             border-radius:4px;margin-bottom:8px}}
.empty-s{{color:#9aa0a6;font-size:12px;padding:16px;text-align:center}}
.updated{{font-size:11px;color:#9aa0a6;text-align:right;padding:12px 20px;
          border-top:1px solid #f0f2f5}}
</style>
</head>
<body>

<!-- 상단 브랜드 바 -->
<div class="top-nav">
  <div class="nav-left">
    <span class="brand">NTRANCE</span>
    <span class="brand-sub">VOC 대시보드</span>
  </div>
  <div class="nav-right">
    <span style="font-size:11px;color:#8892b0">생성: {now}</span>
  </div>
</div>

<!-- 게임 탭 + 날짜 + 기간 -->
<div class="tab-bar">
  <div class="game-tabs">
    <button class="tab-btn active">
      <span class="tab-dot"></span>DK모바일:리본
    </button>
  </div>
  <div class="right-controls">
    <select class="date-select" id="date-sel" onchange="switchDate(this.value)">
      {date_opts}
    </select>
    <div class="period-toggle">
      <button class="ptgl active" id="btn-daily" onclick="switchPeriod('D',this)">일간</button>
      <button class="ptgl"        id="btn-weekly" onclick="switchPeriod('W',this)">주간</button>
    </div>
  </div>
</div>

<div class="main">
  <div class="rpt-card">
    {panels_html}
    <div class="updated">마지막 업데이트: {now}</div>
  </div>
</div>

<script>
var _date = '{latest}';
var _period = 'D';

function switchDate(d) {{
  document.getElementById('panel-'+_date).style.display='none';
  _date = d;
  document.getElementById('panel-'+_date).style.display='block';
  document.getElementById(_period+'-'+_date).style.display='block';
  var other = _period==='D' ? 'W' : 'D';
  document.getElementById(other+'-'+_date).style.display='none';
}}

function switchPeriod(p, btn) {{
  document.querySelectorAll('.ptgl').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById(_period+'-'+_date).style.display='none';
  _period = p;
  document.getElementById(_period+'-'+_date).style.display='block';
}}

function toggleVoc(id) {{
  var d=document.getElementById(id);
  var a=document.getElementById('ar-'+id);
  if(!d)return;
  var open=d.style.display!=='none';
  d.style.display=open?'none':'block';
  if(a)a.textContent=open?'▸':'▾';
}}
</script>
</body>
</html>"""

    OUTPUT.write_text(html, encoding="utf-8")
    print(f"[DONE] 대시보드 v5.0 생성: {OUTPUT}")


if __name__ == "__main__":
    generate()
