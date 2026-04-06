"""automl_reporter CLI — typer 기반 2개 서브커맨드: run, inspect."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import typer

from shared.logger import get_logger
from automl_reporter.feature_inspector import FeatureInspector
from automl_reporter.report_builder import AutoMLReportBuilder
from automl_reporter.runner import AutoMLConfig, AutoMLRunner, TaskType

log = get_logger(__name__)

app = typer.Typer(name="automl_reporter", help="AutoML 파이프라인 및 데이터 프로파일링 도구")

_VALID_TASK_TYPES = [t.value for t in TaskType]


@app.command()
def run(
    input: Path = typer.Option(..., help="입력 CSV 파일 경로"),
    target: Optional[str] = typer.Option(None, help="타겟 컬럼명 (None이면 군집화 모드)"),
    output: Path = typer.Option(Path("./output"), help="출력 디렉토리"),
    top_n: int = typer.Option(5, "--top-n", help="비교할 상위 N개 모델 수"),
    task_type: Optional[str] = typer.Option(
        None,
        "--task-type",
        help=(
            "태스크 유형 강제 지정 "
            "(binary_classification / multiclass_classification / regression / clustering)"
        ),
    ),
    report: bool = typer.Option(True, "--report/--no-report", help="PDF 리포트 생성 여부"),
) -> None:
    """AutoML 파이프라인을 실행하고 선택적으로 PDF 리포트를 생성합니다."""
    # ── 입력 파일 검증 ──────────────────────────────────────────────────
    if not input.exists():
        typer.echo(f"[오류] 파일을 찾을 수 없음: {input}", err=True)
        raise typer.Exit(code=1)

    # ── task_type 검증 ──────────────────────────────────────────────────
    resolved_task_type: Optional[TaskType] = None
    if task_type is not None:
        if task_type not in _VALID_TASK_TYPES:
            typer.echo(
                f"[오류] 지원하지 않는 task_type: '{task_type}'. "
                f"허용값: {_VALID_TASK_TYPES}",
                err=True,
            )
            raise typer.Exit(code=1)
        resolved_task_type = TaskType(task_type)

    # ── CSV 로드 ────────────────────────────────────────────────────────
    try:
        df = pd.read_csv(input, encoding="utf-8-sig")
    except Exception as exc:
        typer.echo(f"[오류] CSV 읽기 실패: {exc}", err=True)
        log.error("CSV_읽기_실패", path=str(input), error=str(exc))
        raise typer.Exit(code=1)

    typer.echo(
        f"[입력] {input} — rows={len(df)}, cols={len(df.columns)}"
        + (f", target={target}" if target else ", 타겟 없음(군집화)")
    )
    log.info(
        "automl_run_시작",
        input=str(input),
        target=target,
        output=str(output),
        top_n=top_n,
        task_type=task_type,
        report=report,
    )

    # ── 출력 디렉토리 생성 ──────────────────────────────────────────────
    output.mkdir(parents=True, exist_ok=True)

    # ── AutoMLRunner 구성 및 실행 ───────────────────────────────────────
    config = AutoMLConfig(
        input_path=input,
        target_column=target,
        task_type=resolved_task_type,
        top_n_models=top_n,
        output_dir=output,
    )
    runner = AutoMLRunner(config)

    typer.echo("[1/3] AutoML 파이프라인 실행 중...")
    try:
        result = runner.run()
    except Exception as exc:
        typer.echo(f"[오류] AutoML 실행 중 예외 발생: {exc}", err=True)
        log.error("AutoML_실행_실패", error=str(exc), exc_info=True)
        raise typer.Exit(code=1)

    typer.echo(
        f"[완료] 최적 모델: {result.best_model_name} | "
        f"태스크: {result.task_type.value} | "
        f"지표: { {k: round(v, 4) for k, v in result.best_metrics.items()} }"
    )
    log.info(
        "AutoML_실행_완료",
        best_model=result.best_model_name,
        task_type=result.task_type.value,
        best_metrics=result.best_metrics,
    )

    # ── PDF 리포트 생성 ─────────────────────────────────────────────────
    if report:
        typer.echo("[2/3] PDF 리포트 생성 중...")
        report_path = output / "automl_report.pdf"
        try:
            builder = AutoMLReportBuilder(result)
            saved_report = builder.build(report_path)
            typer.echo(f"[리포트] {saved_report}")
            log.info("PDF_리포트_생성_완료", path=str(saved_report))
        except Exception as exc:
            typer.echo(f"[경고] PDF 리포트 생성 실패: {exc}", err=True)
            log.warning("PDF_리포트_생성_실패", error=str(exc))
    else:
        typer.echo("[2/3] 리포트 생성 건너뜀 (--no-report)")

    # ── 최적 모델 저장 ──────────────────────────────────────────────────
    typer.echo("[3/3] 최적 모델 저장 중...")
    model_save_path = output / "best_model.pkl"
    try:
        saved_model = runner.save_best_model(model_save_path)
        typer.echo(f"[모델 저장] {saved_model}")
        log.info("모델_저장_완료", path=str(saved_model))
    except Exception as exc:
        typer.echo(f"[경고] 모델 저장 실패: {exc}", err=True)
        log.warning("모델_저장_실패", error=str(exc))

    # ── 요약 출력 ───────────────────────────────────────────────────────
    typer.echo("")
    typer.echo("=" * 50)
    typer.echo("[ AutoML 요약 ]")
    typer.echo(f"  태스크 유형  : {result.task_type.value}")
    typer.echo(f"  최적 모델    : {result.best_model_name}")
    typer.echo(f"  평가 모델 수 : {len(result.model_results)}개")
    if result.best_metrics:
        for metric, value in result.best_metrics.items():
            typer.echo(f"  {metric:<12} : {value:.4f}")
    typer.echo(f"  출력 디렉토리: {output.resolve()}")
    typer.echo("=" * 50)


@app.command()
def inspect(
    input: Path = typer.Option(..., help="입력 CSV 파일 경로"),
) -> None:
    """CSV 데이터 프로파일링을 수행합니다."""
    # ── 입력 파일 검증 ──────────────────────────────────────────────────
    if not input.exists():
        typer.echo(f"[오류] 파일을 찾을 수 없음: {input}", err=True)
        raise typer.Exit(code=1)

    # ── CSV 로드 ────────────────────────────────────────────────────────
    try:
        df = pd.read_csv(input, encoding="utf-8-sig")
    except Exception as exc:
        typer.echo(f"[오류] CSV 읽기 실패: {exc}", err=True)
        log.error("CSV_읽기_실패", path=str(input), error=str(exc))
        raise typer.Exit(code=1)

    log.info("inspect_시작", input=str(input), rows=len(df), cols=len(df.columns))

    # ── 프로파일링 ──────────────────────────────────────────────────────
    inspector = FeatureInspector(df)

    try:
        profile = inspector.profile()
    except Exception as exc:
        typer.echo(f"[오류] 프로파일링 중 예외 발생: {exc}", err=True)
        log.error("프로파일링_실패", error=str(exc), exc_info=True)
        raise typer.Exit(code=1)

    # ── 타겟 추천 및 전처리 제안 ────────────────────────────────────────
    try:
        suggested_target = inspector.suggest_target()
    except Exception as exc:
        typer.echo(f"[경고] 타겟 추천 실패: {exc}", err=True)
        log.warning("타겟_추천_실패", error=str(exc))
        suggested_target = None

    try:
        suggestions = inspector.get_preprocessing_suggestions()
    except Exception as exc:
        typer.echo(f"[경고] 전처리 제안 생성 실패: {exc}", err=True)
        log.warning("전처리_제안_실패", error=str(exc))
        suggestions = []

    # ── 결과 출력 ───────────────────────────────────────────────────────
    shape = profile["shape"]
    dtypes: dict[str, str] = profile["dtypes"]
    missing: dict[str, float] = profile["missing"]
    text_columns: list[str] = profile["text_columns"]

    typer.echo("")
    typer.echo("=" * 55)
    typer.echo("[ 데이터 프로파일 요약 ]")
    typer.echo("=" * 55)

    # 기본 정보
    typer.echo(f"  파일       : {input}")
    typer.echo(f"  Shape      : {shape[0]:,}행 × {shape[1]}열")

    # dtype 분포
    from collections import Counter
    dtype_counts: Counter = Counter(dtypes.values())
    dtype_summary = ", ".join(f"{dtype}({cnt})" for dtype, cnt in dtype_counts.items())
    typer.echo(f"  Dtype 분포 : {dtype_summary}")

    # 결측률 상위 5개
    high_missing = sorted(
        [(col, pct) for col, pct in missing.items() if pct > 0],
        key=lambda x: x[1],
        reverse=True,
    )[:5]
    if high_missing:
        typer.echo("  결측률 상위:")
        for col, pct in high_missing:
            typer.echo(f"    - {col}: {pct * 100:.1f}%")
    else:
        typer.echo("  결측률     : 결측값 없음")

    # 텍스트 컬럼
    if text_columns:
        typer.echo(f"  텍스트 컬럼: {', '.join(text_columns)}")
    else:
        typer.echo("  텍스트 컬럼: 없음")

    # 상수 컬럼
    constant_columns: list[str] = profile.get("constant_columns", [])
    if constant_columns:
        typer.echo(f"  상수 컬럼  : {', '.join(constant_columns)}")

    # 높은 카디널리티
    high_cardinality: list[str] = profile.get("high_cardinality", [])
    if high_cardinality:
        typer.echo(f"  고카디널리티: {', '.join(high_cardinality)}")

    # 고상관 쌍
    correlations: dict[str, float] = profile.get("correlations", {})
    if correlations:
        typer.echo("  고상관 쌍 (|r| > 0.9):")
        for pair, corr_val in list(correlations.items())[:5]:
            typer.echo(f"    - {pair}: {corr_val:.4f}")

    # 타겟 추천
    typer.echo("-" * 55)
    if suggested_target:
        typer.echo(f"  추천 타겟  : {suggested_target}")
    else:
        typer.echo("  추천 타겟  : 없음 (군집화 모드 권장)")

    # 전처리 제안
    if suggestions:
        typer.echo("  전처리 제안:")
        for i, suggestion in enumerate(suggestions, start=1):
            typer.echo(f"    {i}. {suggestion}")
    else:
        typer.echo("  전처리 제안: 없음 (데이터 품질 양호)")

    typer.echo("=" * 55)

    log.info(
        "inspect_완료",
        shape=shape,
        text_columns=text_columns,
        suggested_target=suggested_target,
        suggestion_count=len(suggestions),
    )
