#!/usr/bin/env python3
"""
analyze_voc.py — DKR 커뮤니티 VOC 규칙 기반 분석기 v5.0
────────────────────────────────────────────────────────
변경 이력:
  v5.0  summarize_lounge_title + (category,summary) 그룹핑 + build_insights 추가
  v4.0  분류 정확도 개선 + 중복/노이즈 제거 + major_issues 품질 개선
  v3.0  LLM 제거, 규칙 기반 단독 확정
  v2.0  LLM 기반 (폐기)
  v1.0  초기 키워드 방식

분류 우선순위 (board_id=4 자유 게시판):
  1순위: BUG_KEYWORDS       → 버그·오류
  2순위: SUGGEST_KEYWORDS   → 건의·요청
  3순위: COMPLAINT_KEYWORDS → 기타
  4순위: default            → 게임 관련

사용법:
  python3 analyze_voc.py                        # 어제 날짜 자동
  python3 analyze_voc.py 2026-04-06             # 특정 날짜
  python3 analyze_voc.py 2026-04-06 --force     # analyzed.json 덮어쓰기
  python3 analyze_voc.py --backfill             # raw 있고 analyzed 없는 날짜 일괄
  python3 analyze_voc.py --backfill --force     # 모든 raw 날짜 재분석
"""

import json
import argparse
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST        = timezone(timedelta(hours=9))
SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data" / "DKR"


# ════════════════════════════════════════════════════════════════════════════
#  ▶ 분류 상수 — 키워드 추가·수정은 이 블록만 수정하세요
# ════════════════════════════════════════════════════════════════════════════

# board_id → 카테고리 직접 매핑 (None = 키워드로 재분류)
BOARD_CATEGORY_MAP: dict[int, str | None] = {
    4: None,           # 자유 게시판   → 키워드 판별 (아래 우선순위 적용)
    5: "게임 관련",     # 질문과 답변   → 직접 매핑
    7: "버그·오류",     # 버그 제보     → 직접 매핑 (무조건)
    9: "건의·요청",     # 건의 게시판   → 직접 매핑 (무조건)
}

# 공식 게시판 IDs
OFFICIAL_BOARD_IDS: set[int] = {11, 13}

# ── 자유 게시판(board_id=4) 키워드 / 우선순위: BUG > SUGGEST > COMPLAINT > default ──

BUG_KEYWORDS: list[str] = [
    # 직접 버그·오류 표현
    "버그", "오류", "에러", "error",
    # 기능 이상
    "안됨", "안돼", "안 돼", "안 됨", "안된다", "안되는", "먹통", "오작동", "작동",
    # 접속 문제
    "팅", "튕", "렉", "랙", "렉걸", "멈춤", "멈춰",
    "접속불가", "접속 불가", "로그인 안", "로그인안", "로딩",
    # 서버 장애
    "서버터", "터졌", "터진", "터짐", "서버 터",
    # 앱 충돌
    "크래시", "crash", "뻗어", "죽어",
    # 추가
    "오작", "끊김", "끊겨", "오류남", "오류 남",
]

SUGGEST_KEYWORDS: list[str] = [
    # 직접 건의·요청
    "건의", "요청", "제안",
    # 정중한 표현
    "해주세요", "해주셨으면", "부탁", "해줘", "해줬으면",
    # 추가·개선
    "추가해", "추가 해", "넣어줘", "개선",
    "바꿔", "바꿔주", "변경해", "변경 해", "고쳐줘", "수정해",
    # 희망 표현
    "이렇게 하면", "이렇게하면",
    "있으면 좋겠", "있으면좋겠",
    "필요한것같", "필요할것같",
    "했으면", "했으면 좋겠",
    # 추가
    "나와야", "나왔으면", "출시해", "출시 해", "좀 해줘",
]

COMPLAINT_KEYWORDS: list[str] = [
    # 서비스 종료 우려
    "섭종", "서비스종료", "서비스 종료", "폐서비스", "폐겜",
    # 게임 비판
    "망겜", "탈주", "탈게", "쫄딱", "지못미",
    # 환불·불만 직접 표현
    "환불", "접는다", "그만할", "관두겠", "접겠",
    # 강화된 불만 표현
    "개망", "망했다", "개판", "엉망", "답없", "답 없",
    "운영 뭐함", "운영뭐함", "운영 뭐해", "뭐하냐", "뭐하냐고",
    "게임사 뭐", "운영진 뭐", "운영자 뭐",
    # 방언·비속어형 불만
    "우짜냐", "우짜냐고", "ㅅㄱ", "현질",
    # 감정 표현
    "버리는", "버려", "갈아탄다",
]

