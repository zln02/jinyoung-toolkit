"""jinyoung-toolkit — Streamlit 메인 허브."""

from __future__ import annotations

import streamlit as st

from shared.logger import get_logger

log = get_logger(__name__)

_TOOLS = {
    "리뷰 분석기": "review_analyzer",
    "AutoML 리포트": "automl_reporter",
}


def main() -> None:
    st.set_page_config(page_title="jinyoung-toolkit", page_icon="🧰", layout="wide")

    selected = st.sidebar.selectbox("도구 선택", list(_TOOLS.keys()))

    if selected == "리뷰 분석기":
        from review_analyzer.app import main as ra_main

        ra_main()
    elif selected == "AutoML 리포트":
        from automl_reporter.app import main as aml_main

        aml_main()


if __name__ == "__main__":
    main()
