"""PresetLoader 테스트."""

from __future__ import annotations

import pytest

from review_analyzer.preset_loader import PresetLoader


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
        """4개 프리셋 목록 반환."""
        loader = PresetLoader()
        presets = loader.list_presets()

        assert len(presets) == 4

        # 각 항목이 name + display_name 키를 가지는지 확인
        for item in presets:
            assert "name" in item
            assert "display_name" in item
            assert isinstance(item["name"], str)
            assert isinstance(item["display_name"], str)

        # 알려진 프리셋 이름이 포함되는지 확인
        names = [p["name"] for p in presets]
        assert "naver_shopping" in names

    def test_load_nonexistent_raises(self) -> None:
        """존재하지 않는 프리셋 로드 시 FileNotFoundError."""
        loader = PresetLoader()

        with pytest.raises(FileNotFoundError):
            loader.load("this_preset_does_not_exist")
