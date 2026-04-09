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
