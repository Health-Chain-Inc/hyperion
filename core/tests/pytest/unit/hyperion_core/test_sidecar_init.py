"""Unit tests for SidecarInit class."""
import logging
from unittest.mock import MagicMock, patch


class TestSidecarInitInitialization:
    """Test SidecarInit initialization."""

    def test_initialization_stores_parameters(self):
        """Test that initialization stores logger and config."""
        from pyfiles.hyperion_core.sidecar_init import SidecarInit

        mock_logger = MagicMock()
        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        init = SidecarInit(
            logger_config=mock_logger,
            project_configurations=config
        )

        assert init.logger == mock_logger
        assert init.project_configurations == config


class TestSetupLogger:
    """Test setup_logger static method."""

    def test_setup_logger_creates_logger(self, tmp_path):
        """Test that setup_logger creates a configured logger."""
        from pyfiles.hyperion_core.sidecar_init import SidecarInit

        log_file = tmp_path / "test.log"

        logger = SidecarInit.setup_logger(
            name='test_logger',
            filename=str(log_file),
            level='DEBUG'
        )

        assert logger is not None
        assert logger.name == 'test_logger'
        assert logger.level == logging.DEBUG

    def test_setup_logger_sets_correct_level(self, tmp_path):
        """Test that logger has correct level set."""
        from pyfiles.hyperion_core.sidecar_init import SidecarInit

        log_file = tmp_path / "test_info.log"

        logger = SidecarInit.setup_logger(
            name='test_info_logger',
            filename=str(log_file),
            level='INFO'
        )

        assert logger.level == logging.INFO

    def test_setup_logger_with_rotation(self, tmp_path):
        """Test setup_logger with file rotation enabled."""
        from pyfiles.hyperion_core.sidecar_init import SidecarInit

        log_file = tmp_path / "test_rotate.log"

        logger = SidecarInit.setup_logger(
            name='test_rotate_logger',
            filename=str(log_file),
            level='DEBUG',
            max_bytes=1024,
            backup_count=5,
            rotate=True
        )

        assert logger is not None
        # Should have RotatingFileHandler
        assert len(logger.handlers) > 0

    def test_setup_logger_without_rotation(self, tmp_path):
        """Test setup_logger with file rotation disabled."""
        from pyfiles.hyperion_core.sidecar_init import SidecarInit

        log_file = tmp_path / "test_no_rotate.log"

        logger = SidecarInit.setup_logger(
            name='test_no_rotate_logger',
            filename=str(log_file),
            level='DEBUG',
            rotate=False
        )

        assert logger is not None

    def test_setup_logger_prevents_duplicate_handlers(self, tmp_path):
        """Test that calling setup_logger twice doesn't duplicate handlers."""
        from pyfiles.hyperion_core.sidecar_init import SidecarInit

        log_file = tmp_path / "test_dup.log"

        logger1 = SidecarInit.setup_logger(
            name='test_dup_logger',
            filename=str(log_file),
            level='DEBUG'
        )
        initial_handler_count = len(logger1.handlers)

        logger2 = SidecarInit.setup_logger(
            name='test_dup_logger',
            filename=str(log_file),
            level='DEBUG'
        )

        # Should be same logger, no new handlers
        assert logger1 is logger2
        assert len(logger2.handlers) == initial_handler_count


class TestGetCurrentHostname:
    """Test get_current_hostname method."""

    @patch('pyfiles.hyperion_core.sidecar_init.socket.getfqdn')
    def test_get_current_hostname_returns_fqdn(self, mock_getfqdn):
        """Test that get_current_hostname returns fully qualified domain name."""
        from pyfiles.hyperion_core.sidecar_init import SidecarInit

        mock_getfqdn.return_value = 'fe-node-1.cluster.local'

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        init = SidecarInit(
            logger_config=MagicMock(),
            project_configurations=config
        )

        hostname = init.get_current_hostname()

        assert hostname == 'fe-node-1.cluster.local'
        mock_getfqdn.assert_called_once()

    @patch('pyfiles.hyperion_core.sidecar_init.socket.getfqdn')
    def test_get_current_hostname_returns_none_on_error(self, mock_getfqdn):
        """Test that get_current_hostname returns None on error."""
        from pyfiles.hyperion_core.sidecar_init import SidecarInit

        mock_getfqdn.side_effect = Exception("Network error")

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        init = SidecarInit(
            logger_config=MagicMock(),
            project_configurations=config
        )

        hostname = init.get_current_hostname()

        assert hostname is None


class TestGetEngine:
    """Test get_engine method."""

    @patch('pyfiles.hyperion_core.sidecar_init.create_engine')
    def test_get_engine_creates_sqlalchemy_engine(self, mock_create_engine):
        """Test that get_engine creates SQLAlchemy engine and caches it in __init__."""
        from pyfiles.hyperion_core.sidecar_init import SidecarInit

        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'test_password'
        }

        init = SidecarInit(
            logger_config=MagicMock(),
            project_configurations=config
        )

        # Engine is now cached in __init__
        assert init.engine == mock_engine
        mock_create_engine.assert_called_once()

        # Verify connection string format
        call_args = mock_create_engine.call_args[0][0]
        assert 'mysql+pymysql://' in call_args
        assert 'root:test_password@localhost:9030' in call_args

    @patch('pyfiles.hyperion_core.sidecar_init.create_engine')
    def test_get_engine_sets_connection_options(self, mock_create_engine):
        """Test that get_engine sets proper connection options."""
        from pyfiles.hyperion_core.sidecar_init import SidecarInit

        mock_create_engine.return_value = MagicMock()

        config = {
            'query_server': 'db-host:9030',
            'username': 'user',
            'root_password': 'pass'
        }

        init = SidecarInit(
            logger_config=MagicMock(),
            project_configurations=config
        )

        init.get_engine()

        call_kwargs = mock_create_engine.call_args[1]
        assert call_kwargs['pool_pre_ping'] is True
        assert call_kwargs['pool_recycle'] == 3600
        assert 'connect_timeout' in call_kwargs['connect_args']