# 카테고리 출력 순서 고정
CATEGORY_ORDER: list[str] = ["버그·오류", "건의·요청", "게임 관련", "기타"]

# ── 노이즈 필터 옵션 ────────────────────────────────────────────────────────
# True: 너무 짧거나 의미 없는 글 필터링 / False: 모든 글 포함
FILTER_NOISE: bool = True

# 제목 최소 길이 (이하이면 기타 또는 제외)
NOISE_MIN_LEN: int = 4

# 의미 없는 글 완전 제외(True) vs 기타 분류(False)
NOISE_EXCLUDE: bool = False

# 노이즈 판단 정규식
_NOISE_PATTERN = re.compile(r"^[ㄱ-ㅎㅏ-ㅣ?!.…~\s]+$")


# ════════════════════════════════════════════════════════════════════════════
#  ▶ 3단계 보고용 요약 파이프라인 — summarize_lounge_title
#
#    Step 1: _classify_intent()   — 다중 신호 가중치 기반 의도 분류
#    Step 2: _normalize_terms()   — 슬랭 → 보고용 표준 단어 변환
#    Step 3: _generate_sentence() — intent + 정제된 제목 → 보고 문장
#
#  [원칙]
#    · 단일 키워드 → 문장 결정 금지 (다중 신호 가중합으로 결정)
#    · LLM 사용 금지 (규칙 + 테이블 기반)
#    · 수정은 각 단계의 상수/로직만 수정
# ════════════════════════════════════════════════════════════════════════════


# ── Step 1 상수: intent 신호 집합 ────────────────────────────────────────────
# 각 집합은 "신호 강도"가 다름 — 가중치 부여 시 참조

# bug 신호
_SIG_BUG_EXPLICIT  = {"버그", "오류", "에러", "error", "crash", "크래시", "이상"}
_SIG_BUG_STATE     = {"십힘", "씹힘", "십혀", "씹혀", "미적용",
                      "안됨", "안 됨", "안돼", "안 돼",
                      "먹통", "오작동", "작동안", "작동 안", "끊겨"}

# system_issue 신호 (기술적 접속/서버 증상 — "서버" 자체는 포함 안 함)
_SIG_SYSTEM_SYMPTOM = {"접속", "로그인", "팅", "튕", "렉", "랙", "로딩",
                        "끊김", "접속불가", "접속 불가", "로그인안", "로그인 안",
                        "터졌", "터진", "서버터"}

# price 신호
_SIG_TRADE_OBJ  = {"가격", "시세", "얼마", "거래", "팔아", "사노",
                   "팔린", "팔림", "팔려", "팔았"}
_SIG_PRICE_DOWN = {"하락", "떨어", "폭락", "가치", "낮아", "싸",
                   "누가사", "누가 사", "망했", "ㅋㅋ팔"}

# complaint 신호
_SIG_COMPLAINT  = {"섭종", "서비스종료", "서비스 종료", "폐겜", "폐서비스",
                   "환불", "접는다", "탈게", "탈주", "망겜",
                   "개판", "뭐하냐", "운영뭐", "운영 뭐", "ㅅㄱ"}


# ── Step 2 상수: 슬랭 정제 테이블 ────────────────────────────────────────────
# (원문_슬랭, 보고용_표준어) — 긴 표현을 먼저 배치 (부분 오버라이드 방지)
_SLANG_TABLE: list[tuple[str, str]] = [
    # 스킬 오작동 계열
    ("씹힘현상",    "미적용 현상"),
    ("십힘현상",    "미적용 현상"),
    ("씹힘",        "미적용"),
    ("십힘",        "미적용"),
    ("씹혀",        "미적용"),
    ("십혀",        "미적용"),
    # 작동 불가 계열
    ("먹통",        "작동 불가"),
    ("안 됨",       "작동 불가"),
    ("안됨",        "작동 불가"),
    ("안 돼",       "작동 불가"),
    ("안돼",        "작동 불가"),
    # 접속 문제 계열
    ("접속불가",    "접속 종료 현상"),
    ("튕김",        "접속 종료 현상"),
    ("팅김",        "접속 종료 현상"),
    ("튕겨",        "접속 종료 현상"),
    ("팅겨",        "접속 종료 현상"),
    ("튕",          "접속 종료 현상"),
    ("팅",          "접속 종료 현상"),
    # 성능 저하 계열
    ("렉걸",        "지연 현상"),
    ("렉",          "지연 현상"),
    ("랙",          "지연 현상"),
    ("끊김",        "지연 현상"),
    # 서버 슬랭
    ("하이퍼섭",    "하이퍼 서버"),
    ("구섭",        "구 서버"),
    ("섭이전",      "서버 이전"),
    ("섭종",        "서비스 종료"),
    ("섭",          "서버"),
    # 서비스 종료 (공백 없는 형태 통일)
    ("서비스종료",  "서비스 종료"),
    # 기타
    ("폐겜",        "게임 폐서비스"),
    ("ㅅㄱ",        ""),   # 불필요 감탄사 제거
]

