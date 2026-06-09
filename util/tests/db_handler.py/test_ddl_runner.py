import logging
from unittest.mock import MagicMock, mock_open, patch

import pandas as pd
import pytest
from sqlalchemy.exc import SQLAlchemyError

from pyfiles.db_handler.ddl_runner import (
    check_first_run, execute_sql_file, execute_sql_statement, fetch_data,
    fetch_data_multiple_rows, insert_dollar_export_logger,
    insert_or_update_dollar_export_logger, insert_or_update_pipeline_meta_info,
    insert_or_update_schema_history)
from pyfiles.dependencies.utilityexception import UtilityException


def test_execute_sql_statement_success():
    db = MagicMock()
    con = db.connect.return_value.__enter__.return_value

    execute_sql_statement(db, "SELECT 1")

    con.execute.assert_called_once()
    args, _ = con.execute.call_args
    assert args[0].text == "SELECT 1"


def test_execute_sql_statement_operational_error_handled():
    db = MagicMock()
    con = db.connect.return_value.__enter__.return_value
    con.execute.side_effect = SQLAlchemyError("pymysql.err.OperationalError 1050")

    execute_sql_statement(db, "SELECT 1")  # Should not raise


def test_execute_sql_statement_other_sqlalchemy_error_raises():
    db = MagicMock()
    con = db.connect.return_value.__enter__.return_value
    con.execute.side_effect = SQLAlchemyError("Different error")

    with pytest.raises(SQLAlchemyError):
        execute_sql_statement(db, "SELECT 1")

def test_insert_or_update_schema_history_insert():
    with patch("pyfiles.db_handler.queries.Queries.get_insert_query", return_value="INSERT"):
        query, params = insert_or_update_schema_history("users", "success", {})

        assert query == "INSERT"
        assert "id" not in params
        assert params["table_name"] == "users"


def test_insert_or_update_schema_history_update():
    db_data = {"id": 10, "version": 3}

    with patch("pyfiles.db_handler.queries.Queries.get_insert_query", return_value="UPDATE"):
        query, params = insert_or_update_schema_history("users", "success", db_data)

        assert query == "UPDATE"
        assert params["id"] == 10
        assert params["version"] == 4

def test_insert_or_update_pipeline_meta_info_insert():
    with patch("pyfiles.db_handler.queries.Queries.get_insert_query", return_value="INSERT"):
        query, params = insert_or_update_pipeline_meta_info("meta", "success", {})

        assert query == "INSERT"
        assert "id" not in params
        assert params["property"] == "meta"


def test_insert_or_update_pipeline_meta_info_update():
    db_data = {"id": 5}

    with patch("pyfiles.db_handler.queries.Queries.get_insert_query", return_value="UPDATE"):
        query, params = insert_or_update_pipeline_meta_info("meta", "success", db_data)

        assert query == "UPDATE"
        assert params["id"] == 5

def test_insert_dollar_export_logger_insert():
    with patch("pyfiles.db_handler.queries.Queries.get_insert_query", return_value="INSERT"):
        query, params = insert_dollar_export_logger(
            "2024-01-01", "2024-01-02", "Patient", "url", "done", {}
        )

        assert query == "INSERT"
        assert "id" not in params
        assert params["resource_type"] == "Patient"


def test_fetch_data_success():
    db = MagicMock()
    con = db.connect.return_value.__enter__.return_value

    row = {"id": 1, "table_name": "users"}
    con.execute.return_value.mappings().fetchone.return_value = row

    result = fetch_data("schema_history", "table_name", "users", db)

    args, _ = con.execute.call_args
    expected_sql = "SELECT * FROM `schema_history` WHERE `table_name` = 'users'"
    assert args[0].text == expected_sql

    assert result == row


def test_fetch_data_failure():
    db = MagicMock()
    con = db.connect.return_value.__enter__.return_value
    con.execute.side_effect = Exception("Database failure")

    with pytest.raises(UtilityException):
        fetch_data("schema_history", "col", "val", db)

def test_fetch_data_multiple_rows_success():
    db = MagicMock()
    con = db.connect.return_value.__enter__.return_value

    con.execute.return_value.fetchall.return_value = [(1, "A"), (2, "B")]
    con.execute.return_value.keys.return_value = ["id", "name"]

    df = fetch_data_multiple_rows("tableX", "col", "val", db)

    args, _ = con.execute.call_args
    expected_sql = "SELECT * FROM `tableX` WHERE `col` = 'val'"
    assert args[0].text == expected_sql

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert list(df.columns) == ["id", "name"]

def test_check_first_run_true():
    db = MagicMock()
    con = db.connect.return_value.__enter__.return_value
    con.execute.return_value.fetchall.return_value = [("table1",)]

    result = check_first_run(db)

    args, _ = con.execute.call_args
    assert args[0].text == "SHOW TABLES;"

    assert result is True


def test_check_first_run_exception_returns_false():
    db = MagicMock()
    db.connect.side_effect = Exception("Error")

    assert check_first_run(db) is False

def test_insert_or_update_dollar_export_logger_insert():
    with patch("pyfiles.db_handler.queries.Queries.get_insert_query", return_value="INSERT"):
        query, params = insert_or_update_dollar_export_logger("prop", "success", {})

        assert query == "INSERT"
        assert "id" not in params
        assert params["property"] == "prop"

