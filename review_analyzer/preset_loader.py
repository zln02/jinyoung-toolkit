"""YAML 프리셋 로더 — review_analyzer/presets/ 디렉토리 기반."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import requests
import yaml
from bs4 import BeautifulSoup

from shared.logger import get_logger

log = get_logger(__name__)

_DEFAULT_PRESETS_DIR = Path(__file__).parent / "presets"

_REQUIRED_KEYS: list[str] = ["name", "display_name", "selectors"]
_REQUIRED_SELECTOR_KEYS: list[str] = ["container", "fields"]


class PresetLoader:
    """YAML 프리셋 로더.

    review_analyzer/presets/ 디렉토리에서 YAML 프리셋을 로드한다.

    Args:
        presets_dir: 프리셋 YAML 파일이 위치한 디렉토리 경로.
            None 이면 패키지 기본 경로(review_analyzer/presets/)를 사용한다.
    """

    def __init__(self, presets_dir: Path | None = None) -> None:
        """초기화. presets_dir이 None이면 review_analyzer/presets/ 사용."""
        self._presets_dir: Path = (
            presets_dir if presets_dir is not None else _DEFAULT_PRESETS_DIR
        )
        log.debug(
            "PresetLoader 초기화 완료",
            presets_dir=str(self._presets_dir),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, preset_name: str) -> dict[str, Any]:
        """프리셋 로드 + 스키마 검증.

        Args:
            preset_name: 프리셋 이름 (확장자 없이). 예: "naver_shopping"

        Returns:
            파싱된 프리셋 딕셔너리.

        Raises:
            FileNotFoundError: 프리셋 파일이 존재하지 않을 때.
            ValueError: 필수 키 누락 등 스키마 검증 실패 시.
        """
        preset_path = self._presets_dir / f"{preset_name}.yaml"

        if not preset_path.exists():
            log.warning("프리셋 파일 없음", preset_name=preset_name, path=str(preset_path))
            raise FileNotFoundError(
                f"프리셋 파일을 찾을 수 없습니다: {preset_path}"
            )

        try:
            with preset_path.open("r", encoding="utf-8") as fh:
                data: dict[str, Any] = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            log.error("YAML 파싱 실패", preset_name=preset_name, error=str(exc))
            raise ValueError(f"YAML 파싱 오류 ({preset_name}): {exc}") from exc

        self._validate_schema(data, preset_name)

        log.info("프리셋 로드 완료", preset_name=preset_name)
        return data

    def validate_selectors(
        self, preset: dict[str, Any], sample_url: str
    ) -> dict[str, bool]:
        """CSS 셀렉터 유효성 검증 (선택적 — 실제 페이지 요청).

        sample_url 페이지에 HTTP GET 요청을 보내 각 CSS 셀렉터가 실제로
        요소를 찾아내는지 확인한다.

        Args:
            preset: load()로 얻은 프리셋 딕셔너리.
            sample_url: 셀렉터를 검증할 실제 페이지 URL.

        Returns:
            셀렉터 이름 → 유효 여부 매핑 딕셔너리.
            예: {"container": True, "reviewer": True, "rating": False, ...}
        """
        results: dict[str, bool] = {}
        selectors: dict[str, Any] = preset.get("selectors", {})

        try:
            resp = requests.get(
                sample_url,
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0 (compatible; PresetLoader/1.0)"},
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as exc:
            log.error(
                "셀렉터 검증용 페이지 요청 실패",
                url=sample_url,
                error=str(exc),
            )
            return results

        # container 검증
        container_sel: str = selectors.get("container", "")
        if container_sel:
            results["container"] = bool(soup.select(container_sel))

        # fields 검증
        fields: dict[str, str] = selectors.get("fields", {})
        for field_name, selector in fields.items():
            try:
                results[field_name] = bool(soup.select(selector))
            except Exception as exc:
                log.warning(
                    "셀렉터 평가 중 오류",
                    field=field_name,
                    selector=selector,
                    error=str(exc),
                )
                results[field_name] = False

        log.info(
            "셀렉터 검증 완료",
            url=sample_url,
            results=results,
        )
        return results

    def get_fallback_selectors(self, preset_name: str) -> dict[str, str] | None:
        """히스토리 기반 fallback 셀렉터 반환.

        presets/ 폴더에 {preset_name}.fallback.yaml 이 있으면 로드하여
        selectors 섹션을 반환한다.

        Args:
            preset_name: 프리셋 이름 (확장자 없이).

        Returns:
            셀렉터 딕셔너리 또는 fallback 파일이 없으면 None.
        """
        fallback_path = self._presets_dir / f"{preset_name}.fallback.yaml"

        if not fallback_path.exists():
            log.debug("fallback 파일 없음", preset_name=preset_name)
            return None

        try:
            with fallback_path.open("r", encoding="utf-8") as fh:
                data: dict[str, Any] = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            log.error(
                "fallback YAML 파싱 실패",
                preset_name=preset_name,
                error=str(exc),
            )
            return None

        selectors: dict[str, str] | None = data.get("selectors")
        if selectors is None:
            log.warning(
                "fallback 파일에 selectors 키 없음",
                preset_name=preset_name,
                path=str(fallback_path),
            )
            return None

        log.info("fallback 셀렉터 로드 완료", preset_name=preset_name)
        return selectors

    def list_presets(self) -> list[dict[str, str]]:
        """사용 가능한 프리셋 목록 반환.

        presets_dir 내의 .yaml 파일을 탐색한다.
        .fallback.yaml 파일은 제외한다.

        Returns:
            [{"name": "naver_shopping", "display_name": "네이버 쇼핑 리뷰"}, ...]
            display_name을 읽지 못한 경우 name 값으로 대체한다.
        """
        result: list[dict[str, str]] = []

        if not self._presets_dir.exists():
            log.warning("presets 디렉토리 없음", path=str(self._presets_dir))
            return result

        yaml_files = sorted(self._presets_dir.glob("*.yaml"))

        for yaml_path in yaml_files:
            # fallback 파일 제외
            if yaml_path.name.endswith(".fallback.yaml"):
                continue

            preset_name = yaml_path.stem

            try:
                with yaml_path.open("r", encoding="utf-8") as fh:
                    data: dict[str, Any] = yaml.safe_load(fh)
                display_name: str = data.get("display_name", preset_name)
            except Exception as exc:
                log.warning(
                    "프리셋 목록 조회 중 파일 읽기 실패",
                    path=str(yaml_path),
                    error=str(exc),
                )
                display_name = preset_name

            result.append({"name": preset_name, "display_name": display_name})

        log.debug("프리셋 목록 조회 완료", count=len(result))
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_schema(self, data: dict[str, Any], preset_name: str) -> None:
        """필수 키 존재 여부를 검증한다.

        Args:
            data: 파싱된 YAML 딕셔너리.
            preset_name: 오류 메시지에 사용할 프리셋 이름.

        Raises:
            ValueError: 필수 키가 누락된 경우.
        """
        for key in _REQUIRED_KEYS:
            if key not in data:
                raise ValueError(
                    f"프리셋 '{preset_name}' 에 필수 키 '{key}' 가 없습니다."
                )

        selectors: Any = data.get("selectors")
        if not isinstance(selectors, dict):
            raise ValueError(
                f"프리셋 '{preset_name}' 의 selectors 값이 dict 타입이 아닙니다."
            )

        for key in _REQUIRED_SELECTOR_KEYS:
            if key not in selectors:
                raise ValueError(
                    f"프리셋 '{preset_name}' 의 selectors 에 필수 키 '{key}' 가 없습니다."
                )

        fields: Any = selectors.get("fields")
        if not isinstance(fields, dict) or len(fields) == 0:
            raise ValueError(
                f"프리셋 '{preset_name}' 의 selectors.fields 가 비어있거나 dict 타입이 아닙니다."
            )

        log.debug("스키마 검증 통과", preset_name=preset_name)
