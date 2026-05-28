"""인사이트랩 (InsightLab) — Streamlit 메인 허브."""

from __future__ import annotations

import streamlit as st

from shared.config import get_settings
from shared.logger import get_logger
from shared.ui_components import render_metrics
import shared.visitor_stats as vstats

log = get_logger(__name__)

_TOOLS = {
    "홈": None,
    "리뷰 분석기": "review_analyzer",
    "AutoML 리포트": "automl_reporter",
}


def _render_landing() -> None:
    """랜딩 페이지 — Hero / 메트릭 / 기능 카드 / 미리보기 (이슈 #4, #5)."""
    # Hero
    st.title("인사이트랩")
    st.caption("InsightLab — 데이터 분석을 더 쉽게, 더 빠르게.")
    st.divider()

    # 실시간 이용 현황 (익명 집계 — IP 미저장)
    _stats = vstats.get_stats()
    render_metrics(
        {
            "누적 접속": f"{_stats['total_visits']:,}",
            "오늘 접속": f"{_stats['today_visits']:,}",
            "누적 분석 실행": f"{_stats['total_activities']:,}",
        },
        num_cols=3,
    )
    st.write("")

    # 3-메트릭 (시각적 신뢰도)
    render_metrics(
        {
            "지원 사이트": "14개",
            "리포트 생성": "5분",
            "ML 모델 선택": "자동",
        },
        num_cols=3,
    )

    st.write("")  # 여백

    # 기능 카드 2열
    col1, col2 = st.columns(2)

    with col1:
        with st.container(border=True):
            st.subheader("🛍️ 리뷰 분석기")
            st.write("고객 리뷰 수집 → 감성 분석 → 키워드/워드클라우드 → PDF 납품까지.")
            st.markdown(
                "- 🛒 14개 사이트 자동 크롤링\n"
                "- 🧠 한국어 감성 + 키워드 추출\n"
                "- 📄 PDF + ZIP 납품 패키지"
            )
            if st.button("리뷰 분석기 시작", key="landing_ra", type="primary"):
                st.session_state["_selected_tool"] = "리뷰 분석기"
                st.rerun()

    with col2:
        with st.container(border=True):
            st.subheader("🤖 AutoML 리포트")
            st.write("CSV 한 장 → 최적 모델 자동 선정 → PDF 리포트까지.")
            st.markdown(
                "- 📁 CSV 한 장만 있으면 OK\n"
                "- 🤖 모델 자동 비교 + 튜닝\n"
                "- 📊 PDF 결과 리포트"
            )
            if st.button("AutoML 리포트 시작", key="landing_aml", type="primary"):
                st.session_state["_selected_tool"] = "AutoML 리포트"
                st.rerun()

    st.write("")  # 여백

    # 결과물 미리보기 placeholder
    with st.expander("예시 리포트 미리보기", expanded=False):
        st.info(
            "샘플 데이터로 먼저 분석해 보면 PDF·워드클라우드·차트가 어떻게 나오는지 "
            "확인할 수 있어요. 좌측 사이드바에서 도구를 선택해 '샘플로 먼저 보기' 를 "
            "눌러보세요."
        )


def _render_visitor_panel() -> None:
    """사이드바 — 익명 이용 현황(접속·활동 집계, IP 미저장)."""
    stats = vstats.get_stats()
    st.sidebar.divider()
    st.sidebar.markdown("**📊 이용 현황**")
    c1, c2 = st.sidebar.columns(2)
    c1.metric("누적 접속", f"{stats['total_visits']:,}")
    c2.metric("오늘 접속", f"{stats['today_visits']:,}")
    c1.metric("누적 분석", f"{stats['total_activities']:,}")
    c2.metric("오늘 분석", f"{stats['today_activities']:,}")
    recent = vstats.get_recent_activities(3)
    if recent:
        st.sidebar.caption("최근 활동")
        for action, hhmm in recent:
            st.sidebar.caption(f"· {action}" + (f" · {hhmm}" if hhmm else ""))


def main() -> None:
    """Streamlit 메인 허브."""
    st.set_page_config(
        page_title="인사이트랩 InsightLab", page_icon="🧰", layout="wide"
    )

    # 익명 접속 집계 — 세션당 1회 (IP 미저장)
    if not st.session_state.get("_visit_recorded"):
        vstats.record_visit()
        st.session_state["_visit_recorded"] = True

    selected = st.sidebar.selectbox(
        "도구 선택",
        list(_TOOLS.keys()),
        index=list(_TOOLS.keys()).index(
            st.session_state.get("_selected_tool", "홈")
        ),
    )
    st.session_state["_selected_tool"] = selected

    _render_visitor_panel()

    # 외부 프로젝트 링크
    settings = get_settings()
    if settings.uis_url:
        st.sidebar.divider()
        st.sidebar.markdown("**다른 프로젝트**")
        st.sidebar.link_button(
            "🏥 감염병 조기경보 (UIS)",
            settings.uis_url,
        )

    if selected == "리뷰 분석기":
        from review_analyzer.app import main as ra_main

        ra_main()
    elif selected == "AutoML 리포트":
        from automl_reporter.app import main as aml_main

        aml_main()
    else:
        _render_landing()


if __name__ == "__main__":
    main()
