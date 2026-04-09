#!/usr/bin/env python3
"""
analyze_voc.py — DKR 커뮤니티 VOC 규칙 기반 분석기 v1.0
────────────────────────────────────────────────────────
입력:  data/DKR/YYYY-MM-DD.json       (crawl_dkr.py 출력)
출력:  data/DKR/YYYY-MM-DD.analyzed.json

생성 필드:
  1. major_issues   — official_posts (공지/업데이트) 기반
  2. voc_groups     — user posts 규칙 기반 category 분류
  3. cs_inquiries   — [] (빈 배열 / CS 자동화 2차에서 구현)
  4. cs_week_trend  — 최근 7일 0값 기본 틀

사용법:
  python3 analyze_voc.py 2026-04-06            # 특정 날짜
  python3 analyze_voc.py                        # 어제 기준 자동
  python3 analyze_voc.py 2026-04-06 --force    # analyzed.json 덮어쓰기
  python3 analyze_voc.py --backfill            # data/DKR/ 내 미처리 날짜 일괄
"""

import json
import argparse
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST        = timezone(timedelta(hours=9))
SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data" / "DKR"

# ── 보드 ID → 기본 카테고리 매핑 ──────────────────────────────────────────────
# board_id=4 (자유 게시판) 은 None → 키워드로 재분류
BOARD_CATEGORY_MAP = {
    4: None,          # 자유 게시판 → 키워드 판별
    5: "게임 관련",    # 질문과 답변
    7: "버그·오류",    # 버그 제보
    9: "건의·요청",    # 건의 게시판
}

# 공식 게시판 IDs
OFFICIAL_BOARD_IDS = {11, 13}

# 자유 게시판(board_id=4) 키워드 분류 — 우선순위: 불만 > 버그 > 건의 > 기본
COMPLAINT_KEYWORDS = [
    "섭종", "서비스종료", "서비스 종료", "망겜", "탈출", "폐겜",
    "폐서비스", "쫄딱", "죽겠다", "망했다",
    "현질", "지못미", "버리는", "버려", "탈주", "탈게",
]

BUG_KEYWORDS = [
    "버그", "오류", "에러", "error", "안됨", "안돼", "안 돼", "안 됨",
    "팅", "먹통", "렉", "렉걸", "튕", "멈춤", "멈춰", "오작동",
    "접속불가", "접속 불가", "로그인 안", "로그인안", "로딩",
    "크래시", "crash", "뻗어", "죽어", "작동",
]

SUGGEST_KEYWORDS = [
    "건의", "요청", "제안", "해주세요", "해주셨으면", "추가해", "추가 해",
    "개선", "바꿔", "바꿔주", "변경해", "변경 해",
    "이렇게 하면", "이렇게하면", "있으면 좋겠", "있으면좋겠",
    "필요한것같", "필요할것같", "했으면", "했으면 좋겠",
    "부탁", "해줘", "해줬으면", "넣어줘", "고쳐줘", "수정해",
]


# ── 카테고리 분류 ─────────────────────────────────────────────────────────────
def classify_post(post: dict) -> str:
    """단일 포스트의 카테고리 반환"""
    board_id = post.get("board_id")
    cat = BOARD_CATEGORY_MAP.get(board_id)
    if cat is not None:
        return cat

    # board_id=4 (자유 게시판) — 키워드 기반 분류
    text = f"{post.get('title', '')} {post.get('body', '')}".lower()

    for kw in COMPLAINT_KEYWORDS:
        if kw in text:
            return "기타"

    for kw in BUG_KEYWORDS:
        if kw in text:
            return "버그·오류"

    for kw in SUGGEST_KEYWORDS:
        if kw in text:
            return "건의·요청"

    return "게임 관련"


# ── major_issues 생성 ─────────────────────────────────────────────────────────
def build_major_issues(official_posts: list) -> list:
    """공식 게시판(공지/업데이트) → major_issues 리스트"""
    issues = []
    for p in official_posts:
        title = p.get("title", "").strip()
        if not title:
            continue
        issues.append({
            "title":    title,
            "board":    p.get("board_name", ""),
            "url":      p.get("url", ""),
            "feed_id":  str(p.get("feed_id", "")),
            "date":     p.get("created_at", "")[:10],
        })
    return issues


