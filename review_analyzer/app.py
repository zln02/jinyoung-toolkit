"""리뷰 분석 프로그램 — Streamlit 메인 앱 (엔트리포인트).

UI 로직은 review_analyzer.ui 서브패키지로 분리:
  - ui/_helpers.py     — 공용 헬퍼(캐싱·URL검증·컬럼추론)
  - ui/crawler_tab.py  — Step 1 데이터 입력
  - ui/analyze_tab.py  — Step 2·3 분석 설정·결과
  - ui/compare_tab.py  — 경쟁사 비교 탭
"""

from __future__ import annotations

import streamlit as st

from review_analyzer.analyzer import AnalysisResult
from shared.logger import get_logger
from shared.ui_components import render_error, render_header, render_step_indicator
import shared.visitor_stats as vstats
from review_analyzer.ui.analyze_tab import (
    _build_zip,
    render_download_section,
    render_results,
    render_step2_settings,
)
from review_analyzer.ui.advanced_tab import render_advanced_analysis
from review_analyzer.ui.compare_tab import render_comparison_input
from review_analyzer.ui.crawler_tab import render_step1_input

# ---------------------------------------------------------------------------
# 하위 호환 re-export (테스트·외부 코드가 app에서 직접 import하는 경우 대응)
# ---------------------------------------------------------------------------
from review_analyzer.ui._helpers import guess_text_column as _guess_text_column
from review_analyzer.ui._helpers import guess_rating_column as _guess_rating_column

log = get_logger(__name__)

_SESSION_DF = "ra_df"
_SESSION_RESULT = "ra_result"
_SESSION_RAW_DF = "ra_raw_df"
_SESSION_CFG = "ra_cfg"  # 분석 시점의 (text_column, rating_column, SentimentConfig)


def main() -> None:
    """Streamlit 앱 진입점."""
    try:
        st.set_page_config(
            page_title="리뷰 분석 스튜디오",
            page_icon="📊",
            layout="wide",
        )
    except st.errors.StreamlitAPIException:
        pass

    render_header(
        title="리뷰 분석 스튜디오",
        subtitle="URL 하나로 리뷰를 뽑고, 경쟁사랑 한눈에 비교하세요",
    )

    tab_analyze, tab_compare, tab_advanced = st.tabs(
        ["📊 리뷰 분석", "⚔️ 경쟁사 비교", "🔬 고급 분석"]
    )

    with tab_analyze:
        # 랜딩의 "🎁 리뷰 분석 샘플로 시작" 클릭 시 자동 로드 + 분석까지 한 번에
        if st.session_state.pop("_auto_sample", None) == "review":
            with st.spinner("샘플 데이터를 자동 분석 중... (약 10초)"):
                try:
                    from review_analyzer.analyzer import ReviewAnalyzer
                    from review_analyzer.ui._helpers import load_sample_df

                    _sdf = load_sample_df()
                    if _sdf is not None and not _sdf.empty:
                        _analyzer = ReviewAnalyzer(
                            text_column="content", rating_column="rating"
                        )
                        _result = _analyzer.run(_sdf)
                        st.session_state[_SESSION_DF] = _sdf
                        st.session_state[_SESSION_RAW_DF] = _sdf
                        st.session_state[_SESSION_RESULT] = _result
                        st.session_state[_SESSION_CFG] = ("content", "rating", None)
                        vstats.record_activity("샘플 데모(리뷰)")
                        st.success("🎉 샘플 자동 분석 완료! 아래에서 결과를 확인하세요.")
                except Exception as exc:
                    log.error("샘플 자동 분석 실패", error=str(exc))

        # Step indicator
        if st.session_state.get(_SESSION_RESULT) is not None:
            current_step = 3
        elif st.session_state.get(_SESSION_DF) is not None:
            current_step = 2
        else:
            current_step = 1
        render_step_indicator(current_step, 3, ["데이터 입력", "분석 설정", "결과 확인"])

        # Step 1: 데이터 입력
        df = render_step1_input()

        # CSV 업로드로 df가 갱신된 경우 session_state 동기화
        if df is not None:
            st.session_state[_SESSION_DF] = df
            if _SESSION_RAW_DF not in st.session_state:
                st.session_state[_SESSION_RAW_DF] = df

        working_df = st.session_state.get(_SESSION_DF)

        if working_df is None or working_df.empty:
            st.info("데이터를 입력하면 분석 설정이 표시됩니다.")
        else:
            st.divider()

            # Step 2: 분석 설정 (+ 고급 설정으로 감성 분석 맞춤)
            text_column, rating_column, sentiment_config = render_step2_settings(
                working_df
            )

            st.divider()

            # 분석 시작 버튼
            if st.button("분석 시작", type="primary"):
                with st.spinner("분석 중..."):
                    try:
                        from review_analyzer.analyzer import ReviewAnalyzer

                        analyzer = ReviewAnalyzer(
                            text_column=text_column,
                            rating_column=rating_column,
                            sentiment_config=sentiment_config,
                        )
                        result = analyzer.run(working_df)
                        st.session_state[_SESSION_RESULT] = result
                        vstats.record_activity("리뷰 분석")
                        # 다운로드(ZIP 재분석)가 화면 결과와 일치하도록 분석 시점 설정 보존
                        st.session_state[_SESSION_CFG] = (
                            text_column,
                            rating_column,
                            sentiment_config,
                        )
                        log.info(
                            "분석 완료",
                            total_reviews=result.total_reviews,
                            avg_rating=result.avg_rating,
                        )
                    except Exception as exc:
                        log.error("분석 실패", error=str(exc))
                        render_error(exc, context="분석")

            # 결과 표시
            result: AnalysisResult | None = st.session_state.get(_SESSION_RESULT)
            if result is not None:
                render_results(result)
                raw_df = st.session_state.get(_SESSION_RAW_DF, working_df)
                saved_text, saved_rating, saved_cfg = st.session_state.get(
                    _SESSION_CFG, (text_column, rating_column, sentiment_config)
                )
                render_download_section(
                    result,
                    raw_df,
                    text_column=saved_text,
                    rating_column=saved_rating,
                    sentiment_config=saved_cfg,
                )

    with tab_compare:
        render_comparison_input()

    with tab_advanced:
        adv_df = st.session_state.get(_SESSION_DF)
        if adv_df is None or adv_df.empty:
            st.info("먼저 '리뷰 분석' 탭에서 데이터를 입력하면 고급 분석을 할 수 있어요.")
        else:
            render_advanced_analysis(adv_df)


if __name__ == "__main__":
    main()
