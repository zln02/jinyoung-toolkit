"""review_analyzer.ui._helpers — 공용 헬퍼 (URL 검증, 컬럼 추론 등).

보안 관련 함수(_validate_url, _is_private_host)는 시그니처·동작 그대로 유지.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd
import streamlit as st

from review_analyzer.preset_loader import PresetLoader

# ---------------------------------------------------------------------------
# 모듈 상수
# ---------------------------------------------------------------------------

PRESET_EMOJI: dict[str, str] = {
    "eleven_st": "🛒",
    "coupang_reviews": "🛒",
    "naver_shopping": "🛒",
    "amazon_reviews": "🛒",
    "yes24_book": "📚",
    "cgv_movie": "🎬",
    "melon_song": "🎵",
    "google_play": "📱",
    "apple_app_store": "📱",
    "youtube_comments": "📺",
    "naver_blog": "📝",
    "naver_cafe": "💬",
    "yanolja_hotel": "🏨",
    "custom_template": "⚙️",
}

SEARCH_PLACEHOLDERS: dict[str, str] = {
    "amazon_reviews": "예: wireless earbuds",
    "coupang_reviews": "예: 무선청소기",
    "naver_shopping": "예: 겨울 코트",
    "eleven_st": "예: 에어프라이어",
    "yes24_book": "예: 클린 코드",
    "cgv_movie": "예: 어벤져스",
    "melon_song": "예: BTS",
    "google_play": "예: 카카오톡",
    "apple_app_store": "예: 인스타그램",
    "youtube_comments": "예: 운동 루틴",
    "naver_blog": "예: 부산 여행",
    "naver_cafe": "예: 자취 꿀팁",
    "yanolja_hotel": "예: 제주 호텔",
}

TEXT_HINTS = ("content", "review", "text", "내용", "리뷰", "댓글", "comment")
RATING_HINTS = ("rating", "star", "score", "평점", "별점", "점수")


# ---------------------------------------------------------------------------
# 캐싱 헬퍼
# ---------------------------------------------------------------------------


@st.cache_resource
def _get_preset_loader() -> PresetLoader:
    """싱글톤 PresetLoader. rerun마다 재생성 방지."""
    return PresetLoader()


@st.cache_data
def list_all_presets() -> list[dict[str, Any]]:
    """14개 프리셋 메타데이터. rerun마다 디스크 IO 방지."""
    return _get_preset_loader().list_presets()


@st.cache_data
def load_preset_dict(name: str) -> dict[str, Any]:
    """프리셋 dict. 같은 이름은 한 번만 로드."""
    return _get_preset_loader().load(name)


@st.cache_data
def load_sample_df() -> "pd.DataFrame | None":
    """샘플 50건 CSV. rerun마다 디스크 IO 방지."""
    from pathlib import Path

    sample_path = (
        Path(__file__).resolve().parent.parent.parent
        / "tests"
        / "fixtures"
        / "sample_reviews_50.csv"
    )
    if not sample_path.exists():
        return None
    return pd.read_csv(sample_path, encoding="utf-8-sig")


# ---------------------------------------------------------------------------
# URL 검증 (보안 관련 — 시그니처·동작 변경 금지)
# ---------------------------------------------------------------------------


def _validate_url(raw: str) -> str | None:
    """URL 형식 검증 후 정규화된 URL 반환. 유효하지 않으면 None."""
    stripped = (raw or "").strip()
    if not stripped:
        return None
    if not (stripped.startswith("http://") or stripped.startswith("https://")):
        return None
    return stripped


def _is_private_host(url: str) -> bool:
    """URL 호스트가 사설 IP 대역인지 확인한다.

    Returns:
        True이면 사설/루프백 호스트 — SSRF 방지를 위해 요청 거부해야 함.
    """
    import ipaddress
    import urllib.parse

    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback
    except ValueError:
        # 호스트가 IP가 아닌 도메인이면 False (DNS 단계 검사는 별도)
        return False


# ---------------------------------------------------------------------------
# 컬럼 추론 헬퍼
# ---------------------------------------------------------------------------


def _match_hint(col_lower: str, hint: str) -> bool:
    """힌트 매칭. 영문은 단어 경계(reviewer 오탐 방지), 한글은 부분일치 허용.

    한글에는 단어 경계 개념이 없어 '번역내용(한국어)' 같은 합성 컬럼명에서
    '내용' 힌트를 놓치고 자동 추천이 엉뚱한 컬럼으로 가는 문제를 해결한다.
    """
    if any("가" <= ch <= "힣" for ch in hint):
        return hint in col_lower
    return re.search(rf"(^|[_\s\-]){re.escape(hint)}([_\s\-]|$)", col_lower) is not None


def _korean_ratio(series: pd.Series) -> float:
    """문자열 컬럼의 한글 음절 비율(0.0~1.0). 한국어 분석기에 적합한 컬럼 가중치."""
    text = "".join(series.dropna().astype(str).head(50).tolist())
    if not text:
        return 0.0
    korean = sum(1 for ch in text if "가" <= ch <= "힣")
    return korean / len(text)


def guess_text_column(df: pd.DataFrame) -> str | None:
    """텍스트(리뷰 내용) 컬럼을 휴리스틱으로 추측.

    1) hint 정확 일치 → 즉시 반환
    2) hint 매칭 컬럼이 여러 개면 한글 비율 최대 우선 (한국어 형태소 분석기 도구이므로
       '원본내용(영어)'·'번역내용(한국어)' 같이 둘 다 매칭되면 한국어 컬럼을 고른다)
    3) 매칭 0개면 평균 길이 최대 object 컬럼 fallback
    """
    cols = list(df.columns)
    cols_lower = [(c, str(c).lower()) for c in cols]

    for hint in TEXT_HINTS:
        for col, col_lower in cols_lower:
            if col_lower == hint:
                return col

    candidates: list[str] = []
    for hint in TEXT_HINTS:
        for col, col_lower in cols_lower:
            if _match_hint(col_lower, hint) and col not in candidates:
                candidates.append(col)
    if candidates:
        if len(candidates) == 1:
            return candidates[0]
        return max(candidates, key=lambda c: _korean_ratio(df[c]))

    object_cols = [c for c in cols if df[c].dtype == object]
    if not object_cols:
        return cols[0] if cols else None
    best = max(
        object_cols,
        key=lambda c: df[c].astype(str).str.len().mean() if len(df) > 0 else 0,
    )
    return best


def guess_rating_column(df: pd.DataFrame) -> str | None:
    """평점 컬럼을 휴리스틱으로 추측."""
    cols = list(df.columns)
    cols_lower = [(c, str(c).lower()) for c in cols]

    for hint in RATING_HINTS:
        for col, col_lower in cols_lower:
            if col_lower == hint:
                return col
        for col, col_lower in cols_lower:
            if _match_hint(col_lower, hint):
                return col

    numeric_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
    return numeric_cols[0] if numeric_cols else None
