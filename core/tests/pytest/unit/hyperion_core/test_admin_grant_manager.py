"""Unit tests for AdminGrantManager class."""
import os
from unittest.mock import MagicMock, patch


class TestAdminGrantManagerInitialization:
    """Test AdminGrantManager initialization."""

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'test_admin_role',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log',
        'LOG_LEVEL': 'DEBUG'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    def test_initialization_sets_parameters(self, mock_logger):
        """Test that initialization sets all parameters from env vars."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()

        manager = AdminGrantManager()

        assert 'localhost:9030' in manager.db_url
        assert manager.admin_role == 'test_admin_role'
        assert manager.log_file_path == '/var/log/fe_audit.log'
        assert manager.max_retries == 3


class TestExtractDatabases:
    """Test _extract_databases method."""

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    def test_extract_databases_bare_identifier(self, mock_logger):
        """Test extracting database name from bare identifier."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        line = "Stmt=CREATE DATABASE test_database|Digest=abc123"
        databases = manager._extract_databases(line)

        assert 'test_database' in databases

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    def test_extract_databases_backticked(self, mock_logger):
        """Test extracting database name from backticked identifier."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        line = "Stmt=CREATE DATABASE `my_database`|Digest=abc123"
        databases = manager._extract_databases(line)

        assert 'my_database' in databases

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    def test_extract_databases_if_not_exists(self, mock_logger):
        """Test extracting database name with IF NOT EXISTS clause."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        line = "Stmt=CREATE DATABASE IF NOT EXISTS new_db|Digest=abc123"
        databases = manager._extract_databases(line)

        assert 'new_db' in databases

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    def test_extract_databases_double_quoted(self, mock_logger):
        """Test extracting database name from double-quoted identifier."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        line = 'Stmt=CREATE DATABASE "my_database"|Digest=abc123'
        databases = manager._extract_databases(line)

        assert 'my_database' in databases

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    def test_extract_databases_single_quoted(self, mock_logger):
        """Test extracting database name from single-quoted identifier."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        line = "Stmt=CREATE DATABASE 'my_database'|Digest=abc123"
        databases = manager._extract_databases(line)

        assert 'my_database' in databases

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    def test_extract_databases_returns_empty_for_non_create(self, mock_logger):
        """Test returns empty list for non-CREATE DATABASE statements."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        line = "Stmt=SELECT * FROM some_table|Digest=abc123"
        databases = manager._extract_databases(line)

        assert databases == []


class TestGrantPrivileges:
    """Test _grant_privileges method."""

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    def test_grant_privileges_hyperion_database(self, mock_logger):
        """Test grants SELECT for hyperion databases."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        mock_conn = MagicMock()

        result = manager._grant_privileges('hyperion_patient_db', mock_conn)

        assert result is True
        # Should have called execute multiple times for SELECT grants
        assert mock_conn.execute.call_count >= 1

        # Extract SQL from TextClause objects - text() wraps SQL strings
        # Access the text content via the .text attribute of TextClause
        sql_statements = []
        for call in mock_conn.execute.call_args_list:
            text_clause = call[0][0]  # First positional argument
            sql_statements.append(str(text_clause.text) if hasattr(text_clause, 'text') else str(text_clause))

        all_sql = ' '.join(sql_statements)
        assert 'SELECT' in all_sql
        assert 'GRANT ALL' not in all_sql  # Should NOT have ALL grants for hyperion databases

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    def test_grant_privileges_non_hyperion_database(self, mock_logger):
        """Test grants ALL for non-hyperion databases."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        mock_conn = MagicMock()

        result = manager._grant_privileges('customer_database', mock_conn)

        assert result is True
        # Extract SQL from TextClause objects
        sql_statements = []
        for call in mock_conn.execute.call_args_list:
            text_clause = call[0][0]  # First positional argument
            sql_statements.append(str(text_clause.text) if hasattr(text_clause, 'text') else str(text_clause))

        all_sql = ' '.join(sql_statements)
        assert 'GRANT ALL' in all_sql

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    def test_grant_privileges_skips_audit_database(self, mock_logger):
        """Test skips audit-related databases."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        mock_conn = MagicMock()

        result = manager._grant_privileges('hyperion_audit_db', mock_conn)

        assert result is True
        mock_conn.execute.assert_not_called()

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    def test_grant_privileges_skips_portal_database(self, mock_logger):
        """Test skips portal-related databases."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        mock_conn = MagicMock()

        result = manager._grant_privileges('hyperion_portal_db', mock_conn)

        assert result is True
        mock_conn.execute.assert_not_called()


class TestProcessDatabases:
    """Test _process_databases method."""

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    @patch('pyfiles.hyperion_core.admin_grant_manager.create_engine')
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._grant_privileges')
    def test_process_databases_success(self, mock_grant, mock_create_engine, mock_logger):
        """Test successful processing of multiple databases."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        mock_grant.return_value = True

        mock_conn = MagicMock()
        mock_engine = mock_create_engine.return_value
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        manager = AdminGrantManager()
        manager._process_databases(['db1', 'db2', 'db3'])

        assert mock_grant.call_count == 3

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    @patch('pyfiles.hyperion_core.admin_grant_manager.create_engine')
    def test_process_databases_retries_on_error(self, mock_create_engine, mock_logger):
        """Test retries on database error."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager
        from sqlalchemy.exc import SQLAlchemyError

        mock_logger.return_value = MagicMock()

        mock_engine = mock_create_engine.return_value

        # First two calls to engine.begin() raise SQLAlchemyError, third succeeds
        mock_context = MagicMock()
        mock_context.__enter__.return_value = MagicMock()
        mock_context.__exit__.return_value = False
        mock_engine.begin.side_effect = [
            SQLAlchemyError("Connection failed"),
            SQLAlchemyError("Connection failed"),
            mock_context
        ]

        manager = AdminGrantManager()

        with patch.object(manager, '_grant_privileges', return_value=True):
            with patch('time.sleep'):  # Skip actual sleep
                manager._process_databases(['test_db'])

        # Should have tried 3 times
        assert mock_engine.begin.call_count == 3


class TestSetupLogger:
    """Test _setup_logger method."""

    def test_setup_logger_creates_logger(self, tmp_path):
        """Test that logger is created with correct settings."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        log_file = tmp_path / "test.log"

        logger = AdminGrantManager._setup_logger(
            name='test_logger',
            filename=str(log_file),
            level='DEBUG',
            rotate=False
        )

        assert logger is not None
        assert logger.level == 10  # DEBUG level

    def test_setup_logger_with_rotation(self, tmp_path):
        """Test that logger is created with rotation when requested."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        log_file = tmp_path / "test_rotate.log"

        logger = AdminGrantManager._setup_logger(
            name='test_rotate_logger',
            filename=str(log_file),
            level='INFO',
            rotate=True
        )

        assert logger is not None


class TestMain:
    """Test main method."""

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    @patch('pyfiles.hyperion_core.admin_grant_manager.create_engine')
    def test_main_calls_startup_sync_and_processes_lines(self, mock_create_engine, mock_logger):
        """Test that main() calls _startup_sync then processes lines from _tail_follow."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        # _tail_follow yields one CREATE DATABASE line then stops
        def fake_tail_follow(path):
            yield ('Stmt=CREATE DATABASE test_db|Digest=abc123', False)

        with patch.object(manager, '_startup_sync') as mock_startup_sync, \
             patch.object(manager, '_tail_follow', side_effect=fake_tail_follow), \
             patch.object(manager, '_process_databases') as mock_process, \
             patch.object(manager, '_touch_health_file'), \
             patch('os.remove'):

            manager.main()

            mock_startup_sync.assert_called_once()
            mock_process.assert_called_once_with(['test_db'])

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    @patch('pyfiles.hyperion_core.admin_grant_manager.create_engine')
    def test_main_calls_post_rotation_sync(self, mock_create_engine, mock_logger):
        """Test that main() calls _startup_sync again when rotation is detected."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        def fake_tail_follow(path):
            yield ('', True)   # rotation signal

        with patch.object(manager, '_startup_sync') as mock_startup_sync, \
             patch.object(manager, '_tail_follow', side_effect=fake_tail_follow), \
             patch.object(manager, '_process_databases'), \
             patch.object(manager, '_touch_health_file'), \
             patch('os.remove'):

            manager.main()

            # Called once on startup + once post-rotation
            assert mock_startup_sync.call_count == 2


class TestTailFollow:
    """Test _tail_follow generator method."""

    ENV = {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    }

    def _make_manager(self, mock_logger, mock_create_engine):
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager
        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()
        return manager

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    @patch('pyfiles.hyperion_core.admin_grant_manager.create_engine')
    def test_tail_follow_yields_new_lines(self, mock_engine, mock_logger):
        """Test that new lines read from file are yielded."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        log_content = 'line one\n'
        mock_file = MagicMock()
        mock_file.readline.side_effect = [log_content, '', '', '', '', '']
        mock_file.fileno.return_value = 5

        lines_yielded = []

        def stop_after_first(signum, frame):
            manager._shutdown = True

        with patch('builtins.open', return_value=mock_file), \
             patch('os.fstat') as mock_fstat, \
             patch.object(manager, '_get_file_inode', return_value=42), \
             patch('time.sleep', side_effect=lambda _: setattr(manager, '_shutdown', True)):

            mock_stat = MagicMock()
            mock_stat.st_ino = 42
            mock_stat.st_size = 100
            mock_fstat.return_value = mock_stat

            manager._shutdown = False
            for line, rotated in manager._tail_follow('/var/log/fe_audit.log'):
                lines_yielded.append((line, rotated))
                manager._shutdown = True
                break

        assert len(lines_yielded) == 1
        assert lines_yielded[0] == ('line one', False)

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    @patch('pyfiles.hyperion_core.admin_grant_manager.create_engine')
    def test_tail_follow_waits_when_file_not_found(self, mock_engine, mock_logger):
        """Test that tail_follow waits and retries when file is not found."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        call_count = [0]

        def open_side_effect(path, mode='r'):
            call_count[0] += 1
            if call_count[0] == 1:
                raise FileNotFoundError("File not found")
            # Shut down after first retry
            manager._shutdown = True
            raise FileNotFoundError("File not found")

        with patch('builtins.open', side_effect=open_side_effect), \
             patch('time.sleep'):

            manager._shutdown = False
            lines = list(manager._tail_follow('/var/log/fe_audit.log'))

        # Generator should have tried to open the file
        assert call_count[0] >= 1
        # No lines yielded (file never opened successfully)
        assert lines == []

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    @patch('pyfiles.hyperion_core.admin_grant_manager.create_engine')
    def test_tail_follow_detects_rotation(self, mock_engine, mock_logger):
        """Test that tail_follow detects inode change and yields rotation signal."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        mock_file = MagicMock()
        # readline returns empty string (idle), triggering rotation check
        mock_file.readline.return_value = ''
        mock_file.fileno.return_value = 5

        original_inode = 100
        new_inode = 200

        def get_inode_side_effect(path):
            return new_inode  # Different from fd inode → rotation

        yielded = []

        with patch('builtins.open', return_value=mock_file), \
             patch('os.fstat') as mock_fstat, \
             patch.object(manager, '_get_file_inode', side_effect=get_inode_side_effect), \
             patch('time.sleep'):

            fd_stat = MagicMock()
            fd_stat.st_ino = original_inode
            fd_stat.st_size = 0
            mock_fstat.return_value = fd_stat

            manager._shutdown = False

            sleep_calls = [0]
            def fake_sleep(secs):
                sleep_calls[0] += 1
                if sleep_calls[0] > 5:
                    manager._shutdown = True

            with patch('time.sleep', side_effect=fake_sleep):
                for line, rotated in manager._tail_follow('/var/log/fe_audit.log'):
                    yielded.append((line, rotated))
                    manager._shutdown = True
                    break

        # Should have yielded the rotation signal (empty line, rotated=True)
        assert any(rotated for _, rotated in yielded)

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    @patch('pyfiles.hyperion_core.admin_grant_manager.create_engine')
    def test_tail_follow_seeks_on_truncation(self, mock_engine, mock_logger):
        """Test that tail_follow seeks to 0 when file is truncated."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        mock_file = MagicMock()
        mock_file.readline.return_value = ''
        mock_file.fileno.return_value = 5
        mock_file.tell.return_value = 1000  # Current position > file size

        seek_calls = []

        def fake_seek(*args):
            seek_calls.append(args[0])

        mock_file.seek = fake_seek

        with patch('builtins.open', return_value=mock_file), \
             patch('os.fstat') as mock_fstat, \
             patch.object(manager, '_get_file_inode', return_value=42):

            call_count = [0]

            def fake_fstat(fd):
                call_count[0] += 1
                stat = MagicMock()
                stat.st_ino = 42
                if call_count[0] <= 1:
                    # First call: seeking to end
                    stat.st_size = 0
                else:
                    # Subsequent calls: size < position (truncation)
                    stat.st_size = 10  # Less than tell() = 1000
                return stat

            mock_fstat.side_effect = fake_fstat

            sleep_calls = [0]
            def fake_sleep(secs):
                sleep_calls[0] += 1
                if sleep_calls[0] >= 6:
                    manager._shutdown = True

            manager._shutdown = False
            with patch('time.sleep', side_effect=fake_sleep):
                list(manager._tail_follow('/var/log/fe_audit.log'))

        # seek(0) should have been called for truncation detection
        assert 0 in seek_calls


class TestStartupSync:
    """Test _startup_sync method."""

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    @patch('pyfiles.hyperion_core.admin_grant_manager.create_engine')
    def test_startup_sync_calls_process_databases(self, mock_create_engine, mock_logger):
        """Test _startup_sync queries SHOW DATABASES and calls _process_databases."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()

        mock_conn = MagicMock()
        # Simulate SHOW DATABASES returning rows
        mock_result = [('user_db',), ('another_db',), ('_statistics_',)]
        mock_conn.execute.return_value = iter(mock_result)

        mock_engine = mock_create_engine.return_value
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        manager = AdminGrantManager()

        with patch.object(manager, '_process_databases') as mock_process:
            manager._startup_sync()

            # Should call _process_databases with non-system databases
            mock_process.assert_called_once()
            args = mock_process.call_args[0][0]
            assert 'user_db' in args
            assert 'another_db' in args
            # System databases should be filtered out
            assert '_statistics_' not in args

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    @patch('pyfiles.hyperion_core.admin_grant_manager.create_engine')
    def test_startup_sync_handles_empty_database_list(self, mock_create_engine, mock_logger):
        """Test _startup_sync handles empty database list gracefully."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()

        mock_conn = MagicMock()
        mock_conn.execute.return_value = iter([])

        mock_engine = mock_create_engine.return_value
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        manager = AdminGrantManager()

        with patch.object(manager, '_process_databases') as mock_process:
            manager._startup_sync()  # Should not raise
            mock_process.assert_not_called()


class TestGetFileInode:
    """Test _get_file_inode method."""

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    @patch('pyfiles.hyperion_core.admin_grant_manager.create_engine')
    def test_get_file_inode_file_not_found_returns_none(self, mock_engine, mock_logger):
        """Test _get_file_inode returns None when file is not found."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        with patch('os.stat', side_effect=FileNotFoundError("No such file")):
            result = manager._get_file_inode('/nonexistent/path')

        assert result is None

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    @patch('pyfiles.hyperion_core.admin_grant_manager.create_engine')
    def test_get_file_inode_oserror_returns_none(self, mock_engine, mock_logger):
        """Test _get_file_inode returns None on OSError."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        with patch('os.stat', side_effect=OSError("Permission denied")):
            result = manager._get_file_inode('/restricted/path')

        assert result is None

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    @patch('pyfiles.hyperion_core.admin_grant_manager.create_engine')
    def test_get_file_inode_returns_inode_number(self, mock_engine, mock_logger):
        """Test _get_file_inode returns correct inode number."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        mock_stat_result = MagicMock()
        mock_stat_result.st_ino = 12345

        with patch('os.stat', return_value=mock_stat_result):
            result = manager._get_file_inode('/var/log/fe_audit.log')

        assert result == 12345


