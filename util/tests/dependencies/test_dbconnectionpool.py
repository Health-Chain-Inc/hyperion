import logging
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from pyfiles.dependencies.dbconnectionpool import DBConnectionPool


@pytest.fixture
def fake_config():
    return {"dummy": "config"}


@pytest.fixture
def fake_engine():
    return MagicMock(name="engine")

def test_dbconnectionpool_init_logs_and_sets_config(fake_config, caplog):
    with caplog.at_level(logging.INFO):
        pool = DBConnectionPool(fake_config)

    assert pool.config == fake_config
    assert "DBConnectionPool instance created" in caplog.text

@patch("pyfiles.dependencies.dbconnectionpool.create_engine")
@patch(
    "pyfiles.dependencies.dbconnectionpool.Handlers.get_silver_layer_core_connection_parameters",
    return_value="user:pwd@host:3306/coredb",
)
def test_initialize_core_success(
    mock_core_params,
    mock_create_engine,
    fake_config,
    fake_engine,
    caplog,
):
    mock_create_engine.return_value = fake_engine

    pool = DBConnectionPool(fake_config)

    with caplog.at_level(logging.INFO):
        engine = pool.initialize("core")

    assert engine == fake_engine
    assert pool.connection_string == "mysql+pymysql://user:pwd@host:3306/coredb"
    mock_core_params.assert_called_once_with(fake_config)
    mock_create_engine.assert_called_once()
    assert "Connection string for core database created successfully" in caplog.text

@patch("pyfiles.dependencies.dbconnectionpool.create_engine")
@patch(
    "pyfiles.dependencies.dbconnectionpool.Handlers.get_silver_layer_audit_connection_parameters",
    return_value="user:pwd@host:3306/auditdb",
)
def test_initialize_audit_success(
    mock_audit_params,
    mock_create_engine,
    fake_config,
    fake_engine,
):
    mock_create_engine.return_value = fake_engine

    pool = DBConnectionPool(fake_config)
    engine = pool.initialize("audit")

    assert engine == fake_engine
    assert pool.connection_string == "mysql+pymysql://user:pwd@host:3306/auditdb"
    mock_audit_params.assert_called_once_with(fake_config)

@patch("pyfiles.dependencies.dbconnectionpool.create_engine")
@patch(
    "pyfiles.dependencies.dbconnectionpool.Handlers.get_database_connection_parameters",
    return_value="user:pwd@host:3306/customdb",
)
def test_initialize_custom_db_type_success(
    mock_generic_params,
    mock_create_engine,
    fake_config,
    fake_engine,
):
    mock_create_engine.return_value = fake_engine

    pool = DBConnectionPool(fake_config)
    engine = pool.initialize("reporting")

    assert engine == fake_engine
    assert pool.connection_string == "mysql+pymysql://user:pwd@host:3306/customdb"
    mock_generic_params.assert_called_once_with(fake_config, "reporting")

@patch("pyfiles.dependencies.dbconnectionpool.create_engine")
@patch(
    "pyfiles.dependencies.dbconnectionpool.Handlers.get_database_connection_parameters",
    return_value="user:pwd@host:3306/defaultdb",
)
def test_initialize_none_db_type(
    mock_generic_params,
    mock_create_engine,
    fake_config,
    fake_engine,
):
    mock_create_engine.return_value = fake_engine

    pool = DBConnectionPool(fake_config)
    engine = pool.initialize(None)

    assert engine == fake_engine
    assert pool.connection_string == "mysql+pymysql://user:pwd@host:3306/defaultdb"
    mock_generic_params.assert_called_once_with(fake_config, None)

@patch("pyfiles.dependencies.dbconnectionpool.create_engine", side_effect=SQLAlchemyError("boom"))
@patch(
    "pyfiles.dependencies.dbconnectionpool.Handlers.get_silver_layer_core_connection_parameters",
    return_value="user:pwd@host:3306/coredb",
)
def test_initialize_create_engine_failure(
    mock_core_params,
    mock_create_engine,
    fake_config,
):
    pool = DBConnectionPool(fake_config)

    with pytest.raises(SQLAlchemyError):
        pool.initialize("core")

    mock_core_params.assert_called_once_with(fake_config)
    mock_create_engine.assert_called_once()

@patch("pyfiles.dependencies.dbconnectionpool.create_engine")
@patch(
    "pyfiles.dependencies.dbconnectionpool.Handlers.get_silver_layer_core_connection_parameters",
    return_value="user:pwd@host:3306/coredb",
)
def test_initialize_inner_try_block_executed(
    mock_core_params,
    mock_create_engine,
    fake_config,
    fake_engine,
):
    mock_create_engine.return_value = fake_engine

    pool = DBConnectionPool(fake_config)
    engine = pool.initialize("core")

    assert engine == fake_engine
    assert hasattr(pool, "engine")

