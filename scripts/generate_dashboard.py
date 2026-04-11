#!/usr/bin/env python3
"""
VOC 대시보드 HTML 생성기 v5.2
변경(v5.1→v5.2):
  [FIX-1] available_dates(): analyzed.json만 있는 날짜도 드롭다운·패널 생성
  [FIX-2] JS onDateChange(): _date 갱신 순서 버그 수정 → 날짜 전환 시 선택 날짜만 노출
  [FIX-3] build_section_chart(): 커뮤니티 현황 범례 top→bottom
  [FIX-4] build_section_cs(): 처리율 꺾은선 % 레이블 표시
  [FIX-5] build_section_cs(): 우측 보조 Y축 숫자 제거 (display:false)
  [FIX-6] build_section_cs(): 하단 "7일 누적" 텍스트 → CS표(전일/금일/증감) + 유형별 도넛 차트
  [FIX-7] build_section_voc(): 항목 단위 집계 → 각 내용별 개별 행 + 개별 링크
  [FIX-8] build_section_cs_detail(): 04번과 동일하게 개별 티켓 행 분리
  [FIX-9] build_report(): 전일 cs_inquiries 로드 → 도넛 전일/증감 비교 지원
"""

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST         = timezone(timedelta(hours=9))
GIT_DIR     = Path(__file__).parent.parent
DATA_DIR    = GIT_DIR / "data" / "DKR"
METRICS_DIR = GIT_DIR / "data" / "metrics"
OUTPUT      = GIT_DIR / "index.html"


# ── 데이터 로드 ───────────────────────────────────────────────
def available_dates() -> list[str]:
    # [FIX-1] raw JSON 날짜 + analyzed.json만 있는 날짜 모두 포함
    raw_dates = set(
        f.stem for f in DATA_DIR.glob("*.json")
        if not f.stem.endswith(".analyzed")
    )
    analyzed_dates = set(
        f.stem.replace(".analyzed", "")
        for f in DATA_DIR.glob("*.analyzed.json")
    )
    return sorted(raw_dates | analyzed_dates, reverse=True)

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
    out = {"major_issues": [], "voc_groups": [], "cs_inquiries": []}
    for d in dates:
        ad = load_analyzed(d)
        if ad:
            out["major_issues"].extend(ad.get("major_issues", []))
            out["voc_groups"].extend(ad.get("voc_groups", []))
            out["cs_inquiries"].extend(ad.get("cs_inquiries", []))
    return out


# ── 지표 데이터 로드 ──────────────────────────────────────────────
def load_metrics(d: str) -> dict | None:
    p = METRICS_DIR / f"{d}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

def available_metric_dates() -> list[str]:
    if not METRICS_DIR.exists():
        return []
    return sorted(
        [f.stem for f in METRICS_DIR.glob("*.json") if not f.stem.startswith(".")],
        reverse=True,
    )

def all_dates_union() -> list[str]:
    """VOC raw 날짜 + 지표 날짜 합집합 (내림차순)"""
    s = set(available_dates()) | set(available_metric_dates())
    return sorted(s, reverse=True)

def build_metrics_js_data() -> str:
    """모든 metrics JSON → JavaScript 객체 문자열"""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from collect_metrics import aggregate_pkg_totals
        pkg_totals = aggregate_pkg_totals()
    except Exception:
        pkg_totals = {"old": [], "hyper": [], "global": []}

    all_m: dict = {}
    if METRICS_DIR.exists():
        for f in sorted(METRICS_DIR.glob("*.json")):
            if f.stem.startswith("."):
                continue
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                all_m[f.stem] = d
            except Exception:
                pass

    return (
        f"const METRICS_DATA={json.dumps(all_m, ensure_ascii=False)};\n"
        f"const PKG_TOTALS={json.dumps(pkg_totals, ensure_ascii=False)};\n"
    )


# ── 00 VOC 인사이트 ───────────────────────────────────────────
def build_section_insights(insights: dict) -> str:
    if not insights:
        return "<p class='empty-s'>인사이트 데이터 없음</p>"

    top_issues = insights.get("top_issues", [])
    trend      = insights.get("trend", {})
    keywords   = insights.get("trending_keywords", [])
    prev_date  = insights.get("prev_date", "")

    parts = []

    # ── TOP 이슈 ──
    if top_issues:
        rows = ""
        for i, iss in enumerate(top_issues, 1):
            cat  = iss.get("category", "")
            summ = iss.get("summary", "")
            cnt  = iss.get("count", 1)
            url  = iss.get("url", "#")
            cls_map = {"버그·오류": "tg-bug", "건의·요청": "tg-sug",
                       "게임 관련": "tg-game", "기타": "tg-etc"}
            cls = cls_map.get(cat, "tg-etc")
            rows += (
                f'<tr><td style="width:28px;text-align:center;font-weight:700;color:#888">#{i}</td>'
                f'<td><span class="tg {cls}">{cat}</span>'
                f' <a href="{url}" target="_blank" class="iss-link">{summ}</a></td>'
                f'<td style="text-align:right;white-space:nowrap;color:#5f6368">{cnt}건</td></tr>'
            )
        parts.append(
            f'<p class="ins-label">📌 TOP VOC</p>'
            f'<table class="ins-tbl">{rows}</table>'
        )

    # ── 트렌드 키워드 ──
    if keywords:
        tags = "".join(
            f'<span class="kw-tag">{kw["word"]} <em>{kw["count"]}</em></span>'
            for kw in keywords
        )
        parts.append(f'<p class="ins-label">🔑 주목 키워드</p><div class="kw-wrap">{tags}</div>')

    if not parts:
        return "<p class='empty-s'>인사이트 데이터 없음</p>"

    return f'<div class="insights-wrap">{"".join(parts)}</div>'


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
        cat  = voc.get("category", "")
        cnt  = voc.get("count", 1)
        summ = voc.get("summary", "")
        url  = voc.get("representative_url", "#")
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
def _nice_axis(max_val: int):
    """최대값 기준 4분할 Y축 (스텝 5의 배수)"""
    if max_val <= 0:
        return 1, 4
    raw_step = max(1, math.ceil(max_val / 4))
    step = max(1, math.ceil(raw_step / 5) * 5)
    nice_max = step * 4
    return step, nice_max


def build_section_chart(chart_dates: list[str], chart_id: str) -> str:
    labels = [d[5:] for d in chart_dates]
    gd, bd, sd, od = [], [], [], []
    for d in chart_dates:
        ad = load_analyzed(d)
        if ad:
            voc = ad.get("voc_groups", [])
            gd.append(sum(x.get("count", 1) for x in voc if x.get("category") == "게임 관련"))
            bd.append(sum(x.get("count", 1) for x in voc if x.get("category") == "버그·오류"))
            sd.append(sum(x.get("count", 1) for x in voc if x.get("category") == "건의·요청"))
            od.append(sum(x.get("count", 1) for x in voc if x.get("category") == "기타"))
        else:
            gd.append(0); bd.append(0); sd.append(0); od.append(0)

    totals   = [gd[i] + bd[i] + sd[i] + od[i] for i in range(len(gd))]
    max_val  = max(totals) if totals else 0
    step, nice_max = _nice_axis(max_val)

    return f"""
    <p class="chart-label">커뮤니티 현황 (유저 게시물 추이 — 최근 7일)</p>
    <div style="max-height:220px"><canvas id="ch-{chart_id}" height="180"></canvas></div>
    <script>
    (function(){{
      const c=document.getElementById('ch-{chart_id}');
      if(!c||c._ok)return;c._ok=true;

      const stackTotalPlugin={{
        id:'stackTotal',
        afterDatasetsDraw(chart){{
          const ctx=chart.ctx;
          const totals={json.dumps(totals)};
          const lastMeta=chart.getDatasetMeta(chart.data.datasets.length-1);
          totals.forEach((t,i)=>{{
            if(t===0)return;
            const bar=lastMeta.data[i];
            if(!bar)return;
            ctx.save();
            ctx.fillStyle='#3c4043';
            ctx.font='bold 11px sans-serif';
            ctx.textAlign='center';
            ctx.textBaseline='bottom';
            ctx.fillText(t,bar.x,bar.y-3);
            ctx.restore();
          }});
        }}
      }};

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
            legend:{{position:'bottom',labels:{{font:{{size:11}},boxWidth:12,padding:8}}}},
            tooltip:{{mode:'index',intersect:false}}
          }},
          scales:{{
            x:{{stacked:true,ticks:{{font:{{size:11}}}},grid:{{display:false}}}},
            y:{{stacked:true,beginAtZero:true,max:{nice_max},
                ticks:{{stepSize:{step},font:{{size:11}}}},grid:{{color:'#eee'}}}}
          }}
        }},
        plugins:[stackTotalPlugin]
      }});
    }})();
    </script>"""


# ── 03 공식 라운지 동향 ───────────────────────────────────────
CAT_ORDER = ["게임 관련", "버그·오류", "건의·요청", "기타"]


