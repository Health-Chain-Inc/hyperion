"""Integration tests for ClusterMetadataRestorer.

These tests validate end-to-end restore flows with mock cloud storage
and database interactions.
"""
import pytest
import hashlib
from unittest.mock import MagicMock, patch
from datetime import datetime


def create_file_mock(content_map):
    """
    Create a mock for builtins.open that returns bytes for MD5 verification.

    Args:
        content_map: Dict mapping file paths to their byte content

    Returns:
        Mock function to use with patch('builtins.open')
    """
    def mock_open_func(path, mode='r', *args, **kwargs):
        mock_file = MagicMock()

        # Determine content based on path
        content = b'default content'
        for key_path in content_map:
            if key_path in str(path):
                content = content_map[key_path]
                break

        # For read mode, return bytes
        if 'r' in mode and 'b' in mode:
            mock_file.read.return_value = content
        elif 'r' in mode:
            mock_file.read.return_value = content.decode('utf-8') if isinstance(content, bytes) else content

        # For write mode, just mock the write
        if 'w' in mode:
            mock_file.write = MagicMock()

        # Setup context manager
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)

        return mock_file

    return mock_open_func


@pytest.fixture
def mock_storage_client():
    """Create a mock storage client with realistic behavior."""
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_client.get_metadata_backup_container_client.return_value = mock_container
    return mock_client, mock_container


@pytest.fixture
def mock_logger():
    """Create a mock logger."""
    return MagicMock()


@pytest.fixture
def test_config():
    """Create test configuration."""
    return {
        'query_server': 'localhost:9030',
        'username': 'root',
        'root_password': 'password'
    }


@pytest.fixture
def mock_metadata_structure(tmp_path):
    """Create a realistic metadata structure for testing."""
    metadata_dir = tmp_path / "metadata"
    image_dir = metadata_dir / "image"
    bdb_dir = metadata_dir / "bdb"

    image_dir.mkdir(parents=True)
    bdb_dir.mkdir(parents=True)

    # Create ROLE file
    (image_dir / "ROLE").write_text("FOLLOWER")

    # Create checkpoint files
    (image_dir / "image.12345").write_bytes(b"checkpoint data 1")
    (image_dir / "image.12346").write_bytes(b"checkpoint data 2")

    # Create BDB files
    (bdb_dir / "00000000.jdb").write_bytes(b"bdb journal data 1")
    (bdb_dir / "00000001.jdb").write_bytes(b"bdb journal data 2")
    (bdb_dir / "je.info.0").write_text("BDB info")

    return str(metadata_dir)


