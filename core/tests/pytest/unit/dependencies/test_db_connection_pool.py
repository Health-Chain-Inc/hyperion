"""Unit tests for DBConnectionPool class."""
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy.exc import SQLAlchemyError

from pyfiles.dependencies.resource_manager import ResourceManager


@pytest.fixture(autouse=True)
def reset_resource_manager():
    """Reset ResourceManager singleton state before each test."""
    ResourceManager().reset()
    yield
    ResourceManager().reset()


def _make_config(pool_size="5"):
    """Return a minimal config dict for DBConnectionPool."""
    return {
        "pools": {"database": pool_size},
    }


@pytest.mark.unit
class TestDBConnectionPoolInit:
    """Test DBConnectionPool __init__."""

    @patch("pyfiles.dependencies.db_connection_pool.ResourceManager")
    @patch("pyfiles.dependencies.db_connection_pool.sessionmaker")
    @patch("pyfiles.dependencies.db_connection_pool.create_engine")
    @patch("pyfiles.dependencies.db_connection_pool.Handlers.get_silver_layer_connection_parameters")
    def test_init_success_creates_engine_and_session_factory(
        self, mock_params, mock_create_engine, mock_sessionmaker, mock_rm
    ):
        """Successful init sets engine, SessionFactory, and connection_string."""
        from pyfiles.dependencies.db_connection_pool import DBConnectionPool

        mock_params.return_value = "user:pass@host:9030/db"
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        mock_session_factory = MagicMock()
        mock_sessionmaker.return_value = mock_session_factory

        pool = DBConnectionPool(_make_config(), "core_db")

        assert pool.engine is mock_engine
        assert pool.SessionFactory is mock_session_factory
        # connection_string is now a local variable (not stored on instance) to avoid credential leakage
        mock_create_engine.assert_called_once()
        call_args = mock_create_engine.call_args
        assert "mysql+pymysql://" in call_args[0][0]

    @patch("pyfiles.dependencies.db_connection_pool.ResourceManager")
    @patch("pyfiles.dependencies.db_connection_pool.sessionmaker")
    @patch("pyfiles.dependencies.db_connection_pool.create_engine")
    @patch("pyfiles.dependencies.db_connection_pool.Handlers.get_silver_layer_connection_parameters")
    def test_init_registers_with_resource_manager(
        self, mock_params, mock_create_engine, mock_sessionmaker, mock_rm_class
    ):
        """__init__ registers the pool and dispose method with ResourceManager."""
        from pyfiles.dependencies.db_connection_pool import DBConnectionPool

        mock_params.return_value = "user:pass@host/db"
        mock_create_engine.return_value = MagicMock()

        mock_rm_instance = MagicMock()
        mock_rm_class.return_value = mock_rm_instance

        pool = DBConnectionPool(_make_config(), "core_db")

        mock_rm_instance.register.assert_called_once_with(
            "db_pool", pool, pool.dispose
        )

    @patch("pyfiles.dependencies.db_connection_pool.ResourceManager")
    @patch("pyfiles.dependencies.db_connection_pool.create_engine")
    @patch("pyfiles.dependencies.db_connection_pool.Handlers.get_silver_layer_connection_parameters")
    def test_init_engine_connect_failure_raises_prerequisite_error(
        self, mock_params, mock_create_engine, mock_rm
    ):
        """SQLAlchemyError on engine.connect() raises PrerequisiteError."""
        from pyfiles.dependencies.data_processing_error import PrerequisiteError
        from pyfiles.dependencies.db_connection_pool import DBConnectionPool

        mock_params.return_value = "user:pass@host/db"
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = SQLAlchemyError("connection refused")
        mock_create_engine.return_value = mock_engine

        with pytest.raises(PrerequisiteError):
            DBConnectionPool(_make_config(), "core_db")

    @patch("pyfiles.dependencies.db_connection_pool.ResourceManager")
    @patch("pyfiles.dependencies.db_connection_pool.create_engine")
    @patch("pyfiles.dependencies.db_connection_pool.Handlers.get_silver_layer_connection_parameters")
    def test_init_create_engine_failure_raises_prerequisite_error(
        self, mock_params, mock_create_engine, mock_rm
    ):
        """SQLAlchemyError raised by create_engine() raises PrerequisiteError."""
        from pyfiles.dependencies.data_processing_error import PrerequisiteError
        from pyfiles.dependencies.db_connection_pool import DBConnectionPool

        mock_params.return_value = "user:pass@host/db"
        mock_create_engine.side_effect = SQLAlchemyError("engine creation failed")

        with pytest.raises(PrerequisiteError):
            DBConnectionPool(_make_config(), "core_db")

    @patch("pyfiles.dependencies.db_connection_pool.ResourceManager")
    @patch("pyfiles.dependencies.db_connection_pool.sessionmaker")
    @patch("pyfiles.dependencies.db_connection_pool.create_engine")
    @patch("pyfiles.dependencies.db_connection_pool.Handlers.get_silver_layer_connection_parameters")
    def test_pool_configuration_values(
        self, mock_params, mock_create_engine, mock_sessionmaker, mock_rm
    ):
        """Engine is created with the required pool configuration parameters."""
        from pyfiles.dependencies.db_connection_pool import DBConnectionPool

        mock_params.return_value = "user:pass@host/db"
        mock_create_engine.return_value = MagicMock()

        DBConnectionPool(_make_config(), "core_db")

        _, kwargs = mock_create_engine.call_args
        assert kwargs.get("pool_pre_ping") is True
        assert kwargs.get("pool_recycle") == 300
        assert kwargs.get("max_overflow") == 2
        assert kwargs.get("pool_timeout") == 30


