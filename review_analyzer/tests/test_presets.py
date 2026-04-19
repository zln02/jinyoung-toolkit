"""PresetLoader 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from review_analyzer.preset_loader import PresetLoader

_PRESETS_DIR = Path(__file__).parent.parent / "presets"
_ALL_PRESET_FILES = sorted(_PRESETS_DIR.glob("*.yaml"))
_ALL_PRESET_NAMES = [p.stem for p in _ALL_PRESET_FILES if not p.name.endswith(".fallback.yaml")]


class TestPresetLoader:

    def test_load_naver_shopping(self) -> None:
        """네이버 쇼핑 프리셋 로드 + 필수 키 확인."""
        loader = PresetLoader()
        preset = loader.load("naver_shopping")

        # 최상위 필수 키
        assert "name" in preset
        assert "display_name" in preset
        assert "selectors" in preset

        # selectors 내부 필수 키
        selectors = preset["selectors"]
        assert "container" in selectors
        assert "fields" in selectors
        assert isinstance(selectors["fields"], dict)
        assert len(selectors["fields"]) > 0

        # 프리셋 이름 일치 확인
        assert preset["name"] == "naver_shopping"

    def test_list_presets_returns_all(self) -> None:
        """모든 프리셋이 목록에 포함되어 반환되는지 확인.

        프리셋 추가/제거 시 카운트는 디렉토리 기준으로 자동 동기화됨.
        """
        loader = PresetLoader()
        presets = loader.list_presets()

        # presets/ 디렉토리의 yaml 파일 수와 일치 (fallback 제외)
        assert len(presets) == len(_ALL_PRESET_NAMES)

        # 각 항목이 name + display_name 키를 가지는지 확인
        for item in presets:
            assert "name" in item
            assert "display_name" in item
            assert isinstance(item["name"], str)
            assert isinstance(item["display_name"], str)

        # 알려진 프리셋 이름이 포함되는지 확인
        names = [p["name"] for p in presets]
        assert "naver_shopping" in names
        # 신규 프리셋 일부 검증
        assert "youtube_comments" in names
        assert "apple_app_store" in names
        assert "naver_blog" in names

    def test_load_nonexistent_raises(self) -> None:
        """존재하지 않는 프리셋 로드 시 FileNotFoundError."""
        loader = PresetLoader()

        with pytest.raises(FileNotFoundError):
            loader.load("this_preset_does_not_exist")


@pytest.mark.parametrize("preset_name", _ALL_PRESET_NAMES)
def test_all_presets_load(preset_name: str) -> None:
    """presets/*.yaml 모든 프리셋을 매개변수화하여 로드 + 스키마 검증."""
    loader = PresetLoader()
    preset = loader.load(preset_name)

    assert preset["name"] == preset_name
    assert "display_name" in preset
    assert "selectors" in preset
    selectors = preset["selectors"]
    assert "container" in selectors
    assert "fields" in selectors
    assert isinstance(selectors["fields"], dict)
    assert len(selectors["fields"]) > 0
