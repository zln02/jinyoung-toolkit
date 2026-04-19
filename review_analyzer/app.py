"""리뷰 분석 프로그램 — Streamlit 메인 앱."""

from __future__ import annotations

import asyncio
import io
import re
import shutil
import tempfile
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from review_analyzer.analyzer import AnalysisResult, ReviewAnalyzer
from review_analyzer.comparator import ComparisonReport, ProductComparator, ProductInput
from review_analyzer.crawler.engine import CrawlConfig, CrawlerEngine, DriverType
from review_analyzer.preset_loader import PresetLoader
from review_analyzer.selector_inferer import (
    SelectorInferenceError,
    infer_preset_from_url,
)
from shared.comparison_report_generator import ComparisonReportGenerator
from shared.config import get_settings
from shared.logger import get_logger
from shared.ui_components import (
    render_download_button,
    render_error,
    render_file_uploader,
    render_header,
    render_metrics,
    render_step_indicator,
)

log = get_logger(__name__)

_SESSION_DF = "ra_df"
_SESSION_RESULT = "ra_result"
_SESSION_RAW_DF = "ra_raw_df"

# ---------------------------------------------------------------------------
# 모듈 상수
# ---------------------------------------------------------------------------

_PRESET_EMOJI: dict[str, str] = {
    "eleven_st": "🛒",
    "coupang_reviews": "🛒",
    "naver_shopping": "🛒",
    "amazon_reviews": "🛒",
    "yes24_book": "📚",
    "cgv_movie": "🎬",
    "melon_song": "🎵",
    "google_play": "📱",
    "apple_app_store": "📱",
    "youtube_comments": "📺",
    "naver_blog": "📝",
    "naver_cafe": "💬",
    "yanolja_hotel": "🏨",
    "custom_template": "⚙️",
}

_SEARCH_PLACEHOLDERS: dict[str, str] = {
    "amazon_reviews": "예: wireless earbuds",
    "coupang_reviews": "예: 무선청소기",
    "naver_shopping": "예: 겨울 코트",
    "eleven_st": "예: 에어프라이어",
    "yes24_book": "예: 클린 코드",
    "cgv_movie": "예: 어벤져스",
    "melon_song": "예: BTS",
    "google_play": "예: 카카오톡",
    "apple_app_store": "예: 인스타그램",
    "youtube_comments": "예: 운동 루틴",
    "naver_blog": "예: 부산 여행",
    "naver_cafe": "예: 자취 꿀팁",
    "yanolja_hotel": "예: 제주 호텔",
}

_TEXT_HINTS = ("content", "review", "text", "내용", "리뷰", "댓글", "comment")
_RATING_HINTS = ("rating", "star", "score", "평점", "별점", "점수")


# ---------------------------------------------------------------------------
# 캐싱 헬퍼 (Streamlit rerun에서 디스크 IO 방지)
# ---------------------------------------------------------------------------


@st.cache_resource
def _get_preset_loader() -> PresetLoader:
    """싱글톤 PresetLoader. rerun마다 재생성 방지."""
    return PresetLoader()


@st.cache_data
def _list_all_presets() -> list[dict[str, Any]]:
    """14개 프리셋 메타데이터. rerun마다 디스크 IO 방지."""
    return _get_preset_loader().list_presets()


@st.cache_data
def _load_preset_dict(name: str) -> dict[str, Any]:
    """프리셋 dict. 같은 이름은 한 번만 로드."""
    return _get_preset_loader().load(name)


@st.cache_data
def _load_sample_df() -> pd.DataFrame | None:
    """샘플 50건 CSV. rerun마다 디스크 IO 방지."""
    sample_path = (
        Path(__file__).resolve().parent.parent
        / "tests"
        / "fixtures"
        / "sample_reviews_50.csv"
    )
    if not sample_path.exists():
        return None
    return pd.read_csv(sample_path, encoding="utf-8-sig")


# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------


def _is_private_host(hostname: str) -> bool:
    """내부망/루프백/링크로컬 호스트 여부. SSRF 방지."""
    if not hostname:
        return True
    lower = hostname.lower()
    if lower in ("localhost", "localhost.localdomain") or lower.endswith(
        (".internal", ".local", ".localhost")
    ):
        return True
    import ipaddress

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _validate_url(raw: str) -> str | None:
    """URL 형식 검증 + SSRF 방지(사설·루프백 IP 차단). 유효하지 않으면 None."""
    from urllib.parse import urlparse

    stripped = (raw or "").strip()
    if not stripped:
        return None
    if not (stripped.startswith("http://") or stripped.startswith("https://")):
        return None
    try:
        parsed = urlparse(stripped)
    except ValueError:
        return None
    if _is_private_host(parsed.hostname or ""):
        return None
    return stripped


