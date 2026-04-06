"""리뷰 분석 프로그램 — Streamlit 메인 앱."""

from __future__ import annotations

import asyncio
import io
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from review_analyzer.analyzer import AnalysisResult, ReviewAnalyzer
from review_analyzer.crawler.engine import CrawlConfig, CrawlerEngine
from review_analyzer.preset_loader import PresetLoader
from shared.logger import get_logger
from shared.ui_components import (
    render_download_button,
    render_file_uploader,
    render_header,
    render_metrics,
)

log = get_logger(__name__)

_SESSION_DF = "ra_df"
_SESSION_RESULT = "ra_result"
_SESSION_RAW_DF = "ra_raw_df"


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _run_crawl(preset_name: str, url: str, max_pages: int) -> pd.DataFrame:
    """크롤링 실행 — asyncio.run 래핑."""
    loader = PresetLoader()
    preset = loader.load(preset_name)

    config = CrawlConfig(
        preset_name=preset_name,
        target_urls=[url],
        max_pages=max_pages,
    )
    engine = CrawlerEngine(config=config, preset=preset)

    crawl_result = asyncio.run(engine.run())
    return crawl_result.dataframe


def _build_zip(raw_df: pd.DataFrame, result: AnalysisResult, project_name: str) -> bytes:
    """납품 패키지 ZIP 바이트 반환."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        analyzer = ReviewAnalyzer()
        try:
            pkg_path = analyzer.save_delivery_package(
                raw_df=raw_df,
                result=result,
                output_dir=tmp_path,
                project_name=project_name,
            )
        except Exception as exc:
            log.error("납품 패키지 생성 실패", error=str(exc))
            # 단순 ZIP 폴백
            zip_path = tmp_path / f"{project_name}.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                buf = io.StringIO()
                raw_df.to_csv(buf, index=False, encoding="utf-8-sig")
                zf.writestr("raw.csv", buf.getvalue())
            pkg_path = zip_path

        return pkg_path.read_bytes()


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


def _render_step1_input() -> pd.DataFrame | None:
    """Step 1: 데이터 입력 섹션 렌더링. 로드된 DataFrame 반환."""
    st.subheader("Step 1. 데이터 입력")

    input_mode = st.radio(
        "데이터 입력 방식",
        options=["CSV 파일 업로드", "사이트에서 수집"],
        horizontal=True,
    )

    df: pd.DataFrame | None = None

    if input_mode == "CSV 파일 업로드":
        df = render_file_uploader()

    else:
        loader = PresetLoader()
        presets = loader.list_presets()

        if not presets:
            st.warning("사용 가능한 프리셋이 없습니다.")
            return None

        preset_options = {p["display_name"]: p["name"] for p in presets}
        selected_display = st.selectbox("사이트 프리셋", list(preset_options.keys()))
        selected_preset = preset_options[selected_display]

        url = st.text_input("수집 URL", placeholder="https://...")
        max_pages = st.number_input(
            "최대 페이지 수",
            min_value=1,
            max_value=500,
            value=10,
            step=1,
        )

        if st.button("크롤링 시작"):
            if not url:
                st.error("URL을 입력해주세요.")
                return None
            with st.spinner("크롤링 중..."):
                try:
                    df = _run_crawl(selected_preset, url, int(max_pages))
                    st.session_state[_SESSION_DF] = df
                    st.session_state[_SESSION_RAW_DF] = df
                    st.success(f"크롤링 완료: {len(df)}건")
                    st.dataframe(df.head())
                except Exception as exc:
                    log.error("크롤링 실패", error=str(exc))
                    st.error(f"크롤링 실패: {exc}")
                    return None

    return df


def _render_step2_settings(df: pd.DataFrame) -> tuple[str, str | None]:
    """Step 2: 분석 설정 섹션 렌더링. (text_column, rating_column) 반환."""
    st.subheader("Step 2. 분석 설정")

    columns = list(df.columns)

    text_column: str = st.selectbox(
        "텍스트(리뷰 내용) 컬럼",
        options=columns,
        index=0,
    )

    rating_options = ["(없음)"] + columns
    rating_selection: str = st.selectbox(
        "평점 컬럼",
        options=rating_options,
        index=0,
    )
    rating_column: str | None = None if rating_selection == "(없음)" else rating_selection

    return text_column, rating_column


def _render_results(result: AnalysisResult) -> None:
    """분석 결과 섹션 전체 렌더링."""
    st.divider()
    st.subheader("분석 결과")

    # 메트릭 카드
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

    # 감성 분포 파이차트
    st.subheader("감성 분포")
    sentiment_df = pd.DataFrame(
        [
            {"감성": k, "건수": v}
            for k, v in result.sentiment_distribution.items()
            if v > 0
        ]
    )
    if not sentiment_df.empty:
        color_map = {"positive": "#4CAF50", "negative": "#F44336", "neutral": "#9E9E9E"}
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

    with col1:
        st.markdown("**긍정 키워드**")
        pos_top10 = result.keywords_positive[:10]
        if pos_top10:
            pos_df = pd.DataFrame(pos_top10, columns=["키워드", "점수"])
            pos_df["점수"] = pos_df["점수"].round(4)
            st.dataframe(pos_df, hide_index=True, use_container_width=True)
        else:
            st.info("데이터 없음")

    with col2:
        st.markdown("**부정 키워드**")
        neg_top10 = result.keywords_negative[:10]
        if neg_top10:
            neg_df = pd.DataFrame(neg_top10, columns=["키워드", "점수"])
            neg_df["점수"] = neg_df["점수"].round(4)
            st.dataframe(neg_df, hide_index=True, use_container_width=True)
        else:
            st.info("데이터 없음")

    # 워드클라우드 탭
    st.subheader("워드클라우드")
    wc_tab_all, wc_tab_pos, wc_tab_neg = st.tabs(["전체", "긍정", "부정"])

    _wc_path = result.wordcloud_path

    with wc_tab_all:
        if _wc_path and Path(_wc_path).exists():
            st.image(str(_wc_path), use_container_width=True)
        else:
            st.info("워드클라우드 이미지가 없습니다.")

    with wc_tab_pos:
        pos_wc = (
            Path(str(_wc_path)).parent / "wordcloud_positive.png"
            if _wc_path
            else None
        )
        if pos_wc and pos_wc.exists():
            st.image(str(pos_wc), use_container_width=True)
        else:
            st.info("긍정 워드클라우드 이미지가 없습니다.")

    with wc_tab_neg:
        neg_wc = (
            Path(str(_wc_path)).parent / "wordcloud_negative.png"
            if _wc_path
            else None
        )
        if neg_wc and neg_wc.exists():
            st.image(str(neg_wc), use_container_width=True)
        else:
            st.info("부정 워드클라우드 이미지가 없습니다.")

    # 인사이트
    st.subheader("인사이트")
    for insight in result.insights:
        st.info(insight)


def _render_download_section(
    result: AnalysisResult,
    raw_df: pd.DataFrame,
) -> None:
    """다운로드 섹션 렌더링."""
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
            zip_bytes = _build_zip(raw_df, result, project_name="review_analysis")
        if zip_bytes:
            render_download_button(
                data=zip_bytes,
                filename="review_analysis_package.zip",
                label="납품 패키지(ZIP) 다운로드",
                mime="application/zip",
            )
        else:
            st.error("납품 패키지 생성에 실패했습니다.")


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------


def main() -> None:
    """Streamlit 앱 진입점."""
    st.set_page_config(
        page_title="리뷰 분석 프로그램",
        page_icon="📊",
        layout="wide",
    )

    render_header(
        title="리뷰 분석 프로그램",
        subtitle="리뷰 수집만 하지 마세요. AI가 분석합니다.",
    )

    # Step 1: 데이터 입력
    df = _render_step1_input()

    # CSV 업로드로 df가 갱신된 경우 session_state 동기화
    if df is not None:
        st.session_state[_SESSION_DF] = df
        if _SESSION_RAW_DF not in st.session_state:
            st.session_state[_SESSION_RAW_DF] = df

    working_df: pd.DataFrame | None = st.session_state.get(_SESSION_DF)

    if working_df is None or working_df.empty:
        st.info("데이터를 입력하면 분석 설정이 표시됩니다.")
        return

    st.divider()

    # Step 2: 분석 설정
    text_column, rating_column = _render_step2_settings(working_df)

    st.divider()

    # 분석 시작 버튼
    if st.button("분석 시작", type="primary"):
        with st.spinner("분석 중..."):
            try:
                analyzer = ReviewAnalyzer(
                    text_column=text_column,
                    rating_column=rating_column,
                )
                result = analyzer.run(working_df)
                st.session_state[_SESSION_RESULT] = result
                log.info(
                    "분석 완료",
                    total_reviews=result.total_reviews,
                    avg_rating=result.avg_rating,
                )
            except Exception as exc:
                log.error("분석 실패", error=str(exc))
                st.error(f"분석 중 오류가 발생했습니다: {exc}")
                return

    # 결과 표시
    result: AnalysisResult | None = st.session_state.get(_SESSION_RESULT)
    if result is not None:
        _render_results(result)

        raw_df: pd.DataFrame = st.session_state.get(_SESSION_RAW_DF, working_df)
        _render_download_section(result, raw_df)


if __name__ == "__main__":
    main()
