#!/usr/bin/env python3
"""
analyze_voc.py — DKR 커뮤니티 VOC 규칙 기반 분석기 v6.0
────────────────────────────────────────────────────────
변경 이력:
  v6.0  이슈 타입 기반 의미 병합 시스템 도입
        - ISSUE_TYPES: 의미 기반 이슈 타입 정의 (접속·서버 장애, 매크로 등)
        - classify_issue_type(): board_id 무관 의미 분류
        - generate_group_summary(): fallback 표현 완전 제거, 실제 내용 기반
        - build_voc_groups() 재설계: issue_type 기준 병합 (board_id 제외)
        - _PROFANITY_PATTERN: 변형 욕설 패턴 강화
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

# 욕설 패턴 (변형 포함) — analyze_voc 내부 정제용
_PROFANITY_PATTERN = re.compile(
    # 긴 패턴 우선 (alternation 순서 중요 — 짧은 패턴 먼저 오면 잔류 발생)
    r'(ssibar[a-z]*|ssiba[a-z]*|sibal|sibbal|ㅅㅂ'
    r'|시발[가-힣]*|씨발[가-힣]*'   # "시발려나" 등 한글 잔류 방지
    r'|개[가-힣]{2,5}달|개[가-힣]{2,5}진'   # 개병진스달 등 (긴 것 먼저)
    r'|개[가-힣]{1,2}달|개[가-힣]{1,2}진'   # 개스달, 개병진 등
    r'|개새|개병|개스|개ㅅ'
    r'|ㄲㅈ|뒤져|뒤지|닥쳐|존나|ㅈ나|지랄'
    r'|애미[가-힣]*|니애미[가-힣]*|에미[가-힣]*'
    r'|병신|새끼|꺼져|럼드라|졷같[가-힣]*|새귀[가-힣]*|놈드라)',
    re.IGNORECASE
)


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
    """노이즈 게시글 판별: 제목이 너무 짧거나 자음/모음만인 경우.

    [v6.0] 제목이 짧아도 본문이 충분하면 노이즈 제외
           (예: 제목="헐;;" / 본문="서버 터진게냐? 확인하라" → 유효 게시글)
    """
    title = (post.get("title") or "").strip()
    body  = (post.get("body")  or "").strip()

    # 본문이 충분하면 제목 길이 무관하게 유효 처리
    has_valid_body = len(body) >= 8 and bool(re.search(r'[가-힣]{2,}', body))

    if len(title) < NOISE_MIN_LEN:
        return not has_valid_body    # 본문 있으면 노이즈 아님
    if _NOISE_PATTERN.match(title):
        return not has_valid_body

    # ㅋ/ㅎ 계열 반응성 게시글 필터 (제목의 50% 이상이 ㅋ/ㅎ → 의미 없는 반응글)
    laugh_chars = sum(1 for c in title if c in 'ㅋㅎ')
    if laugh_chars >= 1 and (laugh_chars / max(len(title.replace(' ', '')), 1)) >= 0.5:
        return not has_valid_body

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


# ════════════════════════════════════════════════════════════════════════════
#  ▶ v7.0 normalize → semantic_topic 기반 요약 시스템 (1차)
#
#  데이터 흐름:
#    원문 → normalize_post_text() → classify_semantic_topic()
#    → build_voc_groups()        → generate_group_summary()
#
#  [v6.0 호환]
#    · voc_groups에 issue_type 유지 (dashboard 호환)
#    · semantic_topic 필드 추가
#    · generate_dashboard.py 수정 없음
# ════════════════════════════════════════════════════════════════════════════

# ── NORMALIZE_TABLE ──────────────────────────────────────────────────────────
# 유저 슬랭 / 감정 표현 → 운영용 표준 표현
# 규칙: 긴 표현을 먼저 배치 (짧은 패턴의 오탐 방지)
NORMALIZE_TABLE: list[tuple[str, str]] = [
    # 서버/접속 장애
    ("서버가 터",       "서버 접속 장애"),
    ("서버 터진",       "서버 접속 장애"),
    ("섭이 터",         "서버 접속 장애"),
    ("섭터졌",          "서버 접속 장애"),
    ("섭터",            "서버 접속 장애"),
    ("서버터",          "서버 접속 장애"),
    ("서버 죽",         "서버 접속 장애"),
    ("접속이 안",       "접속 불가"),
    ("접속 안됨",       "접속 불가"),
    ("접속불가",        "접속 불가"),
    ("접속안됨",        "접속 불가"),
    ("로그인 안",       "로그인 불가"),
    ("로그인안됨",      "로그인 불가"),
    ("로그인안",        "로그인 불가"),
    ("렉이 심",         "게임 지연"),
    ("랙이 심",         "게임 지연"),
    ("렉 때문",         "게임 지연"),
    ("랙 때문",         "게임 지연"),
    ("렉걸",            "게임 지연"),
    ("랙걸",            "게임 지연"),
    ("튕김",            "접속 종료"),
    ("팅김",            "접속 종료"),
    ("튕겨",            "접속 종료"),
    ("팅겨",            "접속 종료"),
    ("튕긴",            "접속 종료"),
    ("끊김",            "접속 종료"),
    ("끊겨",            "접속 종료"),
    # 매크로/불법
    ("매크로 안잡",     "매크로 제재 요청"),
    ("메크로 안잡",     "매크로 제재 요청"),
    ("매크로 제재",     "매크로 제재 요청"),
    ("메크로 제재",     "매크로 제재 요청"),
    ("매크로",          "매크로 신고"),
    ("메크로",          "매크로 신고"),
    ("작업장 많",       "작업장 제재 요청"),
    ("작업장 왜",       "작업장 제재 요청"),
    ("작업장",          "작업장 신고"),
    ("자동사냥",        "자동사냥 신고"),
    ("불법프로그램",    "불법 프로그램 신고"),
    ("불법 프로그램",   "불법 프로그램 신고"),
    # 유저 간 분쟁
    ("말걸고 막말",     "유저 간 채팅 분쟁"),
    ("말 걸고 막말",    "유저 간 채팅 분쟁"),
    ("채팅으로 욕",     "채팅 욕설 신고"),
    ("채팅 욕설",       "채팅 욕설 신고"),
    ("채팅 신고",       "채팅 신고 요청"),
    ("욕설 신고",       "채팅 욕설 신고"),
    ("귓말 신고",       "채팅 신고 요청"),
    # 운영 불만
    ("운영 뭐함",       "운영 대응 불만"),
    ("운영뭐함",        "운영 대응 불만"),
    ("운영 뭐해",       "운영 대응 불만"),
    ("운영진 뭐",       "운영 대응 불만"),
    ("뭐하냐고",        "운영 대응 불만"),
    ("뭐하냐",          "운영 대응 불만"),
    ("망겜",            "게임 운영 불만"),
    ("폐겜",            "서비스 종료 우려"),
    ("섭종",            "서비스 종료 우려"),
    ("탈게",            "게임 이탈 의향"),
    ("접겠",            "게임 이탈 의향"),
    ("환불",            "환불 요청"),
    # 과금/강화
    ("현질유도",        "과금 구조 불만"),
    ("현질 유도",       "과금 구조 불만"),
    ("현질 강요",       "과금 구조 불만"),
    ("현질",            "과금 구조 불만"),
    ("과금유도",        "과금 구조 불만"),
    ("강화 확률",       "강화 시스템 불만"),
    ("강화확률",        "강화 시스템 불만"),
    ("강화 터",         "강화 실패 불만"),
    ("강화터",          "강화 실패 불만"),
    # 보상/이벤트
    ("보상 안들어",     "보상 미지급"),
    ("보상이 안",       "보상 미지급"),
    ("보상 누락",       "보상 미지급"),
    ("보상 못",         "보상 미지급"),
    ("보상안됨",        "보상 미지급"),
    ("카운트 안",       "카운트 미적용"),
    ("카운팅 안",       "카운트 미적용"),
    ("카운터 안",       "카운트 미적용"),
    ("횟수 초기화",     "구매 횟수 오류"),
    ("구매횟수",        "구매 횟수 오류"),
    ("구매 횟수",       "구매 횟수 오류"),
    # 기능 오류 — "도 안" 조사 포함 패턴 우선
    ("분해도 안",       "아이템 기능 오류"),
    ("삭제도 안",       "아이템 기능 오류"),
    ("거래도 안",       "거래 기능 오류"),
    ("귓말도 안",       "귓말 기능 오류"),
    ("강화 할수가 없",  "아이템 기능 오류"),   # "전설문장강화 할수가 없습니다"
    ("강화할수가없",    "아이템 기능 오류"),
    ("분해 안",         "아이템 기능 오류"),
    ("삭제 안",         "아이템 기능 오류"),
    ("거래 안",         "거래 기능 오류"),
    ("거래소 안",       "거래 기능 오류"),
    ("귓말 안",         "귓말 기능 오류"),
    ("모두 불가",       "아이템 기능 오류"),   # "분해삭제거래 모두 불가" 커버
    # 건의 — 서버 통합 (다양한 슬랭 커버)
    ("서버 합쳐",       "서버 통합 건의"),
    ("서버 통합",       "서버 통합 건의"),
    ("섭통합",          "서버 통합 건의"),
    ("섭합",            "서버 통합 건의"),
    ("합쳐줘",          "서버 통합 건의"),
    ("썹끼리 묶",       "서버 통합 건의"),   # "짜투리썹끼리묶어서"
    ("써버끼리 묶",     "서버 통합 건의"),
    ("썹끼리묶",        "서버 통합 건의"),
    ("써버끼리묶",      "서버 통합 건의"),
    ("인터섭",          "서버 통합 건의"),
    ("이전권",          "서버 이전권 건의"),
    ("현돌 초기화",     "현돌 초기화 건의"),
    # 건의 — 이벤트/기간 연장
    ("이벤트 연장",     "이벤트 기간 연장 건의"),
    ("이벤트기간",      "이벤트 기간 연장 건의"),
    ("기간 늘려",       "이벤트 기간 연장 건의"),
    ("기간좀더",        "이벤트 기간 연장 건의"),
    # 직업 밸런스
    ("버리는 케릭",     "직업 성능 저하 우려"),   # "팔라딘은 이제 버리는 케릭인가요"
    ("버리는 캐릭",     "직업 성능 저하 우려"),
    ("직업 약",         "직업 밸런스 불만"),
    ("밸런스 안",       "직업 밸런스 불만"),
    # 콘텐츠 통제 — 긴 표현 우선
    ("죽이는건 통제",   "사냥터 통제 문의"),       # "루멘탑에서 죽이는건 통제인가요"
    ("사냥터 통제",     "사냥터 통제 문의"),
    ("던전 통제",       "콘텐츠 통제 문의"),
    # 길드 분쟁 — 구체적 행위 표현 우선
    ("팽쳐버리",        "길드 강제 탈퇴 분쟁"),   # "바로팽쳐버리고" — 길드 강제 추방
    ("팽시키",          "길드 강제 탈퇴 분쟁"),   # "팽시키는"
    ("길드 분쟁",       "길드 간 분쟁"),
    ("빡 길드",         "특정 길드 분쟁"),
    ("강협",            "특정 길드 분쟁"),
    ("막말",            "유저 간 채팅 분쟁"),
    # 이벤트 초기화/재진행 건의
    ("이벤트 초기화",   "이벤트 초기화 건의"),
    ("초기화좀해줘",    "이벤트 초기화 건의"),    # "초기화좀해줘요" 커버
    ("초기화 한번",     "이벤트 초기화 건의"),
    ("이벤트 재진행",   "이벤트 재진행 건의"),
    # 전투/쟁 콘텐츠 재개 의견 (쟁=서버 간 전투 콘텐츠)
    ("쟁합시다",        "전투 콘텐츠 재개 의견"),   # "2주 잘쉬었으니 쟁합시다"
    ("쟁하러",          "전투 콘텐츠 재개 의견"),   # "구섭 쟁하러 가즈아"
    ("쟁 콘텐츠",       "전투 콘텐츠 재개 의견"),
    # 재화 수급 효율 문의 (다야=다이아, 벌이=수익)
    ("다야벌이",        "다이아 수급 관련 문의"),   # "구섭 다야벌이 이정도면"
    ("다야 벌이",       "다이아 수급 관련 문의"),
    ("다야 팔아",       "다이아 수급 관련 문의"),   # "만다야 팔아먹은거"
    # 인터서버 통합 반대 건의 (긴 표현 우선)
    ("인터합치지말고",  "서버 통합 반대 건의"),  # "인터합치지말고 각써버당 농사시즌"
    ("인터합치지",      "서버 통합 반대 건의"),
    ("인터합치는",      "서버 통합 건의"),        # "인터합치는거에요"
    # 인터서버 일정 문의
    ("인터 서버별",     "인터 서버 일정 문의"),
    ("인터서버별",      "인터 서버 일정 문의"),
    ("인터 바뀌",       "인터 서버 일정 문의"),
    ("인터 언제",       "인터 서버 일정 문의"),
    # 접속 장애 변형 표현 (조사 포함 패턴)
    ("튕기더니",        "접속 종료"),             # "갑자기 튕기더니 접 안되요"
    ("접 안되요",       "접속 불가"),
    ("접안돼",          "접속 불가"),
    ("접이 안",         "접속 불가"),
    # 렉/랙 — 단독 사용 금지 (케렉/캐릭 등 오탐 방지)
    # 렉걸, 렉이 심, 렉 때문 등 긴 표현만 위에서 처리
    # ── v7.2 신규: 글로벌/신서버 ─────────────────────────────────────────────
    ("글로벌 오피셜",     "글로벌 서버 공식 발표"),   # "글로벌 오피셜 떴네"
    ("글로벌 출시",       "글로벌 서버 공식 발표"),
    ("글로벌 사전예약",   "글로벌 서버 사전예약"),
    ("글로벌 서버",       "글로벌 서버 정보"),
    ("글로벌",            "글로벌 서버 정보"),         # broad — 비특정 언급
    ("신서버 오픈",       "신서버 정보"),
    ("신서버",            "신서버 정보"),
    ("새서버",            "신서버 정보"),
    ("오피셜",            "공식 발표"),                # "오피셜떴네" 슬랭 처리
    # ── v7.2 신규: 편의성/프리셋 건의 ──────────────────────────────────────────
    ("프리셋 추가",       "프리셋 기능 확장 건의"),
    ("프리셋",            "프리셋 기능 건의"),
    ("편의 패치",         "편의성 개선 건의"),
    ("편의성 패치",       "편의성 개선 건의"),
    ("편의 기능",         "편의성 개선 건의"),
    ("편의성 개선",       "편의성 개선 건의"),
    # ── v7.2 신규: 스킬 모션/표시 오류 ─────────────────────────────────────────
    ("스킬모션 않보",     "스킬 모션 표시 오류"),      # "스킬모션 않보여요"
    ("스킬모션 안보",     "스킬 모션 표시 오류"),
    ("스킬 모션 않보",    "스킬 모션 표시 오류"),
    ("스킬 모션 안보",    "스킬 모션 표시 오류"),
    ("모션 않보여",       "스킬 모션 표시 오류"),
    ("모션 안보여",       "스킬 모션 표시 오류"),
    ("않보여요",          "표시 오류"),                # 범용 표시 오류 fallback
    ("안보여요",          "표시 오류"),
    # ── v7.2 신규: 드랍 오류 ────────────────────────────────────────────────────
    ("드랍안된다",        "아이템 드랍 오류"),         # "드랍안된다 수정좀해라"
    ("드랍 안됨",         "아이템 드랍 오류"),
    ("드랍이 안",         "아이템 드랍 오류"),
    ("드랍 안되",         "아이템 드랍 오류"),
    ("드랍안됨",          "아이템 드랍 오류"),
]


def normalize_post_text(title: str, body: str = "") -> str:
    """유저 원문 → 운영용 정제 텍스트.

    처리 순서:
      1. 캐릭터명/서버명 헤더 제거
      2. 욕설 제거
      3. NORMALIZE_TABLE 치환 (긴 표현 우선)
      4. 감정 부사/이모지 제거
    반환: 운영용 정제 텍스트 (요약·분류에 사용)
    """
    text = f"{title} {body or ''}".strip()

    # 1. 헤더 제거
    text = re.sub(r'캐릭터명\s*:\s*\S+\s*', '', text)
    text = re.sub(r'서버명\s*:\s*\S+\s*', '', text)

    # 2. 욕설 제거
    text = _PROFANITY_PATTERN.sub(' ', text)

    # 3. 다중 공백 정규화 (NORMALIZE_TABLE 스캔 전 필수)
    # body에 연속 공백이 있으면 "죽이는건  통제" ≠ "죽이는건 통제" 로 미매칭
    text = re.sub(r'\s{2,}', ' ', text).strip()

    text_lower = text.lower()
    result_parts = []
    replaced_spans: list[tuple[int, int]] = []

    # 긴 표현부터 매칭 (NORMALIZE_TABLE 순서가 이미 긴 것 우선)
    for slang, formal in NORMALIZE_TABLE:
        idx = text_lower.find(slang)
        while idx != -1:
            end = idx + len(slang)
            # 이미 치환된 범위와 겹치면 스킵
            if not any(s <= idx < e or s < end <= e for s, e in replaced_spans):
                replaced_spans.append((idx, end))
                result_parts.append(formal)
            idx = text_lower.find(slang, end)

    # 치환된 운영용 표현 + 미치환 텍스트 합산
    # 미치환 부분은 원문에서 의미 있는 명사 추출 시도
    if result_parts:
        # 연속 중복 제거 (같은 패턴이 여러 번 매칭된 경우)
        deduped = [result_parts[0]]
        for part in result_parts[1:]:
            if part != deduped[-1]:
                deduped.append(part)
        normalized = " ".join(deduped)
    else:
        # 치환 없음 → 원문 정제본 그대로 사용
        normalized = re.sub(r'\s+', ' ', text).strip()

    # 4. 감정 부사 제거 (요약 노출 방지)
    _EMOT = re.compile(r'(진짜|정말|ㅋㅋ+|ㅠㅠ+|ㅎㅎ+|ㄷㄷ+|ㅜㅜ+|헐+|대박|미쳤|미쳐|개웃|개쩐)')
    normalized = _EMOT.sub('', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()

    return normalized


# ── TOPIC_RULES ──────────────────────────────────────────────────────────────
# (topic_key, [normalized 텍스트에서 탐색할 운영 표현 목록], 매핑 카테고리)
# 순서 = 우선순위 (구체적인 것 먼저)
TOPIC_RULES: list[tuple[str, list[str], str]] = [
    ("매크로신고",       ["매크로 신고", "매크로 제재 요청", "작업장 신고",
                         "작업장 제재 요청", "자동사냥 신고", "불법 프로그램 신고"],    "게임 관련"),
    ("콘텐츠진행불가",   ["소탕 불가", "입장 불가", "클리어 불가", "던전 소탕",
                         "던전 진행 불가", "소탕이 안"],                                "버그·오류"),
    ("보상오류",         ["보상 미지급", "카운트 미적용", "구매 횟수 오류",
                         "이벤트 보상 오류"],                                           "버그·오류"),
    ("서버접속장애",     ["서버 접속 장애", "접속 불가", "로그인 불가",
                         "게임 지연", "접속 종료", "서버 다운"],                        "버그·오류"),
    ("아이템기능오류",   ["아이템 기능 오류", "거래 기능 오류", "귓말 기능 오류",
                         "기능 오류", "기능 오작동",
                         "스킬 모션 표시 오류", "표시 오류", "아이템 드랍 오류"],      "버그·오류"),
    ("채팅분쟁",         ["유저 간 채팅 분쟁", "채팅 욕설 신고", "채팅 신고 요청"],    "게임 관련"),
    ("거래시세",         ["거래 가격", "시세"],                                         "게임 관련"),
    ("서버통합건의",     ["서버 통합 건의", "서버 이전권 건의"],                        "건의·요청"),
    ("콘텐츠건의",       ["현돌 초기화 건의", "콘텐츠 추가", "개선 요청",
                         "이벤트 기간 연장 건의"],                                    "건의·요청"),
    # ── v7.2 신규 topics ─────────────────────────────────────────────────────
    ("글로벌신서버",     ["글로벌 서버 공식 발표", "글로벌 서버 사전예약",
                         "글로벌 서버 정보", "신서버 정보"],                          "게임 관련"),
    ("편의성건의",       ["프리셋 기능 확장 건의", "프리셋 기능 건의",
                         "편의성 개선 건의"],                                         "건의·요청"),
    ("과금불만",         ["과금 구조 불만", "환불 요청"],                               "기타"),
    ("강화불만",         ["강화 시스템 불만", "강화 실패 불만"],                       "기타"),
    ("서비스종료우려",   ["서비스 종료 우려", "게임 이탈 의향"],                       "기타"),
    ("운영불만",         ["운영 대응 불만", "게임 운영 불만"],                         "기타"),
    # ── v7.1 신규 topic ──────────────────────────────────────────────────────
    ("직업밸런스",       ["직업 성능 저하 우려", "직업 밸런스 불만"],                  "게임 관련"),
    ("콘텐츠통제",       ["사냥터 통제 문의", "콘텐츠 통제 문의"],                     "게임 관련"),
    ("길드분쟁",         ["길드 강제 탈퇴 분쟁", "특정 길드 분쟁", "길드 간 분쟁"],   "게임 관련"),
    ("이벤트초기화건의", ["이벤트 초기화 건의", "이벤트 재진행 건의"],                "건의·요청"),
    ("인터서버문의",     ["인터 서버 일정 문의"],                                       "게임 관련"),
    ("재화수급문의",     ["다이아 수급 관련 문의"],                                      "게임 관련"),
    ("전투콘텐츠의견",   ["전투 콘텐츠 재개 의견"],                                      "게임 관련"),
    ("기타",             [],                                                            "기타"),
]

# topic → 대시보드 표시용 카테고리 매핑
TOPIC_CATEGORY: dict[str, str] = {t: cat for t, _, cat in TOPIC_RULES}

# topic → 이슈 타입 역매핑 (dashboard 호환용 issue_type 유지)
TOPIC_TO_ISSUE_TYPE: dict[str, str] = {
    "서버접속장애":    "접속·서버 장애",
    "콘텐츠진행불가":  "던전·콘텐츠 진행 불가",
    "보상오류":        "아이템·보상 오류",
    "아이템기능오류":  "기능·스킬 오류",
    "매크로신고":      "매크로·불법 행위 제보",
    "채팅분쟁":        "게임 개선 건의",
    "거래시세":        "가격·거래 문의",
    "서버통합건의":    "서버 통합·이전 건의",
    "콘텐츠건의":      "게임 개선 건의",
    "과금불만":        "운영·정책 불만",
    "강화불만":        "운영·정책 불만",
    "서비스종료우려":  "서비스 종료 우려",
    "운영불만":        "운영·정책 불만",
    "직업밸런스":        "게임 일반",
    "콘텐츠통제":        "게임 일반",
    "길드분쟁":          "게임 일반",
    "이벤트초기화건의":  "게임 개선 건의",
    "인터서버문의":      "게임 일반",
    "재화수급문의":      "게임 일반",
    "전투콘텐츠의견":    "게임 일반",
    "글로벌신서버":      "게임 일반",
    "편의성건의":        "게임 개선 건의",
    "기타":              "게임 일반",
}


def classify_semantic_topic(normalized_text: str) -> str:
    """normalize 된 텍스트 → semantic topic.

    TOPIC_RULES의 운영용 표현 포함 여부로 판단.
    (raw 원문이 아닌 normalized 결과에서 탐색 → 오탐 방지)
    """
    for topic, expressions, _ in TOPIC_RULES[:-1]:   # 마지막 "기타" 제외
        if expressions and any(expr in normalized_text for expr in expressions):
            return topic
    return "기타"


def extract_dominant_phenomena(posts_normalized: list[str], topic: str) -> list[str]:
    """그룹 내 normalized 텍스트들에서 등장 빈도 상위 현상 추출.

    반환: 빈도 내림차순 현상 목록 (최대 2개)
    """
    if not posts_normalized:
        return []

    # topic별 현상 어휘 풀
    topic_vocab: dict[str, list[str]] = {
        "서버접속장애":   ["서버 접속 장애", "접속 불가", "로그인 불가",
                           "게임 지연", "접속 종료"],
        "보상오류":       ["보상 미지급", "카운트 미적용", "구매 횟수 오류"],
        "매크로신고":     ["매크로 신고", "매크로 제재 요청",
                           "작업장 신고", "작업장 제재 요청",
                           "자동사냥 신고", "불법 프로그램 신고"],
        "콘텐츠진행불가": ["소탕 불가", "입장 불가", "클리어 불가"],
        "아이템기능오류": ["아이템 기능 오류", "거래 기능 오류",
                           "귓말 기능 오류"],
        "채팅분쟁":       ["유저 간 채팅 분쟁", "채팅 욕설 신고",
                           "채팅 신고 요청"],
        "과금불만":       ["과금 구조 불만", "환불 요청"],
        "강화불만":       ["강화 시스템 불만", "강화 실패 불만"],
        "운영불만":       ["운영 대응 불만", "게임 운영 불만"],
    }

    vocab = topic_vocab.get(topic, [])
    if not vocab:
        return []

    combined = " ".join(posts_normalized)
    freq = [(v, combined.count(v)) for v in vocab if v in combined]
    freq.sort(key=lambda x: -x[1])
    return [v for v, _ in freq[:2]]

# 이슈 타입 정의 — 순서가 우선순위 (구체적인 타입이 앞에 와야 함)
# (이슈타입명, [매칭 키워드], 매핑 카테고리)
ISSUE_TYPES: list[tuple[str, list[str], str]] = [
    # ① 매크로 — 구체적 표현 우선, "메크로"(오타)도 포함
    ("매크로·불법 행위 제보",
     ["매크로", "메크로", "작업장", "불법 프로그램", "다중 접속 의심", "자동사냥"],
     "게임 관련"),
    # ② 던전 소탕/진행 불가
    ("던전·콘텐츠 진행 불가",
     ["소탕 안됨", "소탕불가", "소탕 불가", "소탕이 안", "입장불가", "입장 불가",
      "클리어가 안", "클리어 안됨", "시련의 던전 권장", "던전 소탕",
      "소탕이안", "소탕안됨"],
     "버그·오류"),
    # ③ 아이템/보상 오류 — 접속과 분리 (카운트, 보상, 이벤트 관련)
    ("아이템·보상 오류",
     ["보상 안됨", "보상 안 됨", "보상이 안", "보상 못", "미지급",
      "파이썬의 요람", "파이썬의요람", "파이썬 요람", "잊혀진탑", "잊탑",
      "미션 이벤트", "카운트가 안", "카운트 안됨", "카운트 안돼",
      "카운트안됨", "카운팅 안됨", "카운터 안됨",
      "구매 횟수", "구매횟수", "횟수 초기화", "횟수가 안"],
     "버그·오류"),
    # ④ 접속/서버 장애 — 단음절 "팅" 제거 (카운팅에 오탐 방지), 섭터 추가
    ("접속·서버 장애",
     ["렉", "랙", "접속불가", "접속 불가", "접속이 안", "접속안됨",
      "로그인 안", "로그인안", "서버터", "서버가 터", "서버 터진",
      "서버 죽", "섭터", "터졌", "터짐", "튕김", "팅김",
      "튕겨", "팅겨", "끊겨", "끊김", "지연"],
     "버그·오류"),
    # ⑤ 기능/스킬 오류
    ("기능·스킬 오류",
     ["버그", "오류", "에러", "error", "씹힘", "십힘", "미적용",
      "작동 안", "작동안", "안됨", "안 됨", "먹통", "오작동"],
     "버그·오류"),
    # ⑥ 서버 통합/이전
    ("서버 통합·이전 건의",
     ["서버 통합", "섭 통합", "섭통합", "합쳐", "인터섭", "섭합",
      "서버 합병", "이전권", "서버이전권"],
     "건의·요청"),
    # ⑦ 게임 개선 건의
    ("게임 개선 건의",
     ["건의", "개선", "제안", "추가해", "해주세요", "해주셨으면",
      "넣어줘", "나왔으면", "출시해", "부탁드립", "부탁드려",
      "제발", "있으면 좋겠", "했으면 좋겠", "해줬으면"],
     "건의·요청"),
    # ⑧ 서비스 종료 우려
    ("서비스 종료 우려",
     ["섭종", "서비스 종료", "서비스종료", "폐겜", "폐서비스", "망겜"],
     "기타"),
    # ⑨ 운영 불만
    ("운영·정책 불만",
     ["운영 뭐", "운영뭐", "뭐하냐", "환불", "접는다", "탈게", "탈주",
      "개판", "엉망", "한심", "뭐하는 거", "운영진"],
     "기타"),
    # ⑩ 가격/거래 — "거래" 단독 키워드 제거 (거래 기능 오류와 혼동)
    # "거래도안되고" 같은 기능 오류는 기능·스킬 오류 또는 게임 일반으로 분류
    ("가격·거래 문의",
     ["시세", "팔린", "팔고", "거래 가격", "얼마에", "사노", "거래 얼마", "팔아요"],
     "게임 관련"),
    # ⑪ 게임 일반 (최후 fallback — 반드시 실제 내용 기반 요약 생성)
    ("게임 일반", [], "게임 관련"),
]

# CS 카테고리 → 이슈 타입 매핑 (generate_dashboard.py 크로스 링크용)
CS_CATEGORY_TO_ISSUE_TYPE: dict[str, str] = {
    "오류":      "접속·서버 장애",
    "설치/실행": "접속·서버 장애",
    "이벤트":   "아이템·보상 오류",
    "게임 이용": "기능·스킬 오류",
    "건의":     "게임 개선 건의",
}


# ── 요약 품질 검증용 상수 ────────────────────────────────────────────────────

# 욕설 제거 후 남는 의미 없는 음절 파편 패턴
_RESIDUE_PATTERN = re.compile(r'(려나|스달|ㅌ은|새귀|달이|병진스|럼드|새귀듫|새귀들)')

# 이슈 타입별 검증 실패 시 fallback 요약
# 규칙: [이슈 타입] + [핵심 현상], 카테고리명 단독 금지
_ISSUE_TYPE_FALLBACK: dict[str, str] = {
    "접속·서버 장애":        "서버 접속 불가 및 게임 지연 현상",
    "매크로·불법 행위 제보": "매크로 사용 의심 유저 제보",
    "던전·콘텐츠 진행 불가": "던전 콘텐츠 소탕 불가 현상",
    "아이템·보상 오류":      "이벤트·아이템 보상 오류 현상",
    "기능·스킬 오류":        "게임 내 기능 오작동 현상",
    "서버 통합·이전 건의":   "서버 통합 건의",
    "게임 개선 건의":        "게임 개선·콘텐츠 추가 건의",
    "서비스 종료 우려":      "서비스 종료 우려 및 게임 비판",
    "운영·정책 불만":        "운영 정책에 대한 유저 불만",
    "가격·거래 문의":        "게임 내 거래·시세 관련 문의",
    "게임 일반":             "게임 이용 관련 기타 문의",
    "글로벌신서버":          "신서버/글로벌 서버 정보 및 사전예약 관련 문의",
    "편의성건의":            "프리셋 기능 확장 및 편의성 개선 건의",
}


def _validate_summary(text: str) -> bool:
    """요약 품질 검증. True=유효 / False=fallback 필요.

    기준:
      1. 최소 8자 이상
      2. 실제 한글/영어 단어(2자 이상) 포함
      3. 욕설 잔류 없음
      4. 의미 없는 음절 파편 없음
    """
    if not text or len(text.strip()) < 8:
        return False
    if not re.search(r'[가-힣a-zA-Z]{2,}', text):
        return False
    if _PROFANITY_PATTERN.search(text):
        return False
    if _RESIDUE_PATTERN.search(text):
        return False
    return True


# ── v6.0 헬퍼 함수 ───────────────────────────────────────────────────────────

def _remove_profanity(text: str) -> str:
    """욕설 패턴 제거 후 반환"""
    if not text:
        return ""
    return _PROFANITY_PATTERN.sub("", text).strip()


def _extract_meaningful_sentence(text: str, max_len: int = 60) -> str:
    """본문에서 의미있는 첫 문장 추출.

    처리:
      1. 캐릭터명/서버명 헤더 제거
      2. 욕설 제거
      3. 최소 6자 이상, 실제 한글/영어 포함 문장 반환
    """
    if not text:
        return ""
    t = re.sub(r'캐릭터명\s*:\s*\S+\s*', '', text)
    t = re.sub(r'서버명\s*:\s*\S+\s*', '', t)
    t = _remove_profanity(t)
    sentences = re.split(r'[.!?\n]', t)
    for sent in sentences:
        sent = re.sub(r'\s+', ' ', sent).strip()
        if len(sent) < 6:
            continue
        # 자음/모음/특수문자만인 경우 스킵
        if re.match(r'^[ㄱ-ㅎㅏ-ㅣ\s?!.…~,ㅋㅠ]+$', sent):
            continue
        # 실제 한글/영어 단어 포함 여부
        if re.search(r'[가-힣a-zA-Z]{2,}', sent):
            return sent[:max_len]
    return ""


def classify_issue_type(post: dict) -> str:
    """게시글 하나 → 이슈 타입명.

    board_id 무관 — 제목+본문 의미 기반 분류.
    ISSUE_TYPES 순서(우선순위)대로 탐색.
    """
    text = f"{post.get('title', '')} {post.get('body', '') or ''}".lower()
    for issue_type, keywords, _ in ISSUE_TYPES[:-1]:   # 마지막 "게임 일반" 제외
        if keywords and any(kw in text for kw in keywords):
            return issue_type
    return "게임 일반"


def generate_group_summary(topic: str, posts: list,
                           posts_normalized: list[str] | None = None) -> str:
    """semantic_topic + 게시글 목록 → 보고용 요약 (v7.0).

    [원칙]
      · 고정 문장 반환 금지 — 반드시 현상/내용 기반
      · normalized 텍스트에서 지배적 현상 추출 후 문장 조합
      · 원문(raw) 그대로 summary에 넣지 않음
    """
    if posts_normalized is None:
        posts_normalized = [
            normalize_post_text(p.get("title", ""), p.get("body", "") or "")
            for p in posts
        ]

    combined_title = " ".join(p.get("title", "") for p in posts)
    combined_body  = " ".join(p.get("body", "") or "" for p in posts)
    combined_raw   = f"{combined_title} {combined_body}"
    combined_norm  = " ".join(posts_normalized)

    # ── 고유 정보 추출 (원문에서) ────────────────────────────────
    server_m = re.search(r'(\d+)\s*섭', combined_title)
    server_s = f"{server_m.group(1)}서버 " if server_m else ""

    # ── topic별 현상 빈도 기반 문장 조합 ────────────────────────

    if topic == "서버접속장애":
        phenomena = extract_dominant_phenomena(posts_normalized, topic)
        if phenomena:
            p1 = phenomena[0]
            p2 = phenomena[1] if len(phenomena) > 1 and phenomena[1] != p1 else None
            if p2:
                return f"{server_s}{p1} 및 {p2} 현상 보고"
            return f"{server_s}{p1} 현상 보고"
        return f"{server_s}서버 접속 오류 현상 보고"

    if topic == "매크로신고":
        phenomena = extract_dominant_phenomena(posts_normalized, topic)
        guild = ""
        if "좀비" in combined_raw.lower():
            guild = "좀비 길드 "
        else:
            en_m = re.search(r'[A-Z][A-Z]+', combined_raw)
            if en_m:
                guild = en_m.group(0) + " 길드 "
        main_phen = phenomena[0] if phenomena else "매크로 신고"
        return f"{server_s}{guild}{main_phen} 관련 제재 요청"

    if topic == "콘텐츠진행불가":
        dungeon_m = re.search(
            r'(시련의\s*던전|파이썬의\s*요람|[가-힣]+\s*던전)',
            combined_raw
        )
        dungeon = dungeon_m.group(0).strip() if dungeon_m else "던전"
        floor_m = re.search(r'(\d+)\s*층', combined_raw)
        floor_s = f" {floor_m.group(1)}층" if floor_m else ""
        phenomena = extract_dominant_phenomena(posts_normalized, topic)
        phen = phenomena[0] if phenomena else "소탕 불가"
        return f"{dungeon}{floor_s} {phen} 현상"

    if topic == "보상오류":
        # 구체적 이벤트/보상명 추출
        if "파이썬" in combined_raw or "요람" in combined_raw:
            return "미션 이벤트 파이썬의 요람 카운트 미적용 현상"
        if "잊혀진탑" in combined_raw or "잊탑" in combined_raw:
            return "잊혀진탑 보상 미지급 현상"
        phenomena = extract_dominant_phenomena(posts_normalized, topic)
        event_m = re.search(r'([가-힣a-zA-Z]+\s*이벤트)', combined_title)
        event_s = event_m.group(0) + " " if event_m else ""
        phen = phenomena[0] if phenomena else "보상 오류"
        return f"{event_s}{phen} 현상"

    if topic == "아이템기능오류":
        # 분해/삭제/거래 "불가" 서브케이스 — 우선 처리
        BUGA_FEATS = ["분해", "삭제", "거래"]
        found_feats = [f for f in BUGA_FEATS if f in combined_raw]
        is_buga = any(kw in combined_raw for kw in
                      ["불가", "안됩니다", "안되고", "안돼요", "안됨", "안돼"])
        if found_feats and is_buga:
            feat_str = "·".join(found_feats)
            return f"아이템 {feat_str} 불가 현상"

        # 귓말 기능 오류
        if "귓말" in combined_raw and is_buga:
            return "귓말 기능 오류 현상"

        # 일반 기능 오류 — 기능명 추출 후 현상 조합
        feat_m = re.search(
            r'(귓말|거래소|분해|삭제|인형|강화|스킬|소환|구매|거래)',
            combined_raw
        )
        if feat_m:
            # "강화 기능 오류" 처럼 기능명 + "기능 오류"로 조합 (중복 방지)
            return f"{feat_m.group(1)} 기능 오류 현상"
        phenomena = extract_dominant_phenomena(posts_normalized, topic)
        phen = phenomena[0] if phenomena else "기능 오류"
        return f"{phen} 현상"

    if topic == "채팅분쟁":
        phenomena = extract_dominant_phenomena(posts_normalized, topic)
        phen = phenomena[0] if phenomena else "유저 간 채팅 분쟁"
        return f"{phen} 신고 및 처리 요청"

    if topic == "서버통합건의":
        if "이전권" in combined_raw:
            return "서버 이전권 아이템 출시 건의"
        return "서버 통합 건의"

    if topic == "콘텐츠건의":
        if "현돌" in combined_raw and "초기화" in combined_raw:
            return "현돌 초기화 콘텐츠 출시 건의"
        # normalize 결과에서 건의 내용 우선 사용 (raw body 노출 방지)
        if posts_normalized:
            norm_combined = " ".join(posts_normalized)
            if "이벤트 기간 연장 건의" in norm_combined:
                # 이벤트명 추출 시도 (원문에서)
                event_m = re.search(
                    r'(\d+주년\s*이벤트|[가-힣a-zA-Z]+\s*이벤트)', combined_raw
                )
                prefix = event_m.group(0) + " " if event_m else ""
                return f"{prefix}기간 연장 건의"
        # 의미 있는 건의 내용 추출 (원문 title 우선 — body보다 간결)
        sent = _extract_meaningful_sentence(combined_title)
        if sent and len(sent) >= 6:
            return sent[:60]
        sent = _extract_meaningful_sentence(combined_body)
        if sent and len(sent) >= 10:
            return sent[:60]
        return "게임 콘텐츠 개선 건의"

    if topic == "과금불만":
        phenomena = extract_dominant_phenomena(posts_normalized, topic)
        phen = phenomena[0] if phenomena else "과금 구조 불만"
        return f"{phen} 관련 유저 의견"

    if topic == "강화불만":
        phenomena = extract_dominant_phenomena(posts_normalized, topic)
        phen = phenomena[0] if phenomena else "강화 시스템 불만"
        return f"{phen} 관련 유저 의견"

    if topic == "서비스종료우려":
        return "서비스 종료 우려 및 게임 비판"

    if topic == "운영불만":
        phenomena = extract_dominant_phenomena(posts_normalized, topic)
        phen = phenomena[0] if phenomena else "운영 대응 불만"
        return f"{phen} 관련 유저 의견"

    if topic == "거래시세":
        return "게임 내 아이템 거래·시세 관련 의견"

    if topic == "직업밸런스":
        # 직업명 추출 (원문 title에서)
        job_m = re.search(
            r'(팔라딘|소서리스|소서|워리어|워로크|버서커|아처|나이트|메이지|검사|마법사)',
            combined_raw
        )
        if job_m:
            return f"{job_m.group(1)} 직업 성능 저하 우려"
        return "직업 밸런스 관련 유저 불만"

    if topic == "콘텐츠통제":
        # 콘텐츠명/장소 추출
        content_m = re.search(r'(루멘탑|루멘|던전|사냥터|필드)', combined_raw)
        if content_m:
            loc = content_m.group(1)
            # 루멘탑·루멘·필드는 "사냥터" 명시
            suffix = " 사냥터" if loc in ("루멘탑", "루멘", "필드") else ""
            return f"{loc}{suffix} 통제 관련 유저 문의"
        return "콘텐츠/사냥터 통제 관련 유저 문의"

    if topic == "길드분쟁":
        combined_norm_str = " ".join(posts_normalized) if posts_normalized else ""
        if "길드 강제 탈퇴 분쟁" in combined_norm_str:
            return "길드 강제 탈퇴 관련 분쟁 유저 불만"
        if "특정 길드 분쟁" in combined_norm_str:
            # 구체 길드명/캐릭명 추출 시도 (원문 title에서)
            guild_m = re.search(r'빡\s*길드|강협', combined_raw)
            if guild_m:
                return f"특정 길드({guild_m.group(0).strip()}) 분쟁 관련 유저 의견"
        return "길드 간 분쟁 관련 유저 의견"

    if topic == "인터서버문의":
        return "인터 서버 로테이션 일정 관련 문의"

    if topic == "전투콘텐츠의견":
        # "연휴" 키워드 있으면 연휴 맥락 명시
        if "연휴" in combined_raw:
            return "연휴 이후 쟁 콘텐츠 재개 관련 유저 의견"
        return "게임 내 전투 콘텐츠 재개 관련 유저 의견"

    if topic == "재화수급문의":
        # "구섭" 유무에 따라 접두어 구분
        server_prefix = "구 서버 " if any(kw in combined_raw for kw in ["구섭", "구 서버"]) else ""
        return f"{server_prefix}다이아 수급 효율 관련 유저 문의"

    if topic == "이벤트초기화건의":
        # 이벤트명 추출 시도
        event_m = re.search(
            r'(\d+주년\s*이벤트|[가-힣a-zA-Z]+\s*이벤트|스페셜\s*\S+)', combined_raw
        )
        if event_m:
            return f"{event_m.group(0)} 초기화 및 재진행 건의"
        return "이벤트 초기화 및 재진행 건의"

    if topic == "글로벌신서버":
        if "사전예약" in combined_raw:
            return "신서버/글로벌 서버 사전예약 관련 문의"
        if "글로벌" in combined_raw:
            return "신서버/글로벌 서버 정보 및 사전예약 관련 문의"
        return "신서버 정보 및 일정 관련 문의"

    if topic == "편의성건의":
        if "프리셋" in combined_raw:
            return "프리셋 기능 확장 및 편의성 개선 건의"
        return "게임 편의성 개선 건의"

    # ── 기타 topic (분류 불가) — 원문 직접 노출 금지, 키워드 기반 분류 ──────
    combined_lower = combined_raw.lower()

    # 긍정 피드백/감상
    if any(kw in combined_lower for kw in
           ["재밌", "재미있", "좋아요", "감사합니", "기대돼", "기대됩", "재밌네"]):
        return "게임 긍정 피드백 및 일반 의견"

    # 스킬/캐릭터 관련 표시/기능 오류 (아이템기능오류로 분류 못된 잔류분)
    if any(kw in combined_lower for kw in ["스킬", "모션", "워리어", "소서", "팔라", "마법"]):
        if any(kw in combined_lower for kw in ["안보", "않보", "오류", "버그", "이상", "않됨"]):
            return "스킬·콘텐츠 표시 오류 관련 유저 의견"
        if any(kw in combined_lower for kw in ["수정", "고쳐", "바꿔", "패치"]):
            return "스킬·콘텐츠 개선 관련 건의"

    # 드랍/아이템 관련
    if any(kw in combined_lower for kw in ["드랍", "드롭", "아이템 수급"]):
        return "아이템 드랍·수급 관련 유저 의견"

    # 이벤트/일정 문의
    if any(kw in combined_lower for kw in ["언제", "일정", "공지", "업데이트 언제"]):
        return "게임 일정·업데이트 관련 문의"

    # 건의/개선 감지 (건의 게시판 미분류 잔류)
    if any(kw in combined_lower for kw in
           ["해주세요", "해줘요", "넣어주", "추가해", "개선해", "수정해", "부탁"]):
        return "게임 개선·기능 추가 관련 건의"

    # 서버/타 서버 이전 문의
    if any(kw in combined_lower for kw in ["서버 이전", "이전권", "서버 합", "섭 합"]):
        return "서버 이전·통합 관련 문의"

    # fallback — 고정 문장 (원문 노출 완전 차단)
    return "기타 유저 의견"


def build_voc_groups(user_posts: list) -> list:
    """v7.0: normalize → semantic_topic 기반 그룹핑 + 요약

    변경 (v6.0->v7.0):
      - normalize_post_text() 레이어 추가
      - classify_semantic_topic() 으로 분류 (TOPIC_RULES 기반)
      - generate_group_summary() 고정 문장 제거, 현상 빈도 기반 조합
      - voc_groups에 semantic_topic 추가 (issue_type 병행 유지 — dashboard 호환)
    """
    # 1. feed_id 중복 제거
    posts = dedup_by_feed_id(user_posts)

    # 2. 노이즈 처리
    if FILTER_NOISE:
        posts = [p for p in posts if not is_noise(p)]

    # 3. normalize + semantic_topic 분류
    typed: list[tuple[str, str, dict, str]] = []   # (topic, issue_type, post, normalized)
    for p in posts:
        norm = normalize_post_text(p.get("title", ""), p.get("body", "") or "")
        topic = classify_semantic_topic(norm)
        # dashboard 호환용 issue_type 유지 (v6.0 classify_issue_type 재사용)
        issue_type = TOPIC_TO_ISSUE_TYPE.get(topic, classify_issue_type(p))
        typed.append((topic, issue_type, p, norm))

    # 4. semantic_topic 기준 그룹핑
    topic_groups: dict[str, list[tuple]] = defaultdict(list)
    for row in typed:
        topic_groups[row[0]].append(row)

    # 5. TOPIC_RULES 순서로 결과 생성
    result = []
    for topic, _, category in TOPIC_RULES:
        rows = topic_groups.get(topic, [])
        if not rows:
            continue

        group_posts      = [r[2] for r in rows]
        posts_normalized = [r[3] for r in rows]
        issue_type       = rows[0][1]   # 그룹 내 첫 번째 issue_type (대표)

        # 요약 생성 (v7.0 — 현상 기반)
        summary = generate_group_summary(topic, group_posts, posts_normalized)
        if not _validate_summary(summary):
            summary = _ISSUE_TYPE_FALLBACK.get(issue_type, "게임 관련 이슈 보고")

        # 대표글: engagement 가중치 최고
        top = max(
            group_posts,
            key=lambda p: p.get("comment_count", 0) * 2 + p.get("like_count", 0)
        )
        feed_ids = [str(p.get("feed_id", "")) for p in group_posts]

        result.append({
            "semantic_topic":     topic,       # v7.0 신규
            "issue_type":         issue_type,  # v6.0 유지 (dashboard 호환)
            "category":           category,
            "summary":            summary,
            "count":              len(group_posts),
            "representative_url": top.get("url", ""),
            "feed_ids":           feed_ids,
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
