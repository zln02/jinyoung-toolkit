"""advanced_analyzer 테스트 — 군집(KMeans)·토픽(LDA)·2D 투영·소표본 가드."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from review_analyzer.advanced_analyzer import (
    ClusterResult,
    TopicResult,
    cluster_reviews,
    extract_topics,
    project_2d,
)
from shared.korean_nlp import KoreanTextProcessor

_FIXTURE = (
    Path(__file__).parent.parent.parent / "tests" / "fixtures" / "sample_reviews_50.csv"
)


@pytest.fixture(scope="module")
def nlp() -> KoreanTextProcessor:
    return KoreanTextProcessor()


@pytest.fixture
def texts() -> pd.Series:
    return pd.read_csv(_FIXTURE)["content"]


class TestCluster:
    def test_auto_k_in_range(self, nlp: KoreanTextProcessor, texts: pd.Series) -> None:
        """자동 군집수 선택 — k가 2..8, silhouette·키워드 존재."""
        cr = cluster_reviews(nlp, texts)
        assert isinstance(cr, ClusterResult)
        assert 2 <= cr.n_clusters <= 8
        assert cr.auto_selected is True
        assert cr.silhouette is not None
        assert len(cr.labels) > 0
        assert cr.keywords_by_cluster  # 비어있지 않음
        assert sum(cr.sizes.values()) == len(cr.labels)

    def test_fixed_k(self, nlp: KoreanTextProcessor, texts: pd.Series) -> None:
        """군집수 지정 — k 고정, 대표리뷰가 클러스터마다 존재."""
        cr = cluster_reviews(nlp, texts, n_clusters=3)
        assert cr.n_clusters == 3
        assert cr.auto_selected is False
        assert set(cr.sizes.keys()) <= {0, 1, 2}
        assert set(cr.representatives.keys()) == set(cr.sizes.keys())

    def test_small_sample_guard(self, nlp: KoreanTextProcessor) -> None:
        """표본 4건 미만 — 예외 없이 빈 결과."""
        cr = cluster_reviews(nlp, pd.Series(["좋아요", "별로", "그냥"]))
        assert cr.n_clusters == 0
        assert cr.labels.empty


class TestTopics:
    def test_extract(self, nlp: KoreanTextProcessor, texts: pd.Series) -> None:
        """LDA 토픽 추출 — 토픽 수·키워드 형식·문서토픽 행렬."""
        tr = extract_topics(nlp, texts, n_topics=3, top_k=8)
        assert isinstance(tr, TopicResult)
        assert tr.n_topics == 3
        assert len(tr.topics) == 3
        for topic in tr.topics:
            assert len(topic) <= 8
            assert all(isinstance(w, str) and isinstance(s, float) for w, s in topic)
        assert tr.doc_topic.shape[1] == 3
        assert tr.doc_topic.shape[0] == len(tr.doc_topic)

    def test_small_guard(self, nlp: KoreanTextProcessor) -> None:
        """표본 3건 미만 — 빈 결과."""
        tr = extract_topics(nlp, pd.Series(["좋아요"]))
        assert tr.n_topics == 0


class TestProjection:
    def test_pca_shape(self, nlp: KoreanTextProcessor, texts: pd.Series) -> None:
        """PCA 2D 투영 — [x,y,cluster] 컬럼, 행 수 일치."""
        cr = cluster_reviews(nlp, texts, n_clusters=3)
        proj = project_2d(cr.tfidf, cr.labels, method="pca")
        assert list(proj.columns) == ["x", "y", "cluster"]
        assert len(proj) == len(cr.tfidf)

    def test_empty_guard(self) -> None:
        """빈 입력 — 빈 DataFrame."""
        proj = project_2d(pd.DataFrame(), pd.Series(dtype=int), method="pca")
        assert proj.empty
