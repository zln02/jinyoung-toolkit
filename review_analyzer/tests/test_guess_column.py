"""텍스트/평점 컬럼 자동감지 회귀 테스트.

이슈 #1: hint 매칭이 컬럼 outer-loop 였던 탓에 ('reviewer', 'content')처럼
'reviewer' 가 먼저 나오는 경우 substring 매치로 reviewer 가 선택되는 버그.
hint outer-loop + word boundary 매칭으로 해결.
"""

from __future__ import annotations

import pandas as pd

from review_analyzer.app import _guess_rating_column, _guess_text_column


def test_guess_text_column_prefers_content_over_reviewer() -> None:
    """'content' 가 'reviewer' 보다 hint 우선순위가 높아야 한다."""
    df = pd.DataFrame(
        {
            "reviewer": ["김철수"],
            "rating": [5],
            "date": ["2026-01-01"],
            "content": ["좋아요"],
            "product_option": ["A"],
        }
    )
    assert _guess_text_column(df) == "content"


def test_guess_text_column_word_boundary() -> None:
    """'reviewer_name' 은 'review' hint 와 boundary 매칭되지 않아야 한다."""
    df = pd.DataFrame(
        {
            "reviewer_name": ["a"],
            "review": ["b"],
        }
    )
    assert _guess_text_column(df) == "review"


def test_guess_text_column_korean_partial_match_picks_korean() -> None:
    """ThinQ CSV 회귀 — '원본내용(영어)'·'번역내용(한국어)' 둘 다 '내용' hint에 매칭되면
    한글 비율 더 높은 한국어 컬럼이 선택돼야 한다.

    이전엔 (1) 단어 경계 regex가 한글에서 작동 안 해 둘 다 매칭 실패 →
    (2) 평균 길이 fallback으로 영어 원문이 선택돼 한국어 형태소 분석기에서 빈 결과 나오던 버그.
    """
    df = pd.DataFrame(
        {
            "플랫폼": ["HN"],
            "원본내용(영어)": ["very long english text " * 20],
            "번역내용(한국어)": ["한국어 번역 본문이 여기 들어갑니다"],
        }
    )
    assert _guess_text_column(df) == "번역내용(한국어)"


def test_guess_text_column_korean_hint_single_match() -> None:
    """한글 hint가 한 컬럼에만 매칭되면 그 컬럼 반환(다른 매칭이 없는 케이스)."""
    df = pd.DataFrame(
        {
            "user_id": [1],
            "리뷰_본문": ["좋아요"],
            "score": [5],
        }
    )
    assert _guess_text_column(df) == "리뷰_본문"


def test_guess_rating_column_prefers_rating_over_random_numeric() -> None:
    """'rating' 이 다른 숫자 컬럼보다 hint 우선순위가 높아야 한다."""
    df = pd.DataFrame(
        {
            "user_id": [1, 2, 3],
            "rating": [5, 4, 3],
            "content": ["a", "b", "c"],
        }
    )
    assert _guess_rating_column(df) == "rating"
