from pathlib import Path

from openpyxl import Workbook

from app.adapters.excel import ExcelAdapter
from app.adapters.generic import ApiAdapter
from app.adapters.registry import adapter_registry
from app.governance import normalize_materials, validate_numeric
from app.data.dictionary import required_fields


def test_adapter_contract_and_mapping() -> None:
    adapter = ApiAdapter("fixture", [{"external_sku": "a-1", "qty": 3}])
    assert adapter.sync(mapping={"external_sku": "sku"}) == 1
    assert adapter.loaded_rows == [{"sku": "a-1", "qty": 3}]


def test_registry_has_generic_and_market_adapters() -> None:
    assert {"database", "api", "webservice", "staging", "market"}.issubset(adapter_registry.names())


def test_excel_template_validation(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["sku", "quantity"])
    sheet.append(["A-1", 4])
    path = tmp_path / "inventory.xlsx"
    workbook.save(path)
    rows = ExcelAdapter({"sku", "quantity"}).read_file(path)
    assert rows == [{"sku": "A-1", "quantity": 4}]


def test_material_normalization_and_numeric_validation() -> None:
    rows = normalize_materials([{"sku": " a-1 ", "name": "螺栓"}, {"sku": "A1", "name": "螺栓"}], {"a-1": "A1"})
    assert rows[0]["sku"] == "A1"
    assert "a-1" in rows[0]["aliases"]
    assert validate_numeric({"quantity": -1, "price": "bad"}, ["quantity", "price"]) == ["quantity must be non-negative", "price must be numeric"]


def test_data_dictionary_exposes_required_contract() -> None:
    assert required_fields("materials") == {"sku", "name", "package_size"}
