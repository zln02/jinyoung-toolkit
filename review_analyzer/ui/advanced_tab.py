"""review_analyzer.ui.advanced_tab — 🔬 고급 분석 탭 (군집·토픽·2D·통계)."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from review_analyzer.advanced_analyzer import (
    ClusterResult,
    TopicResult,
    cluster_reviews,
    extract_topics,
    project_2d,
    summary_stats,
)
from review_analyzer.analyzer import ReviewAnalyzer
from review_analyzer.ui._helpers import guess_rating_column, guess_text_column
from shared.logger import get_logger
from shared.ui_components import render_error, render_metrics

log = get_logger(__name__)

# session: (ClusterResult, TopicResult, proj_df, stats, method)
_ADV_RESULT = "adv_result"


def render_advanced_analysis(df: pd.DataFrame) -> None:
    """고급 분석 탭 — TF-IDF 군집/토픽/2D/통계 (전문가용)."""
    st.subheader("🔬 고급 분석 (전문가용)")
    st.caption(
        "TF-IDF 기반 군집화·토픽 모델링(LDA)·2D 시각화·통계 요약. 탐색적 분석에 사용하세요."
    )

    columns = list(df.columns)
    guessed_text = guess_text_column(df)
    text_index = columns.index(guessed_text) if guessed_text in columns else 0

    col1, col2 = st.columns(2)
    with col1:
        text_column = st.selectbox(
            "텍스트 컬럼", options=columns, index=text_index, key="adv_text"
        )
    with col2:
        rating_options = ["(없음)"] + columns
        guessed_rating = guess_rating_column(df)
        r_idx = (
            rating_options.index(guessed_rating)
            if guessed_rating and guessed_rating in rating_options
            else 0
        )
        rating_sel = st.selectbox(
            "평점 컬럼(통계용·선택)", options=rating_options, index=r_idx, key="adv_rating"
        )
    rating_column = None if rating_sel == "(없음)" else rating_sel

    with st.expander("⚙️ 분석 설정", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            auto_k = st.checkbox("군집 수 자동 (silhouette)", value=True)
            n_clusters = None if auto_k else st.slider("군집 수 k", 2, 8, 4)
        with c2:
            n_topics = st.slider("토픽 수", 2, 10, 5)
        with c3:
            method = st.radio(
                "2D 투영",
                options=["pca", "tsne"],
                horizontal=True,
                format_func=lambda m: "PCA (빠름)" if m == "pca" else "t-SNE",
            )
        max_features = st.slider("TF-IDF 최대 단어 수", 100, 1000, 500, step=100)

    if st.button("고급 분석 실행", type="primary", key="adv_run"):
        with st.spinner("군집·토픽 분석 중... (데이터에 따라 수십 초)"):
            try:
                analyzer = ReviewAnalyzer(
                    text_column=text_column, rating_column=rating_column
                )
                clean = analyzer.preprocess(df)
                if len(clean) < 4:
                    st.warning(
                        f"분석에 데이터가 부족해요(유효 {len(clean)}건, 최소 4건 필요)."
                    )
                    return
                texts = clean[text_column]
                nlp = analyzer.nlp

                cr = cluster_reviews(
                    nlp, texts, n_clusters=n_clusters, max_features=max_features
                )
                tr = extract_topics(
                    nlp, texts, n_topics=n_topics, max_features=max_features
                )
                proj = project_2d(cr.tfidf, cr.labels, method=method)

                sentiment = None
                if rating_column:
                    try:
                        sentiment = analyzer.analyze_sentiment(clean)["sentiment"]
                    except Exception:
                        sentiment = None
                stats = summary_stats(clean, text_column, cr, rating_column, sentiment)

                st.session_state[_ADV_RESULT] = (cr, tr, proj, stats, method)
                log.info("고급 분석 완료", k=cr.n_clusters, n_topics=tr.n_topics)
            except Exception as exc:
                log.error("고급 분석 실패", error=str(exc))
                render_error(exc, context="고급 분석")
                return

    saved = st.session_state.get(_ADV_RESULT)
    if saved is None:
        st.info("설정을 고르고 '고급 분석 실행'을 누르면 결과가 표시됩니다.")
        return

    cr, tr, proj, stats, method = saved
    _render_cluster(cr)
    _render_projection(proj, method)
    _render_topics(tr)
    _render_stats(stats)


def _render_cluster(cr: ClusterResult) -> None:
    st.divider()
    st.subheader("📦 리뷰 군집")
    if cr.n_clusters == 0:
        st.info("군집을 만들지 못했어요 (데이터 부족 또는 분리 불가).")
        return

    sil_txt = f"{cr.silhouette:.3f}" if cr.silhouette is not None else "N/A"
    render_metrics(
        {
            "군집 수": str(cr.n_clusters),
            "군집 품질 점수": sil_txt,
            "자동 선택": "예" if cr.auto_selected else "아니오",
        }
    )
    # 비전공자용 해석 — silhouette 점수 기준
    if cr.silhouette is not None:
        if cr.silhouette >= 0.5:
            st.caption("✨ **군집이 명확하게 나뉘었어요** (점수 0.5 이상)")
        elif cr.silhouette >= 0.2:
            st.caption("🙂 **보통 수준의 분리** — 군집이 일부 겹쳐있을 수 있어요")
        else:
            st.caption("⚠️ **군집 경계가 흐릿** — 데이터가 비슷하거나 더 많이 모아야 할 수 있어요")

    size_df = pd.DataFrame(
        [{"군집": f"클러스터 {k}", "리뷰 수": v} for k, v in cr.sizes.items()]
    )
    if not size_df.empty:
        fig = px.bar(size_df, x="군집", y="리뷰 수", color="군집", height=280)
        fig.update_layout(showlegend=False, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    for c in sorted(cr.sizes.keys()):
        kws = cr.keywords_by_cluster.get(str(c), [])
        kw_str = ", ".join(k for k, _ in kws[:8]) or "(키워드 없음)"
        with st.expander(f"클러스터 {c} · {cr.sizes[c]}건 · {kw_str[:40]}"):
            st.markdown(f"**대표 키워드:** {kw_str}")
            rep = cr.representatives.get(c, "")
            if rep:
                st.markdown(f"**대표 리뷰:** {rep[:200]}")


def _render_projection(proj: pd.DataFrame, method: str) -> None:
    st.divider()
    st.subheader(f"🗺️ 2D 군집 시각화 ({'PCA' if method == 'pca' else 't-SNE'})")
    if proj.empty:
        st.info("시각화할 데이터가 부족해요.")
        return
    fig = px.scatter(
        proj, x="x", y="y", color="cluster", labels={"cluster": "클러스터"}, height=420
    )
    fig.update_traces(marker=dict(size=9, opacity=0.75))
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)


def _render_topics(tr: TopicResult) -> None:
    st.divider()
    st.subheader("🧩 토픽 모델링 (LDA)")
    if tr.n_topics == 0 or not tr.topics:
        st.info("토픽을 추출하지 못했어요.")
        return

    cols = st.columns(min(tr.n_topics, 3))
    for i, topic in enumerate(tr.topics):
        with cols[i % len(cols)]:
            st.markdown(f"**토픽 {i + 1}**")
            kw_df = pd.DataFrame(topic[:8], columns=["단어", "가중치"])
            kw_df["가중치"] = kw_df["가중치"].round(2)
            st.dataframe(kw_df, hide_index=True, use_container_width=True)

    if not tr.doc_topic.empty:
        mean_share = tr.doc_topic.mean().reset_index()
        mean_share.columns = ["토픽", "평균 비중"]
        fig = px.bar(mean_share, x="토픽", y="평균 비중", height=260)
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)


def _render_stats(stats: dict[str, Any]) -> None:
    st.divider()
    st.subheader("📊 통계 요약")
    render_metrics(
        {
            "총 리뷰": f"{stats.get('총_리뷰', 0):,}건",
            "리뷰길이 평균": f"{stats.get('리뷰길이_평균', 'N/A')}자",
            "리뷰길이 중앙": f"{stats.get('리뷰길이_중앙', 'N/A')}자",
        }
    )
    ct = stats.get("평점x감성")
    if ct is not None and hasattr(ct, "empty") and not ct.empty:
        st.markdown("**평점 × 감성 교차표**")
        st.dataframe(ct, use_container_width=True)
