"""review_analyzer CLI — typer 기반 3개 서브커맨드: crawl, analyze, full."""

import asyncio
from pathlib import Path

import pandas as pd
import typer

from shared.logger import get_logger
from review_analyzer.analyzer import ReviewAnalyzer
from review_analyzer.crawler.engine import CrawlConfig, CrawlerEngine, DriverType
from review_analyzer.preset_loader import PresetLoader

logger = get_logger(__name__)

app = typer.Typer(name="review_analyzer", help="리뷰 분석 프로그램")


@app.command()
def crawl(
    preset: str = typer.Option(..., help="프리셋 이름"),
    urls: list[str] = typer.Option(..., help="크롤링 대상 URL"),
    output: Path = typer.Option(Path("./output"), help="출력 디렉토리"),
    max_pages: int = typer.Option(100, help="최대 페이지 수"),
    driver: str = typer.Option("httpx", help="드라이버 (httpx/selenium/api)"),
) -> None:
    """사이트에서 리뷰를 크롤링합니다."""
    try:
        driver_type = DriverType(driver)
    except ValueError:
        typer.echo(f"[오류] 지원하지 않는 드라이버: {driver}", err=True)
        raise typer.Exit(code=1)

    loader = PresetLoader()
    try:
        preset_data = loader.load(preset)
    except Exception as exc:
        typer.echo(f"[오류] 프리셋 로드 실패: {exc}", err=True)
        logger.error("프리셋 로드 실패: preset=%s, err=%s", preset, exc)
        raise typer.Exit(code=1)

    config = CrawlConfig(
        preset_name=preset,
        target_urls=urls,
        max_pages=max_pages,
        output_dir=output,
        driver_type=driver_type,
    )

    typer.echo(f"[크롤링 시작] preset={preset}, urls={len(urls)}개, driver={driver}")
    logger.info("크롤링 시작: preset=%s, urls=%d, driver=%s", preset, len(urls), driver)

    try:
        result = asyncio.run(CrawlerEngine(config, preset_data).run())
    except Exception as exc:
        typer.echo(f"[오류] 크롤링 중 예외 발생: {exc}", err=True)
        logger.error("크롤링 실패: %s", exc, exc_info=True)
        raise typer.Exit(code=1)

    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / f"{preset}_crawled.csv"
    result.data.to_csv(csv_path, index=False, encoding="utf-8-sig")

    typer.echo(
        f"[완료] 수집={result.total_collected}, 실패={result.total_failed}, "
        f"소요={result.elapsed_seconds:.1f}s → {csv_path}"
    )
    logger.info(
        "크롤링 완료: collected=%d, failed=%d, elapsed=%.1fs, path=%s",
        result.total_collected,
        result.total_failed,
        result.elapsed_seconds,
        csv_path,
    )


@app.command()
def analyze(
    input: Path = typer.Option(..., help="입력 CSV 파일 경로"),
    output: Path = typer.Option(Path("./output"), help="출력 디렉토리"),
    text_column: str = typer.Option("content", help="텍스트 컬럼명"),
    rating_column: str = typer.Option("rating", help="평점 컬럼명 (없으면 'none')"),
    report: bool = typer.Option(True, help="PDF 리포트 생성"),
    package: bool = typer.Option(True, help="납품 패키지 생성"),
) -> None:
    """CSV 리뷰 데이터를 분석합니다."""
    if not input.exists():
        typer.echo(f"[오류] 파일을 찾을 수 없음: {input}", err=True)
        raise typer.Exit(code=1)

    try:
        df = pd.read_csv(input, encoding="utf-8-sig")
    except Exception as exc:
        typer.echo(f"[오류] CSV 읽기 실패: {exc}", err=True)
        logger.error("CSV 읽기 실패: path=%s, err=%s", input, exc)
        raise typer.Exit(code=1)

    if text_column not in df.columns:
        typer.echo(
            f"[오류] 텍스트 컬럼 '{text_column}'이 CSV에 없음. "
            f"존재하는 컬럼: {list(df.columns)}",
            err=True,
        )
        raise typer.Exit(code=1)

    effective_rating = None if rating_column.lower() == "none" else rating_column
    if effective_rating and effective_rating not in df.columns:
        typer.echo(
            f"[경고] 평점 컬럼 '{effective_rating}'이 없어 평점 분석을 건너뜀."
        )
        logger.warning("평점 컬럼 없음: column=%s", effective_rating)
        effective_rating = None

    output.mkdir(parents=True, exist_ok=True)

    analyzer = ReviewAnalyzer(
        text_column=text_column,
        rating_column=effective_rating,
    )

    typer.echo(f"[분석 시작] rows={len(df)}, text_col={text_column}")
    logger.info("분석 시작: rows=%d, text_col=%s", len(df), text_column)

    try:
        result = analyzer.run(df)
    except Exception as exc:
        typer.echo(f"[오류] 분석 중 예외 발생: {exc}", err=True)
        logger.error("분석 실패: %s", exc, exc_info=True)
        raise typer.Exit(code=1)

    typer.echo(f"[분석 완료] 감성 분포: {result.sentiment_distribution}")

    if report:
        try:
            report_path = analyzer.generate_report(result, output / "report.pdf")
            typer.echo(f"[리포트] {report_path}")
            logger.info("리포트 생성: %s", report_path)
        except Exception as exc:
            typer.echo(f"[경고] 리포트 생성 실패: {exc}", err=True)
            logger.warning("리포트 생성 실패: %s", exc)

    if package:
        project_name = input.stem
        try:
            pkg_path = analyzer.save_delivery_package(
                df, result, output, project_name=project_name
            )
            typer.echo(f"[납품 패키지] {pkg_path}")
            logger.info("납품 패키지 저장: %s", pkg_path)
        except Exception as exc:
            typer.echo(f"[경고] 납품 패키지 생성 실패: {exc}", err=True)
            logger.warning("납품 패키지 생성 실패: %s", exc)