# ── voc_groups 생성 ───────────────────────────────────────────────────────────
def build_voc_groups(user_posts: list) -> list:
    """유저 포스트 → category별 그룹핑 → voc_groups 리스트"""
    from collections import defaultdict

    groups: dict[str, list] = defaultdict(list)
    for p in user_posts:
        cat = classify_post(p)
        groups[cat].append(p)

    result = []
    # 카테고리 출력 순서 고정
    ORDER = ["버그·오류", "건의·요청", "게임 관련", "기타"]
    for cat in ORDER:
        posts = groups.get(cat, [])
        if not posts:
            continue

        # 대표글: 댓글 수 + 좋아요 가중치 기준 상위 1개
        key_fn = lambda p: (p.get("comment_count", 0) * 2 + p.get("like_count", 0))
        top = sorted(posts, key=key_fn, reverse=True)[0]

        # 대표 요약: 제목 그대로 사용 (LLM 없음)
        summary = top.get("title", "").strip()[:80]

        result.append({
            "category":           cat,
            "summary":            summary,
            "count":              len(posts),
            "representative_url": top.get("url", ""),
            "feed_ids":           [str(p.get("feed_id", "")) for p in posts],
        })

    return result


# ── cs_week_trend 기본 틀 생성 ────────────────────────────────────────────────
def build_cs_week_trend(target_date: str) -> list:
    """target_date 기준 최근 7일 0값 틀 생성 (CS 수집 후 collect_cs_data.py가 채움)"""
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    return [
        {
            "date":      (dt - timedelta(days=i)).strftime("%Y-%m-%d"),
            "received":  0,
            "processed": 0,
        }
        for i in range(6, -1, -1)
    ]


# ── 메인 분석 함수 ────────────────────────────────────────────────────────────
def analyze(date_label: str, force: bool = False) -> bool:
    raw_path      = DATA_DIR / f"{date_label}.json"
    analyzed_path = DATA_DIR / f"{date_label}.analyzed.json"

    if not raw_path.exists():
        print(f"[SKIP] raw JSON 없음: {raw_path.name}")
        return False

    if analyzed_path.exists() and not force:
        print(f"[SKIP] analyzed.json 이미 존재: {analyzed_path.name}  (--force 로 덮어쓰기)")
        return True

    with open(raw_path, encoding="utf-8") as f:
        raw = json.load(f)

    official_posts = raw.get("official_posts", [])
    user_posts     = raw.get("posts", [])

    major_issues  = build_major_issues(official_posts)
    voc_groups    = build_voc_groups(user_posts)
    cs_week_trend = build_cs_week_trend(date_label)

    analyzed = {
        "date":          date_label,
        "major_issues":  major_issues,
        "voc_groups":    voc_groups,
        "cs_inquiries":  [],           # CS 자동화 2차에서 채움
        "cs_week_trend": cs_week_trend,
    }

    with open(analyzed_path, "w", encoding="utf-8") as f:
        json.dump(analyzed, f, ensure_ascii=False, indent=2)

    m = raw.get("meta", {})
    print(f"[OK] {analyzed_path.name} 생성 완료")
    print(f"     공식 이슈: {len(major_issues)}건 / VOC 그룹: {len(voc_groups)}개 / 유저 포스트: {len(user_posts)}건")
    for g in voc_groups:
        print(f"       [{g['category']}] {g['count']}건  대표: {g['summary'][:40]}")
    return True


# ── 백필 ─────────────────────────────────────────────────────────────────────
def backfill(force: bool = False):
    """data/DKR/ 내 raw JSON이 있고 analyzed.json이 없는 날짜 일괄 처리"""
    raw_files = sorted(DATA_DIR.glob("*.json"))
    targets = []
    for f in raw_files:
        # *.analyzed.json 은 제외, YYYY-MM-DD.json 만
        if ".analyzed." in f.name:
            continue
        date_label = f.stem  # "2026-04-06"
        targets.append(date_label)

    if not targets:
        print("[INFO] 처리 대상 raw JSON 없음")
        return

    print(f"[BACKFILL] 대상: {len(targets)}건")
    ok = 0
    for d in targets:
        if analyze(d, force=force):
            ok += 1
    print(f"[BACKFILL] 완료: {ok}/{len(targets)}")


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="DKR VOC 규칙 기반 분석")
    parser.add_argument(
        "date", nargs="?",
        default=(datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d"),
        help="분석 날짜 YYYY-MM-DD (기본: 어제)",
    )
    parser.add_argument(
        "--force", "-f", action="store_true",
        help="analyzed.json 이미 존재해도 덮어쓰기",
    )
    parser.add_argument(
        "--backfill", action="store_true",
        help="data/DKR/ 내 미처리 날짜 일괄 분석",
    )
    args = parser.parse_args()

    if args.backfill:
        backfill(force=args.force)
    else:
        ok = analyze(args.date, force=args.force)
        if not ok:
            import sys; sys.exit(1)


if __name__ == "__main__":
    main()