class TestCheckLeaderFE:
    """Test check_leader_fe method."""

    @patch.object(
        __import__('pyfiles.hyperion_core.sidecar_init', fromlist=['SidecarInit']).SidecarInit,
        'get_current_hostname'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.sidecar_init', fromlist=['SidecarInit']).SidecarInit,
        'get_engine'
    )
    def test_check_leader_fe_returns_true_when_leader(self, mock_engine, mock_hostname):
        """Test returns True when current node is the leader."""
        from pyfiles.hyperion_core.sidecar_init import SidecarInit

        mock_hostname.return_value = 'fe-node-1'

        # Mock SHOW FRONTENDS result
        mock_result = [
            {'IP': 'fe-node-1', 'Role': 'LEADER'},
            {'IP': 'fe-node-2', 'Role': 'FOLLOWER'}
        ]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.mappings.return_value.all.return_value = mock_result
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        init = SidecarInit(
            logger_config=MagicMock(),
            project_configurations=config
        )

        result = init.check_leader_fe()

        assert result is True

    @patch.object(
        __import__('pyfiles.hyperion_core.sidecar_init', fromlist=['SidecarInit']).SidecarInit,
        'get_current_hostname'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.sidecar_init', fromlist=['SidecarInit']).SidecarInit,
        'get_engine'
    )
    def test_check_leader_fe_returns_false_when_follower(self, mock_engine, mock_hostname):
        """Test returns False when current node is a follower."""
        from pyfiles.hyperion_core.sidecar_init import SidecarInit

        mock_hostname.return_value = 'fe-node-2'

        mock_result = [
            {'IP': 'fe-node-1', 'Role': 'LEADER'},
            {'IP': 'fe-node-2', 'Role': 'FOLLOWER'}
        ]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.mappings.return_value.all.return_value = mock_result
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        init = SidecarInit(
            logger_config=MagicMock(),
            project_configurations=config
        )

        result = init.check_leader_fe()

        assert result is False

    @patch.object(
        __import__('pyfiles.hyperion_core.sidecar_init', fromlist=['SidecarInit']).SidecarInit,
        'get_current_hostname'
    )
    def test_check_leader_fe_returns_false_when_hostname_fails(self, mock_hostname):
        """Test returns False when hostname lookup fails."""
        from pyfiles.hyperion_core.sidecar_init import SidecarInit

        mock_hostname.return_value = None

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        init = SidecarInit(
            logger_config=MagicMock(),
            project_configurations=config
        )

        result = init.check_leader_fe()

        assert result is False

    @patch.object(
        __import__('pyfiles.hyperion_core.sidecar_init', fromlist=['SidecarInit']).SidecarInit,
        'get_current_hostname'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.sidecar_init', fromlist=['SidecarInit']).SidecarInit,
        'get_engine'
    )
    def test_check_leader_fe_returns_false_when_engine_fails(self, mock_engine, mock_hostname):
        """Test returns False when engine is not available."""
        from pyfiles.hyperion_core.sidecar_init import SidecarInit

        mock_hostname.return_value = 'fe-node-1'
        mock_engine.return_value = None

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        init = SidecarInit(
            logger_config=MagicMock(),
            project_configurations=config
        )

        result = init.check_leader_fe()

        assert result is False

    @patch.object(
        __import__('pyfiles.hyperion_core.sidecar_init', fromlist=['SidecarInit']).SidecarInit,
        'get_current_hostname'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.sidecar_init', fromlist=['SidecarInit']).SidecarInit,
        'get_engine'
    )
    def test_check_leader_fe_returns_false_on_sqlalchemy_error(self, mock_engine, mock_hostname):
        """Test returns False when SQLAlchemy error occurs."""
        from pyfiles.hyperion_core.sidecar_init import SidecarInit
        from sqlalchemy.exc import SQLAlchemyError

        mock_hostname.return_value = 'fe-node-1'
        mock_engine.return_value.connect.side_effect = SQLAlchemyError("Connection failed")

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        init = SidecarInit(
            logger_config=MagicMock(),
            project_configurations=config
        )

        result = init.check_leader_fe()

        assert result is False

    @patch.object(
        __import__('pyfiles.hyperion_core.sidecar_init', fromlist=['SidecarInit']).SidecarInit,
        'get_current_hostname'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.sidecar_init', fromlist=['SidecarInit']).SidecarInit,
        'get_engine'
    )
    def test_check_leader_fe_returns_false_when_not_in_list(self, mock_engine, mock_hostname):
        """Test returns False when current hostname not in frontend list."""
        from pyfiles.hyperion_core.sidecar_init import SidecarInit

        mock_hostname.return_value = 'fe-node-3'  # Not in the list

        mock_result = [
            {'IP': 'fe-node-1', 'Role': 'LEADER'},
            {'IP': 'fe-node-2', 'Role': 'FOLLOWER'}
        ]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.mappings.return_value.all.return_value = mock_result
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        init = SidecarInit(
            logger_config=MagicMock(),
            project_configurations=config
        )

        result = init.check_leader_fe()

        assert result is False
