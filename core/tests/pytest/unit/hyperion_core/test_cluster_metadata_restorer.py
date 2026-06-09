"""Unit tests for ClusterMetadataRestorer class."""
import pytest
import os
import tempfile
import hashlib
from unittest.mock import MagicMock, patch, mock_open
from datetime import datetime


class TestHashFileMd5:
    """Test _hash_file_md5 chunked hashing helper (High fix — streams large files)."""

    def test_md5_matches_oneshot_for_small_file(self, tmp_path):
        from pyfiles.hyperion_core.cluster_metadata_restorer import _hash_file_md5
        data = b"hello world\nthis is line two\n"
        f = tmp_path / "small.bin"
        f.write_bytes(data)
        assert _hash_file_md5(str(f)) == hashlib.md5(data).digest()

    def test_md5_matches_oneshot_for_file_larger_than_chunk(self, tmp_path):
        """File >8MB exercises the multi-chunk path; result must equal one-shot MD5.

        Use a fast bytes allocation (constant byte * size) rather than a Python
        generator — the test only needs the file to exceed _HASH_CHUNK_BYTES so
        the inner ``while chunk`` loop iterates twice; the content doesn't matter.
        """
        from pyfiles.hyperion_core.cluster_metadata_restorer import _hash_file_md5, _HASH_CHUNK_BYTES
        # Just over the chunk size — instant allocation, ~8MB written, ~100ms hash.
        data = b"X" * (_HASH_CHUNK_BYTES + 1024)
        assert len(data) > _HASH_CHUNK_BYTES
        f = tmp_path / "large.bin"
        f.write_bytes(data)
        assert _hash_file_md5(str(f)) == hashlib.md5(data).digest()

    def test_md5_of_empty_file(self, tmp_path):
        from pyfiles.hyperion_core.cluster_metadata_restorer import _hash_file_md5
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        assert _hash_file_md5(str(f)) == hashlib.md5(b"").digest()

    def test_raises_filenotfounderror_for_missing_path(self, tmp_path):
        from pyfiles.hyperion_core.cluster_metadata_restorer import _hash_file_md5
        with pytest.raises(FileNotFoundError):
            _hash_file_md5(str(tmp_path / "does_not_exist.bin"))


class TestMetadataRestorerError:
    """Custom exception (High fix — replaces bare Exception sites)."""

    def test_subclasses_exception(self):
        from pyfiles.hyperion_core.cluster_metadata_restorer import MetadataRestorerError
        assert issubclass(MetadataRestorerError, Exception)

    def test_preserves_message(self):
        from pyfiles.hyperion_core.cluster_metadata_restorer import MetadataRestorerError
        err = MetadataRestorerError("staging dir missing")
        assert str(err) == "staging dir missing"

    def test_supports_raise_from_chaining(self):
        from pyfiles.hyperion_core.cluster_metadata_restorer import MetadataRestorerError
        with pytest.raises(MetadataRestorerError) as exc_info:
            try:
                raise ValueError("root cause")
            except ValueError as err:
                raise MetadataRestorerError("higher context") from err
        assert isinstance(exc_info.value.__cause__, ValueError)


class TestClusterMetadataRestorerInitialization:
    """Test ClusterMetadataRestorer initialization."""

    def test_initialization_stores_parameters(self):
        """Test that initialization stores all parameters."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        mock_storage = MagicMock()
        mock_logger = MagicMock()
        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        restorer = ClusterMetadataRestorer(
            storage_client=mock_storage,
            logger_config=mock_logger,
            project_configurations=config
        )

        assert restorer.storage_client == mock_storage
        assert restorer.max_retries == 3
        assert restorer.retry_delay == 2

    def test_initialization_with_custom_retry_settings(self):
        """Test initialization with custom retry settings."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        restorer = ClusterMetadataRestorer(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config,
            max_retries=5,
            retry_delay=10
        )

        assert restorer.max_retries == 5
        assert restorer.retry_delay == 10


