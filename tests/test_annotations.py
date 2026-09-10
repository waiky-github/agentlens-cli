"""Tests for manual regulation annotations (regulations.py annotations, 2026-09-10)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentlens_cli import regulations as reg


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Point AGENTLENS_ANNOTATIONS at a temp file and reset the module cache."""
    monkeypatch.setenv("AGENTLENS_ANNOTATIONS", str(tmp_path / "annotations.json"))
    reg._invalidate_annotations_cache()
    yield
    reg._invalidate_annotations_cache()


class TestAnnotationWriteRead:
    def test_add_and_load(self, tmp_path):
        refs = reg.add_annotation("SOME_UNKNOWN_TITLE", "网信办《智能体规范应用与创新发展实施意见》", "测试-示例", "人工标注")
        assert refs[0]["regulation"].startswith("网信办")
        # 文件落盘
        data = json.loads((tmp_path / "annotations.json").read_text(encoding="utf-8"))
        assert "SOME_UNKNOWN_TITLE" in data
        # 再次读取生效
        assert reg._lookup_regulations("SOME_UNKNOWN_TITLE")[0]["article"] == "测试-示例"

    def test_annotations_override_static_table(self):
        # 静态表里已有的 title 被人工标注覆盖
        existing_title = next(iter(reg.REGULATIONS))
        reg.add_annotation(existing_title, "EU AI Act (2024/1689)", "Art. 99", "override test")
        refs = reg._lookup_regulations(existing_title)
        assert refs[0]["regulation"] == "EU AI Act (2024/1689)"
        assert refs[0]["note"] == "override test"

    def test_unknown_falls_through_when_no_annotation(self):
        refs = reg._lookup_regulations("NEVER_SEEN_TITLE_XYZ")
        assert refs[0]["regulation"] == "unknown"

    def test_list_annotations(self, tmp_path):
        reg.add_annotation("A_TITLE", "R1", "art1")
        reg.add_annotation("B_TITLE", "R2", "art2")
        ann = reg.list_annotations()
        assert set(ann.keys()) == {"A_TITLE", "B_TITLE"}


class TestMapFindingWithAnnotation:
    def test_map_finding_uses_annotation(self, tmp_path):
        reg.add_annotation("MAP_TEST_TITLE", "OWASP Agent Control Standard (ACS 2026)", "approval gate", "标注")
        f = reg.map_finding({"title": "MAP_TEST_TITLE"}, layer="cost")
        refs = f["regulation_refs"]
        assert any(r["regulation"].startswith("OWASP Agent Control Standard") for r in refs)
        # OWASP 层兜底不应重复添加同一条
        assert len([r for r in refs if r["regulation"].startswith("OWASP Agent")]) == 1


class TestUnknownAggregation:
    def _make_report(self, tmp_path, findings):
        html = (
            '<!DOCTYPE html><html><head></head><body>'
            '<script id="findings-data" type="application/json">'
            + json.dumps(findings, ensure_ascii=False).replace("</", "<\\/")
            + "</script></body></html>"
        )
        p = tmp_path / "audit-test.html"
        p.write_text(html, encoding="utf-8")
        return p

    def test_extract_unknown_from_report(self, tmp_path):
        # 静态表真实存在的 title（known）vs 不存在的（unknown）——实时 _lookup 判断
        known_title = next(iter(reg.REGULATIONS))
        findings = [
            {"title": known_title, "layer": "cost", "regulation_refs": [{"regulation": "网信办..."}]},
            {"title": "UNKNOWN_A", "layer": "cost", "regulation_refs": [{"regulation": "unknown"}]},
            {"title": "UNKNOWN_A", "layer": "decision", "regulation_refs": [{"regulation": "unknown"}]},
            {"title": "UNKNOWN_B", "layer": "shadow", "regulation_refs": []},
        ]
        report = self._make_report(tmp_path, findings)
        from agentlens_cli.__main__ import _extract_unknown_titles_from_report

        agg = _extract_unknown_titles_from_report(report)
        assert agg["UNKNOWN_A"]["count"] == 2
        assert agg["UNKNOWN_B"]["count"] == 1
        assert known_title not in agg