# ── Step 2 보조: 스킬명 추출용 suffix ────────────────────────────────────────
# (정제된 텍스트 기준 — normalize 후 탐색)
_SKILL_SUFFIX_NORM = [
    "미적용 현상", "미적용", "작동 불가",
    "접속 종료 현상", "지연 현상",
    "오류", "버그", "에러", "현상",
]


# ── Step 1: 의도 분류 ─────────────────────────────────────────────────────────

def _classify_intent(title: str, category: str) -> str:
    """다중 신호 가중합 기반 intent 분류.

    각 intent별 score를 계산하고 최고값을 반환.
    임계값(1.5) 미달 시 "general" 반환.

    intent 종류:
      bug          — 기능·스킬 오류
      system_issue — 접속·서버 인프라 장애
      price_drop   — 캐릭터·아이템 가치 하락 우려
      price_question — 거래·시세 정보 문의
      complaint    — 운영·서비스 불만
      general      — 위 어디에도 해당 없음
    """
    from collections import defaultdict
    t = title.lower()

    scores: dict[str, float] = defaultdict(float)

    # ── bug ──────────────────────────────────────────────────────
    explicit_hits = sum(1 for s in _SIG_BUG_EXPLICIT if s in t)
    state_hits    = sum(1 for s in _SIG_BUG_STATE    if s in t)
    if explicit_hits >= 1:
        scores["bug"] += 2.0 * explicit_hits
    if state_hits >= 1:
        scores["bug"] += 2.5 * state_hits
    if category == "버그·오류":           # 보드 직접 매핑 보너스
        scores["bug"] += 2.0

    # ── system_issue ─────────────────────────────────────────────
    # 기술 증상 신호가 있을 때만 활성화 (서버/서버이전 언급은 제외)
    sys_hits = sum(1 for s in _SIG_SYSTEM_SYMPTOM if s in t)
    if sys_hits >= 1:
        # 버그 신호와 겹칠 때: 접속 관련이면 system_issue 강화
        if explicit_hits + state_hits == 0:
            scores["system_issue"] += 2.5 * sys_hits
        else:
            scores["system_issue"] += 1.0 * sys_hits  # bug와 경쟁

    # ── price_drop ───────────────────────────────────────────────
    trade_hits = sum(1 for s in _SIG_TRADE_OBJ  if s in t)
    down_hits  = sum(1 for s in _SIG_PRICE_DOWN if s in t)
    if trade_hits >= 1 and down_hits >= 1:
        scores["price_drop"] += 3.5   # 거래 + 하락 동시 → 명확한 가치 우려
    elif down_hits >= 2:
        scores["price_drop"] += 3.0   # 하락 신호 2개 이상
    elif down_hits == 1 and trade_hits >= 1:
        scores["price_drop"] += 2.5

    # ── price_question ───────────────────────────────────────────
    if trade_hits >= 1 and down_hits == 0:
        scores["price_question"] += 2.0 * trade_hits  # 거래만 → 시세 문의
    elif trade_hits >= 2:
        scores["price_question"] += 1.0               # 거래 신호 2개라면 보조 인정

    # ── complaint ────────────────────────────────────────────────
    complaint_hits = sum(1 for s in _SIG_COMPLAINT if s in t)
    if complaint_hits >= 1:
        scores["complaint"] += 3.5 * complaint_hits
    if category == "기타":
        scores["complaint"] += 1.5                    # 기타 카테고리 보너스

    # ── 결정 ─────────────────────────────────────────────────────
    if not scores:
        return "general"
    best_intent, best_score = max(scores.items(), key=lambda x: x[1])
    return best_intent if best_score >= 1.5 else "general"


# ── Step 2: 슬랭 정제 ────────────────────────────────────────────────────────

def _normalize_terms(title: str) -> str:
    """슬랭 → 보고용 표준 단어 치환 (테이블 순서대로 적용)."""
    result = title
    for slang, formal in _SLANG_TABLE:
        result = result.replace(slang, formal)
    return result.strip()