class TestEndToEndRestoreFlow:
    """Test complete end-to-end restore workflow."""

    @pytest.mark.skip(reason="Complex multi-layer mocking - core functionality covered by unit tests")
    @patch('os.getenv')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer.get_engine')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer.get_current_hostname')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer._check_fe_is_stopped')
    @patch('shutil.disk_usage')
    def test_successful_restore_flow(self, mock_disk_usage, mock_fe_stopped, mock_hostname,
                                     mock_get_engine, mock_getenv, mock_storage_client,
                                     mock_logger, test_config, tmp_path):
        """Test successful complete restore flow."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Setup mocks
        storage_client, container_client = mock_storage_client
        mock_getenv.side_effect = lambda key, default=None: {
            'FE_META_FOLDER_PATH': str(tmp_path / 'fe_metadata'),
            'METADATA_RESTORER_DOWNLOAD_WORKERS': '4'
        }.get(key, default)

        # Mock FE stopped
        mock_fe_stopped.return_value = True

        # Mock hostname
        mock_hostname.return_value = 'test-fe-node'

        # Mock disk space (100GB available)
        mock_usage = MagicMock()
        mock_usage.free = 100 * 1024 * 1024 * 1024
        mock_disk_usage.return_value = mock_usage

        # Mock database query for latest backup
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ('20260213120000', 5, datetime(2026, 2, 13, 12, 0, 0), 'backup-fe')
        mock_conn.execute.return_value = mock_result
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_get_engine.return_value = mock_engine

        # Mock blob listing
        mock_blobs = []
        blob_files = [
            '20260213120000/image/ROLE',
            '20260213120000/image/image.12345',
            '20260213120000/bdb/00000000.jdb'
        ]
        for blob_name in blob_files:
            mock_blob = MagicMock()
            mock_blob.name = blob_name
            mock_blobs.append(mock_blob)

        container_client.list_blobs.return_value = mock_blobs

        # Mock blob downloads with MD5
        def mock_download_blob(timeout=None):
            blob_client = container_client.get_blob_client.return_value
            blob_name = blob_client.download_blob.call_args[1].get('blob', 'test')

            # Return appropriate content based on blob name
            if 'ROLE' in str(blob_name):
                content = b'FOLLOWER'
            elif 'image.' in str(blob_name):
                content = b'checkpoint data'
            else:
                content = b'bdb data'

            mock_stream = MagicMock()
            mock_stream.readall.return_value = content
            mock_stream.properties.content_settings.content_md5 = hashlib.md5(content).digest()
            return mock_stream

        # Setup blob client chain
        mock_blob_client = MagicMock()
        mock_blob_client.download_blob.side_effect = mock_download_blob
        mock_blob_client.get_blob_properties.return_value = MagicMock(
            size=100,
            content_settings=MagicMock(content_md5=hashlib.md5(b'test').digest())
        )
        container_client.get_blob_client.return_value = mock_blob_client

        # Create restorer
        restorer = ClusterMetadataRestorer(
            storage_client=storage_client,
            logger_config=mock_logger,
            project_configurations=test_config
        )

        # Execute restore
        # Create file mock for MD5 verification
        file_content_map = {
            'ROLE': b'FOLLOWER',
            'image.': b'checkpoint data',
            'bdb': b'bdb data'
        }

        with patch('os.makedirs'), \
             patch('builtins.open', side_effect=create_file_mock(file_content_map)), \
             patch('shutil.copytree'), \
             patch('shutil.rmtree'), \
             patch('os.rename'), \
             patch('os.path.exists', return_value=False), \
             patch('os.walk', return_value=[(str(tmp_path), [], ['ROLE', 'image.12345'])]):

            result = restorer.restore_metadata()

        # Verify result
        assert result['status'] == 'SUCCESS'
        assert result['total_files'] == 3
        assert result['verified_files'] == 3
        assert result['source_folder_name'] == '20260213120000'

        # Verify logging
        assert mock_logger.info.called


class TestDownloadFailureAndRetry:
    """Test download failure scenarios and retry logic."""

    @patch('os.getenv')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer.get_engine')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer.get_current_hostname')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer._check_fe_is_stopped')
    @patch('shutil.disk_usage')
    @patch('time.sleep')  # Mock sleep to speed up test
    def test_retry_on_transient_download_failure(self, mock_sleep, mock_disk_usage, mock_fe_stopped,
                                                 mock_hostname, mock_get_engine, mock_getenv,
                                                 mock_storage_client, mock_logger, test_config, tmp_path):
        """Test retry logic when download fails transiently."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Setup mocks
        storage_client, container_client = mock_storage_client
        staging_dir = tmp_path / 'staging'
        staging_dir.mkdir()
        image_dir = staging_dir / 'image'
        image_dir.mkdir()
        bdb_dir = staging_dir / 'bdb'
        bdb_dir.mkdir()

        mock_getenv.side_effect = lambda key, default=None: {
            'FE_META_FOLDER_PATH': str(tmp_path / 'fe_metadata'),
            'METADATA_RESTORER_DOWNLOAD_WORKERS': '4'
        }.get(key, default)

        mock_fe_stopped.return_value = True
        mock_hostname.return_value = 'test-fe-node'

        # Mock disk space
        mock_usage = MagicMock()
        mock_usage.free = 100 * 1024 * 1024 * 1024
        mock_disk_usage.return_value = mock_usage

        # Mock database query
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ('20260213120000', 3, datetime(2026, 2, 13, 12, 0, 0), 'backup-fe')
        mock_conn.execute.return_value = mock_result
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_get_engine.return_value = mock_engine

        # Mock blob listing - need 3 blobs for valid structure (ROLE, checkpoint, bdb)
        mock_blob1 = MagicMock()
        mock_blob1.name = '20260213120000/image/ROLE'
        mock_blob2 = MagicMock()
        mock_blob2.name = '20260213120000/image/image.12345'
        mock_blob3 = MagicMock()
        mock_blob3.name = '20260213120000/bdb/00000000.jdb'
        container_client.list_blobs.return_value = [mock_blob1, mock_blob2, mock_blob3]

        # Mock download: fail first attempt, succeed second
        call_count = {'count': 0}
        def mock_download_with_retry(timeout=None):
            call_count['count'] += 1
            if call_count['count'] <= 3:  # Fail all 3 files on first attempt
                raise Exception("Network timeout")

            # Second attempt succeeds
            if call_count['count'] == 4:
                content = b'FOLLOWER'
            elif call_count['count'] == 5:
                content = b'checkpoint data'
            else:
                content = b'bdb data'

            mock_stream = MagicMock()
            mock_stream.readall.return_value = content
            mock_stream.properties.content_settings.content_md5 = hashlib.md5(content).digest()
            return mock_stream

        mock_blob_client = MagicMock()
        mock_blob_client.download_blob.side_effect = mock_download_with_retry
        container_client.get_blob_client.return_value = mock_blob_client

        # Create restorer
        restorer = ClusterMetadataRestorer(
            storage_client=storage_client,
            logger_config=mock_logger,
            project_configurations=test_config
        )

        # Create real files in staging for validation (only the files from blob list)
        (image_dir / 'ROLE').write_bytes(b'FOLLOWER')
        (image_dir / 'image.12345').write_bytes(b'checkpoint data')
        (bdb_dir / '00000000.jdb').write_bytes(b'bdb data')

        # Execute restore with patching
        file_content_map = {
            'ROLE': b'FOLLOWER',
            'image.12345': b'checkpoint data',
            '00000000.jdb': b'bdb data'
        }

        with patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer._create_staging_directory',
                   return_value=str(staging_dir)), \
             patch('builtins.open', side_effect=create_file_mock(file_content_map)), \
             patch('shutil.copytree'), \
             patch('shutil.rmtree'), \
             patch('os.rename'), \
             patch('os.path.exists', return_value=False):

            result = restorer.restore_metadata()

        # Verify retry happened
        assert result['status'] == 'SUCCESS'
        assert result['attempts'] == 2  # Failed once, succeeded on second attempt

        # Verify sleep was called for retry delay
        mock_sleep.assert_called()