@pytest.mark.unit
class TestDBConnectionPoolCreateConnection:
    """Test create_connection() method."""

    @patch("pyfiles.dependencies.db_connection_pool.ResourceManager")
    @patch("pyfiles.dependencies.db_connection_pool.sessionmaker")
    @patch("pyfiles.dependencies.db_connection_pool.create_engine")
    @patch("pyfiles.dependencies.db_connection_pool.Handlers.get_silver_layer_connection_parameters")
    def test_create_connection_delegates_to_engine(
        self, mock_params, mock_create_engine, mock_sessionmaker, mock_rm
    ):
        """create_connection() calls engine.connect() and returns the result."""
        from pyfiles.dependencies.db_connection_pool import DBConnectionPool

        mock_params.return_value = "user:pass@host/db"
        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_engine.connect.return_value = mock_connection
        mock_create_engine.return_value = mock_engine

        pool = DBConnectionPool(_make_config(), "core_db")

        # Reset the call count from __init__
        mock_engine.connect.reset_mock()

        result = pool.create_connection()

        mock_engine.connect.assert_called_once()
        assert result is mock_connection


@pytest.mark.unit
class TestDBConnectionPoolDispose:
    """Test dispose() method."""

    @patch("pyfiles.dependencies.db_connection_pool.ResourceManager")
    @patch("pyfiles.dependencies.db_connection_pool.sessionmaker")
    @patch("pyfiles.dependencies.db_connection_pool.create_engine")
    @patch("pyfiles.dependencies.db_connection_pool.Handlers.get_silver_layer_connection_parameters")
    def test_dispose_calls_engine_dispose_and_sets_none(
        self, mock_params, mock_create_engine, mock_sessionmaker, mock_rm
    ):
        """dispose() calls engine.dispose() and then sets self.engine to None."""
        from pyfiles.dependencies.db_connection_pool import DBConnectionPool

        mock_params.return_value = "user:pass@host/db"
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        pool = DBConnectionPool(_make_config(), "core_db")
        pool.dispose()

        mock_engine.dispose.assert_called_once()
        assert pool.engine is None

    @patch("pyfiles.dependencies.db_connection_pool.ResourceManager")
    @patch("pyfiles.dependencies.db_connection_pool.sessionmaker")
    @patch("pyfiles.dependencies.db_connection_pool.create_engine")
    @patch("pyfiles.dependencies.db_connection_pool.Handlers.get_silver_layer_connection_parameters")
    def test_dispose_idempotent_when_engine_is_none(
        self, mock_params, mock_create_engine, mock_sessionmaker, mock_rm
    ):
        """Calling dispose() twice does not raise even after engine is None."""
        from pyfiles.dependencies.db_connection_pool import DBConnectionPool

        mock_params.return_value = "user:pass@host/db"
        mock_create_engine.return_value = MagicMock()

        pool = DBConnectionPool(_make_config(), "core_db")
        pool.dispose()  # sets engine to None
        pool.dispose()  # second call — should not raise