def build_section_voc(voc_groups: list[dict], raw_map: dict, pfx: str = "v") -> str:
    # [FIX-7] 항목(카테고리) 단위 집계 → 각 내용(item) 개별 행 + 개별 링크 + rowspan
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

        row_count = len(items)  # rowspan 계산

        for i_item, item in enumerate(items):
            item_cnt = item.get("count", 1)
            summ     = item.get("summary", "")
            url      = item.get("representative_url", "#")
            feed_ids = [str(f) for f in item.get("feed_ids", [])]

            # 아코디언 상세 (기존 로직 유지)
            det_parts = []
            for fid in feed_ids:
                post = raw_map.get(fid)
                if not post:
                    continue
                ptitle = post.get("title", "")
                pbody  = (post.get("body") or "").strip()
                if len(pbody) > 250:
                    pbody = pbody[:250] + "…"
                purl  = post.get("url", "#")
                bhtml = f'<div class="det-body">{pbody}</div>' if pbody else ""
                det_parts.append(
                    f'<div class="det-item">'
                    f'<a href="{purl}" target="_blank" class="det-title">{ptitle}</a>{bhtml}'
                    f'</div>'
                )

            vid     = f"{pfx}{idx}"
            has_exp = bool(det_parts)
            arr     = f'<span id="ar-{vid}" class="arr">▸</span>' if has_exp else '<span class="arr-ph"></span>'
            oc_attr = f' onclick="toggleVoc(\'{vid}\')" style="cursor:pointer"' if has_exp else ''
            exp_div = (
                f'<div id="{vid}" class="det-group" style="display:none">{"".join(det_parts)}</div>'
            ) if has_exp else ""

            # [FIX-7] 첫 번째 item에만 cat-td (rowspan), 이후 행은 생략
            cat_cell = ""
            if i_item == 0:
                cat_cell = f'<td class="cat-td" rowspan="{row_count}">{cat}</td>'

            # [FIX-7] 개별 item 링크
            note_cell = f'<a href="{url}" target="_blank" class="link-btn" onclick="event.stopPropagation()">[링크]</a>'

            rows += f"""
        <tr>
          {cat_cell}
          <td class="content-td">
            <div class="voc-row-item"{oc_attr}>
              <div class="voc-item-main">
                {arr}<span class="vitem-link">{summ}</span>
              </div>
            </div>
            {exp_div}
          </td>
          <td class="ref-td">{item_cnt}건</td>
          <td class="note-td">{note_cell}</td>
        </tr>"""
            idx += 1

    return f"""
    <table class="voc-tbl">
      <thead>
        <tr>
          <th style="width:76px">항목</th>
          <th>내용</th>
          <th style="width:52px">건수</th>
          <th style="width:70px">비고</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


# ── 04 1:1 문의 동향 ──────────────────────────────────────────
# CS 문의 카테고리 (Hive 기준 8개 분류)
CS_CAT_ORDER = ["결제", "계정", "설치/실행", "오류", "건의", "게임 이용", "이벤트", "기타"]

# 도넛 컬러 (8개 카테고리 대응)
_CS_DONUT_COLORS = [
    "rgba(220,50,50,0.80)",    # 결제
    "rgba(26,115,232,0.80)",   # 계정
    "rgba(251,188,4,0.85)",    # 설치/실행
    "rgba(234,67,53,0.75)",    # 오류
    "rgba(52,168,83,0.80)",    # 건의
    "rgba(70,157,198,0.80)",   # 게임 이용
    "rgba(142,64,200,0.75)",   # 이벤트
    "rgba(154,160,166,0.65)",  # 기타
]


def build_section_cs(
    cs_inquiries: list[dict],
    cs_week_trend: list[dict] = None,
    prev_cs_inquiries: list[dict] = None,   # [FIX-9] 전일 CS 데이터
) -> str:
    import json as _json

    # ── 주간 추이 복합 차트 ──
    trend_html = ""
    if cs_week_trend:
        labels    = [t["date"][5:] for t in cs_week_trend]
        received  = [t.get("received", t.get("dkr", 0)) for t in cs_week_trend]
        processed = [t.get("processed", 0) for t in cs_week_trend]
        rates     = [
            round(processed[i] / received[i] * 100) if received[i] > 0 else 0
            for i in range(len(received))
        ]

        step_cs, max_cs = _nice_axis(max(max(received), max(processed)) if received else 0)
        max_rate = max(rates) if rates else 0
        rate_max = max(120, math.ceil(max_rate / 20) * 20 + 20) if max_rate > 100 else 120

        chart_id = f"cs_combo_{labels[-1].replace('-','')}"

        # ── [FIX-6] 하단 CS 표 데이터 계산 ──
        today_recv  = received[-1] if received else 0
        today_proc  = processed[-1] if processed else 0
        today_rate_v = rates[-1] if rates else 0
        today_miss  = max(0, today_recv - today_proc)
        yest_recv   = received[-2]  if len(received)  >= 2 else 0
        yest_proc   = processed[-2] if len(processed) >= 2 else 0
        yest_rate_v = rates[-2]     if len(rates)     >= 2 else 0
        yest_miss   = max(0, yest_recv - yest_proc)
        yest_label  = labels[-2]    if len(labels)    >= 2 else "-"

        def _delta(v, sfx="건"):
            if v > 0: return f'<span style="color:#c0392b;font-weight:bold">▲{v}{sfx}</span>'
            if v < 0: return f'<span style="color:#1a73e8;font-weight:bold">▼{abs(v)}{sfx}</span>'
            return f'<span style="color:#9aa0a6">■0{sfx}</span>'

        # ── 유형별 도넛 — 항상 렌더링 (데이터 없으면 회색 placeholder) ──
        dnt_id = f"cs_dnt_{labels[-1].replace('-','')}"

        prev_map = {}
        if prev_cs_inquiries:
            for _pi in prev_cs_inquiries:
                prev_map[_pi.get("category", "")] = _pi.get("count", 0)

        # 8개 카테고리 전체 기준으로 집계 (데이터 없는 카테고리는 0)
        inq_map = {x.get("category", ""): x for x in cs_inquiries} if cs_inquiries else {}
        dnt_labels_list = CS_CAT_ORDER
        dnt_data_list   = [inq_map[c].get("count", 0) if c in inq_map else 0 for c in CS_CAT_ORDER]
        has_dnt_data    = sum(dnt_data_list) > 0

        # 지표 이슈 판단 (delta ±5 초과 시 표시)
        def _issue_flag(cur, prv):
            d = cur - prv
            if d > 5:  return f'<span style="color:#c0392b;font-size:10px">⚠ 급증</span>'
            if d < -5: return f'<span style="color:#1e8449;font-size:10px">↓ 감소</span>'
            return '<span style="color:#9aa0a6;font-size:10px">-</span>'

        # 유형별 표 행 (항상 전체 카테고리 표시)
        dnt_rows = ""
        for _ci, _cat in enumerate(CS_CAT_ORDER):
            _item  = inq_map.get(_cat)
            _cur   = _item.get("count", 0) if _item else 0
            _prv   = prev_map.get(_cat, 0)
            _dlt   = _cur - _prv
            _prv_s = str(_prv) if prev_cs_inquiries is not None else "-"
            _dot   = f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{_CS_DONUT_COLORS[_ci]};margin-right:4px;vertical-align:middle"></span>'
            dnt_rows += (
                f'<tr>'
                f'<td style="font-size:11px;text-align:left;padding:3px 5px;border-bottom:1px solid #f0f2f5">{_dot}{_cat}</td>'
                f'<td style="font-size:11px;padding:3px 5px;text-align:center;border-bottom:1px solid #f0f2f5">{_prv_s}</td>'
                f'<td style="font-size:11px;padding:3px 5px;text-align:center;font-weight:{"bold" if _cur>0 else "normal"};border-bottom:1px solid #f0f2f5">{_cur}</td>'
                f'<td style="font-size:11px;padding:3px 5px;text-align:center;border-bottom:1px solid #f0f2f5">{_delta(_dlt)}</td>'
                f'<td style="font-size:11px;padding:3px 5px;text-align:center;border-bottom:1px solid #f0f2f5">{_issue_flag(_cur, _prv)}</td>'
                f'</tr>'
            )

        # 도넛 섹션 — 항상 canvas + JS 생성 (데이터 없으면 회색 원으로 표시)
        _donut_data_js    = _json.dumps([1] if not has_dnt_data else dnt_data_list)
        _donut_colors_js  = _json.dumps(["rgba(220,220,220,0.4)"] if not has_dnt_data
                                        else _CS_DONUT_COLORS[:len(CS_CAT_ORDER)])
        _donut_labels_js  = _json.dumps(CS_CAT_ORDER, ensure_ascii=False)
        _donut_tooltip_fn = (
            "function(c){return '데이터 없음';}"
            if not has_dnt_data else
            "function(c){var t=c.dataset.data.reduce(function(a,b){return a+b;},0);"
            "return c.label+': '+c.parsed+'건 ('+Math.round(c.parsed/t*100)+'%)';}"
        )

        dnt_section_html = f"""
      <div>
        <p style="font-size:11px;font-weight:700;color:#5f6368;margin-bottom:5px">유형별 문의 접수 현황</p>
        <div style="display:grid;grid-template-columns:130px 1fr;gap:8px;align-items:start">
          <div style="position:relative;height:150px"><canvas id="{dnt_id}"></canvas></div>
          <table style="width:100%;border-collapse:collapse">
            <thead>
              <tr>
                <th style="font-size:10px;padding:3px 5px;background:#f1f3f4;color:#5f6368;font-weight:600;text-align:left;border-bottom:1.5px solid #e8eaed">분류</th>
                <th style="font-size:10px;padding:3px 5px;background:#f1f3f4;color:#5f6368;font-weight:600;text-align:center;border-bottom:1.5px solid #e8eaed">전일</th>
                <th style="font-size:10px;padding:3px 5px;background:#f1f3f4;color:#5f6368;font-weight:600;text-align:center;border-bottom:1.5px solid #e8eaed">금일</th>
                <th style="font-size:10px;padding:3px 5px;background:#f1f3f4;color:#5f6368;font-weight:600;text-align:center;border-bottom:1.5px solid #e8eaed">증감</th>
                <th style="font-size:10px;padding:3px 5px;background:#f1f3f4;color:#5f6368;font-weight:600;text-align:center;border-bottom:1.5px solid #e8eaed">지표이슈</th>
              </tr>
            </thead>
            <tbody>{dnt_rows}</tbody>
          </table>
        </div>
        {"<p style='font-size:10px;color:#9aa0a6;margin-top:4px;text-align:center'>· CS 데이터 미수집 (Hive 브라우저 수집 필요)</p>" if not has_dnt_data else ""}
      </div>"""

        dnt_js = f"""
    <script>
    (function(){{
      var c=document.getElementById('{dnt_id}');
      if(!c||c._ok)return;c._ok=true;
      var hasData={str(has_dnt_data).lower()};
      new Chart(c,{{
        type:'doughnut',
        data:{{
          labels:{_donut_labels_js},
          datasets:[{{
            data:{_donut_data_js},
            backgroundColor:{_donut_colors_js},
            borderWidth:hasData?2:1,
            borderColor:hasData?'#fff':'rgba(200,200,200,0.5)'
          }}]
        }},
        options:{{
          responsive:true,maintainAspectRatio:false,cutout:'58%',
          plugins:{{
            legend:{{display:false}},
            tooltip:{{enabled:hasData,callbacks:{{label:{_donut_tooltip_fn}}}}}
          }}
        }}
      }});
    }})();
    </script>"""

        trend_html = f"""
        <div style="margin-bottom:8px">
          <div style="position:relative;height:160px">
            <canvas id="{chart_id}"></canvas>
          </div>
        </div>
        <script>
        (function(){{
          var ctx = document.getElementById('{chart_id}').getContext('2d');
          var barLabelPlugin = {{
            id:'barLabel',
            afterDraw: function(chart) {{
              var c = chart.ctx;
              chart.data.datasets.forEach(function(ds, di) {{
                var meta = chart.getDatasetMeta(di);
                if (meta.hidden) return;
                if (ds.type === 'line') {{
                  // [FIX-4] 처리율 꺾은선 각 포인트에 % 레이블 표시
                  meta.data.forEach(function(pt, i) {{
                    var val = ds.data[i];
                    if (!val && val !== 0) return;
                    c.save();
                    c.font = 'bold 10px sans-serif';
                    c.fillStyle = 'rgba(220,50,50,0.9)';
                    c.textAlign = 'center';
                    c.textBaseline = 'bottom';
                    c.fillText(val + '%', pt.x, pt.y - 5);
                    c.restore();
                  }});
                  return;
                }}
                // 막대 레이블
                meta.data.forEach(function(bar, i) {{
                  var val = ds.data[i];
                  if (!val) return;
                  c.save();
                  c.font = 'bold 10px sans-serif';
                  c.fillStyle = '#333';
                  c.textAlign = 'center';
                  c.textBaseline = 'bottom';
                  c.fillText(val, bar.x, bar.y - 2);
                  c.restore();
                }});
              }});
            }}
          }};
          new Chart(ctx, {{
            data: {{
              labels: {_json.dumps(labels)},
              datasets: [
                {{
                  type: 'bar',
                  label: '인입량',
                  data: {_json.dumps(received)},
                  backgroundColor: 'rgba(123,104,238,0.75)',
                  borderRadius: 3,
                  yAxisID: 'y'
                }},
                {{
                  type: 'bar',
                  label: '처리량',
                  data: {_json.dumps(processed)},
                  backgroundColor: 'rgba(160,160,160,0.75)',
                  borderRadius: 3,
                  yAxisID: 'y'
                }},
                {{
                  type: 'line',
                  label: '처리율',
                  data: {_json.dumps(rates)},
                  borderColor: 'rgba(220,50,50,0.85)',
                  borderDash: [5,3],
                  borderWidth: 1.5,
                  pointBackgroundColor: 'rgba(220,50,50,0.85)',
                  pointRadius: 3,
                  tension: 0.2,
                  yAxisID: 'y1'
                }}
              ]
            }},
            options: {{
              responsive: true,
              maintainAspectRatio: false,
              plugins: {{
                legend: {{
                  position: 'bottom',
                  labels: {{ font: {{size:11}}, boxWidth:12, padding:8 }}
                }},
                tooltip: {{
                  mode: 'index',
                  intersect: false,
                  callbacks: {{
                    label: function(c) {{
                      if (c.dataset.label === '처리율') return c.dataset.label + ': ' + c.parsed.y + '%';
                      return c.dataset.label + ': ' + c.parsed.y + '건';
                    }}
                  }}
                }}
              }},
              scales: {{
                y: {{
                  min: 0, max: {max_cs},
                  ticks: {{ stepSize: {step_cs}, callback: function(v){{ return v+'건'; }}, font:{{size:11}} }},
                  grid: {{ color: '#eee' }}
                }},
                y1: {{
                  display: false,
                  position: 'right',
                  min: 0, max: {rate_max},
                  grid: {{ drawOnChartArea: false }}
                }},
                x: {{ ticks:{{font:{{size:11}}}}, grid:{{ display:false }} }}
              }}
            }},
            plugins: [barLabelPlugin]
          }});
        }})();
        </script>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:8px;padding-bottom:4px">
          <div>
            <p style="font-size:11px;font-weight:700;color:#5f6368;margin-bottom:6px">CS 접수/처리 현황</p>
            <table style="width:100%;border-collapse:collapse;font-size:12px">
              <thead>
                <tr>
                  <th style="background:#f1f3f4;padding:7px 8px;color:#5f6368;font-size:11px;font-weight:600;border-bottom:1.5px solid #e8eaed;text-align:center">일자</th>
                  <th style="background:#f1f3f4;padding:7px 8px;color:#5f6368;font-size:11px;font-weight:600;border-bottom:1.5px solid #e8eaed;text-align:center">접수</th>
                  <th style="background:#f1f3f4;padding:7px 8px;color:#5f6368;font-size:11px;font-weight:600;border-bottom:1.5px solid #e8eaed;text-align:center">처리</th>
                  <th style="background:#f1f3f4;padding:7px 8px;color:#5f6368;font-size:11px;font-weight:600;border-bottom:1.5px solid #e8eaed;text-align:center">미처리</th>
                  <th style="background:#f1f3f4;padding:7px 8px;color:#5f6368;font-size:11px;font-weight:600;border-bottom:1.5px solid #e8eaed;text-align:center">처리율</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td style="padding:7px 8px;border-bottom:1px solid #f0f2f5;text-align:center;font-size:11px">{yest_label}<br><span style="color:#9aa0a6;font-size:10px">(전일)</span></td>
                  <td style="padding:7px 8px;border-bottom:1px solid #f0f2f5;text-align:center">{yest_recv}</td>
                  <td style="padding:7px 8px;border-bottom:1px solid #f0f2f5;text-align:center">{yest_proc}</td>
                  <td style="padding:7px 8px;border-bottom:1px solid #f0f2f5;text-align:center">{yest_miss}</td>
                  <td style="padding:7px 8px;border-bottom:1px solid #f0f2f5;text-align:center">{yest_rate_v}%</td>
                </tr>
                <tr>
                  <td style="padding:7px 8px;border-bottom:1px solid #f0f2f5;text-align:center;font-size:11px;font-weight:bold">{labels[-1]}<br><span style="color:#1a73e8;font-size:10px">(당일)</span></td>
                  <td style="padding:7px 8px;border-bottom:1px solid #f0f2f5;text-align:center;font-weight:bold">{today_recv}</td>
                  <td style="padding:7px 8px;border-bottom:1px solid #f0f2f5;text-align:center;font-weight:bold">{today_proc}</td>
                  <td style="padding:7px 8px;border-bottom:1px solid #f0f2f5;text-align:center;font-weight:bold">{today_miss}</td>
                  <td style="padding:7px 8px;border-bottom:1px solid #f0f2f5;text-align:center;font-weight:bold">{today_rate_v}%</td>
                </tr>
                <tr style="background:#f0f4ff">
                  <td style="padding:7px 8px;text-align:center;font-weight:bold;color:#5f6368;font-size:11px">증감</td>
                  <td style="padding:7px 8px;text-align:center">{_delta(today_recv - yest_recv)}</td>
                  <td style="padding:7px 8px;text-align:center">{_delta(today_proc - yest_proc)}</td>
                  <td style="padding:7px 8px;text-align:center">{_delta(today_miss - yest_miss)}</td>
                  <td style="padding:7px 8px;text-align:center">{_delta(today_rate_v - yest_rate_v, '%')}</td>
                </tr>
              </tbody>
            </table>
          </div>
          {dnt_section_html}
        </div>
        {dnt_js}"""

    # [FIX-CS05] detail_html은 05 섹션(build_section_cs_detail)으로 분리
    if not trend_html:
        return """
        <div class="cs-placeholder">
          <p>📋 Hive 콘솔에서 당일 문의 데이터를 수동으로 업데이트해 주세요.</p>
          <p class="cs-hint">→ console.withhive.com → 문의 목록 → 한국어 → 전체 검색</p>
        </div>"""

    return trend_html


# ── 05 CS 상세 문의 ──────────────────────────────────────────────
def build_section_cs_detail(cs_inquiries: list[dict]) -> str:
    """CS 상세 문의 테이블 — representative 키 기반 렌더링 (05 섹션)"""
    if not cs_inquiries:
        return "<p class='empty-s' style='color:#888;font-size:12px'>당일 DKR 문의 없음</p>"

    by_cat = {c: [] for c in CS_CAT_ORDER}
    for item in cs_inquiries:
        cat = item.get("category", "기타")
        by_cat.setdefault(cat, []).append(item)

    rows = ""
    for cat in CS_CAT_ORDER:
        items = by_cat.get(cat, [])
        if not items:
            continue
        total = sum(x.get("count", 1) for x in items)
        content = ""
        for item in items:
            # [FIX-representative] "summary" 키 없음 → representative 리스트 사용
            representative = item.get("representative", [])
            if representative:
                summ = representative[0].get("title", "")[:60]
                sub_items = [
                    f"{r.get('title', '')[:50]} [{r.get('status', '')}]"
                    for r in representative[1:]
                ]
            else:
                summ      = item.get("summary", "")
                sub_items = item.get("items", [])
            cnt      = item.get("count", 1)
            sub_html = ""
            if sub_items:
                sub_html = "<ul class='cs-sub'>" + "".join(f"<li>{s}</li>" for s in sub_items) + "</ul>"
            cnt_txt = f'<span class="cnt-s">({cnt}건)</span>' if cnt > 1 else ""
            content += f'<div class="cs-item">{summ}{cnt_txt}{sub_html}</div>'
        rows += f"""
            <tr>
              <td class="cat-td">{cat}</td>
              <td class="content-td cs-content">{content}</td>
              <td class="ref-td">{total}건</td>
            </tr>"""

    if not rows:
        return "<p class='empty-s'>수집된 문의 없음</p>"

    return f"""
            <table class="voc-tbl">
              <thead>
                <tr>
                  <th style="width:76px">항목</th>
                  <th>내용</th>
                  <th style="width:52px">건수</th>
                </tr>
              </thead>
              <tbody>{rows}</tbody>
            </table>"""


# ── 05 CS 동향 ──────────────────────────────────────────────
# ── 리포트 섹션 래퍼 ──────────────────────────────────────────
def sec(num: str, title: str, body: str) -> str:
    return f"""
    <div class="rpt-section">
      <div class="rpt-sec-hd"><span class="sec-num">{num}</span>{title}</div>
      <div class="rpt-sec-body">{body}</div>
    </div>"""


def build_report(date_str: str, period: str, all_dates: list[str]) -> str:
    if period == "daily":
        analyzed = load_analyzed(date_str) or {"major_issues": [], "voc_groups": [], "cs_inquiries": []}
        raw_map  = build_raw_map([date_str])

        end = datetime.strptime(date_str, "%Y-%m-%d")
        chart_dates = [(end - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]

        # [FIX-9] 전일 analyzed.json 로드 → build_section_cs에 전달
        prev_date_str  = (end - timedelta(days=1)).strftime("%Y-%m-%d")
        prev_analyzed  = load_analyzed(prev_date_str) or {}
        prev_cs_inqs   = prev_analyzed.get("cs_inquiries", [])

        chart_id = f"D{date_str.replace('-','')}"
        label    = f"{date_str} 일일 서비스 현황"

        return (
            f'<div class="rpt-header"><span class="rpt-game">DK모바일:리본</span>'
            f'<span class="rpt-title">{label}</span>'
            f'<span class="rpt-ts">조회: {datetime.now(KST).strftime("%Y-%m-%d %H:%M")}</span></div>'
            + sec("00", "VOC 인사이트",     build_section_insights(analyzed.get("insights", {})))
            + sec("01", "주요 이슈",        build_section_issues(analyzed))
            + sec("02", "운영 지표",        build_section_chart(chart_dates, chart_id))
            + sec("03", "1:1 문의 동향",    build_section_cs(
                analyzed.get("cs_inquiries", []),
                analyzed.get("cs_week_trend"),
                prev_cs_inquiries=prev_cs_inqs,   # [FIX-9]
            ))
            + sec("04", "공식 라운지 동향", build_section_voc(
                analyzed.get("voc_groups", []), raw_map,
                pfx=f"D{date_str.replace('-','')}_"))
            + sec("05", "CS 상세 문의",    build_section_cs_detail(
                analyzed.get("cs_inquiries", [])))
        )
    else:  # weekly
        idx        = all_dates.index(date_str) if date_str in all_dates else 0
        week_dates = all_dates[idx: idx + 7]
        analyzed   = merge_analyzed(week_dates)
        raw_map    = build_raw_map(week_dates)
        wrange     = f"{week_dates[-1]} ~ {week_dates[0]}" if len(week_dates) > 1 else week_dates[0]
        chart_id   = f"W{date_str.replace('-','')}"
        sorted_wd  = sorted(week_dates)

        return (
            f'<div class="rpt-header"><span class="rpt-game">DK모바일:리본</span>'
            f'<span class="rpt-title">주간 서비스 현황</span>'
            f'<span class="rpt-ts">집계기간: {wrange}</span></div>'
            + sec("01", "주간 주요 이슈",   build_section_issues(analyzed))
            + sec("02", "운영 지표",        build_section_chart(sorted_wd, chart_id))
            + sec("03", "1:1 문의 동향",    build_section_cs(
                analyzed.get("cs_inquiries", []),
                analyzed.get("cs_week_trend"),
            ))
            + sec("04", "공식 라운지 동향", build_section_voc(
                analyzed.get("voc_groups", []), raw_map,
                pfx=f"W{date_str.replace('-','')}_"))
            + sec("05", "CS 상세 문의",    build_section_cs_detail(
                analyzed.get("cs_inquiries", [])))
        )


# ── HTML 전체 생성 ────────────────────────────────────────────
def generate():
    voc_dates = available_dates()   # [FIX-1] analyzed-only 날짜 포함
    all_d     = all_dates_union()
    now       = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    latest    = all_d[0] if all_d else ""

    # [FIX-DATE] report_date = latest - 1일 (전일 기준 리포트)
    if all_d:
        _latest_dt  = datetime.strptime(all_d[0], "%Y-%m-%d")
        _report_dt  = _latest_dt - timedelta(days=1)
        report_date = _report_dt.strftime("%Y-%m-%d")
        default_date = report_date if report_date in all_d else all_d[0]
    else:
        default_date = ""

    # [FIX-DROPDOWN] report_date 이하 날짜만 드롭다운에 표시 (today 제외)
    date_opts = "".join(
        f'<option value="{d}"{" selected" if d == default_date else ""}>{d}</option>\n'
        for d in all_d if d <= default_date
    )

    panels_html = ""
    for date_str in voc_dates:   # voc_dates now includes analyzed-only dates
        is_first = (date_str == default_date)
        panels_html += f"""
        <div id="panel-{date_str}" class="date-panel" style="display:{'block' if is_first else 'none'}">
          <div id="D-{date_str}" class="period-panel" style="display:block">{build_report(date_str,"daily",voc_dates)}</div>
          <div id="W-{date_str}" class="period-panel" style="display:none">{build_report(date_str,"weekly",voc_dates)}</div>
        </div>"""

    if not panels_html:
        panels_html = "<p class='empty-s'>VOC 데이터 없음</p>"

    metrics_js = build_metrics_js_data()

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>NTRANCE 대시보드 — DK모바일:리본</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Malgun Gothic","Apple SD Gothic Neo",sans-serif;
      background:#eef0f3;color:#1a1a2e;font-size:13px;min-height:100vh}}
:root{{--green:#1e8449;--red:#c0392b;--blue:#1a73e8;--gray:#5f6368}}

/* ── 네비 ── */
.top-nav{{background:#1a1a2e;padding:0 20px;display:flex;align-items:center;
          justify-content:space-between;height:48px;box-shadow:0 2px 8px rgba(0,0,0,.3)}}
.brand{{color:#fff;font-size:15px;font-weight:700;letter-spacing:-.3px}}
.brand-sub{{color:#8892b0;font-size:11px}}

/* ── 탭바 (2단) ── */
.tab-bar-top{{background:#fff;border-bottom:1px solid #e8eaed;padding:0 20px;
              display:flex;align-items:center;justify-content:space-between;height:44px}}
.game-tabs{{display:flex;gap:4px}}
.tab-btn{{padding:8px 16px;border:none;border-bottom:3px solid transparent;background:none;
          cursor:pointer;font-size:13px;font-weight:600;color:#5f6368;
          display:flex;align-items:center;gap:6px;transition:all .2s}}
.tab-btn.active{{color:#1a73e8;border-bottom-color:#1a73e8}}
.tab-dot{{width:8px;height:8px;border-radius:50%;background:#1a73e8}}

/* VOC/지표 섹션 탭 */
.stab-bar{{background:#f8f9fa;border-bottom:2px solid #e8eaed;padding:0 20px;
           display:flex;align-items:center;justify-content:space-between;height:38px}}
.stab-group{{display:flex;gap:2px}}
.stab{{padding:6px 18px;border:none;border-radius:4px 4px 0 0;
       background:none;cursor:pointer;font-size:12.5px;font-weight:700;
       color:#5f6368;transition:all .15s;border-bottom:2px solid transparent;margin-bottom:-2px}}
.stab.active{{background:#fff;color:#1a73e8;border-color:#1a73e8}}
.right-controls{{display:flex;align-items:center;gap:8px}}
.date-select{{padding:5px 10px;border:1.5px solid #dde1e7;border-radius:6px;
              font-size:12px;color:#3c4043;background:#fff;cursor:pointer;outline:none}}
.date-select:focus{{border-color:#1a73e8}}
.period-toggle{{display:flex;border:1.5px solid #dde1e7;border-radius:6px;overflow:hidden}}
.ptgl{{padding:5px 12px;border:none;background:#fff;font-size:12px;font-weight:600;
       color:#5f6368;cursor:pointer;transition:all .15s}}
.ptgl.active{{background:#1a73e8;color:#fff}}
.ptgl:not(:last-child){{border-right:1px solid #dde1e7}}

/* ── 지표 서브탭 ── */
.mnav-bar{{display:flex;gap:4px;padding:12px 20px 0;background:#fff;
           border-bottom:1px solid #e8eaed;margin-bottom:16px}}
.mnav{{padding:8px 20px;border:none;border-bottom:2.5px solid transparent;
       background:none;cursor:pointer;font-size:12.5px;font-weight:700;
       color:#5f6368;transition:all .15px}}
.mnav.active{{color:#1a73e8;border-bottom-color:#1a73e8}}

/* ── 지표 KPI 카드 ── */
.kpi-row{{display:flex;gap:12px;flex-wrap:wrap;padding:16px 20px 0}}
.kpi-card{{flex:1;min-width:200px;background:#f8f9fa;border:1px solid #e8eaed;
           border-radius:8px;padding:14px 18px}}
.kpi-card-label{{font-size:11px;color:#5f6368;font-weight:600;margin-bottom:4px}}
.kpi-card-value{{font-size:22px;font-weight:800;color:#1a1a2e;line-height:1.2}}
.kpi-card-delta{{font-size:11.5px;margin-top:3px}}
.kpi-pills{{display:flex;gap:8px;flex-wrap:wrap;padding:12px 20px}}
.kpi-pill{{background:#fff;border:1px solid #e8eaed;border-radius:6px;
           padding:8px 14px;min-width:90px;text-align:center}}
.kpi-pill-label{{font-size:10px;color:#5f6368;font-weight:600;margin-bottom:2px}}
.kpi-pill-value{{font-size:15px;font-weight:800;color:#1a1a2e}}
.kpi-pill-delta{{font-size:10px;margin-top:2px}}

/* ── 지표 서버 테이블 ── */
.m-tbl{{width:100%;border-collapse:collapse;font-size:12.5px}}
.m-tbl th{{background:#f1f3f4;padding:8px 12px;text-align:center;font-size:11px;
           color:#5f6368;border-bottom:1.5px solid #e8eaed;font-weight:600}}
.m-tbl td{{padding:9px 12px;border-bottom:1px solid #f0f2f5;text-align:center}}
.m-tbl tr:last-child td{{font-weight:700;background:#f8f9fa}}
.m-tbl td:first-child{{text-align:left;font-weight:600;color:#3c4043}}
.m-na{{color:#bdbdbd;font-style:italic}}
.m-global{{color:#9aa0a6;font-style:italic}}

/* ── 패키지 테이블 ── */
.pkg-cols{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;padding:16px 20px}}
.pkg-col{{background:#fff;border:1px solid #e8eaed;border-radius:8px;overflow:hidden}}
.pkg-col-hd{{background:#f1f3f4;padding:10px 14px;font-size:12px;font-weight:700;
             color:#3c4043;border-bottom:1px solid #e8eaed}}
.pkg-inner{{display:grid;grid-template-columns:1fr 1fr;}}
.pkg-sub-hd{{padding:6px 10px;font-size:10.5px;font-weight:700;color:#5f6368;
             background:#fafafa;border-bottom:1px solid #f0f2f5;text-align:center}}
.pkg-row{{display:flex;align-items:center;padding:5px 10px;border-bottom:1px solid #f9f9f9;
          font-size:11.5px;gap:6px}}
.pkg-rank{{font-size:10px;font-weight:800;color:#fff;background:#9aa0a6;
           border-radius:3px;padding:1px 5px;min-width:22px;text-align:center}}
.pkg-rank-1{{background:#f9a825}}.pkg-rank-2{{background:#bdbdbd}}.pkg-rank-3{{background:#a1887f}}
.pkg-name{{flex:1;color:#3c4043;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.pkg-qty{{font-weight:700;color:#1a73e8;white-space:nowrap}}
.pkg-empty{{padding:20px;text-align:center;color:#9aa0a6;font-size:12px;font-style:italic}}

/* ── 지표 차트 레이아웃 ── */
.m-chart-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:16px 20px}}
.m-chart-box{{background:#f8f9fa;border:1px solid #e8eaed;border-radius:8px;padding:12px}}
.m-chart-title{{font-size:11.5px;font-weight:700;color:#3c4043;margin-bottom:8px}}
.m-chart-wrap{{position:relative;height:130px}}
.m-bar-pair{{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:0 20px 16px}}
.m-bar-box{{background:#f8f9fa;border:1px solid #e8eaed;border-radius:8px;padding:12px}}

/* 플랫폼 파이 */
.plat-row{{display:flex;gap:12px;padding:0 20px 16px;flex-wrap:wrap}}
.plat-box{{flex:1;min-width:160px;background:#f8f9fa;border:1px solid #e8eaed;
           border-radius:8px;padding:12px;text-align:center}}
.plat-title{{font-size:11px;font-weight:700;color:#5f6368;margin-bottom:8px}}
.plat-chart-wrap{{position:relative;height:110px;max-width:150px;margin:0 auto}}

/* 증감 색상 */
.dg{{color:var(--green)}} .dr{{color:var(--red)}} .dn{{color:var(--gray)}}

/* ── 본문 ── */
.main{{max-width:1100px;margin:20px auto;padding:0 14px 40px}}
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
.rpt-sec-hd{{display:flex;align-items:center;gap:10px;padding:12px 20px 10px;
             background:#f8f9fa;border-bottom:1px solid #e8eaed;
             font-size:13px;font-weight:700;color:#3c4043}}
.sec-num{{background:#1a73e8;color:#fff;font-size:11px;font-weight:800;
          padding:2px 7px;border-radius:3px;letter-spacing:.5px}}
.rpt-sec-body{{padding:16px 20px}}

/* 주요 이슈 */
.iss-list{{list-style:none;display:flex;flex-direction:column;gap:7px}}
.iss-list li{{display:flex;align-items:flex-start;gap:8px;font-size:12.5px;line-height:1.5}}
.tg{{font-size:10px;font-weight:700;padding:2px 6px;border-radius:3px;
     white-space:nowrap;flex-shrink:0;margin-top:2px}}
.tg-notice{{background:#e3f2fd;color:#1565c0}}
.tg-update{{background:#e8f5e9;color:#2e7d32}}
.tg-bug{{background:#fce8e6;color:#c62828}}
.tg-sug{{background:#fff3cd;color:#b45309}}
.tg-game{{background:#e8f0fe;color:#1a73e8}}
.tg-etc{{background:#f1f3f4;color:#5f6368}}
.iss-link{{color:#1a1a2e;text-decoration:none;font-weight:500}}
.iss-link:hover{{color:#1a73e8;text-decoration:underline}}
.cnt-s{{font-size:11px;color:#9aa0a6;margin-left:2px}}

/* 인사이트 */
.insights-wrap{{display:flex;flex-direction:column;gap:14px}}
.ins-label{{font-size:11.5px;font-weight:700;color:#3c4043;margin-bottom:4px}}
.ins-tbl{{width:100%;border-collapse:collapse;font-size:12.5px}}
.ins-tbl td{{padding:5px 8px;border-bottom:1px solid #f1f3f4;vertical-align:middle}}
.ins-tbl tr:last-child td{{border-bottom:none}}
.kw-wrap{{display:flex;flex-wrap:wrap;gap:6px}}
.kw-tag{{background:#e8f0fe;color:#1a73e8;font-size:11.5px;font-weight:600;
         padding:3px 9px;border-radius:12px;display:inline-flex;align-items:center;gap:4px}}
.kw-tag em{{font-style:normal;color:#9aa0a6;font-weight:400;font-size:10.5px}}

/* 차트 */
.chart-label{{font-size:12px;color:#5f6368;font-weight:600;margin-bottom:10px}}

/* VOC 테이블 */
.voc-tbl{{width:100%;border-collapse:collapse}}
.voc-tbl th{{background:#f1f3f4;padding:8px 10px;text-align:left;font-size:11px;
             color:#5f6368;border-bottom:1.5px solid #e8eaed;font-weight:600}}
.voc-tbl td{{border-bottom:1px solid #f0f2f5;vertical-align:middle}}
.cat-td{{padding:10px 10px;font-weight:700;font-size:12px;color:#3c4043;
         white-space:nowrap;width:76px;text-align:center}}
.content-td{{padding:4px 0;vertical-align:middle}}
.ref-td{{padding:10px 8px;text-align:center;font-size:12px;color:#5f6368;
         white-space:nowrap;width:52px;font-weight:600}}

/* VOC 아이템 */
.voc-row-item{{display:flex;align-items:center;justify-content:space-between;
               padding:7px 10px;gap:8px;transition:background .15s}}
.voc-row-item[onclick]{{cursor:pointer}}
.voc-row-item[onclick]:hover{{background:#f8f9fa;border-radius:4px}}
.voc-sep{{border-top:1px dashed #e8eaed}}
.voc-item-main{{display:flex;align-items:center;gap:4px;flex:1;min-width:0}}
.arr{{font-size:11px;color:#1a73e8;flex-shrink:0;width:13px}}
.arr-ph{{width:13px;flex-shrink:0}}
.vitem-link{{font-size:12.5px;color:#3c4043;text-decoration:none;line-height:1.5;flex:1}}
.vitem-link:hover{{color:#1a73e8}}
.link-btn{{font-size:11px;color:#1a73e8;text-decoration:none;font-weight:600;
           white-space:nowrap;flex-shrink:0;display:inline-block;margin:2px 0}}
.link-btn:hover{{text-decoration:underline}}
.note-td{{padding:8px 6px;text-align:center;vertical-align:middle;
          border-bottom:1px solid #f0f2f5;font-size:11px}}

/* 아코디언 상세 */
.det-group{{background:#f0f4ff;border-radius:6px;margin:2px 8px 8px;padding:10px 12px}}
.det-item{{padding:6px 0;border-bottom:1px solid #dde6ff}}
.det-item:last-child{{border-bottom:none;padding-bottom:0}}
.det-title{{font-size:12px;font-weight:600;color:#1a1a2e;text-decoration:none;
            display:block;margin-bottom:3px}}
.det-title:hover{{color:#1a73e8;text-decoration:underline}}
.det-body{{font-size:11px;color:#5f6368;line-height:1.6;padding-left:4px;margin-top:2px}}

/* CS 문의 */
.cs-item{{padding:6px 10px;font-size:12.5px;color:#3c4043;line-height:1.5}}
.cs-sep{{border-top:1px dashed #e8eaed}}
.cs-sub{{margin:4px 0 0 16px;list-style:disc;color:#5f6368;font-size:11.5px}}
.cs-sub li{{padding:2px 0}}
.cs-placeholder{{padding:16px;background:#fffbf0;border-radius:6px;
                 border:1px dashed #fbbc04;text-align:center}}
.cs-placeholder p{{font-size:12.5px;color:#5f6368;margin-bottom:4px}}
.cs-hint{{font-size:11px;color:#9aa0a6 !important}}
.cs-content{{vertical-align:middle}}
/* 05 CS 동향 배지 */
.cs-det-row{{display:flex;align-items:center;gap:5px;padding:5px 10px;font-size:12px;line-height:1.4}}
.cs-badge{{display:inline-block;padding:1px 6px;border-radius:10px;font-size:10.5px;font-weight:600;white-space:nowrap}}
.cs-badge-recv{{background:#fff3e0;color:#e65100}}
.cs-badge-proc{{background:#e3f2fd;color:#1565c0}}
.cs-badge-done{{background:#e8f5e9;color:#2e7d32}}
.cs-badge-view{{background:#f3e5f5;color:#6a1b9a}}
.cs-badge-del{{background:#fafafa;color:#9e9e9e}}
.cs-badge-etc{{background:#f5f5f5;color:#616161}}
.cs-date{{font-size:10.5px;color:#9aa0a6;white-space:nowrap}}
.cs-ttl{{color:#3c4043;font-size:12px}}
.cs-pending{{color:#e53935;font-weight:600;font-size:11.5px}}

.period-bar{{font-size:12px;color:#5f6368;background:#f8f9fa;padding:6px 12px;
             border-radius:4px;margin-bottom:8px}}
.empty-s{{color:#9aa0a6;font-size:12px;padding:16px;text-align:center}}
.updated{{font-size:11px;color:#9aa0a6;text-align:right;padding:12px 20px;
          border-top:1px solid #f0f2f5}}
</style>
</head>
<body>

<!-- ── 상단 네비 ── -->
<div class="top-nav">
  <div style="display:flex;align-items:center;gap:10px">
    <span class="brand">NTRANCE</span>
    <span class="brand-sub">게임 대시보드</span>
  </div>
  <span style="font-size:11px;color:#8892b0">생성: {now}</span>
</div>

<!-- ── 게임 탭 + VOC/지표 섹션 탭 ── -->
<div class="tab-bar-top">
  <div class="game-tabs">
    <button class="tab-btn active">
      <span class="tab-dot"></span>DK모바일:리본
    </button>
  </div>
  <div class="stab-group">
    <button class="stab active" id="stab-voc"     onclick="switchSection('voc')">VOC</button>
    <button class="stab"        id="stab-metrics"  onclick="switchSection('metrics')">지표</button>
  </div>
  <div class="right-controls">
    <select class="date-select" id="date-sel" onchange="onDateChange(this.value)">
      {date_opts}
    </select>
    <div class="period-toggle">
      <button class="ptgl active" id="btn-D" onclick="switchPeriod('D',this)">일간</button>
      <button class="ptgl"        id="btn-W" onclick="switchPeriod('W',this)">주간</button>
      <button class="ptgl"        id="btn-M" onclick="switchPeriod('M',this)" style="display:none">월간</button>
    </div>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════
     VOC 섹션
══════════════════════════════════════════════════════ -->
<div id="sect-voc" class="main">
  <div class="rpt-card">
    {panels_html}
    <div class="updated">마지막 업데이트: {now}</div>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════
     지표 섹션
══════════════════════════════════════════════════════ -->
<div id="sect-metrics" class="main" style="display:none">
  <div class="rpt-card">
    <!-- 지표 서브탭 -->
    <div class="mnav-bar">
      <button class="mnav active" id="mnav-revenue"  onclick="switchMetricsSub('revenue')">매출</button>
      <button class="mnav"        id="mnav-packages"  onclick="switchMetricsSub('packages')">패키지</button>
      <button class="mnav"        id="mnav-users"     onclick="switchMetricsSub('users')">유저지표</button>
    </div>
    <div id="m-content" style="padding-bottom:20px">
      <p class="empty-s" style="padding:40px">날짜를 선택하거나 지표 데이터를 업데이트하세요.</p>
    </div>
    <div class="updated">마지막 업데이트: {now}</div>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════
     JavaScript
══════════════════════════════════════════════════════ -->
<script>
// ── 지표 데이터 (Python 임베드) ──────────────────────────────────
{metrics_js}

// ── 전역 상태 ────────────────────────────────────────────────────
var _section='voc', _sub='revenue', _date='{latest}', _period='D';
var _charts={{}};

// ── 섹션 전환 (VOC ↔ 지표) ──────────────────────────────────────
function switchSection(sec){{
  _section=sec;
  document.querySelectorAll('.stab').forEach(b=>b.classList.remove('active'));
  document.getElementById('stab-'+sec).classList.add('active');
  document.getElementById('sect-voc').style.display    = sec==='voc'     ? '' : 'none';
  document.getElementById('sect-metrics').style.display = sec==='metrics' ? '' : 'none';
  var btnM = document.getElementById('btn-M');
  if(sec==='metrics'){{
    btnM.style.display='';
  }}else{{
    btnM.style.display='none';
    if(_period==='M'){{switchPeriod('D',document.getElementById('btn-D'));return;}}
  }}
  if(sec==='metrics') renderCurrentMetrics();
}}

// ── 날짜 변경 ─────────────────────────────────────────────────
// [FIX-2] 버그 수정: _date를 vocSwitchDate 호출 전에 갱신하면 기존 패널을 찾지 못함
//          → vocSwitchDate 내부에서 _date 갱신하도록 순서 변경
function onDateChange(d){{
  if(_section==='voc'){{
    vocSwitchDate(d);   // vocSwitchDate 안에서 _date=d 처리
  }}else{{
    _date=d;
    renderCurrentMetrics();
  }}
}}

// ── 기간 전환 ─────────────────────────────────────────────────
function switchPeriod(p,btn){{
  document.querySelectorAll('.ptgl').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  if(_section==='voc'){{
    var oldId=_period+'-'+_date;
    var el=document.getElementById(oldId);
    if(el)el.style.display='none';
    _period=p;
    var newEl=document.getElementById(_period+'-'+_date);
    if(newEl)newEl.style.display='block';
  }}else{{
    _period=p;
    renderCurrentMetrics();
  }}
}}

// ── VOC 기존 로직 ──────────────────────────────────────────────
// [FIX-2] _date 갱신을 이 함수 내부에서 처리 (onDateChange에서 중복 갱신 제거)
function vocSwitchDate(d){{
  var old=document.getElementById('panel-'+_date);  // 기존 _date로 이전 패널 참조
  if(old)old.style.display='none';
  _date=d;                                           // 이후 _date 갱신
  var np=document.getElementById('panel-'+d);
  if(np){{
    np.style.display='block';
    var pp=_period==='M'?'D':_period;
    var pp_el=document.getElementById(pp+'-'+d);
    if(pp_el)pp_el.style.display='block';
    var other=pp==='D'?'W':'D';
    var ot_el=document.getElementById(other+'-'+d);
    if(ot_el)ot_el.style.display='none';
  }}
}}
function toggleVoc(id){{
  var d=document.getElementById(id),a=document.getElementById('ar-'+id);
  if(!d)return;
  var open=d.style.display!=='none';
  d.style.display=open?'none':'block';
  if(a)a.textContent=open?'▸':'▾';
}}

// ── 지표 서브탭 ────────────────────────────────────────────────
function switchMetricsSub(sub){{
  _sub=sub;
  document.querySelectorAll('.mnav').forEach(b=>b.classList.remove('active'));
  document.getElementById('mnav-'+sub).classList.add('active');
  renderCurrentMetrics();
}}

// ── 헬퍼: 날짜 계산 ───────────────────────────────────────────
function addDays(ds,n){{
  var d=new Date(ds+'T00:00:00');d.setDate(d.getDate()+n);
  return d.toISOString().slice(0,10);
}}
function prevDate(ds){{return addDays(ds,-1);}}
function getWeekRange(ds){{
  var d=new Date(ds+'T00:00:00');
  var dow=d.getDay();
  var sinceT=(dow-4+7)%7;
  var ws=addDays(ds,-sinceT);
  var we=addDays(ws,6);
  return [ws,we];
}}
function getPrevWeekRange(ds){{
  var [ws,]=getWeekRange(ds);
  var pws=addDays(ws,-7);
  return [pws,addDays(pws,6)];
}}
function getMonthRange(ds){{
  var ms=ds.slice(0,7)+'-01';
  var d=new Date(ds.slice(0,7)+'-01T00:00:00');
  d.setMonth(d.getMonth()+1);d.setDate(0);
  return [ms, d.toISOString().slice(0,10)];
}}
function getPrevMonthRange(ds){{
  var [ms,]=getMonthRange(ds);
  var d=new Date(ms+'T00:00:00');d.setMonth(d.getMonth()-1);
  var pms=d.toISOString().slice(0,7)+'-01';
  return getMonthRange(pms);
}}
function datesInRange(start,end){{
  var arr=[], cur=start;
  while(cur<=end){{arr.push(cur);cur=addDays(cur,1);}}
  return arr;
}}
function getLast7(ds){{
  var arr=[];for(var i=6;i>=0;i--)arr.push(addDays(ds,-i));
  return arr;
}}

// ── 헬퍼: 포맷 ────────────────────────────────────────────────
function fmtKRW(n){{
  if(n===null||n===undefined||isNaN(n))return '-';
  if(Math.abs(n)>=1e8)return (n/1e8).toFixed(1)+'억';
  if(Math.abs(n)>=1e4)return Math.round(n/1e4).toLocaleString()+'만';
  return n.toLocaleString();
}}
function fmtKRWFull(n){{
  if(n===null||n===undefined||isNaN(n))return '-';
  return n.toLocaleString()+'원';
}}
function fmtNum(n){{
  if(n===null||n===undefined||isNaN(n))return '-';
  if(Math.abs(n)>=1e4)return Math.round(n/1e4).toFixed(1)+'만';
  return n.toLocaleString();
}}
function fmtPct(n){{
  if(n===null||n===undefined||isNaN(n))return '-';
  return (n*100).toFixed(1)+'%';
}}
function fmtDelta(cur,prev,posGood){{
  if(cur===null||cur===undefined||prev===null||prev===undefined||prev===0) return '';
  var diff=cur-prev, pct=(diff/Math.abs(prev))*100;
  var pos=diff>=0;
  var sym=pos?'▲':'▼';
  var cls=(pos===posGood)?'dg':'dr';
  var absDiff=Math.abs(diff);
  var dStr=absDiff>=1e8?(absDiff/1e8).toFixed(1)+'억':
           absDiff>=1e4?Math.round(absDiff/1e4)+'만':
           absDiff.toLocaleString();
  return '<span class="'+cls+'">'+sym+dStr+' ('+pct.toFixed(1)+'%)</span>';
}}

// ── 집계: 날짜 범위 합산 ──────────────────────────────────────
function aggregateDates(start,end){{
  var r={{
    old:{{rev_total:0,rev_pure:0,dau:0,nu:0,pu:0,npu:0,platform:{{}},_days:[]}},
    hyper:{{rev_total:0,rev_pure:0,dau:0,nu:0,pu:0,npu:0,platform:{{}},_days:[]}},
  }};
  datesInRange(start,end).forEach(function(ds){{
    var d=METRICS_DATA[ds];
    if(!d) return;
    ['old','hyper'].forEach(function(srv){{
      if(!d[srv]) return;
      var s=r[srv],m=d[srv];
      s.rev_total+=m.rev_total||0;
      s.rev_pure +=m.rev_pure||0;
      s.dau+=m.dau||0; s.nu+=m.nu||0;
      s.pu+=m.pu||0;   s.npu+=m.npu||0;
      var pl=m.platform||{{}};
      Object.keys(pl).forEach(function(k){{s.platform[k]=(s.platform[k]||0)+pl[k];}});
      s._days.push({{date:ds,dau:m.dau||0,pu:m.pu||0,npu:m.npu||0,
                     arpu:m.arpu||0,arppu:m.arppu||0,
                     rev_total:m.rev_total||0,rev_pure:m.rev_pure||0}});
    }});
  }});
  ['old','hyper'].forEach(function(srv){{
    var s=r[srv];
    s.pur  = s.dau>0 ? s.pu/s.dau : 0;
    s.arpu = s.dau>0 ? Math.round(s.rev_total/s.dau) : 0;
    s.arppu= s.pu>0  ? Math.round(s.rev_total/s.pu)  : 0;
  }});
  var thuData=METRICS_DATA[start];
  if(thuData&&thuData.week&&thuData.week.week_start===start){{
    if(thuData.week.old) {{r.old.wau=thuData.week.old.wau;r.old.wnu=thuData.week.old.wnu;r.old.wpu=thuData.week.old.wpu;r.old.wnpu=thuData.week.old.wnpu;r.old.wpur=thuData.week.old.wpur;r.old.warpu=thuData.week.old.warpu;r.old.warppu=thuData.week.old.warppu;}}
    if(thuData.week.hyper){{r.hyper.wau=thuData.week.hyper.wau;r.hyper.wnu=thuData.week.hyper.wnu;r.hyper.wpu=thuData.week.hyper.wpu;r.hyper.wnpu=thuData.week.hyper.wnpu;r.hyper.wpur=thuData.week.hyper.wpur;r.hyper.warpu=thuData.week.hyper.warpu;r.hyper.warppu=thuData.week.hyper.warppu;}}
  }}
  var firstData=METRICS_DATA[start];
  if(firstData&&firstData.month&&firstData.month.month===start.slice(0,7)){{
    if(firstData.month.old) {{r.old.mau=firstData.month.old.mau;r.old.mnu=firstData.month.old.mnu;r.old.mpu=firstData.month.old.mpu;r.old.mnpu=firstData.month.old.mnpu;r.old.mpur=firstData.month.old.mpur;r.old.marpu=firstData.month.old.marpu;r.old.marppu=firstData.month.old.marppu;}}
    if(firstData.month.hyper){{r.hyper.mau=firstData.month.hyper.mau;r.hyper.mnu=firstData.month.hyper.mnu;r.hyper.mpu=firstData.month.hyper.mpu;r.hyper.mnpu=firstData.month.hyper.mnpu;r.hyper.mpur=firstData.month.hyper.mpur;r.hyper.marpu=firstData.month.hyper.marpu;r.hyper.marppu=firstData.month.hyper.marppu;}}
  }}
  r.total={{
    rev_total:(r.old.rev_total||0)+(r.hyper.rev_total||0),
    rev_pure :(r.old.rev_pure||0)+(r.hyper.rev_pure||0),
    dau:(r.old.dau||0)+(r.hyper.dau||0),
    nu :(r.old.nu||0)+(r.hyper.nu||0),
    pu :(r.old.pu||0)+(r.hyper.pu||0),
    npu:(r.old.npu||0)+(r.hyper.npu||0),
  }};
  var t=r.total;
  t.pur  = t.dau>0 ? t.pu/t.dau : 0;
  t.arpu = t.dau>0 ? Math.round(t.rev_total/t.dau) : 0;
  t.arppu= t.pu>0  ? Math.round(t.rev_total/t.pu)  : 0;
  return r;
}}

// ── 지표 가져오기 (기간에 맞게) ────────────────────────────────
function getMetrics(dateStr,period){{
  var m, prev, chartDates, label;
  if(period==='D'){{
    var day=METRICS_DATA[dateStr];
    if(!day)return null;
    m={{old:day.old||{{}},hyper:day.hyper||{{}},global:null}};
    m.total={{
      rev_total:(m.old.rev_total||0)+(m.hyper.rev_total||0),
      rev_pure :(m.old.rev_pure||0)+(m.hyper.rev_pure||0),
      dau:(m.old.dau||0)+(m.hyper.dau||0),
      nu :(m.old.nu||0)+(m.hyper.nu||0),
      pu :(m.old.pu||0)+(m.hyper.pu||0),
      npu:(m.old.npu||0)+(m.hyper.npu||0),
    }};
    var t=m.total;
    t.pur=t.dau>0?t.pu/t.dau:0;t.arpu=t.dau>0?Math.round(t.rev_total/t.dau):0;t.arppu=t.pu>0?Math.round(t.rev_total/t.pu):0;
    var pd=METRICS_DATA[prevDate(dateStr)];
    prev={{old:pd?.old||null,hyper:pd?.hyper||null}};
    chartDates=getLast7(dateStr); label=dateStr;
  }} else if(period==='W'){{
    var [ws,we]=getWeekRange(dateStr);
    m=aggregateDates(ws,we);
    var [pws,pwe]=getPrevWeekRange(dateStr);
    prev=aggregateDates(pws,pwe);
    chartDates=datesInRange(ws,we);
    label=ws.slice(5)+'~'+we.slice(5)+' (주간)';
  }} else {{
    var [ms,me]=getMonthRange(dateStr);
    m=aggregateDates(ms,me);
    var [pms,pme]=getPrevMonthRange(dateStr);
    prev=aggregateDates(pms,pme);
    chartDates=datesInRange(ms,me);
    label=dateStr.slice(0,7)+' (월간)';
  }}
  return {{m:m,prev:prev,chartDates:chartDates,label:label}};
}}

// ── 차트 관리 ────────────────────────────────────────────────
function destroyChart(id){{
  if(_charts[id]){{_charts[id].destroy();delete _charts[id];}}
}}
function makeChart(id,type,labels,datasets,opts){{
  destroyChart(id);
  var ctx=document.getElementById(id);
  if(!ctx)return;
  _charts[id]=new Chart(ctx,{{
    type:type,
    data:{{labels:labels,datasets:datasets}},
    options:Object.assign({{responsive:true,maintainAspectRatio:false}},opts)
  }});
}}

// ── 매출 렌더 ───────────────────────────────────────────────
function renderRevenue(dateStr,period){{
  var res=getMetrics(dateStr,period);
  var el=document.getElementById('m-content');
  if(!res){{el.innerHTML='<p class="empty-s" style="padding:40px">해당 날짜 지표 데이터 없음</p>';return;}}
  var {{m,prev,chartDates,label}}=res;
  var isD=period==='D', isW=period==='W';

  var dKey=isD?'dau':isW?'wau':'mau';
  var nKey=isD?'nu':isW?'wnu':'mnu';
  var pKey=isD?'pu':isW?'wpu':'mpu';
  var npKey=isD?'npu':isW?'wnpu':'mnpu';
  var purKey=isD?'pur':isW?'wpur':'mpur';
  var arpuKey=isD?'arpu':isW?'warpu':'marpu';
  var arppuKey=isD?'arppu':isW?'warppu':'marppu';

  var o=m.old||{{}}, h=m.hyper||{{}}, tot=m.total||{{}};
  var po=prev?.old||{{}}, ph=prev?.hyper||{{}};

  var revT=tot.rev_total||0, revP=tot.rev_pure||0;
  var prevRevT=(po.rev_total||0)+(ph.rev_total||0);
  var prevRevP=(po.rev_pure||0)+(ph.rev_pure||0);

  var dau=tot[dKey]||tot.dau||0, nu=tot[nKey]||tot.nu||0;
  var pu=tot[pKey]||tot.pu||0,   npu=tot[npKey]||tot.npu||0;
  var pur=tot[purKey]||tot.pur||0;
  var arpu=tot[arpuKey]||tot.arpu||0;
  var arppu=tot[arppuKey]||tot.arppu||0;
  var prevDau=(po[dKey]||po.dau||0)+(ph[dKey]||ph.dau||0);
  var prevPu=(po[pKey]||po.pu||0)+(ph[pKey]||ph.pu||0);

  var html='<div style="padding:10px 20px 4px"><span style="font-size:12px;color:#5f6368;font-weight:700">📅 '+label+'</span></div>';

  html+='<div class="kpi-row">';
  html+='<div class="kpi-card"><div class="kpi-card-label">총 매출</div>';
  html+='<div class="kpi-card-value">'+fmtKRW(revT)+'원</div>';
  html+='<div class="kpi-card-delta">'+fmtDelta(revT,prevRevT,true)+'</div></div>';
  html+='<div class="kpi-card"><div class="kpi-card-label">순수 유저 매출</div>';
  html+='<div class="kpi-card-value">'+fmtKRW(revP)+'원</div>';
  html+='<div class="kpi-card-delta">'+fmtDelta(revP,prevRevP,true)+'</div></div>';
  html+='</div>';

  html+='<div class="kpi-pills">';
  var pills=[
    ['DAU', dau, prevDau, fmtNum, true],
    ['NU',  nu,  (po.nu||0)+(ph.nu||0), fmtNum, true],
    ['PU',  pu,  prevPu, fmtNum, true],
    ['NPU', npu, (po.npu||0)+(ph.npu||0), fmtNum, true],
    ['PUR', pur, tot.pur||0, fmtPct, true],
    ['ARPU', arpu, (prevDau>0?Math.round(prevRevT/prevDau):0), fmtKRW, true],
    ['ARPPU',arppu,(prevPu>0?Math.round(prevRevT/prevPu):0),   fmtKRW, true],
  ];
  pills.forEach(function(p){{
    html+='<div class="kpi-pill">';
    html+='<div class="kpi-pill-label">'+p[0]+'</div>';
    html+='<div class="kpi-pill-value">'+p[3](p[1])+'</div>';
    html+='<div class="kpi-pill-delta">'+fmtDelta(p[1],p[2],p[4])+'</div>';
    html+='</div>';
  }});
  html+='</div>';

  html+='<div class="m-bar-pair">';
  html+='<div class="m-bar-box"><div class="m-chart-title">총 매출 추이</div><div class="m-chart-wrap"><canvas id="ch-rev-total"></canvas></div></div>';
  html+='<div class="m-bar-box"><div class="m-chart-title">순수 유저 매출 추이</div><div class="m-chart-wrap"><canvas id="ch-rev-pure"></canvas></div></div>';
  html+='</div>';

  html+='<div style="padding:0 20px 6px;font-size:12px;font-weight:700;color:#3c4043">플랫폼별 매출 비중</div>';
  html+='<div class="plat-row">';
  html+=buildPlatBox('구서버', o.platform||{{}});
  html+=buildPlatBox('하이퍼서버', h.platform||{{}});
  html+=buildPlatBox('글로벌서버 (미오픈)', null);
  html+='</div>';

  html+='<div style="padding:0 20px 16px">';
  html+='<div style="font-size:12px;font-weight:700;color:#3c4043;margin-bottom:8px">서버별 매출 집계</div>';
  html+='<table class="m-tbl"><thead><tr><th style="text-align:left">구분</th><th>구서버</th><th>하이퍼서버</th><th>글로벌서버</th><th>합계</th></tr></thead><tbody>';
  html+='<tr><td>총매출</td><td>'+fmtKRW(o.rev_total)+'원</td><td>'+fmtKRW(h.rev_total)+'원</td><td class="m-global">미오픈</td><td>'+ fmtKRW(revT)+'원</td></tr>';
  html+='<tr><td>순수유저매출</td><td>'+fmtKRW(o.rev_pure)+'원</td><td>'+fmtKRW(h.rev_pure)+'원</td><td class="m-global">미오픈</td><td>'+fmtKRW(revP)+'원</td></tr>';
  html+='</tbody></table></div>';

  el.innerHTML=html;

  var labels=chartDates.map(function(d){{return d.slice(5);}});
  makeChart('ch-rev-total','bar',labels,[
    {{label:'구서버',   data:chartDates.map(function(d){{return METRICS_DATA[d]?.old?.rev_total||0;}}), backgroundColor:'rgba(26,115,232,.75)',stack:'s'}},
    {{label:'하이퍼서버',data:chartDates.map(function(d){{return METRICS_DATA[d]?.hyper?.rev_total||0;}}),backgroundColor:'rgba(52,168,83,.75)',stack:'s'}},
  ],{{plugins:{{legend:{{position:'top',labels:{{font:{{size:10}},boxWidth:10}}}},tooltip:{{mode:'index',intersect:false}}}},scales:{{x:{{stacked:true,ticks:{{font:{{size:10}}}},grid:{{display:false}}}},y:{{stacked:true,beginAtZero:true,ticks:{{font:{{size:10}},callback:function(v){{return v>=1e8?(v/1e8).toFixed(0)+'억':v>=1e4?(v/1e4).toFixed(0)+'만':v;}}}}}}}}}});
  makeChart('ch-rev-pure','bar',labels,[
    {{label:'구서버',    data:chartDates.map(function(d){{return METRICS_DATA[d]?.old?.rev_pure||0;}}),   backgroundColor:'rgba(26,115,232,.65)',stack:'s'}},
    {{label:'하이퍼서버',data:chartDates.map(function(d){{return METRICS_DATA[d]?.hyper?.rev_pure||0;}}), backgroundColor:'rgba(52,168,83,.65)', stack:'s'}},
  ],{{plugins:{{legend:{{position:'top',labels:{{font:{{size:10}},boxWidth:10}}}},tooltip:{{mode:'index',intersect:false}}}},scales:{{x:{{stacked:true,ticks:{{font:{{size:10}}}},grid:{{display:false}}}},y:{{stacked:true,beginAtZero:true,ticks:{{font:{{size:10}},callback:function(v){{return v>=1e8?(v/1e8).toFixed(0)+'억':v>=1e4?(v/1e4).toFixed(0)+'만':v;}}}}}}}}}});

  renderPieChart('pie-old',  o.platform||{{}});
  renderPieChart('pie-hyper',h.platform||{{}});
}}

function buildPlatBox(title, platform){{
  var inner;
  if(!platform){{
    inner='<div style="padding:20px;font-size:11px;color:#9aa0a6;font-style:italic">미오픈</div>';
  }}else{{
    inner='<div class="plat-chart-wrap"><canvas id="pie-'+title.slice(0,4)+'"></canvas></div>';
  }}
  return '<div class="plat-box"><div class="plat-title">'+title+'</div>'+inner+'</div>';
}}
function renderPieChart(id,platform){{
  destroyChart(id);
  var ctx=document.getElementById(id);
  if(!ctx||!platform) return;
  var keys=Object.keys(platform).filter(function(k){{return platform[k]>0;}});
  if(!keys.length) return;
  var colors=['#4285f4','#34a853','#fbbc04','#ea4335','#9aa0a6','#46bdc6'];
  _charts[id]=new Chart(ctx,{{
    type:'doughnut',
    data:{{
      labels:keys,
      datasets:[{{data:keys.map(function(k){{return platform[k]||0;}}),backgroundColor:colors.slice(0,keys.length),borderWidth:1}}]
    }},
    options:{{responsive:true,maintainAspectRatio:false,
              plugins:{{legend:{{position:'bottom',labels:{{font:{{size:9}},boxWidth:8,padding:4}}}},
                        tooltip:{{callbacks:{{label:function(c){{
                          var total=c.dataset.data.reduce(function(a,b){{return a+b;}},0);
                          return c.label+': '+(c.parsed/total*100).toFixed(1)+'%';
                        }}}}}}}}}}
  }});
}}

// ── 패키지 렌더 ─────────────────────────────────────────────
function renderPackages(dateStr,period){{
  var el=document.getElementById('m-content');
  var day=METRICS_DATA[dateStr];
  var todayOld   = day?.pkg_old   || [];
  var todayHyper = day?.pkg_hyper || [];
  var totalOld   = PKG_TOTALS.old   || [];
  var totalHyper = PKG_TOTALS.hyper || [];
  var label=period==='D'?dateStr:period==='W'?'주간':dateStr.slice(0,7)+' 월간';
  var html='<div style="padding:10px 20px 4px"><span style="font-size:12px;color:#5f6368;font-weight:700">📦 패키지 판매 현황 — '+label+'</span></div>';
  html+='<div class="pkg-cols">';
  html+=buildPkgCol('구서버',    totalOld,   todayOld);
  html+=buildPkgCol('하이퍼서버',totalHyper, todayHyper);
  html+=buildPkgCol('글로벌서버 (미오픈)', null, null);
  html+='</div>';
  el.innerHTML=html;
}}
function buildPkgCol(title,totalList,todayList){{
  var hd='<div class="pkg-col-hd">'+title+'</div>';
  if(!totalList && !todayList){{
    return '<div class="pkg-col">'+hd+'<div class="pkg-empty">서비스 미오픈</div></div>';
  }}
  var inner='<div class="pkg-inner">';
  inner+='<div><div class="pkg-sub-hd">전체기간 TOP</div>'+buildPkgList(totalList||[])+'</div>';
  inner+='<div><div class="pkg-sub-hd">당일 TOP</div>'+buildPkgList(todayList||[])+'</div>';
  inner+='</div>';
  return '<div class="pkg-col">'+hd+inner+'</div>';
}}
function buildPkgList(list){{
  if(!list.length) return '<div class="pkg-empty">데이터 없음</div>';
  return list.slice(0,10).map(function(item,i){{
    var rankCls='pkg-rank'+(i<3?' pkg-rank-'+(i+1):'');
    return '<div class="pkg-row"><span class="'+rankCls+'">'+(i+1)+'</span><span class="pkg-name" title="'+item.name+'">'+item.name+'</span><span class="pkg-qty">'+item.qty.toLocaleString()+'</span></div>';
  }}).join('');
}}

// ── 유저지표 렌더 ───────────────────────────────────────────
function renderUsers(dateStr,period){{
  var res=getMetrics(dateStr,period);
  var el=document.getElementById('m-content');
  if(!res){{el.innerHTML='<p class="empty-s" style="padding:40px">해당 날짜 지표 데이터 없음</p>';return;}}
  var {{m,prev,chartDates,label}}=res;
  var isD=period==='D', isW=period==='W';
  var dKey=isD?'dau':isW?'wau':'mau';
  var nKey=isD?'nu':isW?'wnu':'mnu';
  var pKey=isD?'pu':isW?'wpu':'mpu';
  var npKey=isD?'npu':isW?'wnpu':'mnpu';
  var purKey=isD?'pur':isW?'wpur':'mpur';
  var arpuKey=isD?'arpu':isW?'warpu':'marpu';
  var arppuKey=isD?'arppu':isW?'warppu':'marppu';

  var html='<div style="padding:10px 20px 4px"><span style="font-size:12px;color:#5f6368;font-weight:700">👤 유저 지표 — '+label+'</span></div>';
  html+='<div class="m-chart-grid">';
  html+='<div class="m-chart-box"><div class="m-chart-title">DAU</div><div class="m-chart-wrap"><canvas id="ch-dau"></canvas></div></div>';
  html+='<div class="m-chart-box"><div class="m-chart-title">PU</div><div class="m-chart-wrap"><canvas id="ch-pu"></canvas></div></div>';
  html+='<div class="m-chart-box"><div class="m-chart-title">NPU</div><div class="m-chart-wrap"><canvas id="ch-npu"></canvas></div></div>';
  html+='<div class="m-chart-box"><div class="m-chart-title">ARPPU</div><div class="m-chart-wrap"><canvas id="ch-arppu"></canvas></div></div>';
  html+='</div>';

  function row(srvLabel, srv, na){{
    if(na) return '<tr><td>'+srvLabel+'</td><td colspan="7" class="m-global">미오픈</td></tr>';
    if(!srv) return '<tr><td>'+srvLabel+'</td><td colspan="7" class="m-na">-</td></tr>';
    return '<tr><td>'+srvLabel+'</td>'+
      '<td>'+fmtNum(srv[dKey]||srv.dau)+'</td>'+
      '<td>'+fmtNum(srv[nKey]||srv.nu)+'</td>'+
      '<td>'+fmtNum(srv[pKey]||srv.pu)+'</td>'+
      '<td>'+fmtNum(srv[npKey]||srv.npu)+'</td>'+
      '<td>'+fmtPct(srv[purKey]||srv.pur)+'</td>'+
      '<td>'+fmtKRW(srv[arpuKey]||srv.arpu)+'</td>'+
      '<td>'+fmtKRW(srv[arppuKey]||srv.arppu)+'</td>'+
      '</tr>';
  }}
  html+='<div style="padding:0 20px 16px">';
  html+='<div style="font-size:12px;font-weight:700;color:#3c4043;margin-bottom:8px">서버별 유저 지표</div>';
  html+='<table class="m-tbl"><thead><tr>';
  html+='<th style="text-align:left">구분</th><th>DAU</th><th>NU</th><th>PU</th><th>NPU</th><th>PUR</th><th>ARPU</th><th>ARPPU</th>';
  html+='</tr></thead><tbody>';
  html+=row('구서버',    m.old,   false);
  html+=row('하이퍼서버',m.hyper, false);
  html+=row('글로벌서버',null,    true);
  html+=row('합계',      m.total, false);
  html+='</tbody></table></div>';

  el.innerHTML=html;

  var labels=chartDates.map(function(d){{return d.slice(5);}});
  var chartCfg={{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{position:'top',labels:{{font:{{size:10}},boxWidth:10}}}}}},scales:{{x:{{ticks:{{font:{{size:10}}}},grid:{{display:false}}}},y:{{beginAtZero:true,ticks:{{font:{{size:10}}}}}}}}}};

  makeChart('ch-dau','line',labels,[
    {{label:'구서버',   data:chartDates.map(function(d){{return METRICS_DATA[d]?.old?.dau||0;}}),   borderColor:'#4285f4',backgroundColor:'rgba(66,133,244,.1)',tension:.3,fill:true}},
    {{label:'하이퍼서버',data:chartDates.map(function(d){{return METRICS_DATA[d]?.hyper?.dau||0;}}),borderColor:'#34a853',backgroundColor:'rgba(52,168,83,.1)', tension:.3,fill:true}},
  ],chartCfg);
  makeChart('ch-pu','line',labels,[
    {{label:'구서버',   data:chartDates.map(function(d){{return METRICS_DATA[d]?.old?.pu||0;}}),    borderColor:'#4285f4',backgroundColor:'rgba(66,133,244,.1)',tension:.3,fill:true}},
    {{label:'하이퍼서버',data:chartDates.map(function(d){{return METRICS_DATA[d]?.hyper?.pu||0;}}),borderColor:'#34a853',backgroundColor:'rgba(52,168,83,.1)', tension:.3,fill:true}},
  ],chartCfg);
  makeChart('ch-npu','line',labels,[
    {{label:'구서버',   data:chartDates.map(function(d){{return METRICS_DATA[d]?.old?.npu||0;}}),    borderColor:'#fbbc04',backgroundColor:'rgba(251,188,4,.1)',tension:.3,fill:true}},
    {{label:'하이퍼서버',data:chartDates.map(function(d){{return METRICS_DATA[d]?.hyper?.npu||0;}}),borderColor:'#ea4335',backgroundColor:'rgba(234,67,53,.1)',tension:.3,fill:true}},
  ],chartCfg);
  makeChart('ch-arppu','line',labels,[
    {{label:'구서버',   data:chartDates.map(function(d){{return METRICS_DATA[d]?.old?.arppu||0;}}),    borderColor:'#4285f4',backgroundColor:'rgba(66,133,244,.1)',tension:.3,fill:true}},
    {{label:'하이퍼서버',data:chartDates.map(function(d){{return METRICS_DATA[d]?.hyper?.arppu||0;}}),borderColor:'#34a853',backgroundColor:'rgba(52,168,83,.1)', tension:.3,fill:true}},
  ],chartCfg);
}}

// ── 메인 렌더 진입점 ─────────────────────────────────────────
function renderCurrentMetrics(){{
  if(_sub==='revenue')  renderRevenue(_date,_period);
  else if(_sub==='packages') renderPackages(_date,_period);
  else                  renderUsers(_date,_period);
}}
</script>
</body>
</html>"""

    OUTPUT.write_text(html, encoding="utf-8")
    print(f"[DONE] 대시보드 v5.2 생성: {OUTPUT}")


if __name__ == "__main__":
    generate()