def _match_hint(col_lower: str, hint: str) -> bool:
    """단어 경계 매칭. 'reviewer' 안의 'review' 처럼 부분일치 오탐을 막는다."""
    return re.search(rf"(^|[_\s\-]){re.escape(hint)}([_\s\-]|$)", col_lower) is not None


def _guess_text_column(df: pd.DataFrame) -> str | None:
    """텍스트(리뷰 내용) 컬럼을 휴리스틱으로 추측.

    힌트 우선순위(``_TEXT_HINTS`` 순서)를 지키기 위해 hint 를 outer-loop 으로 둔다.
    1) hint 와 정확 일치 → 즉시 채택
    2) hint 와 단어 경계 일치 → 채택 ('content' 가 'reviewer' 보다 먼저 잡혀야 함)
    3) fallback: object 컬럼 중 평균 길이가 가장 긴 컬럼
    """
    cols = list(df.columns)
    cols_lower = [(c, str(c).lower()) for c in cols]

    for hint in _TEXT_HINTS:
        for col, col_lower in cols_lower:
            if col_lower == hint:
                return col
        for col, col_lower in cols_lower:
            if _match_hint(col_lower, hint):
                return col

    object_cols = [c for c in cols if df[c].dtype == object]
    if not object_cols:
        return cols[0] if cols else None
    best = max(
        object_cols,
        key=lambda c: df[c].astype(str).str.len().mean() if len(df) > 0 else 0,
    )
    return best


def _guess_rating_column(df: pd.DataFrame) -> str | None:
    """평점 컬럼을 휴리스틱으로 추측. (텍스트 컬럼과 동일한 우선순위 규칙)"""
    cols = list(df.columns)
    cols_lower = [(c, str(c).lower()) for c in cols]

    for hint in _RATING_HINTS:
        for col, col_lower in cols_lower:
            if col_lower == hint:
                return col
        for col, col_lower in cols_lower:
            if _match_hint(col_lower, hint):
                return col

    numeric_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
    return numeric_cols[0] if numeric_cols else None


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _run_crawl(
    preset_or_dict: str | dict[str, Any],
    url: str,
    max_pages: int,
    respect_robots_txt: bool = True,
) -> pd.DataFrame:
    """크롤링 실행 — asyncio.run 래핑.

    Args:
        preset_or_dict: 프리셋 이름(str)이면 PresetLoader로 로드, dict면 그대로 사용.
        url: 크롤링 대상 URL.
        max_pages: 최대 페이지 수.
        respect_robots_txt: robots.txt 준수 여부.
    """
    if isinstance(preset_or_dict, dict):
        preset = preset_or_dict
        preset_name = str(preset.get("name", "auto_inferred"))
    else:
        preset_name = preset_or_dict
        loader = PresetLoader()
        preset = loader.load(preset_name)

    driver_type_str = (preset.get("driver", {}) or {}).get("type", "httpx")
    try:
        driver_type = DriverType(driver_type_str)
    except ValueError:
        log.warning("알 수 없는 driver type, httpx로 폴백", driver_type=driver_type_str)
        driver_type = DriverType.HTTPX

    config = CrawlConfig(
        preset_name=preset_name,
        target_urls=[url],
        max_pages=max_pages,
        driver_type=driver_type,
        respect_robots_txt=respect_robots_txt,
    )
    engine = CrawlerEngine(config=config, preset=preset)

    crawl_result = asyncio.run(engine.run())
    return crawl_result.data


def _build_fallback_zip(raw_df: pd.DataFrame, zip_path: Path) -> bytes:
    """raw.csv만 담은 최소 ZIP 생성 (폴백용)."""
    with zipfile.ZipFile(zip_path, "w") as zf:
        buf = io.BytesIO()
        raw_df.to_csv(buf, index=False, encoding="utf-8-sig")
        zf.writestr("raw.csv", buf.getvalue())
    return zip_path.read_bytes()


