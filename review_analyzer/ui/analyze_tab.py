"""review_analyzer.ui.analyze_tab — Step 2·3 분석 설정 및 결과 섹션."""

from __future__ import annotations

import io
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from review_analyzer.analyzer import AnalysisResult, ReviewAnalyzer, SentimentConfig
from shared.logger import get_logger
from shared.ui_components import render_download_button, render_error, render_metrics
from review_analyzer.ui._helpers import guess_rating_column, guess_text_column

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# 빌드 헬퍼 (ZIP·PDF)
# ---------------------------------------------------------------------------


def _build_fallback_zip(raw_df: pd.DataFrame, zip_path: Path) -> bytes:
    """raw.csv만 담은 최소 ZIP 생성 (폴백용)."""
    with zipfile.ZipFile(zip_path, "w") as zf:
        buf = io.BytesIO()
        raw_df.to_csv(buf, index=False, encoding="utf-8-sig")
        zf.writestr("raw.csv", buf.getvalue())
    return zip_path.read_bytes()


def _build_zip(
    raw_df: pd.DataFrame,
    result: AnalysisResult,
    project_name: str,
    text_column: str = "content",
    rating_column: str | None = "rating",
    sentiment_config: SentimentConfig | None = None,
) -> tuple[bytes, bool]:
    """납품 패키지 ZIP 바이트 반환. (zip_bytes, is_fallback).

    save_delivery_package가 raw_df를 다시 분석하므로, 사용자가 고른 컬럼·감성설정을
    그대로 넘겨야 결과가 화면과 일치한다(기본 생성자 사용 시 어긋나던 버그 수정).
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / f"{project_name}.zip"
        analyzer = ReviewAnalyzer(
            text_column=text_column,
            rating_column=rating_column,
            sentiment_config=sentiment_config,
        )

        try:
            analyzer.save_delivery_package(
                raw_df=raw_df,
                result=result,
                output_dir=tmp_path,
                project_name=project_name,
            )
        except Exception as exc:
            log.error("납품 패키지 생성 실패, 폴백 사용", error=str(exc))
            return _build_fallback_zip(raw_df, zip_path), True

        try:
            shutil.make_archive(
                str(zip_path.with_suffix("")), "zip", tmp_path, project_name
            )
        except Exception as exc:
            log.error("ZIP 압축 실패, 폴백 사용", error=str(exc))
            return _build_fallback_zip(raw_df, zip_path), True

        return zip_path.read_bytes(), False


def _build_pdf(result: AnalysisResult) -> bytes:
    """PDF 리포트 바이트 반환."""
    with tempfile.TemporaryDirectory() as tmp:
        output_path = Path(tmp) / "report.pdf"
        analyzer = ReviewAnalyzer()
        try:
            saved = analyzer.generate_report(result, output_path)
            return saved.read_bytes()
        except Exception as exc:
            log.error("PDF 생성 실패", error=str(exc))
            return b""


# ---------------------------------------------------------------------------
# 섹션 렌더러
# ---------------------------------------------------------------------------


# 고급 설정 라벨 ↔ 내부 값 매핑
_MODE_LABELS: dict[str, str] = {
    "자동 (평점 우선, 없으면 키워드)": "auto",
    "평점만": "rating",
    "키워드만": "keyword",
}
_SCALE_LABELS: dict[str, float | None] = {
    "자동 감지": None,
    "5점 만점": 5.0,
    "10점 만점": 10.0,
    "100% (만족도)": 100.0,
}


def _render_advanced_settings(has_rating: bool) -> SentimentConfig:
    """⚙️ 고급 설정 expander — 분석 방식·평점 척도·긍부정 경계를 SentimentConfig로 반환.

    평점 컬럼이 없거나 키워드 모드면 평점 관련 위젯은 숨긴다(의미가 없으므로).
    """
    with st.expander("⚙️ 고급 설정 (감성 분석 맞춤)", expanded=False):
        mode_label = st.radio(
            "분석 방식",
            options=list(_MODE_LABELS.keys()),
            index=0,
            help=(
                "자동: 평점이 있으면 평점으로, 못 읽으면 리뷰 텍스트 키워드로 분석. "
                "평점만: 평점으로만(못 읽으면 중립). 키워드만: 평점 무시하고 텍스트로만."
            ),
        )
        mode = _MODE_LABELS[mode_label]

        rating_scale: float | None = None
        positive_threshold = 4.0
        negative_threshold = 2.0

        uses_rating = has_rating and mode in ("auto", "rating")
        if uses_rating:
            scale_label = st.selectbox(
                "평점 척도",
                options=list(_SCALE_LABELS.keys()),
                index=0,
                help="리뷰 평점의 만점 기준. '자동 감지'는 값 크기로 추정합니다.",
            )
            rating_scale = _SCALE_LABELS[scale_label]

            negative_threshold, positive_threshold = st.slider(
                "긍정/부정 경계 (5점 환산 기준)",
                min_value=0.0,
                max_value=5.0,
                value=(2.0, 4.0),
                step=0.5,
                help="이 값 이하는 부정, 이상은 긍정, 그 사이는 중립으로 분류합니다.",
            )
        else:
            st.caption("키워드 방식에서는 평점 척도·경계 설정이 사용되지 않습니다.")

        return SentimentConfig(
            mode=mode,
            rating_scale=rating_scale,
            positive_threshold=float(positive_threshold),
            negative_threshold=float(negative_threshold),
        )


def render_step2_settings(df: pd.DataFrame) -> tuple[str, str | None, SentimentConfig]:
    """Step 2: 분석 설정 섹션 렌더링. (text_column, rating_column, SentimentConfig) 반환."""
    st.subheader("Step 2. 분석 설정")

    columns = list(df.columns)

    guessed_text = guess_text_column(df)
    text_index = columns.index(guessed_text) if guessed_text in columns else 0
    text_column: str = st.selectbox(
        "텍스트(리뷰 내용) 컬럼",
        options=columns,
        index=text_index,
    )

    rating_options = ["(없음)"] + columns
    guessed_rating = guess_rating_column(df)
    rating_index = (
        rating_options.index(guessed_rating)
        if guessed_rating and guessed_rating in rating_options
        else 0
    )
    rating_selection: str = st.selectbox(
        "평점 컬럼",
        options=rating_options,
        index=rating_index,
    )
    rating_column: str | None = None if rating_selection == "(없음)" else rating_selection

    st.info(
        "💡 텍스트 컬럼: 리뷰 내용 / 평점 컬럼: 평점이 든 컬럼"
        "(숫자·'만족도 100%' 등 자동 인식, 세부 조정은 아래 고급 설정)"
    )

    sentiment_config = _render_advanced_settings(has_rating=rating_column is not None)

    return text_column, rating_column, sentiment_config


def render_results(result: AnalysisResult) -> None:
    """분석 결과 섹션 전체 렌더링."""
    st.divider()
    st.subheader("분석 결과")

    total = result.total_reviews or 1
    pos_ratio = result.sentiment_distribution.get("positive", 0) / total * 100
    neg_ratio = result.sentiment_distribution.get("negative", 0) / total * 100

    metrics: dict[str, Any] = {
        "총 리뷰 수": f"{result.total_reviews:,}건",
        "평균 평점": f"{result.avg_rating:.2f}" if result.avg_rating else "N/A",
        "긍정 비율": f"{pos_ratio:.1f}%",
        "부정 비율": f"{neg_ratio:.1f}%",
    }
    render_metrics(metrics)

    # 비전공자용 자동 해석 — 긍정 비율 기준 한 줄 평
    if pos_ratio >= 80:
        st.caption("👍 **전반적으로 우호적** — 80% 이상이 긍정 의견이에요.")
    elif pos_ratio >= 50:
        st.caption("🙂 **보통 수준의 만족도** — 긍정·부정이 섞여 있어요. 부정 키워드 점검 권장.")
    else:
        st.caption("⚠️ **부정 의견이 많음** — 어떤 점이 불편한지 부정 키워드를 우선 살펴보세요.")

    # 감성 분포 파이차트
    st.subheader("감성 분포")
    _label_map = {"positive": "긍정", "negative": "부정", "neutral": "중립"}
    sentiment_df = pd.DataFrame(
        [
            {"감성": _label_map.get(k, k), "건수": v}
            for k, v in result.sentiment_distribution.items()
            if v > 0
        ]
    )
    if not sentiment_df.empty:
        color_map = {"긍정": "#4CAF50", "부정": "#F44336", "중립": "#9E9E9E"}
        fig = px.pie(
            sentiment_df,
            names="감성",
            values="건수",
            color="감성",
            color_discrete_map=color_map,
        )
        st.plotly_chart(fig, use_container_width=True)

    # 키워드 Top 10
    st.subheader("키워드 Top 10")
    col1, col2 = st.columns(2)

    def _render_keyword_block(
        title: str,
        items: list[tuple[str, float]],
        bar_color: str,
    ) -> None:
        st.markdown(f"**{title}**")
        if not items:
            st.info("데이터 없음")
            return
        kw_df = pd.DataFrame(items, columns=["키워드", "점수"])
        kw_df["점수"] = kw_df["점수"].round(4)
        fig = px.bar(
            kw_df,
            x="점수",
            y="키워드",
            orientation="h",
            color_discrete_sequence=[bar_color],
            height=320,
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=20, b=0),
            yaxis={"categoryorder": "total ascending"},
        )
        st.plotly_chart(fig, use_container_width=True)
        with st.expander("표로 보기", expanded=False):
            st.dataframe(kw_df, hide_index=True, use_container_width=True)

    with col1:
        _render_keyword_block("긍정 키워드", result.keywords_positive[:10], "#4CAF50")

    with col2:
        _render_keyword_block("부정 키워드", result.keywords_negative[:10], "#F44336")

    # 워드클라우드
    st.subheader("워드클라우드")
    _wc_path = result.wordcloud_path

    wc_images: dict[str, Path] = {}
    if _wc_path is not None and Path(_wc_path).exists():
        wc_images["전체"] = Path(_wc_path)
        pos_wc = Path(str(_wc_path)).parent / "wordcloud_positive.png"
        neg_wc = Path(str(_wc_path)).parent / "wordcloud_negative.png"
        if pos_wc.exists():
            wc_images["긍정"] = pos_wc
        if neg_wc.exists():
            wc_images["부정"] = neg_wc

    if wc_images:
        tabs = st.tabs(list(wc_images.keys()))
        for tab, (label, path) in zip(tabs, wc_images.items()):
            with tab:
                st.image(str(path), use_container_width=True)
    elif _wc_path is None:
        st.info("워드클라우드를 만들지 못했어요. (텍스트 데이터가 부족할 수 있어요)")
    else:
        st.info("워드클라우드를 만들지 못했어요. (캐시 파일이 사라졌어요)")

    # 인사이트
    st.subheader("인사이트")
    for insight in result.insights:
        st.info(insight)


def render_download_section(
    result: AnalysisResult,
    raw_df: pd.DataFrame,
    text_column: str = "content",
    rating_column: str | None = "rating",
    sentiment_config: SentimentConfig | None = None,
) -> None:
    """다운로드 섹션 렌더링. ZIP 재분석 시 사용자 설정을 그대로 사용."""
    st.divider()
    st.subheader("다운로드")

    col_pdf, col_zip = st.columns(2)

    with col_pdf:
        with st.spinner("PDF 생성 중..."):
            pdf_bytes = _build_pdf(result)
        if pdf_bytes:
            render_download_button(
                data=pdf_bytes,
                filename="review_report.pdf",
                label="PDF 리포트 다운로드",
                mime="application/pdf",
            )
        else:
            st.error("PDF 생성에 실패했습니다.")

    with col_zip:
        with st.spinner("납품 패키지 생성 중..."):
            zip_bytes, is_fallback = _build_zip(
                raw_df,
                result,
                project_name="review_analysis",
                text_column=text_column,
                rating_column=rating_column,
                sentiment_config=sentiment_config,
            )
        if is_fallback:
            st.warning("전체 패키지 생성에 실패하여 원본 CSV만 포함된 ZIP을 제공합니다.")
        if zip_bytes:
            render_download_button(
                data=zip_bytes,
                filename="review_analysis_package.zip",
                label="납품 패키지(ZIP) 다운로드",
                mime="application/zip",
            )
        else:
            st.error("납품 패키지 생성에 실패했습니다.")