def test_execute_sql_file_runs_sql_correctly():
    core_db = MagicMock()
    audit_db = MagicMock()

    sql_in_file = "CREATE TABLE IF NOT EXISTS fhir_lineage(id int);"

    with (
        patch("builtins.open", mock_open(read_data=sql_in_file)),
        patch("pyfiles.db_handler.ddl_runner.execute_sql_statement") as exec_mock,
        patch("pyfiles.db_handler.ddl_runner.fetch_data", return_value={}),
        patch("pyfiles.db_handler.ddl_runner.insert_or_update_schema_history",
              return_value=("Q", {})),
        patch("pyfiles.db_handler.ddl_runner.insert_or_update_pipeline_meta_info",
              return_value=("Q", {})),
    ):
        execute_sql_file(core_db, audit_db, "mock.sql", "true", "true")

        exec_mock.assert_any_call(audit_db, "CREATE TABLE IF NOT EXISTS fhir_lineage(id int)")

def test_execute_sql_file_runs_sql_correctly_fhir_audit():
    core_db = MagicMock()
    audit_db = MagicMock()

    sql_in_file = "CREATE TABLE IF NOT EXISTS fhir_audit(id int);"

    with (
        patch("builtins.open", mock_open(read_data=sql_in_file)),
        patch("pyfiles.db_handler.ddl_runner.execute_sql_statement"),
        patch("pyfiles.db_handler.ddl_runner.fetch_data", return_value={}),
        patch("pyfiles.db_handler.ddl_runner.insert_or_update_schema_history",
              return_value=("Q", {})),
        patch("pyfiles.db_handler.ddl_runner.insert_or_update_pipeline_meta_info",
              return_value=("Q", {})),
    ):
        execute_sql_file(core_db, audit_db, "mock.sql", "false", "false")

def test_execute_sql_file_runs_sql_correctly_fhir_lineage():
    core_db = MagicMock()
    audit_db = MagicMock()

    sql_in_file = "CREATE TABLE IF NOT EXISTS fhir_lineage(id int);"

    with (
        patch("builtins.open", mock_open(read_data=sql_in_file)),
        patch("pyfiles.db_handler.ddl_runner.execute_sql_statement"),
        patch("pyfiles.db_handler.ddl_runner.fetch_data", return_value={}),
        patch("pyfiles.db_handler.ddl_runner.insert_or_update_schema_history",
              return_value=("Q", {})),
        patch("pyfiles.db_handler.ddl_runner.insert_or_update_pipeline_meta_info",
              return_value=("Q", {})),
    ):
        execute_sql_file(core_db, audit_db, "mock.sql", "false", "false")

def test_execute_sql_file_runs_sql_correctly_patient():
    core_db = MagicMock()
    audit_db = MagicMock()

    sql_in_file = "CREATE TABLE IF NOT EXISTS patient(id int);"

    with (
        patch("builtins.open", mock_open(read_data=sql_in_file)),
        patch("pyfiles.db_handler.ddl_runner.execute_sql_statement") as exec_mock,
        patch("pyfiles.db_handler.ddl_runner.fetch_data", return_value={}),
        patch("pyfiles.db_handler.ddl_runner.insert_or_update_schema_history",
              return_value=("Q", {})),
        patch("pyfiles.db_handler.ddl_runner.insert_or_update_pipeline_meta_info",
              return_value=("Q", {})),
    ):
        execute_sql_file(core_db, audit_db, "mock.sql", "true", "true")

        exec_mock.assert_any_call(core_db, "CREATE TABLE IF NOT EXISTS patient(id int)")

def test_fetch_data_multiple_rows_exception():
    mock_connection = MagicMock()
    mock_context = mock_connection.connect.return_value.__enter__.return_value

    # Simulate DB failure
    mock_context.execute.side_effect = Exception("DB error")

    with patch("logging.exception") as log_mock:
        with pytest.raises(UtilityException) as exc:
            fetch_data_multiple_rows(
                "users", "name", "Alice", mock_connection
            )

        # Logging check
        log_mock.assert_called_once()
        assert "Fetch Data Multiple Rows function failed!!" in str(exc.value)

def test_execute_sql_statement_success_with_params():
    db = MagicMock()
    con = db.connect.return_value.__enter__.return_value
    params = {"id": 1}

    execute_sql_statement(db, "INSERT INTO test VALUES (:id)", params=params)

    con.execute.assert_called_once()
    args, kwargs = con.execute.call_args

    assert args[0].text == "INSERT INTO test VALUES (:id)"
    assert args[1] == params

def test_execute_sql_statement_operational_error_1050(caplog):
    db = MagicMock()
    con = db.connect.return_value.__enter__.return_value

    error = SQLAlchemyError("pymysql.err.OperationalError (1050): table exists")
    con.execute.side_effect = error

    with caplog.at_level(logging.INFO):
        execute_sql_statement(db, "CREATE TABLE t")

    assert "Already Exists" in caplog.text

def test_execute_sql_statement_programming_error_1007(caplog):
    db = MagicMock()
    con = db.connect.return_value.__enter__.return_value

    error = SQLAlchemyError("pymysql.err.ProgrammingError (1007): db exists")
    con.execute.side_effect = error

    with caplog.at_level(logging.INFO):
        execute_sql_statement(db, "CREATE DATABASE x")

    assert "Database Already Exists" in caplog.text

def test_execute_sql_statement_generic_sqlalchemy_error():
    db = MagicMock()
    con = db.connect.return_value.__enter__.return_value

    error = SQLAlchemyError("Some other SQL error")
    con.execute.side_effect = error

    with pytest.raises(SQLAlchemyError):
        execute_sql_statement(db, "INVALID SQL")

def test_execute_sql_statement_generic_exception(caplog):
    db = MagicMock()
    con = db.connect.return_value.__enter__.return_value

    con.execute.side_effect = Exception("unexpected failure")

    with caplog.at_level(logging.INFO):
        execute_sql_statement(db, "ANY SQL")

    assert "Exception while executing sql statement" in caplog.text
    assert "unexpected failure" in caplog.text
