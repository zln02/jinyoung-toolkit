"""review_analyzer.ui.compare_tab — 경쟁사 비교 탭 렌더러."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from review_analyzer.comparator import ComparisonReport, ProductComparator, ProductInput
from review_analyzer.crawler.engine import DriverType
from review_analyzer.comparison_report_generator import ComparisonReportGenerator
from shared.logger import get_logger
from review_analyzer.ui._helpers import (
    PRESET_EMOJI,
    _validate_url,
    list_all_presets,
    load_preset_dict,
)

log = get_logger(__name__)

_SESSION_COMPARISON_REPORT = "comparison_report"


def render_comparison_input() -> None:
    """경쟁사 비교 리포트 입력 UI 및 결과 표시."""
    st.markdown("### 경쟁사 비교 리포트 생성")

    all_presets = list_all_presets()
    preset_options: dict[str, str] = {
        f"{PRESET_EMOJI.get(p['name'], '🔧')} {p['display_name']}": p["name"]
        for p in all_presets
    }
    preset_display_names = list(preset_options.keys())

    if not preset_display_names:
        st.warning("사용 가능한 프리셋이 없습니다.")
        return

    selected_display = st.selectbox(
        "어떤 사이트의 리뷰를 비교할까요?",
        options=preset_display_names,
        key="cmp_preset_select",
    )
    selected_preset_name: str = preset_options[selected_display]

    st.markdown("**제품 URL 입력**")
    default_labels_all = ["우리 제품", "경쟁사 A", "경쟁사 B", "경쟁사 C"]
    labels: list[str] = []
    urls: list[str] = []
    for i in range(4):
        with st.container(border=True):
            st.caption(f"{i+1}/4 · {'우리 제품 (필수)' if i == 0 else '경쟁사 (선택)'}")
            col_name, col_url = st.columns([1, 3])
            with col_name:
                lbl = st.text_input("이름", value=default_labels_all[i], key=f"cmp_label{i}")
            with col_url:
                u = st.text_input(
                    "제품 URL",
                    placeholder="https://...",
                    key=f"cmp_url{i}",
                )
            labels.append(lbl)
            urls.append(u)

    if st.button("비교 리포트 생성", type="primary", key="cmp_run_btn"):
        our_url = _validate_url(urls[0])
        if our_url is None:
            st.error("우리 제품 URL을 확인해 주세요. http:// 또는 https:// 로 시작해야 해요.")
            return
        competitor_inputs: list[tuple[str, str]] = []
        for i in range(1, 4):
            v = _validate_url(urls[i])
            if v:
                competitor_inputs.append((labels[i].strip() or default_labels_all[i], v))
        if not competitor_inputs:
            st.error("경쟁사 URL을 최소 1개 입력해 주세요. (http:// 또는 https:// 로 시작)")
            return

        try:
            preset_dict: dict[str, Any] = load_preset_dict(selected_preset_name)
        except Exception as exc:
            log.error("프리셋_로드_실패", preset=selected_preset_name, error=str(exc))
            st.error("사이트 설정을 불러오지 못했어요")
            return

        product_inputs: list[ProductInput] = [
            ProductInput(
                label=labels[0].strip() or "우리 제품",
                url=our_url,
                preset_name=selected_preset_name,
            )
        ]
        for lbl, u in competitor_inputs:
            product_inputs.append(
                ProductInput(label=lbl, url=u, preset_name=selected_preset_name)
            )

        try:
            comparator = ProductComparator(products=product_inputs, preset=preset_dict)
        except ValueError as exc:
            st.error("입력값을 확인해 주세요: " + str(exc))
            return

        with st.status("경쟁사 리뷰를 수집하는 중...", expanded=True) as status:
            try:
                status.write("1/3 · 4개 제품 페이지 수집 중...")
                crawled = asyncio.run(
                    comparator.crawl_all(
                        max_pages=1,
                        driver=DriverType.SELENIUM,
                        respect_robots=True,
                    )
                )
                status.write("2/3 · 리뷰 분석 중...")
                analyzed = comparator.analyze_all(crawled)
                failed = [p.label for p in analyzed if p.result.total_reviews == 0]
                status.write("3/3 · 비교 리포트 작성 중...")
                summary = comparator.build_summary(analyzed)
                win, lose = comparator.diagnose_gaps(analyzed)
                actions = comparator.generate_action_items(lose, analyzed)
                report: ComparisonReport = ComparisonReport(
                    products=analyzed,
                    summary_rows=summary,
                    win_points=win,
                    lose_points=lose,
                    action_items=actions,
                    failed_products=failed,
                )
                st.session_state[_SESSION_COMPARISON_REPORT] = report
                log.info(
                    "비교_리포트_생성_완료",
                    products=len(report.products),
                    win_points=len(report.win_points),
                    lose_points=len(report.lose_points),
                )
                status.update(label="완료!", state="complete", expanded=False)
            except Exception as exc:
                log.error("비교_리포트_생성_실패", error=str(exc))
                status.update(label="문제가 생겼어요", state="error")
                st.error("리포트를 만드는 중 문제가 생겼어요. 다시 시도해 주세요.")
                return

    # 결과 표시
    report_result: ComparisonReport | None = st.session_state.get(_SESSION_COMPARISON_REPORT)
    if report_result is not None:
        st.divider()
        st.subheader("비교 결과")

        if report_result.failed_products:
            joined = ", ".join(report_result.failed_products)
            st.warning(f"⚠️ {joined} — 크롤링 실패, 분석에서 제외됨")

        if report_result.summary_rows:
            try:
                summary_df = pd.DataFrame(report_result.summary_rows)
                summary_df.columns = [
                    "제품명", "리뷰 수", "평균 평점", "긍정%", "부정%", "평균 문장 길이"
                ]
                st.dataframe(summary_df, hide_index=True, use_container_width=True)
            except Exception as exc:
                log.error("요약_테이블_표시_실패", error=str(exc))
                st.warning("요약 테이블 표시에 실패했습니다.")

        if report_result.win_points:
            st.markdown("**우리가 이기는 포인트**")
            for point in report_result.win_points:
                st.success(point)

        if report_result.lose_points:
            st.markdown("**우리가 지는 포인트**")
            for point in report_result.lose_points:
                st.warning(point)

        if report_result.action_items:
            st.markdown("**💡 권장 개선 포인트**")
            for item in report_result.action_items:
                st.info(item)

        st.markdown("**PDF 다운로드**")
        if st.button("PDF 다운로드 준비", key="cmp_pdf_btn"):
            with st.spinner("PDF를 만드는 중..."):
                try:
                    with tempfile.TemporaryDirectory() as tmp:
                        tmp_pdf_path = Path(tmp) / "comparison_report.pdf"
                        ComparisonReportGenerator().render(report_result, tmp_pdf_path)
                        pdf_bytes = tmp_pdf_path.read_bytes()
                except Exception as exc:
                    log.error("비교_PDF_생성_실패", error=str(exc))
                    st.error("PDF를 만드는 중 문제가 생겼어요. 다시 시도해 주세요.")
                    pdf_bytes = b""
            if pdf_bytes:
                st.download_button(
                    label="📄 PDF 다운로드",
                    data=pdf_bytes,
                    file_name="comparison_report.pdf",
                    mime="application/pdf",
                    key="cmp_pdf_download",
                )
