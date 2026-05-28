"""review_analyzer.advanced_analyzer — 전문가용 고급 분석.

TF-IDF 기반 군집화(KMeans)·토픽모델링(LDA)·2D 시각화(PCA/t-SNE)·통계 요약.
Streamlit 비의존 순수 로직 — 단위 테스트가 쉽다. shared/korean_nlp의 벡터화를 재사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA, LatentDirichletAllocation
from sklearn.manifold import TSNE
from sklearn.metrics import pairwise_distances, silhouette_score

from shared.korean_nlp import KoreanTextProcessor
from shared.logger import get_logger

logger = get_logger(__name__)

_RANDOM_STATE = 42


@dataclass
class ClusterResult:
    """KMeans 군집 결과 컨테이너."""

    labels: pd.Series  # 문서 index → 클러스터 id
    n_clusters: int
    silhouette: float | None
    keywords_by_cluster: dict[str, list[tuple[str, float]]]
    sizes: dict[int, int]
    representatives: dict[int, str]  # 클러스터 id → 대표 리뷰(centroid 최근접)
    tfidf: pd.DataFrame  # 2D 투영 재사용
    auto_selected: bool = False

    @classmethod
    def empty(cls, reason: str) -> "ClusterResult":
        logger.warning("군집 분석 빈 결과: %s", reason)
        return cls(
            labels=pd.Series(dtype=int),
            n_clusters=0,
            silhouette=None,
            keywords_by_cluster={},
            sizes={},
            representatives={},
            tfidf=pd.DataFrame(),
        )


@dataclass
class TopicResult:
    """LDA 토픽 모델링 결과 컨테이너."""

    topics: list[list[tuple[str, float]]]  # 토픽별 [(단어, 가중치)]
    doc_topic: pd.DataFrame  # 문서 × 토픽 비중
    n_topics: int

    @classmethod
    def empty(cls, reason: str) -> "TopicResult":
        logger.warning("토픽 분석 빈 결과: %s", reason)
        return cls(topics=[], doc_topic=pd.DataFrame(), n_topics=0)


def _clean_texts(texts: pd.Series) -> pd.Series:
    """결측·공백 텍스트를 제거한다(원본 index 보존)."""
    s = texts.dropna().astype(str).str.strip()
    return s[s.str.len() > 0]


def cluster_reviews(
    nlp: KoreanTextProcessor,
    texts: pd.Series,
    n_clusters: int | None = None,
    max_features: int = 500,
    top_k: int = 10,
) -> ClusterResult:
    """리뷰를 TF-IDF + KMeans로 군집화한다.

    n_clusters=None이면 silhouette가 최대인 k(2..min(8, n-1))를 자동 선택한다.
    클러스터별 대표 키워드(extract_keywords_by_group)와 centroid 최근접 대표 리뷰를 함께 반환.
    """
    texts = _clean_texts(texts)
    n = len(texts)
    if n < 4:
        return ClusterResult.empty(f"표본 부족(n={n}, 최소 4)")

    try:
        tfidf = nlp.to_tfidf_features(texts, max_features=max_features)
    except ValueError as exc:
        return ClusterResult.empty(f"TF-IDF 변환 실패: {exc}")

    X = tfidf.to_numpy()
    auto = n_clusters is None

    if auto:
        k_max = min(8, n - 1)
        best_k, best_score, best_labels = 0, -1.0, None
        for k in range(2, k_max + 1):
            lbl = KMeans(n_clusters=k, random_state=_RANDOM_STATE, n_init=10).fit_predict(X)
            if len(set(lbl)) < 2:
                continue
            try:
                score = float(silhouette_score(X, lbl))
            except Exception:
                continue
            if score > best_score:
                best_k, best_score, best_labels = k, score, lbl
        if best_labels is None:
            return ClusterResult.empty("군집 분리 실패")
        k_final, labels_arr, sil = best_k, best_labels, best_score
    else:
        k_final = max(2, min(int(n_clusters), n - 1))
        labels_arr = KMeans(
            n_clusters=k_final, random_state=_RANDOM_STATE, n_init=10
        ).fit_predict(X)
        try:
            sil = float(silhouette_score(X, labels_arr)) if len(set(labels_arr)) > 1 else None
        except Exception:
            sil = None

    labels = pd.Series(labels_arr, index=texts.index, name="cluster")
    sizes = {int(k): int(v) for k, v in labels.value_counts().sort_index().items()}

    try:
        keywords = nlp.extract_keywords_by_group(texts, labels, top_k=top_k)
    except Exception as exc:
        logger.warning("클러스터 키워드 추출 실패: %s", exc)
        keywords = {}

    # 대표 리뷰 — 각 클러스터 centroid에 가장 가까운 문서
    reps: dict[int, str] = {}
    for c in sorted(set(int(x) for x in labels_arr)):
        idx = labels.index[labels.to_numpy() == c]
        sub = tfidf.loc[idx].to_numpy()
        centroid = sub.mean(axis=0, keepdims=True)
        dist = pairwise_distances(sub, centroid).ravel()
        reps[c] = str(texts.loc[idx[int(np.argmin(dist))]])

    logger.info("군집 완료: k=%d, silhouette=%s, auto=%s", k_final, sil, auto)
    return ClusterResult(
        labels=labels,
        n_clusters=k_final,
        silhouette=(float(sil) if sil is not None else None),
        keywords_by_cluster=keywords,
        sizes=sizes,
        representatives=reps,
        tfidf=tfidf,
        auto_selected=auto,
    )


def extract_topics(
    nlp: KoreanTextProcessor,
    texts: pd.Series,
    n_topics: int = 5,
    max_features: int = 500,
    top_k: int = 10,
) -> TopicResult:
    """LDA 토픽 모델링 — 토픽별 상위 단어와 문서-토픽 비중."""
    texts = _clean_texts(texts)
    n = len(texts)
    if n < 3:
        return TopicResult.empty(f"표본 부족(n={n}, 최소 3)")

    try:
        tfidf = nlp.to_tfidf_features(texts, max_features=max_features)
    except ValueError as exc:
        return TopicResult.empty(f"TF-IDF 변환 실패: {exc}")

    k = max(2, min(int(n_topics), n - 1))
    lda = LatentDirichletAllocation(n_components=k, random_state=_RANDOM_STATE)
    try:
        doc_topic_arr = lda.fit_transform(tfidf.to_numpy())
    except Exception as exc:
        return TopicResult.empty(f"LDA 실패: {exc}")

    feature_names = list(tfidf.columns)
    topics: list[list[tuple[str, float]]] = []
    for comp in lda.components_:
        order = comp.argsort()[::-1][:top_k]
        topics.append([(feature_names[i], float(comp[i])) for i in order])

    doc_topic = pd.DataFrame(
        doc_topic_arr,
        index=texts.index,
        columns=[f"토픽{i + 1}" for i in range(k)],
    )
    logger.info("토픽 모델링 완료: n_topics=%d", k)
    return TopicResult(topics=topics, doc_topic=doc_topic, n_topics=k)


def project_2d(
    tfidf: pd.DataFrame,
    labels: pd.Series,
    method: str = "pca",
) -> pd.DataFrame:
    """TF-IDF 행렬을 2D로 투영한다. 반환: [x, y, cluster] DataFrame.

    method="pca"(빠름) | "tsne"(국소 구조 보존, 소표본 perplexity 자동 축소).
    """
    if tfidf.empty or len(tfidf) < 3:
        return pd.DataFrame(columns=["x", "y", "cluster"])

    X = tfidf.to_numpy()
    n = len(X)
    try:
        if method == "tsne":
            perplexity = max(2, min(30, n - 1))
            reducer = TSNE(
                n_components=2,
                init="pca",
                perplexity=perplexity,
                random_state=_RANDOM_STATE,
            )
        else:
            reducer = PCA(n_components=2)
        coords = reducer.fit_transform(X)
    except Exception as exc:
        logger.warning("2D 투영 실패(method=%s): %s", method, exc)
        return pd.DataFrame(columns=["x", "y", "cluster"])

    out = pd.DataFrame({"x": coords[:, 0], "y": coords[:, 1]}, index=tfidf.index)
    aligned = labels.reindex(tfidf.index)
    out["cluster"] = aligned.astype("Int64").astype(str)
    return out


def summary_stats(
    df: pd.DataFrame,
    text_column: str,
    cluster: ClusterResult,
    rating_column: str | None = None,
    sentiment: pd.Series | None = None,
) -> dict[str, Any]:
    """전문가용 통계 요약 dict.

    군집 품질(silhouette)·크기 분포·리뷰 길이 통계·평점×감성 교차표를 모은다.
    """
    stats: dict[str, Any] = {}
    texts = _clean_texts(df[text_column]) if text_column in df.columns else pd.Series(dtype=str)

    stats["총_리뷰"] = int(len(texts))
    stats["군집_수"] = cluster.n_clusters
    stats["silhouette"] = cluster.silhouette
    stats["군집_크기"] = cluster.sizes

    if len(texts):
        lengths = texts.str.len()
        stats["리뷰길이_평균"] = round(float(lengths.mean()), 1)
        stats["리뷰길이_중앙"] = float(lengths.median())
        stats["리뷰길이_최대"] = int(lengths.max())

    if sentiment is not None and rating_column and rating_column in df.columns:
        try:
            stats["평점x감성"] = pd.crosstab(df[rating_column], sentiment)
        except Exception as exc:
            logger.warning("평점x감성 교차표 실패: %s", exc)

    return stats