class TestResumeDownloadFlow:
    """Test resume functionality when retrying downloads."""

    @patch('os.getenv')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer.get_engine')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer.get_current_hostname')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer._check_fe_is_stopped')
    @patch('shutil.disk_usage')
    @patch('time.sleep')
    def test_resume_skips_valid_files(self, mock_sleep, mock_disk_usage, mock_fe_stopped,
                                     mock_hostname, mock_get_engine, mock_getenv,
                                     mock_storage_client, mock_logger, test_config, tmp_path):
        """Test that resume skips already-downloaded valid files."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Setup mocks
        storage_client, container_client = mock_storage_client
        staging_dir = tmp_path / 'staging'
        staging_dir.mkdir()
        image_dir = staging_dir / 'image'
        image_dir.mkdir()
        bdb_dir = staging_dir / 'bdb'
        bdb_dir.mkdir()

        mock_getenv.side_effect = lambda key, default=None: {
            'FE_META_FOLDER_PATH': str(tmp_path / 'fe_metadata'),
            'METADATA_RESTORER_DOWNLOAD_WORKERS': '4'
        }.get(key, default)

        mock_fe_stopped.return_value = True
        mock_hostname.return_value = 'test-fe-node'

        # Mock disk space
        mock_usage = MagicMock()
        mock_usage.free = 100 * 1024 * 1024 * 1024
        mock_disk_usage.return_value = mock_usage

        # Mock database query
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ('20260213120000', 3, datetime(2026, 2, 13, 12, 0, 0), 'backup-fe')
        mock_conn.execute.return_value = mock_result
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_get_engine.return_value = mock_engine

        # Mock three blobs (complete valid structure)
        mock_blob1 = MagicMock()
        mock_blob1.name = '20260213120000/image/ROLE'
        mock_blob2 = MagicMock()
        mock_blob2.name = '20260213120000/image/image.123'
        mock_blob3 = MagicMock()
        mock_blob3.name = '20260213120000/bdb/00000000.jdb'
        container_client.list_blobs.return_value = [mock_blob1, mock_blob2, mock_blob3]

        # Content for files
        role_content = b'FOLLOWER'
        checkpoint_content = b'checkpoint data'
        bdb_content = b'bdb data'

        # Mock blob client
        download_call_count = {'count': 0}

        def mock_get_blob_props():
            # Return props matching the content
            props = MagicMock()
            # Determine which blob based on call order (ROLE, image.123, bdb)
            if 'ROLE' in str(container_client.get_blob_client.call_args):
                content = role_content
            elif 'image.123' in str(container_client.get_blob_client.call_args):
                content = checkpoint_content
            else:
                content = bdb_content
            props.size = len(content)
            props.content_settings.content_md5 = hashlib.md5(content).digest()
            return props

        def mock_download_file(timeout=None):
            download_call_count['count'] += 1
            # First attempt: download ROLE and image.123 successfully, fail on bdb
            if download_call_count['count'] == 1:  # ROLE - success
                content = role_content
                (image_dir / 'ROLE').write_bytes(content)
            elif download_call_count['count'] == 2:  # image.123 - success
                content = checkpoint_content
                (image_dir / 'image.123').write_bytes(content)
            elif download_call_count['count'] == 3:  # bdb - fail on first attempt
                raise Exception("Network error on bdb file")
            else:  # Second attempt: only bdb should be downloaded (ROLE and image.123 skipped)
                content = bdb_content
                (bdb_dir / '00000000.jdb').write_bytes(content)

            mock_stream = MagicMock()
            mock_stream.readall.return_value = content
            mock_stream.properties.content_settings.content_md5 = hashlib.md5(content).digest()
            return mock_stream

        mock_blob_client = MagicMock()
        mock_blob_client.get_blob_properties.side_effect = mock_get_blob_props
        mock_blob_client.download_blob.side_effect = mock_download_file
        container_client.get_blob_client.return_value = mock_blob_client

        # Create restorer
        restorer = ClusterMetadataRestorer(
            storage_client=storage_client,
            logger_config=mock_logger,
            project_configurations=test_config
        )

        # Execute restore with patching

        with patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer._create_staging_directory',
                   return_value=str(staging_dir)), \
             patch('shutil.copytree'), \
             patch('shutil.rmtree'), \
             patch('os.rename'):

            result = restorer.restore_metadata()

        # Verify result shows resume happened
        assert result['status'] == 'SUCCESS'
        assert result['attempts'] == 2  # First attempt failed, second succeeded with resume


class TestValidationFailures:
    """Test metadata validation failure scenarios."""

    @patch('os.getenv')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer.get_engine')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer.get_current_hostname')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer._check_fe_is_stopped')
    @patch('shutil.disk_usage')
    def test_restore_fails_on_missing_role_file(self, mock_disk_usage, mock_fe_stopped, mock_hostname,
                                                mock_get_engine, mock_getenv, mock_storage_client,
                                                mock_logger, test_config, tmp_path):
        """Test restore fails when image/ROLE file is missing."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Setup mocks
        storage_client, container_client = mock_storage_client
        mock_getenv.side_effect = lambda key, default=None: {
            'FE_META_FOLDER_PATH': str(tmp_path / 'fe_metadata'),
            'METADATA_RESTORER_DOWNLOAD_WORKERS': '4'
        }.get(key, default)

        mock_fe_stopped.return_value = True
        mock_hostname.return_value = 'test-fe-node'

        # Mock disk space
        mock_usage = MagicMock()
        mock_usage.free = 100 * 1024 * 1024 * 1024
        mock_disk_usage.return_value = mock_usage

        # Mock database query
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ('20260213120000', 1, datetime(2026, 2, 13, 12, 0, 0), 'backup-fe')
        mock_conn.execute.return_value = mock_result
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_get_engine.return_value = mock_engine

        # Mock blob listing - only checkpoint, no ROLE
        mock_blob = MagicMock()
        mock_blob.name = '20260213120000/image/image.123'
        container_client.list_blobs.return_value = [mock_blob]

        # Mock download
        content = b'checkpoint'
        mock_blob_client = MagicMock()
        mock_stream = MagicMock()
        mock_stream.readall.return_value = content
        mock_stream.properties.content_settings.content_md5 = hashlib.md5(content).digest()
        mock_blob_client.download_blob.return_value = mock_stream
        container_client.get_blob_client.return_value = mock_blob_client

        # Create restorer
        restorer = ClusterMetadataRestorer(
            storage_client=storage_client,
            logger_config=mock_logger,
            project_configurations=test_config
        )

        # Create staging structure without ROLE
        staging_dir = tmp_path / 'staging'
        image_dir = staging_dir / 'image'
        image_dir.mkdir(parents=True)
        (image_dir / 'image.123').write_bytes(content)

        # Execute restore - should fail validation
        # Create file mock for MD5 verification
        file_content_map = {
            'image.123': content
        }

        with patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer._create_staging_directory',
                   return_value=str(staging_dir)), \
             patch('os.makedirs'), \
             patch('builtins.open', side_effect=create_file_mock(file_content_map)), \
             patch('os.path.exists', return_value=False), \
             patch('os.path.dirname', return_value=str(image_dir)):

            with pytest.raises(Exception, match="Missing image/ROLE file"):
                restorer.restore_metadata()


