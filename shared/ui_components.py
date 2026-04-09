"""Streamlit 공통 UI 컴포넌트 모듈."""

from typing import Any

import pandas as pd
import streamlit as st

from shared.logger import get_logger

logger = get_logger(__name__)


def render_header(title: str, subtitle: str = "") -> None:
    """페이지 헤더를 렌더링한다.

    Args:
        title: 페이지 제목.
        subtitle: 페이지 부제목 (선택).
    """
    st.title(title)
    if subtitle:
        st.caption(subtitle)
    st.divider()


def render_step_indicator(current_step: int, total_steps: int, labels: list[str]) -> None:
    """Step 진행 표시기를 렌더링한다 (이슈 #6).

    상단 progress 바 + Streamlit 네이티브 ``st.container(border=True)`` 카드로
    스텝별 상태(완료/현재/미래)를 시각화한다. HTML 직접 삽입은 사용하지 않는다.

    Args:
        current_step: 현재 스텝 (1-based).
        total_steps: 전체 스텝 수.
        labels: 각 스텝의 레이블 목록.
    """
    progress_value = (current_step - 1) / max(total_steps - 1, 1)
    progress_value = max(0.0, min(progress_value, 1.0))
    st.progress(progress_value)

    cols = st.columns(total_steps)
    for i, (col, label) in enumerate(zip(cols, labels), start=1):
        with col:
            with st.container(border=True):
                if i < current_step:
                    st.markdown(f"✅ **Step {i}**")
                    st.caption(label)
                elif i == current_step:
                    st.markdown(f"🔵 **Step {i}**")
                    st.markdown(f"**{label}**")
                else:
                    st.markdown(f"⚪ Step {i}")
                    st.caption(f"_{label}_")


_ERROR_MAP: dict[str, str] = {
    "KeyError": "선택한 컬럼이 데이터에 없습니다. 컬럼명을 확인해주세요.",
    "ValueError": "데이터 형식이 올바르지 않습니다. CSV 파일을 확인해주세요.",
    "FileNotFoundError": "파일을 찾을 수 없습니다.",
    "TimeoutError": "요청 시간이 초과되었습니다. 네트워크를 확인해주세요.",
    "SelectorInferenceError": (
        "AI가 페이지를 자동으로 분석하지 못했어요. "
        "주소가 맞는지 확인하거나, '자주 쓰는 사이트에서 고르기'로 시도해 보세요."
    ),
}


def render_error(exc: Exception, context: str = "") -> None:
    """예외 유형에 따른 사용자 친화적 에러 메시지를 표시한다.

    Args:
        exc: 발생한 예외.
        context: 에러 발생 맥락 (예: "분석", "크롤링").
    """
    exc_type = type(exc).__name__
    friendly = _ERROR_MAP.get(exc_type)
    if friendly:
        st.error(f"{friendly}")
    else:
        prefix = f"{context} 중 " if context else ""
        st.error(f"{prefix}오류가 발생했습니다: {exc}")
    logger.error("UI 에러 표시: %s — %s", exc_type, exc)


def render_file_uploader(
    label: str = "데이터 파일 업로드",
    accepted_types: list[str] | None = None,
) -> pd.DataFrame | None:
    """CSV 및 Excel 파일 업로더를 렌더링하고 파싱된 DataFrame을 반환한다.

    Args:
        label: 업로더 레이블.
        accepted_types: 허용할 파일 확장자 목록. 기본값은 ["csv", "xlsx", "xls"].

    Returns:
        파싱 성공 시 DataFrame, 실패 또는 미업로드 시 None.
    """
    if accepted_types is None:
        accepted_types = ["csv", "xlsx", "xls"]

    uploaded_file = st.file_uploader(label, type=accepted_types)
    if uploaded_file is None:
        return None

    try:
        if uploaded_file.name.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(uploaded_file)
        else:
            df = pd.read_csv(uploaded_file, encoding="utf-8-sig")
        logger.info(
            "파일 업로드 성공: %s (%d행)", uploaded_file.name, len(df)
        )
        st.dataframe(df.head())
        return df
    except Exception as exc:
        logger.error("파일 파싱 실패: %s — %s", uploaded_file.name, exc)
        st.error(f"파일을 읽는 중 오류가 발생했습니다: {exc}")
        return None


def render_download_button(
    data: bytes,
    filename: str,
    label: str = "다운로드",
    mime: str = "application/octet-stream",
) -> None:
    """다운로드 버튼을 렌더링한다.

    Args:
        data: 다운로드할 바이트 데이터.
        filename: 저장될 파일명.
        label: 버튼 레이블.
        mime: MIME 타입.
    """
    st.download_button(
        label=label,
        data=data,
        file_name=filename,
        mime=mime,
    )


def render_progress(
    current: int, total: int, message: str = ""
) -> None:
    """진행률 바를 렌더링한다.

    Args:
        current: 현재 진행 값.
        total: 전체 값.
        message: 진행 상태 메시지 (선택).
    """
    progress_value = current / total if total > 0 else 0.0
    st.progress(progress_value)
    if message:
        st.text(message)


def render_metrics(metrics: dict[str, Any], num_cols: int = 4) -> None:
    """메트릭 카드를 num_cols열 레이아웃으로 렌더링한다.

    Args:
        metrics: 레이블-값 쌍의 딕셔너리.
        num_cols: 한 행에 표시할 열 수. 기본값은 4.
    """
    items = list(metrics.items())

    for i in range(0, len(items), num_cols):
        chunk = items[i : i + num_cols]
        cols = st.columns(len(chunk))
        for col, (label, value) in zip(cols, chunk):
            with col:
                st.metric(label=label, value=value)


def render_dataframe_preview(
    df: pd.DataFrame,
    title: str = "데이터 미리보기",
    max_rows: int = 10,
) -> None:
    """DataFrame 미리보기를 렌더링한다.

    Args:
        df: 표시할 DataFrame.
        title: 섹션 제목.
        max_rows: 표시할 최대 행 수.
    """
    st.subheader(title)
    st.dataframe(df.head(max_rows))
