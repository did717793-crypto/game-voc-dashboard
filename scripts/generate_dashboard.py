#!/usr/bin/env python3
"""
VOC 대시보드 HTML 생성기 v1.0
- JSON 크롤링 데이터를 읽어 인터랙티브 HTML 대시보드 생성
- 일간(24h) / 주간(7일) 탭
- 게임 탭: DKR → 추후 COCW / 베르시온 확장
"""

import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
SCRIPT_DIR = Path(__file__).parent
DATA_BASE = SCRIPT_DIR.parent / "data"
OUTPUT_FILE = SCRIPT_DIR.parent / "dashboard.html"

GAMES = {
    "DKR": {
        "label": "DK모바일:리본",
        "color": "#1a73e8",
        "data_dir": DATA_BASE / "DKR",
    },
    # 추후 추가
    # "COCW": {"label": "CoC: Assemble", "color": "#e84315", "data_dir": DATA_BASE / "COCW"},
    # "VER": {"label": "베르시온", "color": "#2e7d32", "data_dir": DATA_BASE / "VER"},
}

# 불용어 (키워드 분석에서 제외)
STOPWORDS = {
    "이", "가", "은", "는", "을", "를", "의", "에", "도", "와", "과",
    "로", "으로", "에서", "하다", "있다", "없다", "그", "이거", "저",
    "합니다", "입니다", "합니까", "했습니다", "하는", "되는", "안",
    "좀", "너무", "정말", "진짜", "그냥", "왜", "뭐", "어", "아",
    "게임", "서버", "유저", "님", "분", "것", "수", "더", "잘",
}


def load_daily_data(game_key: str, date_str: str) -> dict | None:
    """특정 날짜의 크롤링 JSON 로드"""
    path = GAMES[game_key]["data_dir"] / f"{date_str}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_available_dates(game_key: str) -> list[str]:
    """수집된 날짜 목록 (최신순)"""
    d = GAMES[game_key]["data_dir"]
    if not d.exists():
        return []
    files = sorted(d.glob("*.json"), reverse=True)
    return [f.stem for f in files]


def extract_keywords(texts: list[str], top_n: int = 20) -> list[tuple[str, int]]:
    """텍스트 목록에서 주요 키워드 추출"""
    words = []
    for text in texts:
        # 한글 2글자 이상 단어 추출
        found = re.findall(r"[가-힣]{2,}", text)
        words.extend([w for w in found if w not in STOPWORDS and len(w) >= 2])
    counter = Counter(words)
    return counter.most_common(top_n)


def simple_sentiment(text: str) -> str:
    """단순 감성 분류 (긍/부/중)"""
    pos = ["좋", "감사", "재밌", "최고", "훌륭", "기대", "완벽", "만족", "추천", "업데이트", "개선"]
    neg = ["버그", "오류", "망", "최악", "환불", "실망", "문제", "불편", "답답", "서버다운", "렉", "끊김", "사기", "삭제"]
    score = 0
    for w in pos:
        if w in text:
            score += 1
    for w in neg:
        if w in text:
            score -= 1
    if score > 0:
        return "pos"
    elif score < 0:
        return "neg"
    return "neu"


def aggregate_data(game_key: str, dates: list[str]) -> dict:
    """여러 날짜 데이터 통합 분석"""
    all_posts = []
    all_texts = []
    sentiment_counts = {"pos": 0, "neg": 0, "neu": 0}

    for d in dates:
        data = load_daily_data(game_key, d)
        if not data:
            continue
        for post in data.get("posts", []):
            post["_date"] = d
            all_posts.append(post)
            full_text = post.get("title", "") + " " + post.get("body", "")
            for c in post.get("comments", []):
                full_text += " " + c.get("text", "")
            all_texts.append(full_text)
            sentiment_counts[simple_sentiment(full_text)] += 1

    # 인기 게시물 (조회수 + 댓글 수 기준)
    top_posts = sorted(
        all_posts,
        key=lambda p: p.get("view_count", 0) + p.get("comment_count", 0) * 3,
        reverse=True,
    )[:10]

    # 키워드
    keywords = extract_keywords([p.get("title", "") for p in all_posts])

    total = sum(sentiment_counts.values()) or 1
    sentiment_pct = {
        k: round(v / total * 100, 1) for k, v in sentiment_counts.items()
    }

    return {
        "total_posts": len(all_posts),
        "total_comments": sum(len(p.get("comments", [])) for p in all_posts),
        "top_posts": top_posts,
        "keywords": keywords,
        "sentiment": sentiment_counts,
        "sentiment_pct": sentiment_pct,
    }


