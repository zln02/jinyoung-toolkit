"""납품 패키지 빌더 모듈.

표준화된 디렉토리 구조로 납품 파일을 패키징한다.

구조:
    {output_dir}/{project_name}/
        01_raw/
        02_clean/
        03_analysis/
        04_report/
        model/          (add_model 호출 시)
        dashboard/      (add_dashboard 호출 시)
        README.md       (generate_readme 호출 시)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from shared.exporters import export_csv
from shared.logger import get_logger

log = get_logger(__name__)

_SUBDIRS = ["01_raw", "02_clean", "03_analysis", "04_report"]


class DeliveryPackage:
    """납품 패키지를 빌드하는 클래스.

    Args:
        output_dir: 패키지를 생성할 상위 디렉토리.
        project_name: 패키지 루트 폴더명 (기본값 "delivery").

    Example:
        pkg = DeliveryPackage(Path("/tmp/out"), "my_project")
        pkg.add_raw(df_raw)
        pkg.add_clean(df_clean)
        pkg.add_report(Path("report.pdf"))
        pkg.build()
    """

    def __init__(
        self,
        output_dir: Path,
        project_name: str = "delivery",
    ) -> None:
        self.output_dir = Path(output_dir)
        self.project_name = project_name
        self.base_dir: Path = self.output_dir / project_name

        # 서브폴더 경로 참조
        self._raw_dir = self.base_dir / "01_raw"
        self._clean_dir = self.base_dir / "02_clean"
        self._analysis_dir = self.base_dir / "03_analysis"
        self._report_dir = self.base_dir / "04_report"
        self._model_dir = self.base_dir / "model"
        self._dashboard_dir = self.base_dir / "dashboard"

        # generate_readme 에서 사용할 메타 캐시
        self._meta: dict[str, Any] = {}

    def add_raw(
        self,
        df: pd.DataFrame,
        filename: str = "raw.csv",
    ) -> None:
        """원시 데이터를 01_raw/ 에 CSV(UTF-8 BOM)로 저장한다.

        Args:
            df: 저장할 DataFrame.
            filename: 저장 파일명 (기본값 "raw.csv").
        """
        dest = self._raw_dir / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        export_csv(df, dest, encoding="utf-8-sig")
        self._meta.setdefault("raw", {})["rows"] = len(df)
        self._meta["raw"]["columns"] = list(df.columns)
        log.info("add_raw 완료", path=str(dest), rows=len(df))

    def add_clean(
        self,
        df: pd.DataFrame,
        filename: str = "clean.csv",
    ) -> None:
        """정제 데이터를 02_clean/ 에 CSV(UTF-8 BOM)로 저장한다.

        Args:
            df: 저장할 DataFrame.
            filename: 저장 파일명 (기본값 "clean.csv").
        """
        dest = self._clean_dir / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        export_csv(df, dest, encoding="utf-8-sig")
        self._meta.setdefault("clean", {})["rows"] = len(df)
        self._meta["clean"]["columns"] = list(df.columns)
        log.info("add_clean 완료", path=str(dest), rows=len(df))

    def add_analysis(self, files: dict[str, Any]) -> None:
        """분석 결과 파일들을 03_analysis/ 에 저장한다.

        값 타입에 따라 저장 방식이 달라진다:
        - pd.DataFrame: CSV(UTF-8 BOM)로 저장
        - Path: shutil.copy2 로 복사
        - str: UTF-8 텍스트 파일로 저장

        Args:
            files: {파일명: 데이터} 딕셔너리.

        Raises:
            TypeError: 지원하지 않는 값 타입이 전달된 경우.
        """
        self._analysis_dir.mkdir(parents=True, exist_ok=True)

        for name, value in files.items():
            dest = self._analysis_dir / name

            if isinstance(value, pd.DataFrame):
                export_csv(value, dest, encoding="utf-8-sig")
                log.info(
                    "add_analysis DataFrame 저장",
                    file=name,
                    rows=len(value),
                )
            elif isinstance(value, Path):
                src = Path(value)
                shutil.copy2(src, dest)
                log.info(
                    "add_analysis 파일 복사",
                    src=str(src),
                    dest=str(dest),
                )
            elif isinstance(value, str):
                dest.write_text(value, encoding="utf-8")
                log.info("add_analysis 텍스트 저장", file=name)
            else:
                raise TypeError(
                    f"add_analysis: 지원하지 않는 타입 '{type(value).__name__}' "
                    f"(key={name!r}). pd.DataFrame, Path, str 중 하나여야 함."
                )

    def add_report(self, pdf_path: Path) -> None:
        """PDF 보고서를 04_report/ 에 복사한다.

        Args:
            pdf_path: 복사할 PDF 파일 경로.

        Raises:
            FileNotFoundError: pdf_path 파일이 존재하지 않는 경우.
        """
        src = Path(pdf_path)
        if not src.exists():
            raise FileNotFoundError(f"add_report: 파일 없음 — {src}")

        self._report_dir.mkdir(parents=True, exist_ok=True)
        dest = self._report_dir / src.name
        shutil.copy2(src, dest)
        log.info("add_report 완료", src=str(src), dest=str(dest))

    def add_model(
        self,
        model_path: Path,
        config: dict[str, Any],
    ) -> None:
        """모델 파일과 설정을 model/ 서브디렉토리에 저장한다.

        모델 파일은 shutil.copy2 로 복사하고,
        config 딕셔너리는 config.json 으로 직렬화한다.

        Args:
            model_path: 복사할 모델 파일 경로.
            config: 모델 설정 딕셔너리.

        Raises:
            FileNotFoundError: model_path 파일이 존재하지 않는 경우.
        """
        src = Path(model_path)
        if not src.exists():
            raise FileNotFoundError(f"add_model: 파일 없음 — {src}")

        self._model_dir.mkdir(parents=True, exist_ok=True)

        dest_model = self._model_dir / src.name
        shutil.copy2(src, dest_model)

        config_path = self._model_dir / "config.json"
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        log.info(
            "add_model 완료",
            model=str(dest_model),
            config=str(config_path),
        )

    def add_dashboard(self, app_code: str) -> None:
        """Streamlit/Dash 앱 코드를 dashboard/app.py 로 저장한다.

        Args:
            app_code: 저장할 Python 앱 코드 문자열.
        """
        self._dashboard_dir.mkdir(parents=True, exist_ok=True)
        dest = self._dashboard_dir / "app.py"
        dest.write_text(app_code, encoding="utf-8")
        log.info("add_dashboard 완료", path=str(dest))

    def generate_readme(self, context: dict[str, Any]) -> None:
        """README.md 를 자동 생성한다.

        context 키:
            - project_name (str): 프로젝트명 (없으면 self.project_name 사용)
            - description (str): 프로젝트 설명 (선택)
            - columns (dict[str, str]): 컬럼명 → 설명 매핑 (선택)
            - run_instructions (list[str]): 실행 방법 목록 (선택)

        내부 _meta (add_raw/add_clean 에서 자동 수집):
            - raw.rows, raw.columns
            - clean.rows, clean.columns

        Args:
            context: README 생성에 사용할 컨텍스트 딕셔너리.
        """
        self.base_dir.mkdir(parents=True, exist_ok=True)

        project_name: str = context.get("project_name", self.project_name)
        description: str = context.get("description", "")
        columns: dict[str, str] = context.get("columns", {})
        run_instructions: list[str] = context.get("run_instructions", [])

        raw_meta = self._meta.get("raw", {})
        clean_meta = self._meta.get("clean", {})

        lines: list[str] = [
            f"# {project_name}",
            "",
        ]

        if description:
            lines += [description, ""]

        # 데이터 요약
        lines += ["## 데이터 요약", ""]
        if raw_meta:
            lines.append(
                f"- 원시 데이터: {raw_meta.get('rows', '-')}행, "
                f"{len(raw_meta.get('columns', []))}컬럼"
            )
        if clean_meta:
            lines.append(
                f"- 정제 데이터: {clean_meta.get('rows', '-')}행, "
                f"{len(clean_meta.get('columns', []))}컬럼"
            )
        lines.append("")

        # 컬럼 설명
        if columns:
            lines += ["## 컬럼 설명", ""]
            lines.append("| 컬럼명 | 설명 |")
            lines.append("|--------|------|")
            for col, desc in columns.items():
                lines.append(f"| `{col}` | {desc} |")
            lines.append("")
        elif raw_meta.get("columns"):
            lines += ["## 컬럼 목록", ""]
            for col in raw_meta["columns"]:
                lines.append(f"- `{col}`")
            lines.append("")

        # 폴더 구조
        lines += [
            "## 폴더 구조",
            "",
            "```",
            f"{self.project_name}/",
            "    01_raw/       # 원시 데이터",
            "    02_clean/     # 정제 데이터",
            "    03_analysis/  # 분석 결과",
            "    04_report/    # 보고서(PDF)",
        ]
        if self._model_dir.exists() or any(
            k == "model" for k in self._meta
        ):
            lines.append("    model/        # 모델 파일 및 설정")
        if self._dashboard_dir.exists():
            lines.append("    dashboard/    # 대시보드 앱")
        lines += ["```", ""]

        # 실행 방법
        if run_instructions:
            lines += ["## 실행 방법", ""]
            for idx, instruction in enumerate(run_instructions, start=1):
                lines.append(f"{idx}. {instruction}")
            lines.append("")

        readme_path = self.base_dir / "README.md"
        readme_path.write_text("\n".join(lines), encoding="utf-8")
        log.info("generate_readme 완료", path=str(readme_path))

    def build(self) -> Path:
        """모든 표준 서브디렉토리를 생성하고 base_dir 를 반환한다.

        이미 존재하는 디렉토리는 그대로 유지한다 (exist_ok=True).

        Returns:
            생성된 패키지 루트 디렉토리 경로 (base_dir).
        """
        for subdir in _SUBDIRS:
            (self.base_dir / subdir).mkdir(parents=True, exist_ok=True)

        log.info(
            "build 완료",
            base_dir=str(self.base_dir),
            subdirs=_SUBDIRS,
        )
        return self.base_dir