class TestTouchHealthFile:
    """Test _touch_health_file method."""

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    @patch('pyfiles.hyperion_core.admin_grant_manager.create_engine')
    def test_touch_health_file_oserror_is_suppressed(self, mock_engine, mock_logger):
        """Test _touch_health_file suppresses OSError gracefully."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager
        from pathlib import Path

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        with patch.object(Path, 'touch', side_effect=OSError("Permission denied")):
            # Should not raise
            manager._touch_health_file()

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    @patch('pyfiles.hyperion_core.admin_grant_manager.create_engine')
    def test_touch_health_file_success(self, mock_engine, mock_logger, tmp_path):
        """Test _touch_health_file creates the health file."""
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()
        health_file = tmp_path / 'healthy'
        manager.health_check_file = str(health_file)

        manager._touch_health_file()

        assert health_file.exists()


class TestHandleSignal:
    """Test _handle_signal method."""

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    @patch('pyfiles.hyperion_core.admin_grant_manager.create_engine')
    def test_handle_signal_sets_shutdown_flag(self, mock_engine, mock_logger):
        """Test that _handle_signal sets _shutdown to True."""
        import signal as signal_mod
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        assert manager._shutdown is False

        manager._handle_signal(signal_mod.SIGTERM, None)

        assert manager._shutdown is True

    @patch.dict(os.environ, {
        'SILVER_LAYER_QUERY_SERVER': 'localhost:9030',
        'SILVER_LAYER_ROOT_USERNAME': 'root',
        'SILVER_LAYER_ROOT_PASSWORD': 'password',
        'ADMIN_ROLE': 'admin',
        'FE_LOG_FILE_PATH': '/var/log/fe_audit.log',
        'FE_LOG_PATH': '/var/log'
    })
    @patch('pyfiles.hyperion_core.admin_grant_manager.AdminGrantManager._setup_logger')
    @patch('pyfiles.hyperion_core.admin_grant_manager.create_engine')
    def test_handle_sigint_sets_shutdown_flag(self, mock_engine, mock_logger):
        """Test that _handle_signal handles SIGINT."""
        import signal as signal_mod
        from pyfiles.hyperion_core.admin_grant_manager import AdminGrantManager

        mock_logger.return_value = MagicMock()
        manager = AdminGrantManager()

        manager._handle_signal(signal_mod.SIGINT, None)

        assert manager._shutdown is True