def _extract_skill_from_normalized(norm: str) -> str | None:
    """정제된 제목에서 스킬/콘텐츠명 추출.

    suffix 앞 단어 블록 → 마지막 4단어 이내를 스킬명으로 사용.
    예) '소서러 블레스 오브 엘리멘탈 미적용 현상' → '소서러 블레스 오브 엘리멘탈'
    """
    for suf in _SKILL_SUFFIX_NORM:
        idx = norm.find(suf)
        if idx >= 2:
            candidate = norm[:idx].strip()
            words = candidate.split()
            if 1 <= len(words) <= 6:
                skill = " ".join(words[-4:]).strip()
                if len(skill) >= 2:
                    return skill
    return None


# ── Step 3: 문장 생성 ────────────────────────────────────────────────────────

def _generate_sentence(intent: str, raw: str, norm: str, category: str,
                       body: str = "") -> str:
    """intent + 정제된 제목 → 보고용 최종 문장.

    body: 본문 텍스트 (summarize_lounge_title에서 선택적으로 전달)
    """
    import re as _re

    raw_lower  = raw.lower()
    body_lower = body.lower()
    combined   = raw_lower + " " + body_lower

    # ── 내용 기반 구체적 패턴 우선 적용 ─────────────────────────
    # 던전 소탕 불가
    if ("던전" in combined or "소탕" in combined) and (
            "안됨" in combined or "안 됨" in combined or "불가" in combined or
            "안되" in combined or "않됨" in combined or "않돼" in combined):
        return "권장 전투력 충족 상태에서 던전 소탕 불가 현상"

    # 상품 구매 횟수 오류
    if ("구매횟수" in combined or ("구매" in combined and "횟수" in combined)):
        return "상품 구매 횟수 미초기화 오류 현상"

    # 매크로 신고 — 서버번호·길드명 추출 (매크로 키워드 필수)
    if "매크로" in combined:
        server_m = _re.search(r'(\d+)\s*섭', raw)
        server_s = f"{server_m.group(1)}서버 " if server_m else ""
        # 길드명 추출
        guild = ""
        for word in raw.split():
            if any(c.isalpha() and not c.isascii() for c in word) and len(word) >= 2:
                if word not in {"영자야", "작업장", "매크로", "제재안하냐", "왜", "뭐임", "ㅋㅋ"}:
                    if "길드" in word or "guild" in word.lower():
                        guild = word + " "
                        break
        # 본문에 영문 길드명 있는지 확인
        en_guild = _re.search(r'[A-Z]{2,}', raw + " " + body)
        if en_guild:
            guild = en_guild.group(0) + " 길드 "
        elif "좀비" in combined:
            guild = "좀비 길드 "
        return f"{server_s}{guild}매크로 사용 의심 제재 요청"

    # 파이썬 요람 / 미션 이벤트 카운트
    if ("파이썬" in combined or "python" in combined) and (
            "카운트" in combined or "카운팅" in combined or "클리어" in combined):
        return "1주년 미션 이벤트 파이썬의 요람 카운트 미적용 현상"

    # ── 기존 intent 기반 분기 ────────────────────────────────────

    if intent == "bug":
        skill = _extract_skill_from_normalized(norm)
        if skill:
            return f"{skill} 스킬 효과 미적용 현상"
        if "접속 종료 현상" in norm or "지연 현상" in norm:
            return "게임 접속 / 로그인 장애 보고"
        return "게임 내 기능 오류 보고"

    if intent == "system_issue":
        return "게임 접속 / 로그인 장애 보고"

    if intent == "price_drop":
        return "캐릭터 가치 하락에 대한 우려"

    if intent == "price_question":
        return "거래 가격에 대한 정보 문의"

    if intent == "complaint":
        if "서비스 종료" in norm or "게임 폐서비스" in norm:
            return "서비스 종료 우려 및 게임 비판"
        return "운영 정책에 대한 유저 불만"

    # ── general: category 기반 폴백 ──────────────────────────────
    if category == "버그·오류":
        # 접속/서버 장애 키워드
        if any(kw in combined for kw in ["접속", "로그인", "렉", "랙", "팅", "튕",
                                          "서버", "터졌", "터진"]):
            return "게임 접속 / 로그인 장애 보고"
        skill = _extract_skill_from_normalized(norm)
        if skill:
            return f"{skill} 스킬 효과 미적용 현상"
        return "게임 내 기능 오류 보고"

    if category == "건의·요청":
        if "이전권" in raw or "이전 권" in raw:
            return "서버 이전 아이템 출시 건의"
        if any(kw in raw for kw in ["합쳐", "통합", "섭합"]):
            return "서버 통합 건의"
        # 서버/접속 관련 건의는 장애 성격 우선
        if any(kw in combined for kw in ["접속", "로그인", "렉", "랙", "서버 터"]):
            return "게임 접속 / 로그인 장애 보고"
        # 현돌 초기화 관련
        if "현돌" in combined and "초기화" in combined:
            return "현돌 초기화 콘텐츠 출시 건의"
        if "서버" in norm or "섭" in raw:
            return "서버 운영 관련 건의"
        return "게임 개선 의견 제출"

    if category == "기타":
        if "서비스 종료" in norm or "폐겜" in raw:
            return "서비스 종료 우려 및 게임 비판"
        return "게임·운영 불만 의견"

    # 게임 관련 (default)
    if any(kw in raw for kw in ["합쳐", "통합", "섭합"]):
        return "서버 통합 관련 의견"
    if "이전권" in raw or "이전 권" in raw:
        return "서버 이전 아이템 관련 의견"
    if "서버 이전" in norm or "섭이전" in raw:
        return "서버 이전 관련 의견"
    if "서버" in norm or "섭" in raw:
        return "서버 운영 관련 의견"
    return "게임 관련 유저 의견"