@app.command()
def full(
    preset: str = typer.Option(..., help="프리셋 이름"),
    urls: list[str] = typer.Option(..., help="크롤링 대상 URL"),
    output: Path = typer.Option(Path("./output"), help="출력 디렉토리"),
) -> None:
    """크롤링 + 분석을 한번에 실행합니다."""
    loader = PresetLoader()
    try:
        preset_data = loader.load(preset)
    except Exception as exc:
        typer.echo(f"[오류] 프리셋 로드 실패: {exc}", err=True)
        logger.error("프리셋 로드 실패: preset=%s, err=%s", preset, exc)
        raise typer.Exit(code=1)

    config = CrawlConfig(
        preset_name=preset,
        target_urls=urls,
        output_dir=output,
    )

    typer.echo(f"[1/2 크롤링 시작] preset={preset}, urls={len(urls)}개")
    logger.info("full 파이프라인 크롤링 시작: preset=%s, urls=%d", preset, len(urls))

    try:
        crawl_result = asyncio.run(CrawlerEngine(config, preset_data).run())
    except Exception as exc:
        typer.echo(f"[오류] 크롤링 중 예외 발생: {exc}", err=True)
        logger.error("full 파이프라인 크롤링 실패: %s", exc, exc_info=True)
        raise typer.Exit(code=1)

    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / f"{preset}_crawled.csv"
    crawl_result.data.to_csv(csv_path, index=False, encoding="utf-8-sig")

    typer.echo(
        f"[크롤링 완료] 수집={crawl_result.total_collected}, "
        f"실패={crawl_result.total_failed}, 소요={crawl_result.elapsed_seconds:.1f}s"
    )
    logger.info(
        "full 파이프라인 크롤링 완료: collected=%d, failed=%d",
        crawl_result.total_collected,
        crawl_result.total_failed,
    )

    if crawl_result.data.empty:
        typer.echo("[경고] 수집된 데이터가 없어 분석을 건너뜀.", err=True)
        logger.warning("수집 데이터 없음, 분석 생략")
        raise typer.Exit(code=0)

    typer.echo(f"[2/2 분석 시작] rows={len(crawl_result.data)}")
    logger.info("full 파이프라인 분석 시작: rows=%d", len(crawl_result.data))

    analyzer = ReviewAnalyzer()

    try:
        analysis_result = analyzer.run(crawl_result.data)
    except Exception as exc:
        typer.echo(f"[오류] 분석 중 예외 발생: {exc}", err=True)
        logger.error("full 파이프라인 분석 실패: %s", exc, exc_info=True)
        raise typer.Exit(code=1)

    typer.echo(f"[분석 완료] 감성 분포: {analysis_result.sentiment_distribution}")

    try:
        report_path = analyzer.generate_report(
            analysis_result, output / f"{preset}_report.pdf"
        )
        typer.echo(f"[리포트] {report_path}")
        logger.info("full 리포트 생성: %s", report_path)
    except Exception as exc:
        typer.echo(f"[경고] 리포트 생성 실패: {exc}", err=True)
        logger.warning("full 리포트 생성 실패: %s", exc)

    try:
        pkg_path = analyzer.save_delivery_package(
            crawl_result.data, analysis_result, output, project_name=preset
        )
        typer.echo(f"[납품 패키지] {pkg_path}")
        logger.info("full 납품 패키지 저장: %s", pkg_path)
    except Exception as exc:
        typer.echo(f"[경고] 납품 패키지 생성 실패: {exc}", err=True)
        logger.warning("full 납품 패키지 생성 실패: %s", exc)


@app.command()
def list_presets() -> None:
    """사용 가능한 프리셋 목록을 출력합니다."""
    loader = PresetLoader()
    try:
        presets = loader.list_presets()
    except Exception as exc:
        typer.echo(f"[오류] 프리셋 목록 로드 실패: {exc}", err=True)
        logger.error("프리셋 목록 로드 실패: %s", exc)
        raise typer.Exit(code=1)

    if not presets:
        typer.echo("등록된 프리셋이 없습니다.")
        return

    typer.echo(f"{'이름':<20} {'설명'}")
    typer.echo("-" * 50)
    for item in presets:
        name = item.get("name", "")
        description = item.get("description", "")
        typer.echo(f"{name:<20} {description}")
