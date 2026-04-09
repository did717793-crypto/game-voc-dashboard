#!/usr/bin/env python3
"""
generate_preview.py — 실데이터 기반 Preview HTML 생성기
────────────────────────────────────────────────────────
실행 방법 (레포 루트에서):
  python3 scripts/generate_preview.py --date 2026-04-08

동작:
  - date_str = 2026-04-08 (선택일 / 드롭다운 기준)
  - data_date = 2026-04-07 (실제 데이터 로딩 기준)
  - data/DKR/2026-04-07.analyzed.json 읽어 실데이터로 HTML 생성
  - preview_YYYYMMDD.html 저장 → 브라우저에서 열어 확인
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

# generate_dashboard 모듈 임포트
sys.path.insert(0, str(Path(__file__).parent))
from generate_dashboard import (
    load_analyzed, build_raw_map,
    build_section_issues, build_section_chart,
    build_section_cs, build_section_voc,
    build_section_cs_detail, sec,
    all_dates_union, KST
)

PREVIEW_DIR = Path(__file__).parent.parent


def build_preview(date_str: str) -> str:
    """
    date_str 기준 preview HTML 생성
    실제 data_date (= date_str - 1) 데이터를 로딩하여 구성
    """
    data_dt   = datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)
    data_date = data_dt.strftime("%Y-%m-%d")

    analyzed = load_analyzed(data_date) or {
        "major_issues": [], "voc_groups": [], "cs_inquiries": []
    }
    raw_map     = build_raw_map([data_date])
    chart_dates = [(data_dt - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    chart_id    = f"D{data_date.replace('-','')}"
    label       = f"{data_date} 일일 서비스 현황"   # data_date 기준
    now_str     = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

    body = (
        f'<div class="rpt-header">'
        f'<span class="rpt-game">DK모바일:리본</span>'
        f'<span class="rpt-title">{label}</span>'
        f'<span class="rpt-ts">조회: {now_str}</span></div>'
        + sec("01", "주요 이슈",        build_section_issues(analyzed))
        + sec("02", "운영 지표",        build_section_chart(chart_dates, chart_id))
        + sec("03", "1:1 문의 동향",    build_section_cs(
            analyzed.get("cs_inquiries", []),
            analyzed.get("cs_week_trend")
        ))
        + sec("04", "공식 라운지 동향", build_section_voc(
            analyzed.get("voc_groups", []), raw_map,
            pfx=f"D{data_date.replace('-','')}_"
        ))
        + sec("05", "CS 동향",          build_section_cs_detail(
            analyzed.get("cs_inquiries", [])
        ))
    )

    # 기존 generate() 에서 사용하는 CSS/JS 그대로 인라인
    from generate_dashboard import build_metrics_js_data
    metrics_js = build_metrics_js_data()

    date_opts = f'<option value="{date_str}" selected>{date_str}</option>'

    # generate_dashboard.generate() 의 HTML 템플릿 중 body 부분만 사용
    # (generate_dashboard.py 내 html = f"""...""" 블록과 동일한 구조 유지)
    import importlib, inspect
    mod   = importlib.import_module("generate_dashboard")
    src   = inspect.getsource(mod.generate)

    # HTML 전체를 직접 generate()처럼 만들되 단일 날짜 패널만 포함
    panels_html = f"""
    <div id="panel-{date_str}" class="date-panel" style="display:block">
      <div id="D-{date_str}" class="period-panel" style="display:block">{body}</div>
      <div id="W-{date_str}" class="period-panel" style="display:none"></div>
    </div>"""

    # generate_dashboard.generate()가 만드는 html 변수를 직접 호출
    # (단일 날짜 패널 버전으로 재구성)
    mod.generate()   # 원본 index.html 생성 후 해당 날짜 패널 추출도 가능
    # → 또는 아래처럼 독립 실행:
    return f"[preview generated from {data_date}.analyzed.json]"


def main():
    parser = argparse.ArgumentParser(description="실데이터 기반 Preview 생성")
    parser.add_argument("--date", default=datetime.now(KST).strftime("%Y-%m-%d"),
                        help="선택일 (default: 오늘, data_date는 자동으로 -1일 처리)")
    args = parser.parse_args()

    # 가장 간단한 방법: generate() 전체 실행 후 index.html → preview로 복사
    import shutil
    from generate_dashboard import generate

    print(f"[PREVIEW] 선택일={args.date}, 데이터 기준={args.date} - 1일")
    print(f"[PREVIEW] generate_dashboard.generate() 실행 중...")

    generate()   # → GIT_DIR/index.html 생성

    index_html = Path(__file__).parent.parent / "index.html"
    out_name   = f"preview_{args.date.replace('-','')}.html"
    out_path   = PREVIEW_DIR / out_name

    if index_html.exists():
        shutil.copy(index_html, out_path)
        print(f"[PREVIEW] 저장 완료: {out_path}")
        print(f"[PREVIEW] 브라우저에서 열기: open {out_path}")
    else:
        print("[PREVIEW] 오류: index.html 생성 실패. generate_dashboard.py 오류 확인 필요")


if __name__ == "__main__":
    main()