# ── 공개 함수: summarize_lounge_title ────────────────────────────────────────

def summarize_lounge_title(title: str, category: str = "", body: str = "") -> str:
    """유저 원문 제목 → 보고용 요약 문장.

    3단계 파이프라인 (LLM 없음):
      Step 1  _classify_intent()       — 다중 신호 가중합 의도 분류
      Step 2  _normalize_terms()       — 슬랭 → 보고용 표준 단어
      Step 3  _generate_sentence()     — intent + 정제어 → 보고 문장

    body: 본문 텍스트 (추가 맥락 제공용)
    """
    intent     = _classify_intent(title, category)   # Step 1
    norm_title = _normalize_terms(title)             # Step 2
    return _generate_sentence(intent, title, norm_title, category, body=body)  # Step 3


# ════════════════════════════════════════════════════════════════════════════
#  분류 로직
# ════════════════════════════════════════════════════════════════════════════

def is_noise(post: dict) -> bool:
    """노이즈 게시글 판별: 제목이 너무 짧거나 자음/모음만인 경우"""
    title = (post.get("title") or "").strip()
    if len(title) < NOISE_MIN_LEN:
        return True
    if _NOISE_PATTERN.match(title):
        return True
    return False


def classify_post(post: dict) -> str:
    """단일 포스트 → 카테고리 문자열

    우선순위:
      board_id 직접 매핑 (4, 9 제외) → BUG → SUGGEST → COMPLAINT → default
    [FIX] board_id=9 (건의 게시판): 내용에 버그 키워드 있으면 버그·오류로 재분류
    """
    board_id = post.get("board_id")

    # board_id=9 (건의 게시판): 내용 기반 재분류 먼저
    if board_id == 9:
        text9 = f"{post.get('title', '')} {post.get('body', '')}".lower()
        for kw in BUG_KEYWORDS:
            if kw in text9:
                return "버그·오류"
        # 버그 키워드 없으면 원래 건의·요청
        return "건의·요청"

    cat = BOARD_CATEGORY_MAP.get(board_id)
    if cat is not None:
        return cat

    # board_id=4 (자유 게시판) — 제목+본문 키워드 판별
    text = f"{post.get('title', '')} {post.get('body', '')}".lower()

    # 1순위: 버그·오류
    for kw in BUG_KEYWORDS:
        if kw in text:
            return "버그·오류"

    # 2순위: 건의·요청
    for kw in SUGGEST_KEYWORDS:
        if kw in text:
            return "건의·요청"

    # 3순위: 기타 (불만/비난)
    for kw in COMPLAINT_KEYWORDS:
        if kw in text:
            return "기타"

    return "게임 관련"


def dedup_by_feed_id(posts: list) -> list:
    """feed_id 기준 완전 중복 제거 (같은 포스트 2번 수집 방어)"""
    seen: set[str] = set()
    result = []
    for p in posts:
        fid = str(p.get("feed_id", ""))
        if fid and fid in seen:
            continue
        if fid:
            seen.add(fid)
        result.append(p)
    return result


# ════════════════════════════════════════════════════════════════════════════
#  필드 생성
# ════════════════════════════════════════════════════════════════════════════

