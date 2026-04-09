#!/usr/bin/env python3
"""
analyze_voc.py — DKR 커뮤니티 VOC LLM 기반 분석기 v2.0
────────────────────────────────────────────────────────
입력:  data/DKR/YYYY-MM-DD.json       (crawl_dkr.py 출력)
출력:  data/DKR/YYYY-MM-DD.analyzed.json

생성 필드:
  1. major_issues   — official_posts (공지/업데이트) 기반, LLM 요약
  2. voc_groups     — user posts 의미 기반 그룹핑 (LLM)
                     fallback: 키워드 방식
  3. cs_inquiries   — [] (빈 배열 / CS 자동화 2차에서 구현)
  4. cs_week_trend  — 최근 7일 0값 기본 틀

사용법:
  python3 analyze_voc.py 2026-04-06            # 특정 날짜
  python3 analyze_voc.py                        # 어제 기준 자동
  python3 analyze_voc.py 2026-04-06 --force    # analyzed.json 덮어쓰기
  python3 analyze_voc.py --backfill            # data/DKR/ 내 미처리 날짜 일괄
  python3 analyze_voc.py 2026-04-06 --no-llm  # 키워드 fallback 강제 사용

설정:
  ANTHROPIC_API_KEY 환경변수 또는
  voc/config.local.json → {"anthropic_api_key": "sk-ant-..."}
"""

import json
import argparse
import re
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST        = timezone(timedelta(hours=9))
SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data" / "DKR"
CONFIG_PATH = SCRIPT_DIR.parent / "config.local.json"

# LLM 모델 설정
LLM_MODEL      = "claude-haiku-4-5-20251001"
LLM_MAX_TOKENS = 4096

# ── 설정 로드 ─────────────────────────────────────────────────────────────────
def load_api_key() -> str | None:
    """ANTHROPIC_API_KEY 환경변수 또는 config.local.json에서 로드"""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return cfg.get("anthropic_api_key", "")
        except Exception:
            pass
    return None


# ════════════════════════════════════════════════════════════════════════════
#  LLM 분석 — 프롬프트 및 호출
# ════════════════════════════════════════════════════════════════════════════