class TestSanitizeErrorMessage:
    """Test _sanitize_error_message static method."""

    def test_sanitize_removes_account_key(self):
        """Test that Azure AccountKey is removed from error messages."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        error_msg = "Connection failed: AccountKey=supersecretkey123;EndpointSuffix=core.windows.net"
        sanitized = ClusterMetadataRestorer._sanitize_error_message(error_msg)

        assert "supersecretkey123" not in sanitized
        assert "[REDACTED]" in sanitized

    def test_sanitize_removes_connection_string(self):
        """Test that full Azure connection string is removed."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        error_msg = "Error: DefaultEndpointsProtocol=https;AccountName=myaccount;AccountKey=secretkey==;EndpointSuffix=core.windows.net"
        sanitized = ClusterMetadataRestorer._sanitize_error_message(error_msg)

        assert "secretkey==" not in sanitized
        assert "[REDACTED]" in sanitized

    def test_sanitize_preserves_safe_content(self):
        """Test that safe content is preserved."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        error_msg = "Download failed for blob: 20260213120000/image/ROLE"
        sanitized = ClusterMetadataRestorer._sanitize_error_message(error_msg)

        assert sanitized == error_msg


class TestGetLatestSuccessfulBackup:
    """Test _get_latest_successful_backup method."""

    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer.get_engine')
    def test_returns_latest_backup_info(self, mock_get_engine):
        """Test successful query returns latest backup info."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Mock database response
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_row = ('20260213120000', 1000, datetime(2026, 2, 13, 12, 0, 0), 'fe-node-1')
        mock_result.fetchone.return_value = mock_row
        mock_conn.execute.return_value = mock_result
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_get_engine.return_value = mock_engine

        restorer = ClusterMetadataRestorer(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        result = restorer._get_latest_successful_backup()

        assert result['folder_name'] == '20260213120000'
        assert result['total_files'] == 1000
        assert result['hostname'] == 'fe-node-1'

    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer.get_engine')
    def test_raises_when_no_backup_found(self, mock_get_engine):
        """Test exception raised when no successful backup found."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Mock database response with no rows
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_get_engine.return_value = mock_engine

        restorer = ClusterMetadataRestorer(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        with pytest.raises(Exception, match="No successful backup found"):
            restorer._get_latest_successful_backup()


class TestCreateStagingDirectory:
    """Test _create_staging_directory method."""

    def test_creates_staging_directory(self):
        """Test that staging directory is created with timestamp."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        restorer = ClusterMetadataRestorer(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        with tempfile.TemporaryDirectory():
            with patch('pyfiles.hyperion_core.cluster_metadata_restorer.os.makedirs') as mock_makedirs:
                staging_path = restorer._create_staging_directory()
                
                assert '.metadata_restore_staging_' in staging_path
                mock_makedirs.assert_called_once()


class TestCheckDiskSpace:
    """Test _check_disk_space method."""

    @patch('shutil.disk_usage')
    @patch('os.walk')
    @patch('os.path.exists')
    @patch('os.path.getsize')
    def test_passes_when_sufficient_space(self, mock_getsize, mock_exists, mock_walk, mock_disk_usage):
        """Test disk space check passes when sufficient space available."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Mock 100GB available
        mock_usage = MagicMock()
        mock_usage.free = 100 * 1024 * 1024 * 1024  # 100GB
        mock_disk_usage.return_value = mock_usage

        # Mock 1GB metadata
        mock_exists.return_value = True
        mock_walk.return_value = [
            ('/metadata', [], ['file1', 'file2'])
        ]
        mock_getsize.return_value = 500 * 1024 * 1024  # 500MB per file

        restorer = ClusterMetadataRestorer(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        # Should not raise
        restorer._check_disk_space('/tmp', '/metadata')

    @patch('shutil.disk_usage')
    @patch('os.walk')
    @patch('os.path.exists')
    @patch('os.path.getsize')
    def test_raises_when_insufficient_space(self, mock_getsize, mock_exists, mock_walk, mock_disk_usage):
        """Test disk space check raises exception when insufficient space."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Mock 1GB available
        mock_usage = MagicMock()
        mock_usage.free = 1 * 1024 * 1024 * 1024  # 1GB
        mock_disk_usage.return_value = mock_usage

        # Mock 10GB metadata
        mock_exists.return_value = True
        mock_walk.return_value = [
            ('/metadata', [], ['file1'])
        ]
        mock_getsize.return_value = 10 * 1024 * 1024 * 1024  # 10GB

        restorer = ClusterMetadataRestorer(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        with pytest.raises(Exception, match="Insufficient disk space"):
            restorer._check_disk_space('/tmp', '/metadata')


class TestDownloadSingleFile:
    """Test _download_single_file method."""

    @patch('os.path.exists')
    @patch('os.makedirs')
    @patch('os.path.dirname')
    def test_downloads_and_verifies_md5(self, mock_dirname, mock_makedirs, mock_exists):
        """Test file download with MD5 verification."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Mock storage client
        mock_storage = MagicMock()
        mock_container = MagicMock()
        mock_blob_client = MagicMock()
        mock_storage.get_metadata_backup_container_client.return_value = mock_container
        mock_container.get_blob_client.return_value = mock_blob_client

        # Mock download stream
        file_content = b"test content"
        expected_md5 = hashlib.md5(file_content).digest()

        mock_download_stream = MagicMock()
        mock_download_stream.readall.return_value = file_content
        mock_download_stream.properties.content_settings.content_md5 = expected_md5
        mock_blob_client.download_blob.return_value = mock_download_stream

        mock_exists.return_value = False  # File doesn't exist yet
        mock_dirname.return_value = '/tmp'

        restorer = ClusterMetadataRestorer(
            storage_client=mock_storage,
            logger_config=MagicMock(),
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        # Mock open to return bytes for MD5 verification
        mock_file = MagicMock()
        mock_file.read.side_effect = [file_content, b""]
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)

        with patch('builtins.open', return_value=mock_file):
            result = restorer._download_single_file('20260213120000/image/ROLE', '/tmp/image/ROLE', skip_if_valid=False)

        assert result is True  # File was downloaded
        mock_blob_client.download_blob.assert_called_once()

    @patch('builtins.open', new_callable=mock_open, read_data=b"test content")
    @patch('os.path.exists')
    @patch('os.path.getsize')
    def test_skips_valid_file_on_resume(self, mock_getsize, mock_exists, mock_file_open):
        """Test file is skipped if already exists and MD5 matches."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Mock storage client
        mock_storage = MagicMock()
        mock_container = MagicMock()
        mock_blob_client = MagicMock()
        mock_storage.get_metadata_backup_container_client.return_value = mock_container
        mock_container.get_blob_client.return_value = mock_blob_client

        # Mock blob properties
        file_content = b"test content"
        expected_md5 = hashlib.md5(file_content).digest()

        mock_props = MagicMock()
        mock_props.size = len(file_content)
        mock_props.content_settings.content_md5 = expected_md5
        mock_blob_client.get_blob_properties.return_value = mock_props

        mock_exists.return_value = True  # File exists
        mock_getsize.return_value = len(file_content)

        restorer = ClusterMetadataRestorer(
            storage_client=mock_storage,
            logger_config=MagicMock(),
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        result = restorer._download_single_file('20260213120000/image/ROLE', '/tmp/image/ROLE', skip_if_valid=True)

        assert result is False  # File was skipped
        mock_blob_client.download_blob.assert_not_called()

    @patch('os.path.exists')
    @patch('os.makedirs')
    @patch('os.path.dirname')
    def test_raises_on_md5_mismatch(self, mock_dirname, mock_makedirs, mock_exists):
        """Test exception raised when MD5 doesn't match."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Mock storage client
        mock_storage = MagicMock()
        mock_container = MagicMock()
        mock_blob_client = MagicMock()
        mock_storage.get_metadata_backup_container_client.return_value = mock_container
        mock_container.get_blob_client.return_value = mock_blob_client

        # Mock download stream with wrong MD5
        file_content = b"test content"
        wrong_md5 = hashlib.md5(b"wrong content").digest()

        mock_download_stream = MagicMock()
        mock_download_stream.readall.return_value = file_content
        mock_download_stream.properties.content_settings.content_md5 = wrong_md5
        mock_blob_client.download_blob.return_value = mock_download_stream

        mock_exists.return_value = False
        mock_dirname.return_value = '/tmp'

        restorer = ClusterMetadataRestorer(
            storage_client=mock_storage,
            logger_config=MagicMock(),
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        # Mock open to return bytes for MD5 verification
        mock_file = MagicMock()
        mock_file.read.side_effect = [file_content, b""]
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)

        with patch('builtins.open', return_value=mock_file):
            with pytest.raises(Exception, match="MD5 mismatch"):
                restorer._download_single_file('20260213120000/image/ROLE', '/tmp/image/ROLE', skip_if_valid=False)

    @patch('os.path.exists')
    @patch('os.makedirs')
    @patch('os.path.dirname')
    def test_raises_when_no_md5_available(self, mock_dirname, mock_makedirs, mock_exists):
        """Test exception raised when blob has no MD5."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Mock storage client
        mock_storage = MagicMock()
        mock_container = MagicMock()
        mock_blob_client = MagicMock()
        mock_storage.get_metadata_backup_container_client.return_value = mock_container
        mock_container.get_blob_client.return_value = mock_blob_client

        # Mock download stream with no MD5
        file_content = b"test content"

        mock_download_stream = MagicMock()
        mock_download_stream.readall.return_value = file_content
        mock_download_stream.properties.content_settings.content_md5 = None
        mock_blob_client.download_blob.return_value = mock_download_stream

        mock_exists.return_value = False
        mock_dirname.return_value = '/tmp'

        restorer = ClusterMetadataRestorer(
            storage_client=mock_storage,
            logger_config=MagicMock(),
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        # Mock open for file writing
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)

        with patch('builtins.open', return_value=mock_file):
            with pytest.raises(Exception, match="No MD5 available"):
                restorer._download_single_file('20260213120000/image/ROLE', '/tmp/image/ROLE', skip_if_valid=False)


class TestDownloadAllFiles:
    """Test _download_all_files method."""

    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer._download_single_file')
    def test_downloads_all_blobs(self, mock_download_single):
        """Test all blobs are downloaded in parallel."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Mock storage client
        mock_storage = MagicMock()
        mock_container = MagicMock()
        mock_storage.get_metadata_backup_container_client.return_value = mock_container

        # Mock blob list
        mock_blob1 = MagicMock()
        mock_blob1.name = '20260213120000/image/ROLE'
        mock_blob2 = MagicMock()
        mock_blob2.name = '20260213120000/image/image.123'
        mock_container.list_blobs.return_value = [mock_blob1, mock_blob2]

        mock_download_single.return_value = True  # All downloads succeed

        restorer = ClusterMetadataRestorer(
            storage_client=mock_storage,
            logger_config=MagicMock(),
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        result = restorer._download_all_files('20260213120000', '/tmp/staging', resume=False)

        assert result['total'] == 2
        assert result['downloaded'] == 2
        assert result['skipped'] == 0
        assert mock_download_single.call_count == 2

    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer._download_single_file')
    def test_resume_skips_valid_files(self, mock_download_single):
        """Test resume mode skips already-valid files."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Mock storage client
        mock_storage = MagicMock()
        mock_container = MagicMock()
        mock_storage.get_metadata_backup_container_client.return_value = mock_container

        # Mock blob list
        mock_blob1 = MagicMock()
        mock_blob1.name = '20260213120000/image/ROLE'
        mock_blob2 = MagicMock()
        mock_blob2.name = '20260213120000/image/image.123'
        mock_container.list_blobs.return_value = [mock_blob1, mock_blob2]

        # First file skipped (valid), second file downloaded
        mock_download_single.side_effect = [False, True]

        restorer = ClusterMetadataRestorer(
            storage_client=mock_storage,
            logger_config=MagicMock(),
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        result = restorer._download_all_files('20260213120000', '/tmp/staging', resume=True)

        assert result['total'] == 2
        assert result['downloaded'] == 1
        assert result['skipped'] == 1

    def test_raises_when_no_blobs_found(self):
        """Test exception raised when folder has no blobs."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Mock storage client
        mock_storage = MagicMock()
        mock_container = MagicMock()
        mock_storage.get_metadata_backup_container_client.return_value = mock_container
        mock_container.list_blobs.return_value = []  # No blobs

        restorer = ClusterMetadataRestorer(
            storage_client=mock_storage,
            logger_config=MagicMock(),
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        with pytest.raises(Exception, match="No files found in cloud folder"):
            restorer._download_all_files('20260213120000', '/tmp/staging', resume=False)

    @patch('pyfiles.hyperion_core.cluster_metadata_restorer.ClusterMetadataRestorer._download_single_file')
    def test_raises_on_download_failure(self, mock_download_single):
        """Test exception raised when download fails."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        # Mock storage client
        mock_storage = MagicMock()
        mock_container = MagicMock()
        mock_storage.get_metadata_backup_container_client.return_value = mock_container

        # Mock blob list
        mock_blob1 = MagicMock()
        mock_blob1.name = '20260213120000/image/ROLE'
        mock_container.list_blobs.return_value = [mock_blob1]

        # Download fails
        mock_download_single.side_effect = Exception("Network error")

        restorer = ClusterMetadataRestorer(
            storage_client=mock_storage,
            logger_config=MagicMock(),
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        with pytest.raises(Exception, match="Parallel download failed"):
            restorer._download_all_files('20260213120000', '/tmp/staging', resume=False)


class TestValidateRestoredMetadata:
    """Test _validate_restored_metadata method."""

    def test_validates_complete_structure(self):
        """Test validation passes for complete metadata structure."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create metadata structure
            image_dir = os.path.join(tmpdir, 'image')
            bdb_dir = os.path.join(tmpdir, 'bdb')
            os.makedirs(image_dir)
            os.makedirs(bdb_dir)

            # Create required files
            with open(os.path.join(image_dir, 'ROLE'), 'w') as f:
                f.write('FOLLOWER')
            with open(os.path.join(image_dir, 'image.12345'), 'w') as f:
                f.write('checkpoint')
            with open(os.path.join(bdb_dir, '00000000.jdb'), 'w') as f:
                f.write('bdb data')

            restorer = ClusterMetadataRestorer(
                storage_client=MagicMock(),
                logger_config=MagicMock(),
                project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
            )

            result = restorer._validate_restored_metadata(tmpdir, expected_file_count=3)

            assert result['image_checkpoint_files'] == 1
            assert result['bdb_files'] == 1
            assert result['total_files'] == 3

    def test_raises_when_image_dir_missing(self):
        """Test exception raised when image/ directory missing."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        with tempfile.TemporaryDirectory() as tmpdir:
            restorer = ClusterMetadataRestorer(
                storage_client=MagicMock(),
                logger_config=MagicMock(),
                project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
            )

            with pytest.raises(Exception, match="Missing image/ directory"):
                restorer._validate_restored_metadata(tmpdir, expected_file_count=0)

    def test_raises_when_role_file_missing(self):
        """Test exception raised when image/ROLE file missing."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create image dir but no ROLE file
            image_dir = os.path.join(tmpdir, 'image')
            os.makedirs(image_dir)

            restorer = ClusterMetadataRestorer(
                storage_client=MagicMock(),
                logger_config=MagicMock(),
                project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
            )

            with pytest.raises(Exception, match="Missing image/ROLE file"):
                restorer._validate_restored_metadata(tmpdir, expected_file_count=0)

    def test_raises_when_no_checkpoint_files(self):
        """Test exception raised when no image.* checkpoint files found."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create image dir with ROLE but no checkpoints
            image_dir = os.path.join(tmpdir, 'image')
            os.makedirs(image_dir)
            with open(os.path.join(image_dir, 'ROLE'), 'w') as f:
                f.write('FOLLOWER')

            restorer = ClusterMetadataRestorer(
                storage_client=MagicMock(),
                logger_config=MagicMock(),
                project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
            )

            with pytest.raises(Exception, match="No image checkpoint files found"):
                restorer._validate_restored_metadata(tmpdir, expected_file_count=1)

    def test_raises_when_bdb_dir_missing(self):
        """Test exception raised when bdb/ directory missing."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create image dir only
            image_dir = os.path.join(tmpdir, 'image')
            os.makedirs(image_dir)
            with open(os.path.join(image_dir, 'ROLE'), 'w') as f:
                f.write('FOLLOWER')
            with open(os.path.join(image_dir, 'image.123'), 'w') as f:
                f.write('checkpoint')

            restorer = ClusterMetadataRestorer(
                storage_client=MagicMock(),
                logger_config=MagicMock(),
                project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
            )

            with pytest.raises(Exception, match="Missing bdb/ directory"):
                restorer._validate_restored_metadata(tmpdir, expected_file_count=2)

    def test_raises_when_file_count_mismatch(self):
        """Test exception raised when file count doesn't match expected."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create valid structure
            image_dir = os.path.join(tmpdir, 'image')
            bdb_dir = os.path.join(tmpdir, 'bdb')
            os.makedirs(image_dir)
            os.makedirs(bdb_dir)

            with open(os.path.join(image_dir, 'ROLE'), 'w') as f:
                f.write('FOLLOWER')
            with open(os.path.join(image_dir, 'image.12345'), 'w') as f:
                f.write('checkpoint')
            with open(os.path.join(bdb_dir, '00000000.jdb'), 'w') as f:
                f.write('bdb data')

            restorer = ClusterMetadataRestorer(
                storage_client=MagicMock(),
                logger_config=MagicMock(),
                project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
            )

            with pytest.raises(Exception, match="File count mismatch"):
                restorer._validate_restored_metadata(tmpdir, expected_file_count=100)


class TestCheckFEIsStopped:
    """Test _check_fe_is_stopped method."""

    @patch('os.path.exists')
    def test_returns_true_when_no_pid_file(self, mock_exists):
        """Test returns True when PID file doesn't exist."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        mock_exists.return_value = False

        restorer = ClusterMetadataRestorer(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        assert restorer._check_fe_is_stopped() is True

    @patch('os.kill')
    @patch('builtins.open', new_callable=mock_open, read_data='12345')
    @patch('os.path.exists')
    def test_returns_false_when_process_running(self, mock_exists, mock_file_open, mock_kill):
        """Test returns False when FE process is running."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        mock_exists.return_value = True
        mock_kill.return_value = None  # Process exists (no exception)

        restorer = ClusterMetadataRestorer(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        assert restorer._check_fe_is_stopped() is False

    @patch('os.kill')
    @patch('builtins.open', new_callable=mock_open, read_data='12345')
    @patch('os.path.exists')
    def test_returns_true_when_process_not_running(self, mock_exists, mock_file_open, mock_kill):
        """Test returns True when FE process is not running."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        mock_exists.return_value = True
        mock_kill.side_effect = OSError()  # Process doesn't exist

        restorer = ClusterMetadataRestorer(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        assert restorer._check_fe_is_stopped() is True


class TestBackupExistingMetadata:
    """Test _backup_existing_metadata method."""

    def test_creates_backup_directory(self):
        """Test backup directory is created with timestamp."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create metadata directory with files
            metadata_dir = os.path.join(tmpdir, 'metadata')
            os.makedirs(metadata_dir)
            with open(os.path.join(metadata_dir, 'testfile'), 'w') as f:
                f.write('test')

            restorer = ClusterMetadataRestorer(
                storage_client=MagicMock(),
                logger_config=MagicMock(),
                project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
            )

            backup_path = restorer._backup_existing_metadata(metadata_dir)

            assert os.path.exists(backup_path)
            assert '.pre_restore_backup_' in backup_path
            assert os.path.exists(os.path.join(backup_path, 'testfile'))


class TestRestoreMetadata:
    """Test _restore_metadata method."""

    def test_removes_existing_and_renames_staging(self):
        """Test existing metadata is removed and staging is renamed."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create existing metadata
            metadata_dir = os.path.join(tmpdir, 'metadata')
            os.makedirs(metadata_dir)
            with open(os.path.join(metadata_dir, 'old_file'), 'w') as f:
                f.write('old')

            # Create staging directory
            staging_dir = os.path.join(tmpdir, 'staging')
            os.makedirs(staging_dir)
            with open(os.path.join(staging_dir, 'new_file'), 'w') as f:
                f.write('new')

            restorer = ClusterMetadataRestorer(
                storage_client=MagicMock(),
                logger_config=MagicMock(),
                project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
            )

            restorer._restore_metadata(staging_dir, metadata_dir)

            # Staging should be renamed to metadata
            assert os.path.exists(metadata_dir)
            assert os.path.exists(os.path.join(metadata_dir, 'new_file'))
            assert not os.path.exists(os.path.join(metadata_dir, 'old_file'))
            assert not os.path.exists(staging_dir)


class TestCleanupStaging:
    """Test _cleanup_staging method."""

    def test_removes_staging_directory(self):
        """Test staging directory is removed."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = os.path.join(tmpdir, 'staging')
            os.makedirs(staging_dir)
            with open(os.path.join(staging_dir, 'file'), 'w') as f:
                f.write('test')

            restorer = ClusterMetadataRestorer(
                storage_client=MagicMock(),
                logger_config=MagicMock(),
                project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
            )

            restorer._cleanup_staging(staging_dir)

            assert not os.path.exists(staging_dir)

    def test_handles_nonexistent_directory(self):
        """Test cleanup handles nonexistent directory gracefully."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        restorer = ClusterMetadataRestorer(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        # Should not raise exception
        restorer._cleanup_staging('/nonexistent/path')


class TestWriteRestoreSummary:
    """Test _write_restore_summary method."""

    @patch('builtins.open', new_callable=mock_open)
    def test_writes_summary_json(self, mock_file_open):
        """Test summary is written to JSON file."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        restorer = ClusterMetadataRestorer(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        result = {
            'status': 'SUCCESS',
            'total_files': 1000,
            'verified_files': 1000
        }

        restorer._write_restore_summary(result)

        mock_file_open.assert_called_once_with('/tmp/.last_metadata_restore.json', 'w')

    @patch('builtins.open', side_effect=IOError('Permission denied'))
    def test_handles_write_failure_gracefully(self, mock_file_open):
        """Test write failure is logged but doesn't raise exception."""
        from pyfiles.hyperion_core.cluster_metadata_restorer import ClusterMetadataRestorer

        mock_logger = MagicMock()
        restorer = ClusterMetadataRestorer(
            storage_client=MagicMock(),
            logger_config=mock_logger,
            project_configurations={'query_server': 'localhost:9030', 'username': 'root', 'root_password': 'pass'}
        )

        result = {'status': 'SUCCESS'}

        # Should not raise exception
        restorer._write_restore_summary(result)

        # Should log warning
        assert mock_logger.warning.called
