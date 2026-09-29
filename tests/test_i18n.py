import json
import re
from pathlib import Path

import pytest

LOCALES = Path(__file__).resolve().parent.parent / "static" / "locales"
BASE = "pt-BR"
PARAM = re.compile(r"\{(\w+)\}")


def _load(code: str) -> dict:
    return json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))


def _others():
    return sorted(p.stem for p in LOCALES.glob("*.json") if p.stem != BASE)


def test_expected_locales_exist():
    assert {p.stem for p in LOCALES.glob("*.json")} >= {"pt-BR", "en", "es"}


@pytest.mark.parametrize("code", _others())
def test_same_keys_as_portuguese(code):
    base, other = _load(BASE), _load(code)
    assert sorted(set(base) - set(other)) == [], f"faltam em {code}"
    assert sorted(set(other) - set(base)) == [], f"sobram em {code}"


@pytest.mark.parametrize("code", _others())
def test_same_placeholders(code):
    base, other = _load(BASE), _load(code)
    for key, text in base.items():
        assert set(PARAM.findall(other[key])) == set(PARAM.findall(text)), f"{code}: {key}"


def test_every_api_error_code_has_a_translation():
    main = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
    codes = set(re.findall(r'(?:api_error\(\d+, |doc_error\()"(\w+)"', main))
    assert codes, "nenhum código de erro encontrado em main.py"
    base = _load(BASE)
    assert sorted(c for c in codes if f"error.{c}" not in base) == []
