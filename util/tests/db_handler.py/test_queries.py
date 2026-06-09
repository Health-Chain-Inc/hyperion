import sys

import pytest

from pyfiles.db_handler.queries import Queries


@pytest.mark.parametrize("table_name,expected_columns", [
    ("schema_history", ["table_name","created_date","created_by","updated_date","version","status","description"]),
    ("pipeline_meta_info", ["property","description","status","created_date","created_by","updated_date"]),
    ("dollar_export_logger", ["since_date_time","till_date_time","resource_type","status_url","dollar_export_status"])
])
def test_get_insert_query_is_update_false(table_name, expected_columns):
    insert_query = Queries.get_insert_query(table_name, is_update=False)
    assert ":id" not in insert_query
    for column in expected_columns:
        assert f":{column}" in insert_query
    assert f"INSERT INTO {table_name}" in insert_query

@pytest.mark.parametrize("table_name,expected_columns", [
    ("schema_history", ["id","table_name","created_date","created_by","updated_date","version","status","description"]),
    ("pipeline_meta_info", ["id","property","description","status","created_date","created_by","updated_date"]),
    ("dollar_export_logger", ["id","since_date_time","till_date_time","resource_type","status_url","dollar_export_status"])
])
def test_get_insert_query_is_update_true(table_name, expected_columns):

    insert_query = Queries.get_insert_query(table_name, is_update=True)
    assert ":id" in insert_query
    for column in expected_columns:
        assert f":{column}" in insert_query
    assert f"INSERT INTO {table_name}" in insert_query

def test_unknown_table_exits(monkeypatch):

    exit_called = {}

    def fake_exit(code):
        exit_called["code"] = code
        raise SystemExit(code)

    monkeypatch.setattr(sys, "exit", fake_exit)

    with pytest.raises(SystemExit) as exc_info:
        Queries.get_insert_query("unknown_table", is_update=False)

    assert exit_called["code"] == 1
    assert exc_info.value.code == 1

def test_queries_constructor():
    q = Queries()
    assert isinstance(q, Queries)

def test_schema_history_fields_in_query():
    table_name = "schema_history"
    fields = ["id","table_name","created_date","created_by","updated_date","version","status","description"]

    # Test with is_update=True (id should be included)
    insert_query = Queries.get_insert_query(table_name, is_update=True)
    for field in fields:
        assert f":{field}" in insert_query, f"Field '{field}' missing in insert query for {table_name}"

def test_pipeline_meta_info_fields_in_query():
    table_name = "pipeline_meta_info"
    fields = ["id","property","description","status","created_date","created_by","updated_date"]

    insert_query = Queries.get_insert_query(table_name, is_update=True)
    for field in fields:
        assert f":{field}" in insert_query, f"Field '{field}' missing in insert query for {table_name}"

def test_dollar_export_logger_fields_in_query():
    table_name = "dollar_export_logger"
    fields = ["id","since_date_time","till_date_time","resource_type","status_url","dollar_export_status"]

    insert_query = Queries.get_insert_query(table_name, is_update=True)
    for field in fields:
        assert f":{field}" in insert_query, f"Field '{field}' missing in insert query for {table_name}"
