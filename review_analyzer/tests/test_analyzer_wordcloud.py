"""워드클라우드 캐시 영속성 회귀 테스트.

이슈 #2: ReviewAnalyzer.run()이 tempfile.TemporaryDirectory를 사용하던 시절
워드클라우드 PNG 경로가 함수 종료와 함께 사라져 UI/PDF 양쪽 모두에서 표시되지 않았다.
이 테스트는 run() 종료 후에도 wordcloud_path가 디스크에 살아 있어야 함을 보장한다.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from review_analyzer.analyzer import ReviewAnalyzer


def test_run_wordcloud_path_persists(tmp_path: Path) -> None:
    """run() 반환 후에도 wordcloud_path가 실재하는 PNG 파일이어야 한다."""
    df = pd.DataFrame(
        {
            "content": ["좋아요 최고예요 추천합니다"] * 5
            + ["별로예요 실망했어요 환불"] * 5,
            "rating": [5, 5, 5, 5, 5, 1, 1, 1, 1, 1],
        }
    )
    analyzer = ReviewAnalyzer(
        text_column="content",
        rating_column="rating",
        cache_root=tmp_path,
    )

    result = analyzer.run(df)

    assert result.wordcloud_path is not None, "wordcloud_path 가 None 이면 안 됨"
    wc_path = Path(result.wordcloud_path)
    assert wc_path.exists(), f"wordcloud PNG 가 실존해야 함: {wc_path}"
    assert wc_path.stat().st_size > 0, "wordcloud PNG 가 빈 파일이면 안 됨"
