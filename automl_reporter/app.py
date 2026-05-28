"""automl_reporter/app.py — AutoML 리포트 Streamlit 앱."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from automl_reporter.feature_inspector import FeatureInspector
from automl_reporter.report_builder import AutoMLReportBuilder
from automl_reporter.runner import AutoMLConfig, AutoMLResult, AutoMLRunner, TaskType
from shared.logger import get_logger
import shared.visitor_stats as vstats
from shared.ui_components import (
    render_dataframe_preview,
    render_download_button,
    render_error,
    render_file_uploader,
    render_header,
    render_metrics,
    render_step_indicator,
)

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# 세션 스테이트 키
# ---------------------------------------------------------------------------

_SESSION_DF = "aml_df"
_SESSION_RESULT = "aml_result"
_SESSION_CONFIG = "aml_config"

# ---------------------------------------------------------------------------
# 태스크 유형 매핑
# ---------------------------------------------------------------------------

_TASK_TYPE_LABEL_MAP: dict[str, TaskType | None] = {
    "자동 감지": None,
    "분류": TaskType.BINARY_CLASSIFICATION,
    "회귀": TaskType.REGRESSION,
    "군집화": TaskType.CLUSTERING,
}

_TASK_TYPE_KR: dict[TaskType, str] = {
    TaskType.BINARY_CLASSIFICATION: "이진 분류",
    TaskType.MULTICLASS_CLASSIFICATION: "다중 분류",
    TaskType.REGRESSION: "회귀",
    TaskType.CLUSTERING: "군집화",
}


# ---------------------------------------------------------------------------
# 샘플 데이터 헬퍼 (이슈 #3)
# ---------------------------------------------------------------------------


@st.cache_data
def _load_sample_tabular_df() -> pd.DataFrame | None:
    """샘플 tabular CSV 로드. rerun마다 디스크 IO 방지.

    리뷰 분석기와 동일하게 ``tests/fixtures/sample_tabular.csv`` 를 사용한다.
    파일이 없으면 None.
    """
    sample_path = (
        Path(__file__).resolve().parent.parent
        / "tests"
        / "fixtures"
        / "sample_tabular.csv"
    )
    if not sample_path.exists():
        return None
    return pd.read_csv(sample_path, encoding="utf-8-sig")


# ---------------------------------------------------------------------------
# Step 1 — 파일 업로드
# ---------------------------------------------------------------------------


def _render_step1_upload() -> pd.DataFrame | None:
    """Step 1: CSV 파일 업로드 섹션을 렌더링한다.

    이슈 #3: 리뷰 분석기와 동일한 톤으로 "샘플로 먼저 보기" 옵션 제공.

    Returns:
        업로드 또는 샘플 로드에 성공한 DataFrame. 없으면 None.
    """
    st.subheader("Step 1. 데이터 업로드")
    st.caption(
        "CSV 또는 Excel 파일을 올리면 됩니다. 한글이 깨지는 파일(엑셀 cp949)도 자동으로 인식해요. "
        "처음이면 '샘플로 먼저 보기'로 체험해 보세요."
    )

    input_mode = st.radio(
        "데이터 입력 방식",
        options=["파일로 올리기 (CSV)", "샘플로 먼저 보기"],
        horizontal=True,
        key="aml_input_mode",
    )

    df: pd.DataFrame | None = None

    if input_mode == "파일로 올리기 (CSV)":
        df = render_file_uploader(label="분석할 데이터 파일 (CSV·Excel, 한글 OK)")
        if df is not None:
            render_dataframe_preview(df)
    else:
        df = _load_sample_tabular_df()
        if df is not None:
            st.success(
                f"샘플 데이터: {len(df)}건, {len(df.columns)}개 컬럼"
            )
            st.dataframe(df.head())
        else:
            st.warning("샘플 데이터 파일이 없습니다.")

    return df


# ---------------------------------------------------------------------------
# Step 2 — 분석 설정
# ---------------------------------------------------------------------------


def _render_step2_settings(
    df: pd.DataFrame,
) -> tuple[str | None, TaskType | None, list[str]]:
    """Step 2: 타겟 컬럼·문제 유형·텍스트 피처 설정 섹션을 렌더링한다.

    FeatureInspector로 추천 타겟을 제안하고, 텍스트(object) 컬럼이 있으면
    '텍스트 피처 포함' 옵션을 제공한다(숫자 컬럼이 부족한 텍스트 위주 데이터 대응).

    Args:
        df: 설정 대상 DataFrame.

    Returns:
        (target_column, task_type, text_columns) 튜플.
        target_column은 군집화 선택 시 None, task_type은 자동 감지 시 None,
        text_columns는 텍스트 피처 미사용 시 빈 리스트.
    """
    st.subheader("Step 2. 분석 설정")

    columns = list(df.columns)

    # 타겟 컬럼 추천
    suggested: str | None = None
    try:
        suggested = FeatureInspector(df).suggest_target()
        if suggested:
            log.info("타겟_컬럼_추천", column=suggested)
    except Exception as exc:
        log.warning("타겟_컬럼_추천_실패", error=str(exc))

    no_target_label = "(없음 — 군집화)"
    target_options = [no_target_label] + columns

    default_index = 0
    if suggested and suggested in columns:
        default_index = target_options.index(suggested)

    selected_target: str = st.selectbox(
        "타겟 컬럼",
        options=target_options,
        index=default_index,
        help="예측 대상 컬럼을 선택하세요. 타겟이 없으면 군집화로 실행됩니다.",
    )

    target_column: str | None = (
        None if selected_target == no_target_label else selected_target
    )

    task_radio_options = ["자동 감지", "분류", "회귀", "군집화"]
    selected_task_label: str = st.radio(
        "문제 유형",
        options=task_radio_options,
        horizontal=True,
        help="자동 감지는 타겟 컬럼의 분포를 분석하여 유형을 결정합니다.",
    )

    task_type: TaskType | None = _TASK_TYPE_LABEL_MAP.get(selected_task_label)

    # 타겟이 없는데 군집화 이외 유형을 선택한 경우 안내
    if target_column is None and task_type not in (
        None,
        TaskType.CLUSTERING,
    ):
        st.warning(
            "타겟 컬럼이 없으면 군집화만 가능합니다. "
            "문제 유형을 '군집화' 또는 '자동 감지'로 변경해 주세요."
        )

    # 텍스트 피처 — object/category 컬럼(타깃 제외)이 있으면 옵션 노출
    text_columns: list[str] = []
    text_candidates = [
        c
        for c in columns
        if c != target_column
        and (df[c].dtype == object or str(df[c].dtype) == "category")
    ]
    if text_candidates:
        use_text = st.checkbox(
            "📝 텍스트 피처 포함 (리뷰·설명 등 글자 데이터를 분석에 사용)",
            value=False,
            help=(
                "숫자 컬럼이 거의 없는 텍스트 위주 데이터라면 켜세요. "
                "한국어 형태소 분석 후 TF-IDF로 변환해 모델 입력으로 씁니다."
            ),
        )
        if use_text:
            try:
                default_text = max(
                    text_candidates,
                    key=lambda c: df[c].astype(str).str.len().mean(),
                )
            except Exception:
                default_text = text_candidates[0]
            text_columns = st.multiselect(
                "텍스트 컬럼 선택",
                options=text_candidates,
                default=[default_text],
                help="분석에 사용할 텍스트 컬럼(여러 개 선택 가능).",
            )

    return target_column, task_type, text_columns


# ---------------------------------------------------------------------------
# AutoML 실행
# ---------------------------------------------------------------------------


def _run_automl(
    df: pd.DataFrame,
    target_column: str | None,
    task_type: TaskType | None,
    text_columns: list[str] | None = None,
) -> AutoMLResult:
    """임시 CSV를 생성하고 AutoMLRunner를 실행한다.

    Args:
        df: 학습에 사용할 DataFrame.
        target_column: 타겟 컬럼명. None이면 군집화.
        task_type: 문제 유형. None이면 자동 감지.
        text_columns: 텍스트 피처로 쓸 컬럼들. 있으면 TF-IDF 변환해 모델 입력에 포함.

    Returns:
        AutoMLResult 인스턴스.

    Raises:
        RuntimeError: AutoML 실행에 실패한 경우.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_csv = Path(tmp_dir) / "input.csv"
        df.to_csv(tmp_csv, index=False, encoding="utf-8-sig")

        config = AutoMLConfig(
            include_text_features=bool(text_columns),
            text_columns=list(text_columns or []),
            input_path=tmp_csv,
            target_column=target_column,
            task_type=task_type,
            output_dir=Path(tmp_dir) / "output",
        )

        log.info(
            "AutoML_실행_요청",
            target_column=target_column,
            task_type=task_type.value if task_type else "auto",
            rows=len(df),
            columns=len(df.columns),
        )

        runner = AutoMLRunner(config)
        result = runner.run()

        # 최적 모델 객체를 세션에서 재사용할 수 없으므로 runner를 config에 함께 저장
        st.session_state[_SESSION_CONFIG] = (config, runner)

        log.info(
            "AutoML_실행_완료",
            best_model=result.best_model_name,
            task_type=result.task_type.value,
        )
        return result