def build_major_issues(official_posts: list, date_label: str = "") -> list:
    """공식 게시판 포스트 → major_issues

    당일 raw.json의 official_posts만 사용.
    없으면 빈 배열 반환 (롤링 없음).

    dashboard가 사용하는 키:
      board_name  (build_section_issues: iss.get("board_name"))
      summary     (build_section_issues: iss.get("summary"))
      url, count, feed_id, date
    """
    # DEBUG
    print(f"  [DEBUG] official_posts 입력: {len(official_posts)}건")

    if not official_posts:
        print(f"  [DEBUG] major_issues 생성 전: 0건")
        print(f"  [DEBUG] major_issues 생성 후: 0건")
        return []

    # 1. feed_id 기준 중복 제거
    unique = dedup_by_feed_id(official_posts)
    print(f"  [DEBUG] major_issues 생성 전 (dedup 후): {len(unique)}건")

    # 2. (board_name + date) 기준 그룹핑 — 같은 날 같은 보드 묶음
    groups: dict[str, list] = defaultdict(list)
    for p in unique:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        date_key = (p.get("created_at") or "")[:10]
        board_nm = p.get("board_name", "")
        groups[f"{board_nm}|{date_key}"].append(p)

    result = []
    for key, posts in groups.items():
        board_nm, date_key = key.split("|", 1)
        rep   = sorted(posts, key=lambda p: str(p.get("feed_id", "")))[0]
        title = (rep.get("title") or "").strip()
        result.append({
            "title":      title,
            "summary":    title,      # 대시보드 iss.get("summary") 사용
            "board_name": board_nm,   # 대시보드 iss.get("board_name") 사용
            "board":      board_nm,   # 하위호환
            "url":        rep.get("url", ""),
            "feed_id":    str(rep.get("feed_id", "")),
            "date":       date_key,
            "count":      len(posts),
        })

    # 3. 최신순 정렬
    result = sorted(result, key=lambda x: x["date"], reverse=True)
    print(f"  [DEBUG] major_issues 생성 후: {len(result)}건")
    return result


def build_voc_groups(user_posts: list) -> list:
    """유저 포스트 → (category, summary) 기준 그룹핑 → voc_groups

    처리 순서:
      1. feed_id 기준 중복 제거
      2. 노이즈 필터 (FILTER_NOISE=True 시)
      3. 카테고리 분류 + summarize_lounge_title 요약
      4. (category, summary) 쌍으로 그룹핑 → count 집계
      5. 대표글 선정 (engagement 가중치: 댓글×2 + 좋아요)
      6. 카테고리 내 count DESC 정렬
    """
    # 1. feed_id 중복 제거
    posts = dedup_by_feed_id(user_posts)

    # 2. 노이즈 처리
    if FILTER_NOISE:
        noise_posts = [p for p in posts if is_noise(p)]
        clean_posts = [p for p in posts if not is_noise(p)]
        if NOISE_EXCLUDE:
            posts = clean_posts
        else:
            posts = clean_posts
            for p in noise_posts:
                p["_forced_cat"] = "기타"
            posts = posts + noise_posts

    # 3. 분류 + 요약 레이블 부여
    classified: list[tuple[str, str, dict]] = []  # (cat, summary, post)
    for p in posts:
        cat = p.pop("_forced_cat", None) or classify_post(p)
        summ = summarize_lounge_title(p.get("title", ""), cat, body=p.get("body", ""))
        classified.append((cat, summ, p))

    # 4. (category, summary) 그룹핑
    group_map: dict[tuple, list] = defaultdict(list)
    for cat, summ, p in classified:
        group_map[(cat, summ)].append(p)

    # 5. 결과 생성: 카테고리 순서 유지, 동일 카테고리 내 count DESC
    result = []
    for cat in CATEGORY_ORDER:
        # 해당 카테고리의 모든 (cat, summ) 쌍 추출
        cat_groups = [(k, v) for k, v in group_map.items() if k[0] == cat]
        if not cat_groups:
            continue

        # count 내림차순 정렬
        cat_groups.sort(key=lambda kv: len(kv[1]), reverse=True)

        for (c, summ), group_posts in cat_groups:
            # 대표글: engagement 가중치 최고
            top = max(
                group_posts,
                key=lambda p: p.get("comment_count", 0) * 2 + p.get("like_count", 0)
            )
            all_fids = [str(p.get("feed_id", "")) for p in group_posts]

            result.append({
                "category":           cat,
                "summary":            summ,
                "count":              len(group_posts),
                "representative_url": top.get("url", ""),
                "feed_ids":           all_fids,
            })

    return result


