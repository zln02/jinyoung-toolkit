"""review_analyzer.ui.crawler_tab — Step 1 데이터 입력 섹션.

크롤링(URL 입력), 파일 업로드, 샘플 데이터 세 가지 모드를 제공한다.
"""

from __future__ import annotations

import asyncio
import re
import urllib.parse
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from review_analyzer.crawler.engine import CrawlConfig, CrawlerEngine, DriverType
from review_analyzer.selector_inferer import (
    SelectorInferenceError,
    infer_preset_from_url,
)
from shared.config import get_settings
from shared.logger import get_logger
from shared.ui_components import render_error, render_file_uploader
from review_analyzer.ui._helpers import (
    PRESET_EMOJI,
    SEARCH_PLACEHOLDERS,
    _validate_url,
    list_all_presets,
    load_preset_dict,
    load_sample_df,
)

log = get_logger(__name__)

_SESSION_DF = "ra_df"
_SESSION_RAW_DF = "ra_raw_df"


def _run_crawl(
    preset_or_dict: str | dict[str, Any],
    url: str,
    max_pages: int,
    respect_robots_txt: bool = True,
) -> pd.DataFrame:
    """크롤링 실행 — asyncio.run 래핑."""
    from review_analyzer.preset_loader import PresetLoader

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


def _parse_keywords(text: str) -> list[str]:
    """줄바꿈·쉼표로 구분된 키워드를 공백·중복 제거해 목록으로 반환."""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in re.split(r"[\n,]+", text):
        kw = raw.strip()
        if kw and kw not in seen:
            seen.add(kw)
            out.append(kw)
    return out


def _crawl_keywords(
    preset_dict: dict[str, Any],
    search_tpl: str,
    keywords: list[str],
    max_pages: int,
    respect_robots_txt: bool,
) -> pd.DataFrame:
    """키워드 목록을 각각 검색 크롤한 뒤 ``_keyword`` 컬럼을 붙여 합친다.

    한 키워드 실패는 건너뛰고(경고) 나머지를 계속 수집한다.
    """
    frames: list[pd.DataFrame] = []
    total = len(keywords)
    prog = st.progress(0.0, text="키워드 수집 준비 중...")
    for i, kw in enumerate(keywords):
        prog.progress(i / total, text=f"'{kw}' 수집 중... ({i + 1}/{total})")
        kw_url = search_tpl.format(keyword=urllib.parse.quote_plus(kw))
        try:
            sub = _run_crawl(
                preset_dict, kw_url, max_pages, respect_robots_txt=respect_robots_txt
            )
            if sub is not None and not sub.empty:
                sub = sub.copy()
                sub["_keyword"] = kw
                frames.append(sub)
        except Exception as exc:  # 한 키워드 실패가 전체를 막지 않도록
            log.error("키워드 크롤 실패", keyword=kw, error=str(exc))
            st.warning(f"'{kw}' 수집 실패: {exc}")
    prog.progress(1.0, text="수집 완료")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def render_step1_input() -> pd.DataFrame | None:
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
        df = load_sample_df()
        if df is not None:
            st.success(f"샘플 데이터를 불러왔어요: {len(df)}건")
            st.dataframe(df.head())
        else:
            st.warning("샘플 데이터 파일이 없습니다.")

    else:
        # custom_template은 샘플 프리셋이므로 UI에서 숨김
        presets = [p for p in list_all_presets() if p["name"] != "custom_template"]

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
                f"{PRESET_EMOJI.get(p['name'], '🔧')} {p['display_name']}": p["name"]
                for p in presets
            }
            selected_display = st.selectbox(
                "어떤 사이트인가요?", list(preset_options_map.keys())
            )
            selected_preset = preset_options_map[selected_display]
            preset_dict = load_preset_dict(selected_preset)
            search_tpl = preset_dict.get("search_url_template")

            if search_tpl:
                keyword = st.text_area(
                    "어떤 키워드로 검색할까요? (여러 개는 줄바꿈 또는 쉼표로)",
                    placeholder=SEARCH_PLACEHOLDERS.get(
                        selected_preset, "예: 검색어1\n검색어2, 검색어3"
                    ),
                    help="키워드를 여러 개 넣으면 각각 검색해서 한 번에 모아와요.",
                    height=100,
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
            # 검색형 프리셋: 키워드 1개 이상을 각각 크롤해 합친다(다중 키워드)
            if not use_ai and search_tpl:
                keywords = _parse_keywords(keyword)
                if not keywords:
                    st.error("검색어를 한 개 이상 입력해 주세요.")
                    return None
                assert preset_dict is not None
                with st.spinner(
                    f"키워드 {len(keywords)}개를 모으는 중... (각 최대 {int(max_pages)}페이지)"
                ):
                    df = _crawl_keywords(
                        preset_dict,
                        search_tpl,
                        keywords,
                        int(max_pages),
                        respect_robots_txt=not ignore_robots,
                    )
                if df is not None and not df.empty:
                    st.session_state[_SESSION_DF] = df
                    st.session_state[_SESSION_RAW_DF] = df
                    st.success(
                        f"🎉 키워드 {len(keywords)}개 · 총 {len(df)}건을 모았어요."
                    )
                    st.dataframe(df.head())
                else:
                    st.error("수집된 데이터가 없어요. 키워드나 페이지 수를 바꿔보세요.")
                return df

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
                st.success(f"✨ AI 분석 완료! {len(fields)}가지 정보를 모아올게요.")
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