def build_posts_table(posts: list[dict]) -> str:
    """게시물 테이블 HTML"""
    if not posts:
        return "<p class='empty'>수집된 게시물이 없습니다.</p>"

    rows = ""
    for p in posts:
        title = p.get("title", "")[:50]
        author = p.get("author", "-")
        views = p.get("view_count", 0)
        comments = p.get("comment_count", 0)
        date = p.get("date", p.get("date_str", "-"))
        if date and "T" in str(date):
            date = date[:10]
        url = p.get("url", "#")
        rows += f"""
        <tr>
          <td><a href="{url}" target="_blank" class="post-link">{title}</a></td>
          <td>{author}</td>
          <td class="num">{views:,}</td>
          <td class="num">{comments:,}</td>
          <td>{date}</td>
        </tr>"""

    return f"""
    <table class="posts-table">
      <thead>
        <tr><th>제목</th><th>작성자</th><th>조회</th><th>댓글</th><th>날짜</th></tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


def build_keyword_badges(keywords: list[tuple[str, int]]) -> str:
    """키워드 뱃지 HTML"""
    if not keywords:
        return "<p class='empty'>키워드 데이터 없음</p>"
    max_count = keywords[0][1] if keywords else 1
    badges = ""
    for word, count in keywords:
        size = 12 + int((count / max_count) * 14)
        opacity = 0.5 + (count / max_count) * 0.5
        badges += f'<span class="keyword-badge" style="font-size:{size}px;opacity:{opacity}">{word} <small>({count})</small></span>'
    return f'<div class="keyword-cloud">{badges}</div>'


def build_sentiment_bar(sentiment_pct: dict) -> str:
    """감성 비율 바 HTML"""
    pos = sentiment_pct.get("pos", 0)
    neg = sentiment_pct.get("neg", 0)
    neu = sentiment_pct.get("neu", 0)
    return f"""
    <div class="sentiment-bar-wrap">
      <div class="sentiment-bar">
        <div class="seg pos" style="width:{pos}%" title="긍정 {pos}%"></div>
        <div class="seg neu" style="width:{neu}%" title="중립 {neu}%"></div>
        <div class="seg neg" style="width:{neg}%" title="부정 {neg}%"></div>
      </div>
      <div class="sentiment-legend">
        <span class="dot pos"></span>긍정 {pos}%
        <span class="dot neu"></span>중립 {neu}%
        <span class="dot neg"></span>부정 {neg}%
      </div>
    </div>"""


def build_game_panel(game_key: str) -> str:
    """게임별 패널 HTML (일간/주간 서브탭)"""
    game = GAMES[game_key]
    dates = get_available_dates(game_key)
    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    if not dates:
        latest = (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")
        return f"""
        <div class="no-data">
          <p>📭 아직 수집된 데이터가 없습니다.</p>
          <p class="hint">크롤러 첫 실행 후 데이터가 쌓이면 여기에 표시됩니다.</p>
          <p class="hint">기대 파일: <code>data/{game_key}/{latest}.json</code></p>
        </div>"""

    # 일간: 최신 날짜
    latest_date = dates[0]
    daily = aggregate_data(game_key, [latest_date])

    # 주간: 최근 7일
    weekly_dates = dates[:7]
    weekly = aggregate_data(game_key, weekly_dates)
    weekly_range = f"{weekly_dates[-1]} ~ {weekly_dates[0]}" if len(weekly_dates) > 1 else weekly_dates[0]

    panel_id = game_key.lower()

    return f"""
    <div class="subtab-nav">
      <button class="subtab-btn active" onclick="switchSubtab('{panel_id}', 'daily', this)">
        📅 일간 <span class="badge">{latest_date}</span>
      </button>
      <button class="subtab-btn" onclick="switchSubtab('{panel_id}', 'weekly', this)">
        📆 주간 <span class="badge">{len(weekly_dates)}일</span>
      </button>
    </div>

    <!-- 일간 -->
    <div id="{panel_id}-daily" class="subtab-content active">
      <div class="stats-row">
        <div class="stat-card">
          <div class="stat-num">{daily['total_posts']:,}</div>
          <div class="stat-label">게시물</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">{daily['total_comments']:,}</div>
          <div class="stat-label">댓글</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">{daily['sentiment_pct'].get('pos', 0)}%</div>
          <div class="stat-label">긍정 비율</div>
        </div>
        <div class="stat-card neg-card">
          <div class="stat-num">{daily['sentiment_pct'].get('neg', 0)}%</div>
          <div class="stat-label">부정 비율</div>
        </div>
      </div>

      <div class="section-title">감성 분포</div>
      {build_sentiment_bar(daily['sentiment_pct'])}

      <div class="section-title">주요 키워드</div>
      {build_keyword_badges(daily['keywords'])}

      <div class="section-title">인기 게시물 TOP 10</div>
      {build_posts_table(daily['top_posts'])}
    </div>

    <!-- 주간 -->
    <div id="{panel_id}-weekly" class="subtab-content">
      <div class="period-label">📊 수집 기간: {weekly_range}</div>
      <div class="stats-row">
        <div class="stat-card">
          <div class="stat-num">{weekly['total_posts']:,}</div>
          <div class="stat-label">게시물</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">{weekly['total_comments']:,}</div>
          <div class="stat-label">댓글</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">{weekly['sentiment_pct'].get('pos', 0)}%</div>
          <div class="stat-label">긍정 비율</div>
        </div>
        <div class="stat-card neg-card">
          <div class="stat-num">{weekly['sentiment_pct'].get('neg', 0)}%</div>
          <div class="stat-label">부정 비율</div>
        </div>
      </div>

      <div class="section-title">감성 분포</div>
      {build_sentiment_bar(weekly['sentiment_pct'])}

      <div class="section-title">주요 키워드 (7일 누적)</div>
      {build_keyword_badges(weekly['keywords'])}

      <div class="section-title">인기 게시물 TOP 10 (7일)</div>
      {build_posts_table(weekly['top_posts'])}
    </div>

    <div class="updated-at">마지막 업데이트: {now_kst}</div>
    """


def generate_html() -> str:
    """전체 대시보드 HTML 생성"""
    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    # 게임 탭 버튼
    tab_buttons = ""
    tab_panels = ""
    first = True
    for game_key, game in GAMES.items():
        active = "active" if first else ""
        tab_buttons += f"""
        <button class="tab-btn {active}" onclick="switchTab('{game_key}', this)">
          <span class="tab-dot" style="background:{game['color']}"></span>
          {game['label']}
        </button>"""
        tab_panels += f"""
        <div id="tab-{game_key}" class="tab-panel {active}">
          {build_game_panel(game_key)}
        </div>"""
        first = False

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NTRANCE VOC 대시보드</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Malgun Gothic", "Apple SD Gothic Neo", sans-serif;
    background: #f0f2f5;
    color: #1a1a2e;
    min-height: 100vh;
  }}
  .header {{
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    color: white;
    padding: 20px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    box-shadow: 0 2px 12px rgba(0,0,0,0.3);
  }}
  .header h1 {{ font-size: 20px; font-weight: 700; letter-spacing: -0.3px; }}
  .header .subtitle {{ font-size: 12px; color: #8892b0; margin-top: 3px; }}
  .header .updated {{ font-size: 11px; color: #8892b0; }}
  .main {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px; }}

  /* 게임 탭 */
  .tab-nav {{
    display: flex;
    gap: 8px;
    margin-bottom: 20px;
    flex-wrap: wrap;
  }}
  .tab-btn {{
    padding: 10px 20px;
    border: 2px solid #dde1e7;
    border-radius: 8px;
    background: white;
    cursor: pointer;
    font-size: 14px;
    font-weight: 600;
    color: #5f6368;
    transition: all 0.2s;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .tab-btn:hover {{ border-color: #1a73e8; color: #1a73e8; }}
  .tab-btn.active {{ background: #1a73e8; border-color: #1a73e8; color: white; }}
  .tab-dot {{ width: 8px; height: 8px; border-radius: 50%; }}
  .tab-panel {{ display: none; }}
  .tab-panel.active {{ display: block; }}

  /* 카드 */
  .panel-card {{
    background: white;
    border-radius: 12px;
    padding: 24px;
    box-shadow: 0 1px 6px rgba(0,0,0,0.08);
  }}

  /* 서브탭 */
  .subtab-nav {{ display: flex; gap: 6px; margin-bottom: 20px; }}
  .subtab-btn {{
    padding: 8px 18px;
    border: 1.5px solid #dde1e7;
    border-radius: 6px;
    background: white;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
    color: #5f6368;
    transition: all 0.2s;
  }}
  .subtab-btn.active {{ background: #e8f0fe; border-color: #1a73e8; color: #1a73e8; }}
  .subtab-content {{ display: none; }}
  .subtab-content.active {{ display: block; }}
  .badge {{
    background: #e8f0fe;
    color: #1a73e8;
    font-size: 11px;
    padding: 2px 6px;
    border-radius: 4px;
    margin-left: 4px;
  }}
  .subtab-btn.active .badge {{ background: white; }}

  /* 통계 카드 */
  .stats-row {{ display: flex; gap: 12px; margin-bottom: 24px; flex-wrap: wrap; }}
  .stat-card {{
    flex: 1;
    min-width: 100px;
    background: #f8f9fa;
    border-radius: 10px;
    padding: 16px;
    text-align: center;
    border: 1.5px solid #e8eaed;
  }}
  .stat-card.neg-card {{ border-color: #fce8e6; background: #fef9f9; }}
  .stat-num {{ font-size: 26px; font-weight: 800; color: #1a73e8; }}
  .neg-card .stat-num {{ color: #d93025; }}
  .stat-label {{ font-size: 12px; color: #5f6368; margin-top: 4px; }}

  /* 섹션 */
  .section-title {{
    font-size: 14px;
    font-weight: 700;
    color: #3c4043;
    margin: 20px 0 10px;
    padding-left: 8px;
    border-left: 3px solid #1a73e8;
  }}

  /* 감성 바 */
  .sentiment-bar-wrap {{ margin-bottom: 8px; }}
  .sentiment-bar {{
    display: flex;
    height: 20px;
    border-radius: 10px;
    overflow: hidden;
    background: #f1f3f4;
  }}
  .seg {{ transition: width 0.5s; }}
  .seg.pos {{ background: #34a853; }}
  .seg.neu {{ background: #fbbc04; }}
  .seg.neg {{ background: #ea4335; }}
  .sentiment-legend {{ display: flex; gap: 16px; font-size: 12px; color: #5f6368; margin-top: 8px; }}
  .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }}
  .dot.pos {{ background: #34a853; }}
  .dot.neu {{ background: #fbbc04; }}
  .dot.neg {{ background: #ea4335; }}

  /* 키워드 클라우드 */
  .keyword-cloud {{ display: flex; flex-wrap: wrap; gap: 8px; padding: 12px; background: #f8f9fa; border-radius: 8px; }}
  .keyword-badge {{
    background: white;
    border: 1px solid #e8eaed;
    border-radius: 6px;
    padding: 4px 10px;
    color: #1a73e8;
    font-weight: 600;
    cursor: default;
    transition: background 0.15s;
  }}
  .keyword-badge:hover {{ background: #e8f0fe; }}
  .keyword-badge small {{ color: #9aa0a6; font-size: 0.75em; }}

  /* 게시물 테이블 */
  .posts-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  .posts-table th {{
    background: #f1f3f4;
    padding: 8px 10px;
    text-align: left;
    font-size: 12px;
    color: #5f6368;
    border-bottom: 1.5px solid #e8eaed;
  }}
  .posts-table td {{
    padding: 9px 10px;
    border-bottom: 1px solid #f1f3f4;
    vertical-align: middle;
  }}
  .posts-table tr:hover td {{ background: #f8f9fa; }}
  .post-link {{ color: #1a1a2e; text-decoration: none; }}
  .post-link:hover {{ color: #1a73e8; text-decoration: underline; }}
  .num {{ text-align: right; color: #5f6368; font-variant-numeric: tabular-nums; }}

  /* 기타 */
  .period-label {{ font-size: 12px; color: #5f6368; margin-bottom: 16px; background: #f8f9fa; padding: 8px 12px; border-radius: 6px; }}
  .updated-at {{ font-size: 11px; color: #9aa0a6; text-align: right; margin-top: 20px; }}
  .empty {{ color: #9aa0a6; font-size: 13px; padding: 20px; text-align: center; }}
  .no-data {{
    text-align: center;
    padding: 60px 20px;
    color: #5f6368;
    background: #f8f9fa;
    border-radius: 10px;
  }}
  .no-data p {{ margin-bottom: 8px; }}
  .hint {{ font-size: 12px; color: #9aa0a6; }}
  code {{ background: #f1f3f4; padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>📊 NTRANCE VOC 대시보드</h1>
    <div class="subtitle">네이버 라운지 유저 동향 자동 수집 · 분석</div>
  </div>
  <div class="updated">생성: {now_kst}</div>
</div>

<div class="main">
  <div class="tab-nav">
    {tab_buttons}
  </div>

  <div class="panel-card">
    {tab_panels}
  </div>
</div>

<script>
function switchTab(gameKey, btn) {{
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tab-' + gameKey).classList.add('active');
}}

function switchSubtab(panelId, subtab, btn) {{
  const panel = btn.closest('.tab-panel');
  panel.querySelectorAll('.subtab-btn').forEach(b => b.classList.remove('active'));
  panel.querySelectorAll('.subtab-content').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById(panelId + '-' + subtab).classList.add('active');
}}
</script>
</body>
</html>"""


def main():
    html = generate_html()
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[DONE] 대시보드 생성 완료: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