def build_cs_week_trend(target_date: str) -> list:
    """최근 7일 0값 틀 — collect_cs_data.py가 실제 값으로 채움"""
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    return [
        {
            "date":      (dt - timedelta(days=i)).strftime("%Y-%m-%d"),
            "received":  0,
            "processed": 0,
        }
        for i in range(6, -1, -1)
    ]


def build_insights(date_label: str, voc_groups: list, user_posts: list) -> dict:
    """VOC 인사이트: top_issues, trend(전일 대비), trending_keywords

    - top_issues: count 상위 3개 그룹 요약
    - trend: 전일 analyzed.json과 카테고리별 count 비교
    - trending_keywords: 당일 제목 단어 빈도 (2글자 이상, 상위 10개)
    """
    # ── top_issues: count 상위 3 ──────────────────────────────────
    top_issues = []
    sorted_groups = sorted(voc_groups, key=lambda g: g["count"], reverse=True)
    for g in sorted_groups[:3]:
        top_issues.append({
            "category": g["category"],
            "summary":  g["summary"],
            "count":    g["count"],
            "url":      g.get("representative_url", ""),
        })

    # ── trend: 전일 비교 ──────────────────────────────────────────
    prev_date = (
        datetime.strptime(date_label, "%Y-%m-%d") - timedelta(days=1)
    ).strftime("%Y-%m-%d")
    prev_path = DATA_DIR / f"{prev_date}.analyzed.json"

    curr_cat_count: dict[str, int] = defaultdict(int)
    for g in voc_groups:
        curr_cat_count[g["category"]] += g["count"]

    trend: dict[str, dict] = {}
    if prev_path.exists():
        try:
            with open(prev_path, encoding="utf-8") as f:
                prev_data = json.load(f)
            prev_cat_count: dict[str, int] = defaultdict(int)
            for g in prev_data.get("voc_groups", []):
                prev_cat_count[g["category"]] += g["count"]

            all_cats = set(list(curr_cat_count.keys()) + list(prev_cat_count.keys()))
            for cat in all_cats:
                curr_n = curr_cat_count.get(cat, 0)
                prev_n = prev_cat_count.get(cat, 0)
                trend[cat] = {
                    "current":  curr_n,
                    "previous": prev_n,
                    "delta":    curr_n - prev_n,
                }
        except Exception:
            pass

    # ── trending_keywords: 제목 단어 빈도 ────────────────────────
    # 불용어
    STOPWORDS = {
        "이", "그", "저", "이게", "저게", "그게", "있어", "있는", "없는",
        "없어", "하는", "하고", "하면", "해서", "해줘", "되는", "되어",
        "인데", "인지", "것같", "것 같", "같은", "같은데", "같아", "같아요",
        "에서", "으로", "로는", "이랑", "이나", "하나", "이다", "임", "게",
        "의", "가", "을", "를", "은", "는", "도", "랑", "와", "과",
        "뭔가", "왜", "어디", "어떻게", "이렇게", "언제", "진짜", "정말",
        "좀", "또", "잘", "다", "더", "게임", "dk", "디케이", "리본",
    }

    word_freq: dict[str, int] = defaultdict(int)
    for p in user_posts:
        title = p.get("title", "")
        # 한글/영어 단어 추출 (2글자 이상)
        words = re.findall(r"[가-힣a-zA-Z]{2,}", title)
        for w in words:
            wl = w.lower()
            if wl not in STOPWORDS and len(wl) >= 2:
                word_freq[wl] += 1

    trending = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:10]
    trending_keywords = [{"word": w, "count": c} for w, c in trending if c >= 2]

    return {
        "top_issues":         top_issues,
        "trend":              trend,
        "trending_keywords":  trending_keywords,
        "prev_date":          prev_date,
    }


# ════════════════════════════════════════════════════════════════════════════
#  메인 분석
# ════════════════════════════════════════════════════════════════════════════

