from app.services.chatbot import ControlledSql, format_tool_facts, redact_sensitive


def test_sensitive_values_are_redacted_recursively() -> None:
    assert redact_sensitive({"api_key": "hidden", "nested": {"password": "hidden"}}) == {"api_key": "[REDACTED]", "nested": {"password": "[REDACTED]"}}


def test_controlled_sql_rejects_union_and_limits_rows() -> None:
    try:
        ControlledSql().validate("SELECT * FROM inventory_snapshots UNION SELECT * FROM users")
    except ValueError:
        pass
    else:
        raise AssertionError("UNION should be rejected")
    assert format_tool_facts("query_warnings", [{"sku": "A", "message": "超储"}]) == "共 1 条预警，首条为 A 的超储"