# ── VOC 분석 프롬프트 ─────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
당신은 모바일 게임 'DK모바일:리본(DKR)'의 커뮤니티 VOC 분석 전문가입니다.
유저 게시글을 읽고 의미 기반으로 분류·요약하는 것이 주요 역할입니다.
반드시 JSON 형식만 반환하고, 설명이나 마크다운 코드블럭(```)은 포함하지 마세요.\
"""

VOC_ANALYSIS_PROMPT = """\
다음은 {date} 기준 수집된 DKR 커뮤니티 게시글입니다.

## 공식 게시글 (official_posts) — 공지사항 및 업데이트
{official_json}

## 유저 게시글 (user_posts) — VOC 분석 대상
{user_json}

──────────────────────────────────────────────
아래 JSON 스키마에 맞게 분석 결과를 반환하세요:

{{
  "major_issues": [
    {{
      "title": "공식 게시글 원본 제목 그대로",
      "summary": "핵심 내용 1~2줄 요약 (없으면 제목 그대로 사용)",
      "board": "게시판명 (공지사항|업데이트 등)",
      "url": "URL 원본 그대로",
      "feed_id": "feed_id 원본 그대로",
      "date": "YYYY-MM-DD"
    }}
  ],
  "voc_groups": [
    {{
      "category": "버그·오류 | 건의·요청 | 게임 관련 | 기타",
      "summary": "이 그룹의 핵심 이슈를 한 줄로 명확하게",
      "count": <int>,
      "representative_url": "대표 게시글 URL",
      "feed_ids": ["feed_id1", "feed_id2", ...]
    }}
  ]
}}

──────────────────────────────────────────────
## 분류 기준 (category)

| 카테고리 | 포함 내용 |
|---------|---------|
| 버그·오류 | 게임 오류, 버그, 접속 장애, 기능 이상, 크래시, 튕김 |
| 건의·요청 | 콘텐츠 추가 요청, 시스템 개선 제안, 운영 정책 변경 요청 |
| 게임 관련 | 일반 게임 플레이 질문, 공략, 정보 공유, 이벤트 문의 |
| 기타 | 커뮤니티 잡담, 서비스 종료 우려, 게임사 불만, 기타 주제 |

## 그룹핑 규칙

1. **의미 기반 묶기**: 동일하거나 매우 유사한 이슈는 반드시 하나의 그룹으로 통합
2. **분리 원칙**: 주제나 맥락이 다르면 별도 그룹으로 구분
3. **대표 URL**: 해당 그룹에서 가장 조회수/댓글이 많거나 내용이 대표적인 게시글 선택
4. **summary**: 구체적이고 명확하게 작성 (예: "서버 점검 중 그룹 매칭 오류 보고 3건")
5. **유저 게시글이 없으면**: voc_groups는 빈 배열 []

## 유의사항
- official_posts가 없으면 major_issues는 빈 배열 []
- feed_ids는 반드시 문자열 배열
- 모든 URL은 입력 데이터 원본 그대로 사용 (임의로 수정 금지)
- JSON 외 텍스트 금지\
"""


def call_llm(prompt: str, api_key: str) -> dict | None:
    """Anthropic API 호출 → JSON dict 반환. 실패 시 None"""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=LLM_MODEL,
            max_tokens=LLM_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()

        # 코드블럭 감싸기 제거 (방어적 처리)
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        return json.loads(raw)
    except Exception as e:
        print(f"[LLM ERROR] {type(e).__name__}: {e}")
        return None


def analyze_with_llm(date_label: str, official_posts: list, user_posts: list,
                     api_key: str) -> dict | None:
    """LLM에 전체 posts를 한 번에 전달하여 분석"""

    def slim_post(p: dict) -> dict:
        """토큰 절약: 분석에 필요한 필드만 추출"""
        return {
            "feed_id":      str(p.get("feed_id", "")),
            "board_name":   p.get("board_name", ""),
            "title":        p.get("title", "")[:200],
            "body":         (p.get("body") or "")[:400],
            "url":          p.get("url", ""),
            "comment_count": p.get("comment_count", 0),
            "like_count":   p.get("like_count", 0),
            "created_at":   (p.get("created_at") or "")[:10],
        }

    official_json = json.dumps(
        [slim_post(p) for p in official_posts], ensure_ascii=False, indent=2
    ) if official_posts else "[]"

    user_json = json.dumps(
        [slim_post(p) for p in user_posts], ensure_ascii=False, indent=2
    ) if user_posts else "[]"

    prompt = VOC_ANALYSIS_PROMPT.format(
        date=date_label,
        official_json=official_json,
        user_json=user_json,
    )

    print(f"[LLM] 모델: {LLM_MODEL} | 공식 {len(official_posts)}건 / 유저 {len(user_posts)}건 분석 중...")
    result = call_llm(prompt, api_key)

    if result is None:
        return None

    # 스키마 검증 및 정규화
    major_issues = result.get("major_issues", [])
    voc_groups   = result.get("voc_groups", [])

    # feed_id 문자열 강제 변환
    for item in major_issues:
        item["feed_id"] = str(item.get("feed_id", ""))
    for grp in voc_groups:
        grp["feed_ids"] = [str(x) for x in grp.get("feed_ids", [])]
        grp["count"]    = int(grp.get("count", len(grp["feed_ids"])))

    return {"major_issues": major_issues, "voc_groups": voc_groups}


# ════════════════════════════════════════════════════════════════════════════
#  키워드 Fallback
# ════════════════════════════════════════════════════════════════════════════

BOARD_CATEGORY_MAP = {
    4: None,           # 자유 게시판 → 키워드 판별
    5: "게임 관련",     # 질문과 답변
    7: "버그·오류",     # 버그 제보
    9: "건의·요청",     # 건의 게시판
}

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


def _classify_keyword(post: dict) -> str:
    board_id = post.get("board_id")
    cat = BOARD_CATEGORY_MAP.get(board_id)
    if cat is not None:
        return cat
    text = f"{post.get('title', '')} {post.get('body', '')}".lower()
    for kw in COMPLAINT_KEYWORDS:
        if kw in text: return "기타"
    for kw in BUG_KEYWORDS:
        if kw in text: return "버그·오류"
    for kw in SUGGEST_KEYWORDS:
        if kw in text: return "건의·요청"
    return "게임 관련"


def analyze_with_keywords(official_posts: list, user_posts: list) -> dict:
    """키워드 기반 fallback 분석"""
    print("[FALLBACK] 키워드 기반 분류 사용")

    # major_issues (요약 없이 제목만)
    major_issues = []
    for p in official_posts:
        title = p.get("title", "").strip()
        if title:
            major_issues.append({
                "title":   title,
                "summary": title,
                "board":   p.get("board_name", ""),
                "url":     p.get("url", ""),
                "feed_id": str(p.get("feed_id", "")),
                "date":    (p.get("created_at") or "")[:10],
            })

    # voc_groups
    from collections import defaultdict
    groups: dict[str, list] = defaultdict(list)
    for p in user_posts:
        cat = _classify_keyword(p)
        groups[cat].append(p)

    ORDER = ["버그·오류", "건의·요청", "게임 관련", "기타"]
    voc_groups = []
    for cat in ORDER:
        posts = groups.get(cat, [])
        if not posts:
            continue
        key_fn = lambda p: p.get("comment_count", 0) * 2 + p.get("like_count", 0)
        top = sorted(posts, key=key_fn, reverse=True)[0]
        voc_groups.append({
            "category":           cat,
            "summary":            top.get("title", "")[:80],
            "count":              len(posts),
            "representative_url": top.get("url", ""),
            "feed_ids":           [str(p.get("feed_id", "")) for p in posts],
        })

    return {"major_issues": major_issues, "voc_groups": voc_groups}


# ════════════════════════════════════════════════════════════════════════════
#  cs_week_trend 기본 틀
# ════════════════════════════════════════════════════════════════════════════

def build_cs_week_trend(target_date: str) -> list:
    """target_date 기준 최근 7일 0값 틀 (collect_cs_data.py가 채움)"""
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    return [
        {"date": (dt - timedelta(days=i)).strftime("%Y-%m-%d"), "received": 0, "processed": 0}
        for i in range(6, -1, -1)
    ]


# ════════════════════════════════════════════════════════════════════════════
#  메인 분석 함수
# ════════════════════════════════════════════════════════════════════════════

def analyze(date_label: str, force: bool = False, use_llm: bool = True) -> bool:
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

    # ── LLM or Fallback ───────────────────────────────────────────────────
    llm_result = None
    if use_llm:
        api_key = load_api_key()
        if api_key:
            llm_result = analyze_with_llm(date_label, official_posts, user_posts, api_key)
            if llm_result is None:
                print("[WARN] LLM 분석 실패 → 키워드 fallback 사용")
        else:
            print("[WARN] ANTHROPIC_API_KEY 없음 → 키워드 fallback 사용")

    if llm_result is not None:
        major_issues = llm_result["major_issues"]
        voc_groups   = llm_result["voc_groups"]
        method = "LLM"
    else:
        kw = analyze_with_keywords(official_posts, user_posts)
        major_issues = kw["major_issues"]
        voc_groups   = kw["voc_groups"]
        method = "키워드"

    cs_week_trend = build_cs_week_trend(date_label)

    analyzed = {
        "date":          date_label,
        "major_issues":  major_issues,
        "voc_groups":    voc_groups,
        "cs_inquiries":  [],
        "cs_week_trend": cs_week_trend,
        "_meta": {
            "analyzed_at": datetime.now(KST).isoformat(),
            "method":      method,
        }
    }

    with open(analyzed_path, "w", encoding="utf-8") as f:
        json.dump(analyzed, f, ensure_ascii=False, indent=2)

    print(f"[OK] {analyzed_path.name} 생성 ({method})")
    print(f"     공식 이슈: {len(major_issues)}건 / VOC 그룹: {len(voc_groups)}개 / 유저 포스트: {len(user_posts)}건")
    for g in voc_groups:
        print(f"       [{g['category']}] {g['count']}건  ─  {g['summary'][:50]}")
    return True


# ════════════════════════════════════════════════════════════════════════════
#  백필
# ════════════════════════════════════════════════════════════════════════════

def backfill(force: bool = False, use_llm: bool = True):
    raw_files = sorted(DATA_DIR.glob("*.json"))
    targets = [f.stem for f in raw_files if ".analyzed." not in f.name]
    if not targets:
        print("[INFO] 처리 대상 raw JSON 없음")
        return
    print(f"[BACKFILL] 대상: {len(targets)}건")
    ok = sum(1 for d in targets if analyze(d, force=force, use_llm=use_llm))
    print(f"[BACKFILL] 완료: {ok}/{len(targets)}")


# ════════════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="DKR VOC LLM 기반 분석 v2.0")
    parser.add_argument(
        "date", nargs="?",
        default=(datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d"),
        help="분석 날짜 YYYY-MM-DD (기본: 어제)",
    )
    parser.add_argument("--force",    "-f", action="store_true", help="analyzed.json 덮어쓰기")
    parser.add_argument("--backfill",       action="store_true", help="미처리 날짜 일괄 분석")
    parser.add_argument("--no-llm",         action="store_true", help="키워드 fallback 강제 사용")
    args = parser.parse_args()

    use_llm = not args.no_llm

    if args.backfill:
        backfill(force=args.force, use_llm=use_llm)
    else:
        ok = analyze(args.date, force=args.force, use_llm=use_llm)
        if not ok:
            import sys; sys.exit(1)


if __name__ == "__main__":
    main()