def analyze(date_label: str, force: bool = False) -> str:
    """
    단일 날짜 분석.
    반환값: "ok" | "skip" | "fail"
    """
    raw_path      = DATA_DIR / f"{date_label}.json"
    analyzed_path = DATA_DIR / f"{date_label}.analyzed.json"

    if not raw_path.exists():
        return "fail_no_raw"

    if analyzed_path.exists() and not force:
        return "skip"

    try:
        with open(raw_path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        print(f"[ERR] {date_label} raw 로드 실패: {e}")
        return "fail_load"

    official_posts = raw.get("official_posts", [])
    user_posts     = raw.get("posts", [])

    major_issues  = build_major_issues(official_posts, date_label=date_label)
    voc_groups    = build_voc_groups(user_posts)
    cs_week_trend = build_cs_week_trend(date_label)
    insights      = build_insights(date_label, voc_groups, user_posts)

    # ── 기존 analyzed.json에서 CS 필드 보존 (MERGE 방식) ──────────────
    # collect_cs_data.py가 저장한 cs_daily, cs_status_counts, cs_inquiries,
    # cs_week_trend 를 덮어쓰지 않도록 기존 값을 먼저 읽어서 유지.
    existing = {}
    if analyzed_path.exists():
        try:
            with open(analyzed_path, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}

    # CS 관련 필드: 기존 값 우선 (없으면 기본값)
    cs_daily_val        = existing.get("cs_daily",        None)
    cs_status_val       = existing.get("cs_status_counts", {})
    cs_inquiries_val    = existing.get("cs_inquiries",    [])
    # cs_week_trend: collect_cs_data가 덮어쓴 버전이 있으면 그걸 우선 사용
    # (collect_cs_data의 cs_week_trend가 실 수집 기반으로 더 정확)
    cs_wt_existing = existing.get("cs_week_trend")
    cs_week_trend_final = cs_wt_existing if cs_wt_existing else cs_week_trend

    analyzed = {
        "date":              date_label,
        "major_issues":      major_issues,
        "voc_groups":        voc_groups,
        "insights":          insights,
        # CS 필드: 기존 값 보존
        "cs_daily":          cs_daily_val,
        "cs_status_counts":  cs_status_val,
        "cs_inquiries":      cs_inquiries_val,
        "cs_week_trend":     cs_week_trend_final,
    }

    try:
        with open(analyzed_path, "w", encoding="utf-8") as f:
            json.dump(analyzed, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ERR] {date_label} analyzed.json 저장 실패: {e}")
        return "fail_save"

    print(
        f"[OK] {date_label}: "
        f"major_issues={len(major_issues)} "
        f"voc_groups={len(voc_groups)} "
        f"user_posts={len(user_posts)}"
    )
    for g in voc_groups:
        print(f"       [{g['category']}] {g['count']}건  {g['summary'][:45]}")
    if insights.get("trending_keywords"):
        kws = ", ".join(k["word"] for k in insights["trending_keywords"][:5])
        print(f"       trending: {kws}")
    return "ok"


def backfill(force: bool = False) -> dict:
    raw_files = sorted(
        f for f in DATA_DIR.glob("*.json")
        if ".analyzed." not in f.name
    )
    if not raw_files:
        print("[INFO] 처리 대상 raw JSON 없음")
        return {}

    results: dict[str, str] = {}
    print(f"[BACKFILL] 대상: {len(raw_files)}건")
    for f in raw_files:
        status = analyze(f.stem, force=force)
        results[f.stem] = status
        if status == "skip":
            print(f"[SKIP] {f.stem} (analyzed.json 존재)")
        elif status.startswith("fail"):
            print(f"[FAIL] {f.stem} ({status})")

    ok   = sum(1 for s in results.values() if s == "ok")
    skip = sum(1 for s in results.values() if s == "skip")
    fail = sum(1 for s in results.values() if s.startswith("fail"))
    print(f"[BACKFILL] 완료: OK={ok}  SKIP={skip}  FAIL={fail}")
    return results


# ════════════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="DKR VOC 규칙 기반 분석 v4.0")
    parser.add_argument(
        "date", nargs="?",
        default=(datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d"),
        help="분석 날짜 YYYY-MM-DD (기본: 어제)",
    )
    parser.add_argument("--force",    "-f", action="store_true",
                        help="analyzed.json 덮어쓰기")
    parser.add_argument("--backfill",       action="store_true",
                        help="raw 있고 analyzed 없는 날짜 일괄 처리")
    args = parser.parse_args()

    if args.backfill:
        backfill(force=args.force)
    else:
        status = analyze(args.date, force=args.force)
        if status == "skip":
            print(f"[SKIP] {args.date} analyzed.json 이미 존재 (--force 로 덮어쓰기)")
        elif status.startswith("fail"):
            reason = {"fail_no_raw": "raw JSON 없음", "fail_load": "raw 로드 오류",
                      "fail_save": "저장 오류"}.get(status, status)
            print(f"[FAIL] {args.date}: {reason}")
            import sys; sys.exit(1)


if __name__ == "__main__":
    main()