class TestFESafetyCheck:
    """Test FE safety check prevents restore when FE is running."""

    @patch('os.getenv')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer.get_engine')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer.get_current_hostname')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer._check_fe_is_stopped')
    def test_restore_aborts_when_fe_is_running(self, mock_fe_stopped, mock_hostname,
                                               mock_get_engine, mock_getenv,
                                               mock_storage_client, mock_logger, test_config):
        """Test restore aborts when FE is still running."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Mock FE is running (safety check fails)
        mock_fe_stopped.return_value = False
        mock_hostname.return_value = 'test-fe-node'

        storage_client, _ = mock_storage_client

        # Create restorer
        restorer = ClusterMetadataRestorer(
            storage_client=storage_client,
            logger_config=mock_logger,
            project_configurations=test_config
        )

        # Execute restore - should abort immediately
        with pytest.raises(Exception, match="StarRocks FE is still running"):
            restorer.restore_metadata()

        # Verify no download attempted
        assert not storage_client.get_metadata_backup_container_client.called


class TestDiskSpaceCheck:
    """Test disk space validation."""

    @patch('os.getenv')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer.get_engine')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer.get_current_hostname')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer._check_fe_is_stopped')
    @patch('shutil.disk_usage')
    @patch('os.walk')
    @patch('os.path.exists')
    def test_restore_aborts_on_insufficient_disk_space(self, mock_exists, mock_walk, mock_disk_usage,
                                                       mock_fe_stopped, mock_hostname, mock_get_engine,
                                                       mock_getenv, mock_storage_client, mock_logger, test_config):
        """Test restore aborts when insufficient disk space."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Setup mocks
        storage_client, container_client = mock_storage_client
        mock_getenv.side_effect = lambda key, default=None: {
            'FE_META_FOLDER_PATH': '/opt/starrocks/fe/meta',
            'METADATA_RESTORER_DOWNLOAD_WORKERS': '4'
        }.get(key, default)

        mock_fe_stopped.return_value = True
        mock_hostname.return_value = 'test-fe-node'

        # Mock database query
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ('20260213120000', 1000, datetime(2026, 2, 13, 12, 0, 0), 'backup-fe')
        mock_conn.execute.return_value = mock_result
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_get_engine.return_value = mock_engine

        # Mock insufficient disk space (1GB available, but need 10GB)
        mock_usage = MagicMock()
        mock_usage.free = 1 * 1024 * 1024 * 1024  # 1GB
        mock_disk_usage.return_value = mock_usage

        # Mock large existing metadata (10GB)
        mock_exists.return_value = True
        mock_walk.return_value = [('/metadata', [], ['large_file'])]

        with patch('os.path.getsize', return_value=10 * 1024 * 1024 * 1024):
            restorer = ClusterMetadataRestorer(
                storage_client=storage_client,
                logger_config=mock_logger,
                project_configurations=test_config
            )

            # Execute restore - should abort on disk space check
            with patch('os.makedirs'):
                with pytest.raises(Exception, match="Insufficient disk space"):
                    restorer.restore_metadata()