def _build_zip(
    raw_df: pd.DataFrame, result: AnalysisResult, project_name: str
) -> tuple[bytes, bool]:
    """납품 패키지 ZIP 바이트 반환. (zip_bytes, is_fallback)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / f"{project_name}.zip"
        analyzer = ReviewAnalyzer()

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


_SESSION_COMPARISON_REPORT = "comparison_report"


def _render_comparison_input() -> None:
    """경쟁사 비교 리포트 입력 UI 및 결과 표시."""
    st.markdown("### 경쟁사 비교 리포트 생성")

    all_presets = _list_all_presets()
    preset_options: dict[str, str] = {
        f"{_PRESET_EMOJI.get(p['name'], '🔧')} {p['display_name']}": p["name"]
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

        # ProductInput 리스트 구성
        try:
            preset_dict: dict[str, Any] = _load_preset_dict(selected_preset_name)
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
                ProductInput(
                    label=lbl,
                    url=u,
                    preset_name=selected_preset_name,
                )
            )

        try:
            comparator = ProductComparator(
                products=product_inputs,
                preset=preset_dict,
            )
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
    report_result: ComparisonReport | None = st.session_state.get(
        _SESSION_COMPARISON_REPORT
    )
    if report_result is not None:
        st.divider()
        st.subheader("비교 결과")

        # 크롤링 실패 경고
        if report_result.failed_products:
            joined = ", ".join(report_result.failed_products)
            st.warning(f"⚠️ {joined} — 크롤링 실패, 분석에서 제외됨")

        # 요약 테이블
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

        # 우위 포인트
        if report_result.win_points:
            st.markdown("**우리가 이기는 포인트**")
            for point in report_result.win_points:
                st.success(point)

        # 열위 포인트
        if report_result.lose_points:
            st.markdown("**우리가 지는 포인트**")
            for point in report_result.lose_points:
                st.warning(point)

        # 권장 개선 포인트
        if report_result.action_items:
            st.markdown("**💡 권장 개선 포인트**")
            for item in report_result.action_items:
                st.info(item)

        # PDF 다운로드 (1클릭)
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


def _render_step1_input() -> pd.DataFrame | None:
    """Step 1: 데이터 입력 섹션 렌더링. 로드된 DataFrame 반환."""
    st.subheader("Step 1. 데이터 입력")

    if st.button("🎁 샘플 데이터로 먼저 체험하기", type="primary", key="ra_sample_btn"):
        st.session_state["ra_input_mode"] = "샘플로 먼저 보기"

    input_mode = st.radio(
        "데이터 입력 방식",
        options=[
            "파일로 올리기 (CSV·Excel)",
            "사이트에서 가져오기",
            "샘플로 먼저 보기",
        ],
        horizontal=True,
        key="ra_input_mode",
    )

    df: pd.DataFrame | None = None

    if input_mode == "파일로 올리기 (CSV·Excel)":
        df = render_file_uploader()
        if df is not None:
            st.caption(f"✅ 업로드 완료 — {len(df):,}건 / {len(df.columns)}개 컬럼")

    elif input_mode == "샘플로 먼저 보기":
        df = _load_sample_df()
        if df is not None:
            st.success(f"샘플 데이터를 불러왔어요: {len(df)}건")
            st.dataframe(df.head())
        else:
            st.warning("샘플 데이터 파일이 없습니다.")

    else:
        # custom_template은 샘플 프리셋이므로 UI에서 숨김
        presets = [p for p in _list_all_presets() if p["name"] != "custom_template"]

        collection_mode = st.radio(
            "📝 어떤 방식으로 가져올까요?",
            options=[
                "자주 쓰는 사이트에서 고르기",
                "AI 자동 분석 (Claude Haiku API, 1건당 약 1원)",
            ],
            index=0,
        )
        use_ai = collection_mode.startswith("AI")

        selected_preset: str | None = None
        preset_dict: dict[str, Any] | None = None
        search_tpl: str | None = None
        keyword: str | None = None
        url: str = ""
        if not use_ai:
            if not presets:
                st.warning("사용 가능한 사이트 목록이 없습니다.")
                return None
            preset_options_map = {
                f"{_PRESET_EMOJI.get(p['name'], '🔧')} {p['display_name']}": p["name"]
                for p in presets
            }
            selected_display = st.selectbox(
                "어떤 사이트인가요?", list(preset_options_map.keys())
            )
            selected_preset = preset_options_map[selected_display]
            preset_dict = _load_preset_dict(selected_preset)
            search_tpl = preset_dict.get("search_url_template")

            if search_tpl:
                keyword = st.text_input(
                    "어떤 키워드로 검색할까요?",
                    placeholder=_SEARCH_PLACEHOLDERS.get(selected_preset, "예: 검색어 입력"),
                    help="키워드를 입력하면 자동으로 검색 결과를 모아와요.",
                )
            else:
                url = st.text_input(
                    "페이지 주소를 붙여넣어 주세요",
                    placeholder="예: https://search.naver.com/...",
                )
        else:
            st.info(
                "✨ 페이지 주소를 알려주시면 AI가 한 번 훑어보고 "
                "필요한 정보를 찾아드려요. (Claude Haiku API, 1건당 약 1원)"
            )
            if not get_settings().anthropic_api_key:
                st.warning(
                    "AI 자동 분석을 쓰려면 관리자에게 AI 키 설정을 요청해 주세요. "
                    "(그 전에는 '자주 쓰는 사이트에서 고르기'만 사용 가능)"
                )
            url = st.text_input(
                "페이지 주소를 붙여넣어 주세요",
                placeholder="예: https://search.naver.com/...",
            )

        max_pages = st.number_input(
            "몇 페이지까지 모을까요?",
            min_value=1,
            max_value=500,
            value=10,
            step=1,
            help=(
                "한 페이지에 보통 10~30개 리뷰가 있어요. "
                "처음엔 1~3페이지로 시작해 보세요."
            ),
        )

        with st.expander("더 보기 (선택 사항)"):
            ignore_robots = st.checkbox(
                "사이트의 수집 정책 무시하고 강제로 모으기 (전문가용)",
                value=False,
                help=(
                    "일부 사이트는 자동 수집을 막아두는데, 체크하면 무시해요. "
                    "일반 사용자는 끄는 걸 권장해요."
                ),
            )
            if ignore_robots:
                st.warning(
                    "주의: 사이트 약관·저작권법에 위반될 수 있어요. "
                    "수집 전에 사이트 이용약관을 확인하고 본인 책임 하에 "
                    "사용해 주세요."
                )

        if st.button("가져오기 시작"):
            if not use_ai and search_tpl:
                if not keyword:
                    st.error("검색어를 먼저 입력해 주세요.")
                    return None
                url = search_tpl.format(
                    keyword=urllib.parse.quote_plus(keyword)
                )

            if not url:
                st.error("페이지 주소를 먼저 입력해 주세요.")
                return None

            preset_input: str | dict[str, Any]
            if use_ai:
                with st.spinner("AI가 페이지를 살펴보는 중..."):
                    try:
                        inferred = asyncio.run(infer_preset_from_url(url))
                    except SelectorInferenceError as exc:
                        log.error("자동 셀렉터 추론 실패", error=str(exc))
                        render_error(exc, context="AI 자동 분석")
                        return None
                    except Exception as exc:
                        log.error("자동 추론 예외", error=str(exc))
                        render_error(exc, context="AI 자동 분석")
                        return None

                fields = inferred.get("selectors", {}).get("fields", {})
                st.success(
                    f"✨ AI 분석 완료! {len(fields)}가지 정보를 모아올게요."
                )
                preset_input = inferred
            else:
                assert preset_dict is not None
                preset_input = preset_dict

            with st.spinner(f"리뷰를 모으는 중이에요... (최대 {max_pages}페이지)"):
                try:
                    df = _run_crawl(
                        preset_input,
                        url,
                        int(max_pages),
                        respect_robots_txt=not ignore_robots,
                    )
                    st.session_state[_SESSION_DF] = df
                    st.session_state[_SESSION_RAW_DF] = df
                    st.success(f"🎉 총 {len(df)}건을 모았어요.")
                    st.dataframe(df.head())
                except Exception as exc:
                    log.error("크롤링 실패", error=str(exc))
                    render_error(exc, context="리뷰 가져오기")
                    return None

    return df


def _render_step2_settings(df: pd.DataFrame) -> tuple[str, str | None]:
    """Step 2: 분석 설정 섹션 렌더링. (text_column, rating_column) 반환."""
    st.subheader("Step 2. 분석 설정")

    columns = list(df.columns)

    guessed_text = _guess_text_column(df)
    text_index = columns.index(guessed_text) if guessed_text in columns else 0
    text_column: str = st.selectbox(
        "텍스트(리뷰 내용) 컬럼",
        options=columns,
        index=text_index,
    )

    rating_options = ["(없음)"] + columns
    guessed_rating = _guess_rating_column(df)
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

    st.info("💡 텍스트 컬럼: 리뷰 내용이 들어있는 컬럼 / 평점 컬럼: 1~5 숫자 평점")

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

    # 키워드 Top 10 (이슈 #7a — 막대 차트 + 표는 expander)
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

    # 존재하는 워드클라우드 이미지 수집
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
            zip_bytes, is_fallback = _build_zip(
                raw_df, result, project_name="review_analysis"
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


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------


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

    tab_analyze, tab_compare = st.tabs(["📊 리뷰 분석", "⚔️ 경쟁사 비교"])

    with tab_analyze:
        # Step indicator
        if st.session_state.get(_SESSION_RESULT) is not None:
            current_step = 3
        elif st.session_state.get(_SESSION_DF) is not None:
            current_step = 2
        else:
            current_step = 1
        render_step_indicator(current_step, 3, ["데이터 입력", "분석 설정", "결과 확인"])

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
        else:
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
                        render_error(exc, context="분석")

            # 결과 표시
            result: AnalysisResult | None = st.session_state.get(_SESSION_RESULT)
            if result is not None:
                _render_results(result)

                raw_df: pd.DataFrame = st.session_state.get(_SESSION_RAW_DF, working_df)
                _render_download_section(result, raw_df)

    with tab_compare:
        _render_comparison_input()


if __name__ == "__main__":
    main()
