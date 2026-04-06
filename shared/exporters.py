"""데이터 내보내기 모듈.

지원 포맷: CSV, JSON, Excel, Parquet
"""

from pathlib import Path

import pandas as pd

from shared.logger import get_logger

log = get_logger(__name__)


def export_csv(
    df: pd.DataFrame,
    output_path: Path,
    encoding: str = "utf-8-sig",
) -> Path:
    """DataFrame을 CSV 파일로 내보낸다.

    Args:
        df: 내보낼 DataFrame.
        output_path: 저장할 파일 경로.
        encoding: 파일 인코딩 (기본값 utf-8-sig, 엑셀 호환 BOM).

    Returns:
        저장된 파일의 Path 객체.

    Raises:
        Exception: 파일 저장 실패 시 예외 재발생.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_csv(output_path, index=False, encoding=encoding)
        log.info("CSV 저장 완료: %s (행=%d)", output_path, len(df))
    except Exception as exc:
        log.error("CSV 저장 실패: %s — %s", output_path, exc)
        raise
    return output_path


def export_json(
    df: pd.DataFrame,
    output_path: Path,
    orient: str = "records",
) -> Path:
    """DataFrame을 JSON 파일로 내보낸다.

    Args:
        df: 내보낼 DataFrame.
        output_path: 저장할 파일 경로.
        orient: JSON 직렬화 방향 (기본값 'records').

    Returns:
        저장된 파일의 Path 객체.

    Raises:
        Exception: 파일 저장 실패 시 예외 재발생.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_path.write_text(
            df.to_json(
                orient=orient,
                force_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        log.info("JSON 저장 완료: %s (행=%d)", output_path, len(df))
    except Exception as exc:
        log.error("JSON 저장 실패: %s — %s", output_path, exc)
        raise
    return output_path


def export_excel(
    df: pd.DataFrame,
    output_path: Path,
    sheet_name: str = "Sheet1",
) -> Path:
    """DataFrame을 Excel 파일로 내보낸다.

    Args:
        df: 내보낼 DataFrame.
        output_path: 저장할 파일 경로 (.xlsx).
        sheet_name: 시트 이름 (기본값 'Sheet1').

    Returns:
        저장된 파일의 Path 객체.

    Raises:
        Exception: 파일 저장 실패 시 예외 재발생.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_excel(
            output_path,
            index=False,
            sheet_name=sheet_name,
            engine="openpyxl",
        )
        log.info("Excel 저장 완료: %s (행=%d)", output_path, len(df))
    except Exception as exc:
        log.error("Excel 저장 실패: %s — %s", output_path, exc)
        raise
    return output_path


def export_parquet(
    df: pd.DataFrame,
    output_path: Path,
) -> Path:
    """DataFrame을 Parquet 파일로 내보낸다.

    Args:
        df: 내보낼 DataFrame.
        output_path: 저장할 파일 경로 (.parquet).

    Returns:
        저장된 파일의 Path 객체.

    Raises:
        Exception: 파일 저장 실패 시 예외 재발생.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(output_path, index=False, engine="pyarrow")
        log.info("Parquet 저장 완료: %s (행=%d)", output_path, len(df))
    except Exception as exc:
        log.error("Parquet 저장 실패: %s — %s", output_path, exc)
        raise
    return output_path