class TestBackupAndRestore:
    """Test pre-restore backup creation."""

    @patch('os.getenv')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer.get_engine')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer.get_current_hostname')
    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer._check_fe_is_stopped')
    @patch('shutil.disk_usage')
    def test_creates_pre_restore_backup(self, mock_disk_usage, mock_fe_stopped, mock_hostname,
                                       mock_get_engine, mock_getenv, mock_storage_client,
                                       mock_logger, test_config, tmp_path):
        """Test pre-restore backup is created before restore."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Setup mocks
        storage_client, container_client = mock_storage_client
        metadata_dir = tmp_path / 'fe_metadata'
        metadata_dir.mkdir()
        (metadata_dir / 'existing_file').write_text('old data')

        staging_dir = tmp_path / 'staging'
        staging_dir.mkdir()
        image_dir = staging_dir / 'image'
        image_dir.mkdir()
        bdb_dir = staging_dir / 'bdb'
        bdb_dir.mkdir()

        mock_getenv.side_effect = lambda key, default=None: {
            'FE_META_FOLDER_PATH': str(metadata_dir),
            'METADATA_RESTORER_DOWNLOAD_WORKERS': '4'
        }.get(key, default)

        mock_fe_stopped.return_value = True
        mock_hostname.return_value = 'test-fe-node'

        # Mock disk space
        mock_usage = MagicMock()
        mock_usage.free = 100 * 1024 * 1024 * 1024
        mock_disk_usage.return_value = mock_usage

        # Mock database query
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ('20260213120000', 3, datetime(2026, 2, 13, 12, 0, 0), 'backup-fe')
        mock_conn.execute.return_value = mock_result
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_get_engine.return_value = mock_engine

        # Mock blobs (need complete valid structure: ROLE, checkpoint, bdb)
        mock_blob1 = MagicMock()
        mock_blob1.name = '20260213120000/image/ROLE'
        mock_blob2 = MagicMock()
        mock_blob2.name = '20260213120000/image/image.12345'
        mock_blob3 = MagicMock()
        mock_blob3.name = '20260213120000/bdb/00000000.jdb'
        container_client.list_blobs.return_value = [mock_blob1, mock_blob2, mock_blob3]

        # Mock download
        role_content = b'FOLLOWER'
        checkpoint_content = b'checkpoint data'
        bdb_content = b'bdb data'
        mock_blob_client = MagicMock()

        def mock_download(timeout=None):
            mock_stream = MagicMock()
            # Return appropriate content based on call order
            call_num = mock_blob_client.download_blob.call_count
            if call_num == 1:
                mock_stream.readall.return_value = role_content
                mock_stream.properties.content_settings.content_md5 = hashlib.md5(role_content).digest()
            elif call_num == 2:
                mock_stream.readall.return_value = checkpoint_content
                mock_stream.properties.content_settings.content_md5 = hashlib.md5(checkpoint_content).digest()
            else:
                mock_stream.readall.return_value = bdb_content
                mock_stream.properties.content_settings.content_md5 = hashlib.md5(bdb_content).digest()
            return mock_stream

        mock_blob_client.download_blob.side_effect = mock_download
        container_client.get_blob_client.return_value = mock_blob_client

        # Create restorer
        restorer = ClusterMetadataRestorer(
            storage_client=storage_client,
            logger_config=mock_logger,
            project_configurations=test_config
        )

        # Create staging files for validation (only files from blob list)
        (image_dir / 'ROLE').write_bytes(role_content)
        (image_dir / 'image.12345').write_bytes(checkpoint_content)
        (bdb_dir / '00000000.jdb').write_bytes(bdb_content)

        # Track copytree calls
        copytree_calls = []
        def mock_copytree(src, dst):
            copytree_calls.append((src, dst))

        # Execute restore
        # Create file mock for MD5 verification
        file_content_map = {
            'ROLE': role_content,
            'image.12345': checkpoint_content,
            '00000000.jdb': bdb_content
        }

        with patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer._create_staging_directory',
                   return_value=str(staging_dir)), \
             patch('os.makedirs'), \
             patch('builtins.open', side_effect=create_file_mock(file_content_map)), \
             patch('shutil.copytree', side_effect=mock_copytree), \
             patch('shutil.rmtree'), \
             patch('os.rename'):

            result = restorer.restore_metadata()

        # Verify backup was created
        assert len(copytree_calls) > 0
        backup_dst = copytree_calls[0][1]
        assert '.pre_restore_backup_' in backup_dst
        assert result['status'] == 'SUCCESS'