# ---------------------------------------------------------------------------
# 결과 렌더링
# ---------------------------------------------------------------------------


def _render_results(result: AutoMLResult) -> None:
    """AutoML 결과 전체 섹션을 렌더링한다.

    메트릭 카드, 모델 비교 테이블, 피처 중요도 차트,
    데이터 요약 expander를 표시한다.

    Args:
        result: AutoMLRunner.run()이 반환한 AutoMLResult 인스턴스.
    """
    st.divider()
    st.subheader("분석 결과")

    # ── 메트릭 카드 ──────────────────────────────────────────────────────
    task_label = _TASK_TYPE_KR.get(result.task_type, result.task_type.value)

    primary_metric_val: str = "N/A"
    primary_metric_name: str = ""
    if result.best_metrics:
        first_key, first_val = next(iter(result.best_metrics.items()))
        primary_metric_name = first_key.upper()
        primary_metric_val = f"{first_val:.4f}"

    metrics: dict[str, Any] = {
        "최적 모델": result.best_model_name,
        primary_metric_name or "지표": primary_metric_val,
        "문제 유형": task_label,
        "비교 모델 수": str(len(result.model_results)),
    }
    render_metrics(metrics)

    # ── 모델 비교 테이블 ─────────────────────────────────────────────────
    st.subheader("모델 비교")

    with st.expander("📊 메트릭 설명"):
        st.markdown(
            "- **ACCURACY**: 전체 예측 중 맞춘 비율\n"
            "- **F1**: 정밀도와 재현율의 조화 평균\n"
            "- **PRECISION**: 양성 예측 중 실제 양성 비율\n"
            "- **RECALL**: 실제 양성 중 양성으로 예측한 비율\n"
            "- **R2**: 회귀 모델의 설명력 (1에 가까울수록 좋음)\n"
            "- **RMSE**: 평균 제곱근 오차 (작을수록 좋음)\n"
            "- **SILHOUETTE**: 군집 간 분리도 (-1~1, 1에 가까울수록 좋음)"
        )

    all_metric_keys: list[str] = []
    for mr in result.model_results:
        for k in mr.metrics:
            if k not in all_metric_keys:
                all_metric_keys.append(k)

    table_rows: list[dict[str, Any]] = []
    for mr in result.model_results:
        row: dict[str, Any] = {
            "모델": mr.name,
            "튜닝": "O" if mr.is_tuned else "X",
            "학습 시간(s)": round(mr.training_time_seconds, 2),
        }
        for k in all_metric_keys:
            val = mr.metrics.get(k)
            row[k.upper()] = round(val, 4) if val is not None else None
        table_rows.append(row)

    if table_rows:
        comparison_df = pd.DataFrame(table_rows)
        st.dataframe(comparison_df, hide_index=True, use_container_width=True)

    # ── 피처 중요도 차트 ─────────────────────────────────────────────────
    if result.feature_importance:
        st.subheader("피처 중요도 Top 10")

        sorted_fi = sorted(
            result.feature_importance.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:10]

        if sorted_fi:
            fi_df = pd.DataFrame(sorted_fi, columns=["피처", "중요도"])
            fig = px.bar(
                fi_df,
                x="중요도",
                y="피처",
                orientation="h",
                title="피처 중요도 Top 10",
                labels={"중요도": "Importance", "피처": "Feature"},
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig, use_container_width=True)

    # ── 데이터 요약 expander ─────────────────────────────────────────────
    with st.expander("데이터 요약 보기"):
        ds = result.data_summary
        col_left, col_right = st.columns(2)

        with col_left:
            st.metric("전체 행 수", f"{ds.get('rows', 0):,}개")
            st.metric("전체 열 수", f"{ds.get('columns', 0)}개")

        with col_right:
            missing_pct: dict[str, float] = ds.get("missing_pct", {})
            high_missing = [
                (col, pct) for col, pct in missing_pct.items() if pct > 0
            ]
            high_missing.sort(key=lambda x: x[1], reverse=True)

            if high_missing:
                missing_lines = "\n".join(
                    f"- {col}: {pct:.1f}%" for col, pct in high_missing[:5]
                )
                st.markdown("**결측 컬럼 (상위 5개)**")
                st.text(missing_lines)
            else:
                st.success("결측값이 없습니다.")

        target_dist: dict[str, Any] | None = ds.get("target_distribution")
        if target_dist is not None:
            st.markdown("**타겟 분포**")
            if "mean" in target_dist:
                st.write(
                    f"평균: {target_dist['mean']:.4f} / "
                    f"표준편차: {target_dist['std']:.4f} / "
                    f"범위: [{target_dist['min']:.4f}, {target_dist['max']:.4f}]"
                )
            else:
                dist_df = pd.DataFrame(
                    list(target_dist.items()), columns=["클래스", "비율"]
                )
                dist_df["비율"] = dist_df["비율"].apply(lambda v: f"{v * 100:.1f}%")
                st.dataframe(dist_df, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# 다운로드 섹션
# ---------------------------------------------------------------------------


def _build_pdf_bytes(result: AutoMLResult) -> bytes:
    """PDF 리포트를 생성하고 바이트로 반환한다.

    Args:
        result: AutoMLResult 인스턴스.

    Returns:
        PDF 파일 바이트. 생성 실패 시 빈 bytes.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_path = Path(tmp_dir) / "automl_report.pdf"
        try:
            builder = AutoMLReportBuilder(result)
            saved = builder.build(output_path)
            return saved.read_bytes()
        except Exception as exc:
            log.error("PDF_생성_실패", error=str(exc))
            return b""


def _build_model_bytes(result: AutoMLResult) -> bytes:
    """최적 모델을 저장하고 바이트로 반환한다.

    세션 스테이트에 저장된 AutoMLRunner를 재사용하여 모델을 저장한다.

    Args:
        result: AutoMLResult 인스턴스 (runner 재사용 식별용).

    Returns:
        모델 파일(.pkl) 바이트. 생성 실패 시 빈 bytes.
    """
    session_pair = st.session_state.get(_SESSION_CONFIG)
    if session_pair is None:
        log.warning("모델_저장_실패_세션_없음")
        return b""

    _config, runner = session_pair

    with tempfile.TemporaryDirectory() as tmp_dir:
        model_path = Path(tmp_dir) / "best_model.pkl"
        try:
            saved = runner.save_best_model(model_path)
            return saved.read_bytes()
        except Exception as exc:
            log.error("모델_저장_실패", error=str(exc))
            return b""


def _render_download_section(result: AutoMLResult) -> None:
    """다운로드 섹션을 렌더링한다.

    PDF 리포트와 최적 모델(.pkl) 다운로드 버튼을 제공한다.

    Args:
        result: AutoMLResult 인스턴스.
    """
    st.divider()
    st.subheader("다운로드")

    col_pdf, col_model = st.columns(2)

    with col_pdf:
        with st.spinner("PDF 리포트 생성 중..."):
            pdf_bytes = _build_pdf_bytes(result)

        if pdf_bytes:
            render_download_button(
                data=pdf_bytes,
                filename="automl_report.pdf",
                label="PDF 리포트 다운로드",
                mime="application/pdf",
            )
        else:
            st.error("PDF 생성에 실패했습니다.")

    with col_model:
        with st.spinner("모델 파일 준비 중..."):
            model_bytes = _build_model_bytes(result)

        if model_bytes:
            render_download_button(
                data=model_bytes,
                filename="best_model.pkl",
                label="최적 모델 다운로드 (.pkl)",
                mime="application/octet-stream",
            )
        else:
            st.error("모델 파일 생성에 실패했습니다.")


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------


def main() -> None:
    """Streamlit 앱 진입점."""
    try:
        st.set_page_config(
            page_title="AutoML 리포트",
            page_icon="🤖",
            layout="wide",
        )
    except st.errors.StreamlitAPIException:
        pass  # 루트 허브에서 이미 호출됨

    render_header(
        title="AutoML 리포트",
        subtitle="CSV만 올리면 AI가 모델을 만들어 줍니다.",
    )

    # Step indicator
    if st.session_state.get(_SESSION_RESULT) is not None:
        current_step = 3
    elif st.session_state.get(_SESSION_DF) is not None:
        current_step = 2
    else:
        current_step = 1
    render_step_indicator(current_step, 3, ["데이터 업로드", "분석 설정", "결과 확인"])

    # Step 1: 파일 업로드
    df = _render_step1_upload()

    if df is not None:
        st.session_state[_SESSION_DF] = df

    working_df: pd.DataFrame | None = st.session_state.get(_SESSION_DF)

    if working_df is None or working_df.empty:
        st.info("CSV 파일을 업로드하면 분석 설정이 표시됩니다.")
        return

    st.divider()

    # Step 2: 분석 설정
    target_column, task_type, text_columns = _render_step2_settings(working_df)

    # 타겟이 없는데 분류/회귀를 선택한 경우 실행 버튼 비활성화
    run_disabled = target_column is None and task_type not in (
        None,
        TaskType.CLUSTERING,
    )

    st.divider()

    if st.button("실행", type="primary", disabled=run_disabled):
        with st.spinner("AutoML 분석 중... 잠시 기다려 주세요."):
            try:
                result = _run_automl(
                    working_df, target_column, task_type, text_columns
                )
                st.session_state[_SESSION_RESULT] = result
                vstats.record_activity("AutoML")
                st.success(
                    f"완료! 최적 모델: {result.best_model_name} "
                    f"({_TASK_TYPE_KR.get(result.task_type, result.task_type.value)})"
                )
            except Exception as exc:
                log.error("AutoML_실행_실패", error=str(exc))
                render_error(exc, context="AutoML")
                return

    # 결과 표시
    result: AutoMLResult | None = st.session_state.get(_SESSION_RESULT)
    if result is not None:
        _render_results(result)
        _render_download_section(result)


if __name__ == "__main__":
    main()
