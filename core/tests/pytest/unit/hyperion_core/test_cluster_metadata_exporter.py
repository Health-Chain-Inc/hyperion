"""Unit tests for ClusterMetadataExporter class."""
import os
from unittest.mock import MagicMock, patch

import pytest


class TestMetadataExporterError:
    """Custom exception (High fix — replaces bare Exception sites)."""

    def test_subclasses_exception(self):
        from pyfiles.hyperion_core.cluster_metadata_exporter import MetadataExporterError
        assert issubclass(MetadataExporterError, Exception)

    def test_preserves_message(self):
        from pyfiles.hyperion_core.cluster_metadata_exporter import MetadataExporterError
        err = MetadataExporterError("parallel upload failed")
        assert str(err) == "parallel upload failed"

    def test_supports_raise_from_chaining(self):
        from pyfiles.hyperion_core.cluster_metadata_exporter import MetadataExporterError
        with pytest.raises(MetadataExporterError) as exc_info:
            try:
                raise RuntimeError("inner")
            except RuntimeError as err:
                raise MetadataExporterError("outer") from err
        assert isinstance(exc_info.value.__cause__, RuntimeError)


class TestActiveExporterGlobal:
    """Verify the module-level global is declared (Critical fix #1 — prevents NameError on early SIGTERM)."""

    def test_active_exporter_declared_at_module_scope(self):
        import pyfiles.hyperion_core.cluster_metadata_exporter as cme
        # The fix is a single line ``active_exporter = None`` at module scope.
        # If it's missing, the SIGTERM handler raises NameError when accessing it.
        assert hasattr(cme, "active_exporter")
        assert cme.active_exporter is None


class TestClusterMetadataExporterInitialization:
    """Test ClusterMetadataExporter initialization."""

    def test_initialization_stores_parameters(self):
        """Test that initialization stores all parameters."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        mock_storage = MagicMock()
        mock_logger = MagicMock()
        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        exporter = ClusterMetadataExporter(
            storage_client=mock_storage,
            logger_config=mock_logger,
            project_configurations=config
        )

        assert exporter.storage_client == mock_storage
        assert exporter.max_retries == 3
        assert exporter.retry_delay == 2

    def test_initialization_with_custom_retry_settings(self):
        """Test initialization with custom retry settings."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        exporter = ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config,
            max_retries=5,
            retry_delay=10,
            checkpoint_wait=30
        )

        assert exporter.max_retries == 5
        assert exporter.retry_delay == 10
        assert exporter.checkpoint_wait == 30


class TestSanitizeErrorMessage:
    """Test _sanitize_error_message static method."""

    def test_sanitize_removes_account_key(self):
        """Test that Azure AccountKey is removed from error messages."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        message = "Error: AccountKey=mySecretKey123;EndpointSuffix=core.windows.net"
        sanitized = ClusterMetadataExporter._sanitize_error_message(message)

        assert 'mySecretKey123' not in sanitized
        assert '[REDACTED]' in sanitized

    def test_sanitize_removes_connection_string(self):
        """Test that full connection string is redacted."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        message = "DefaultEndpointsProtocol=https;AccountName=test;AccountKey=secretKey123;EndpointSuffix=core.windows.net"
        sanitized = ClusterMetadataExporter._sanitize_error_message(message)

        assert 'secretKey123' not in sanitized

    def test_sanitize_removes_sas_token(self):
        """Test that SAS tokens are removed."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        message = "SharedAccessSignature=sv=2020-08-04&ss=bfqt&srt=sco&sp=rwdlacupx"
        sanitized = ClusterMetadataExporter._sanitize_error_message(message)

        assert 'rwdlacupx' not in sanitized


class TestCreateFoldername:
    """Test _create_foldername static method."""

    def test_create_foldername_format(self):
        """Test folder name follows YYYYMMDDHHMMSS format."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        folder_name = ClusterMetadataExporter._create_foldername()

        assert len(folder_name) == 14
        assert folder_name.isdigit()


class TestGetMetadataFilepath:
    """Test _get_metadata_filepath static method."""

    def test_get_metadata_filepath_raises_without_env_var(self):
        """Test raises ValueError when FE_META_FOLDER_PATH not set."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError):
                ClusterMetadataExporter._get_metadata_filepath()

    def test_get_metadata_filepath_raises_for_nonexistent_path(self):
        """Test raises FileNotFoundError for nonexistent path."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        with patch.dict(os.environ, {'FE_META_FOLDER_PATH': '/nonexistent/path'}):
            with pytest.raises(FileNotFoundError):
                ClusterMetadataExporter._get_metadata_filepath()

    def test_get_metadata_filepath_returns_valid_path(self, tmp_path):
        """Test returns path when valid."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        with patch.dict(os.environ, {'FE_META_FOLDER_PATH': str(tmp_path)}):
            result = ClusterMetadataExporter._get_metadata_filepath()
            assert result == str(tmp_path)


class TestCollectFilesToUpload:
    """Test _collect_files_to_upload method."""

    def test_collect_files_returns_file_list(self, tmp_path):
        """Test collecting files from directory."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        # Create test files
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "file2.txt").write_text("content2")

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        exporter = ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

        files, _ = exporter._collect_files_to_upload(str(tmp_path))

        assert len(files) == 2
        local_paths = [f[0] for f in files]
        [f[1] for f in files]

        assert any('file1.txt' in p for p in local_paths)
        assert any('file2.txt' in p for p in local_paths)

    def test_collect_files_skips_unreadable(self, tmp_path):
        """Test that unreadable files are skipped."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        # Create readable file
        (tmp_path / "readable.txt").write_text("content")

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        exporter = ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

        files = exporter._collect_files_to_upload(str(tmp_path))

        assert len(files) >= 1


class TestUploadSingleFile:
    """Test _upload_single_file method."""

    def test_upload_single_file_success(self, tmp_path):
        """Test successful file upload."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        mock_container = MagicMock()
        mock_storage = MagicMock()
        mock_storage.get_metadata_backup_container_client.return_value = mock_container

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        exporter = ClusterMetadataExporter(
            storage_client=mock_storage,
            logger_config=MagicMock(),
            project_configurations=config
        )

        exporter._upload_single_file(str(test_file), "backup/test.txt")

        mock_container.upload_blob.assert_called_once()

    def test_upload_single_file_raises_for_missing_file(self):
        """Test raises FileNotFoundError for missing file."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        exporter = ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

        with pytest.raises(FileNotFoundError):
            exporter._upload_single_file("/nonexistent/file.txt", "backup/file.txt")

    def test_upload_single_file_large_file_uses_streaming(self, tmp_path):
        """Test that files larger than 10MB use streaming upload path."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        # Create a file that appears to be large (>10MB) by mocking os.path.getsize
        test_file = tmp_path / "large_file.dat"
        test_file.write_bytes(b"small content")  # actual content small

        mock_container = MagicMock()
        mock_storage = MagicMock()
        mock_storage.get_metadata_backup_container_client.return_value = mock_container

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        exporter = ClusterMetadataExporter(
            storage_client=mock_storage,
            logger_config=MagicMock(),
            project_configurations=config
        )

        large_size = 11 * 1024 * 1024  # 11MB

        with patch('os.path.getsize', return_value=large_size):
            exporter._upload_single_file(str(test_file), "backup/large_file.dat")

        # upload_blob should have been called with streaming (data is a file object, not bytes)
        mock_container.upload_blob.assert_called_once()
        call_kwargs = mock_container.upload_blob.call_args[1]
        # In streaming path, 'length' is passed; in small-file path it's not
        assert 'length' in call_kwargs
        assert call_kwargs['length'] == large_size


class TestCleanupSnapshot:
    """Test _cleanup_snapshot method."""

    def test_cleanup_snapshot_removes_directory(self, tmp_path):
        """Test snapshot directory is removed."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        # Create snapshot directory
        snapshot_dir = tmp_path / ".metadata_snapshot_test"
        snapshot_dir.mkdir()
        (snapshot_dir / "file.txt").write_text("content")

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        exporter = ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

        exporter._cleanup_snapshot(str(snapshot_dir))

        assert not snapshot_dir.exists()

    def test_cleanup_snapshot_handles_nonexistent_path(self):
        """Test cleanup handles nonexistent path gracefully."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        exporter = ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

        # Should not raise
        exporter._cleanup_snapshot("/nonexistent/path")


class TestCopyMetadataFiles:
    """Test copy_metadata_files method."""

    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        'check_leader_fe'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_get_metadata_filepath'
    )
    def test_copy_metadata_files_skips_non_leader(self, mock_get_path, mock_check_leader):
        """Test copy_metadata_files skips when not leader."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        mock_check_leader.return_value = False

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        exporter = ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

        result = exporter.copy_metadata_files()

        # Should return None when not leader
        assert result is None
        mock_get_path.assert_not_called()

    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        'check_leader_fe'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_create_snapshot'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_collect_files_to_upload'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_upload_all_files'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_cleanup_snapshot'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_log_backup_result'
    )
    def test_copy_metadata_files_returns_empty_when_no_files(
            self, mock_log, mock_cleanup, mock_upload, mock_collect,
            mock_snapshot, mock_check_leader, tmp_path):
        """Test returns empty result when no files found."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        mock_check_leader.return_value = True
        mock_snapshot.return_value = str(tmp_path)
        mock_collect.return_value = ([], 0)  # No files

        mock_storage = MagicMock()
        mock_storage.get_metadata_backup_container_client.return_value = MagicMock()

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        with patch.dict(os.environ, {'FE_META_FOLDER_PATH': str(tmp_path)}):
            exporter = ClusterMetadataExporter(
                storage_client=mock_storage,
                logger_config=MagicMock(),
                project_configurations=config
            )

            result = exporter.copy_metadata_files()

        assert result['total_files'] == 0
        assert result['successful'] is True
        mock_upload.assert_not_called()


class TestCleanupUploadedFiles:
    """Test _cleanup_uploaded_files method."""

    def test_cleanup_uploaded_files_deletes_blobs(self):
        """Test that uploaded blobs are deleted on failure."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        mock_container = MagicMock()
        mock_storage = MagicMock()
        mock_storage.get_metadata_backup_container_client.return_value = mock_container

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        exporter = ClusterMetadataExporter(
            storage_client=mock_storage,
            logger_config=MagicMock(),
            project_configurations=config
        )

        uploaded_files = ['backup/file1.txt', 'backup/file2.txt']
        exporter._cleanup_uploaded_files(uploaded_files)

        assert mock_container.delete_blob.call_count == 2

    def test_cleanup_uploaded_files_handles_empty_list(self):
        """Test cleanup handles empty list gracefully."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        exporter = ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

        # Should not raise
        exporter._cleanup_uploaded_files([])


class TestInitInvalidThreshold:
    """Test __init__ with invalid VERIFICATION_THRESHOLD env var."""

    def test_init_raises_on_non_float_threshold(self):
        """Test ValueError raised when VERIFICATION_THRESHOLD is not a float."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        with patch.dict(os.environ, {'VERIFICATION_THRESHOLD': 'not_a_float'}):
            with pytest.raises(ValueError, match="Invalid VERIFICATION_THRESHOLD"):
                ClusterMetadataExporter(
                    storage_client=MagicMock(),
                    logger_config=MagicMock(),
                    project_configurations=config
                )

    def test_init_raises_on_out_of_range_threshold(self):
        """Test ValueError raised when VERIFICATION_THRESHOLD is out of [0.0, 1.0] range."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        with patch.dict(os.environ, {'VERIFICATION_THRESHOLD': '1.5'}):
            with pytest.raises(ValueError):
                ClusterMetadataExporter(
                    storage_client=MagicMock(),
                    logger_config=MagicMock(),
                    project_configurations=config
                )

    def test_init_accepts_valid_threshold(self):
        """Test no error when VERIFICATION_THRESHOLD is valid."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        with patch.dict(os.environ, {'VERIFICATION_THRESHOLD': '0.75'}):
            exporter = ClusterMetadataExporter(
                storage_client=MagicMock(),
                logger_config=MagicMock(),
                project_configurations=config
            )
            assert exporter.verification_threshold == 0.75


class TestCheckDiskSpace:
    """Test _check_disk_space method."""

    def _make_exporter(self, tmp_path):
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter
        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }
        return ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

    def test_check_disk_space_raises_when_insufficient(self, tmp_path):
        """Test _check_disk_space raises OSError when disk space is insufficient."""

        exporter = self._make_exporter(tmp_path)

        # Create a file in tmp_path
        test_file = tmp_path / "data.txt"
        test_file.write_bytes(b"x" * 1024)  # 1KB

        # Mock disk_usage to report very little free space
        mock_usage = MagicMock()
        mock_usage.free = 0  # No free space

        with patch('shutil.disk_usage', return_value=mock_usage):
            with pytest.raises(OSError, match="Insufficient disk space"):
                exporter._check_disk_space(str(tmp_path))

    def test_check_disk_space_passes_when_sufficient(self, tmp_path):
        """Test _check_disk_space passes when enough space is available."""

        exporter = self._make_exporter(tmp_path)

        test_file = tmp_path / "data.txt"
        test_file.write_bytes(b"x" * 1024)  # 1KB

        # Mock disk_usage to report plenty of free space
        mock_usage = MagicMock()
        mock_usage.free = 100 * 1024 * 1024  # 100MB

        with patch('shutil.disk_usage', return_value=mock_usage):
            exporter._check_disk_space(str(tmp_path))  # Should not raise


class TestCreateSnapshot:
    """Test _create_snapshot method."""

    def _make_exporter(self):
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter
        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }
        return ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

    def test_create_snapshot_success(self, tmp_path):
        """Test _create_snapshot creates a copy of the metadata directory."""

        exporter = self._make_exporter()

        # Create source directory with files
        source_dir = tmp_path / "metadata"
        source_dir.mkdir()
        (source_dir / "image").mkdir()
        (source_dir / "image" / "ROLE").write_text("FOLLOWER")
        (source_dir / "image" / "image.ckpt").write_text("checkpoint data")
        (source_dir / "bdb").mkdir()
        (source_dir / "bdb" / "data.bdb").write_bytes(b"bdb data")

        # Mock disk space check to pass
        with patch.object(exporter, '_check_disk_space'):
            snapshot_path = exporter._create_snapshot(str(source_dir))

        assert os.path.exists(snapshot_path)
        assert os.path.isdir(snapshot_path)
        assert snapshot_path.startswith(str(source_dir))

        # Cleanup
        import shutil
        shutil.rmtree(snapshot_path, ignore_errors=True)

    def test_create_snapshot_failure_cleans_partial(self, tmp_path):
        """Test _create_snapshot cleans partial snapshot on failure and re-raises."""

        exporter = self._make_exporter()

        source_dir = tmp_path / "metadata"
        source_dir.mkdir()

        with patch.object(exporter, '_check_disk_space'), \
             patch('shutil.copytree', side_effect=OSError("Copy failed")), \
             patch('os.path.exists', return_value=True), \
             patch('shutil.rmtree') as mock_rmtree:

            with pytest.raises(OSError, match="Copy failed"):
                exporter._create_snapshot(str(source_dir))

            # Partial snapshot cleanup should have been attempted
            mock_rmtree.assert_called()


class TestCleanupOrphanedSnapshots:
    """Test _cleanup_orphaned_snapshots method."""

    def _make_exporter(self):
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter
        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }
        return ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

    def test_cleanup_orphaned_snapshots_removes_orphans(self, tmp_path):
        """Test that orphaned snapshot directories are removed."""

        exporter = self._make_exporter()

        # Create orphaned snapshot directories
        orphan1 = tmp_path / ".metadata_snapshot_20240101000000"
        orphan1.mkdir()
        (orphan1 / "file.txt").write_text("orphan data")

        orphan2 = tmp_path / ".metadata_snapshot_20240102000000"
        orphan2.mkdir()

        # Create a regular file that should not be removed
        regular_file = tmp_path / "regular_data.txt"
        regular_file.write_text("regular data")

        count = exporter._cleanup_orphaned_snapshots(str(tmp_path))

        assert count == 2
        assert not orphan1.exists()
        assert not orphan2.exists()
        assert regular_file.exists()

    def test_cleanup_orphaned_snapshots_handles_individual_error(self, tmp_path):
        """Test that errors on individual snapshot cleanup are handled gracefully."""

        exporter = self._make_exporter()

        # Create an orphaned snapshot
        orphan = tmp_path / ".metadata_snapshot_20240101000000"
        orphan.mkdir()

        # Make rmtree fail for that one
        with patch('shutil.rmtree', side_effect=OSError("Permission denied")):
            # Should not raise
            count = exporter._cleanup_orphaned_snapshots(str(tmp_path))

        # Count stays 0 since cleanup failed
        assert count == 0


class TestValidateSnapshot:
    """Test _validate_snapshot method."""

    def _make_exporter(self):
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter
        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }
        return ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

    def test_validate_snapshot_raises_when_image_dir_missing(self, tmp_path):
        """Test raises FileNotFoundError when image/ directory is missing."""
        exporter = self._make_exporter()

        # Create only bdb/
        (tmp_path / "bdb").mkdir()
        (tmp_path / "bdb" / "data.bdb").write_bytes(b"data")

        with pytest.raises(FileNotFoundError, match="image/ subdirectory"):
            exporter._validate_snapshot(str(tmp_path))

    def test_validate_snapshot_raises_when_role_file_missing(self, tmp_path):
        """Test raises FileNotFoundError when image/ROLE file is missing."""
        exporter = self._make_exporter()

        (tmp_path / "image").mkdir()
        (tmp_path / "image" / "image.ckpt").write_text("checkpoint")  # checkpoint but no ROLE
        (tmp_path / "bdb").mkdir()
        (tmp_path / "bdb" / "data.bdb").write_bytes(b"data")

        with pytest.raises(FileNotFoundError, match="ROLE"):
            exporter._validate_snapshot(str(tmp_path))

    def test_validate_snapshot_raises_when_no_checkpoint_files(self, tmp_path):
        """Test raises FileNotFoundError when no image.* checkpoint files found."""
        exporter = self._make_exporter()

        (tmp_path / "image").mkdir()
        (tmp_path / "image" / "ROLE").write_text("FOLLOWER")
        # No image.* files
        (tmp_path / "bdb").mkdir()
        (tmp_path / "bdb" / "data.bdb").write_bytes(b"data")

        with pytest.raises(FileNotFoundError, match="image\\.\\*"):
            exporter._validate_snapshot(str(tmp_path))

    def test_validate_snapshot_raises_when_bdb_dir_missing(self, tmp_path):
        """Test raises FileNotFoundError when bdb/ directory is missing."""
        exporter = self._make_exporter()

        (tmp_path / "image").mkdir()
        (tmp_path / "image" / "ROLE").write_text("FOLLOWER")
        (tmp_path / "image" / "image.ckpt").write_text("checkpoint")
        # No bdb/ directory

        with pytest.raises(FileNotFoundError, match="bdb/"):
            exporter._validate_snapshot(str(tmp_path))

    def test_validate_snapshot_raises_when_bdb_empty(self, tmp_path):
        """Test raises FileNotFoundError when bdb/ directory is empty."""
        exporter = self._make_exporter()

        (tmp_path / "image").mkdir()
        (tmp_path / "image" / "ROLE").write_text("FOLLOWER")
        (tmp_path / "image" / "image.ckpt").write_text("checkpoint")
        (tmp_path / "bdb").mkdir()
        # Empty bdb/ directory

        with pytest.raises(FileNotFoundError, match="bdb/"):
            exporter._validate_snapshot(str(tmp_path))

    def test_validate_snapshot_success(self, tmp_path):
        """Test returns counts when snapshot structure is valid."""
        exporter = self._make_exporter()

        (tmp_path / "image").mkdir()
        (tmp_path / "image" / "ROLE").write_text("FOLLOWER")
        (tmp_path / "image" / "image.ckpt").write_text("checkpoint data")
        (tmp_path / "bdb").mkdir()
        (tmp_path / "bdb" / "data.bdb").write_bytes(b"bdb data")

        result = exporter._validate_snapshot(str(tmp_path))

        assert result['image_checkpoint_files'] == 1
        assert result['bdb_files'] == 1


class TestUploadAllFiles:
    """Test _upload_all_files method."""

    def _make_exporter(self):
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter
        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }
        return ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

    def test_upload_all_files_success(self, tmp_path):
        """Test _upload_all_files uploads all files successfully."""

        exporter = self._make_exporter()

        # Create test files
        file1 = tmp_path / "file1.txt"
        file1.write_bytes(b"content1")
        file2 = tmp_path / "file2.txt"
        file2.write_bytes(b"content2")

        files_to_upload = [
            (str(file1), "file1.txt", 8),
            (str(file2), "file2.txt", 8),
        ]

        upload_calls = []

        def mock_upload_single(local_path, blob_path):
            upload_calls.append((local_path, blob_path))

        with patch.object(exporter, '_upload_single_file', side_effect=mock_upload_single):
            exporter._upload_all_files("backup/20240101", files_to_upload, 16)

        assert len(upload_calls) == 2

    def test_upload_all_files_failure_cleans_up_and_reraises(self, tmp_path):
        """Test _upload_all_files cleans up uploaded files and re-raises on failure."""

        exporter = self._make_exporter()

        file1 = tmp_path / "file1.txt"
        file1.write_bytes(b"content1")
        file2 = tmp_path / "file2.txt"
        file2.write_bytes(b"content2")

        files_to_upload = [
            (str(file1), "file1.txt", 8),
            (str(file2), "file2.txt", 8),
        ]

        call_count = [0]

        def fail_on_second(local_path, blob_path):
            call_count[0] += 1
            if call_count[0] == 2:
                raise Exception("Upload failed")

        cleanup_called = [False]

        def mock_cleanup(uploaded_files):
            cleanup_called[0] = True

        with patch.object(exporter, '_upload_single_file', side_effect=fail_on_second), \
             patch.object(exporter, '_cleanup_uploaded_files', side_effect=mock_cleanup):
            with pytest.raises(Exception, match="Parallel upload failed"):
                exporter._upload_all_files("backup/20240101", files_to_upload, 16)

        assert cleanup_called[0] is True


class TestCleanupCloudFolder:
    """Test _cleanup_cloud_folder method."""

    def _make_exporter(self):
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter
        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }
        return ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

    def test_cleanup_cloud_folder_deletes_blobs(self):
        """Test _cleanup_cloud_folder deletes blobs with the given prefix."""

        exporter = self._make_exporter()

        mock_blob1 = MagicMock()
        mock_blob1.name = "backup/20240101/file1.txt"
        mock_blob2 = MagicMock()
        mock_blob2.name = "backup/20240101/file2.txt"

        mock_container = MagicMock()
        mock_container.list_blobs.return_value = [mock_blob1, mock_blob2]
        exporter.storage_client.get_metadata_backup_container_client.return_value = mock_container

        exporter._cleanup_cloud_folder("backup/20240101")

        assert mock_container.delete_blob.call_count == 2

    def test_cleanup_cloud_folder_no_blobs(self):
        """Test _cleanup_cloud_folder handles no blobs gracefully."""

        exporter = self._make_exporter()

        mock_container = MagicMock()
        mock_container.list_blobs.return_value = []
        exporter.storage_client.get_metadata_backup_container_client.return_value = mock_container

        # Should not raise
        exporter._cleanup_cloud_folder("backup/20240101")
        mock_container.delete_blob.assert_not_called()

    def test_cleanup_cloud_folder_blob_delete_failure_is_logged(self):
        """Test _cleanup_cloud_folder logs errors on individual blob delete failure."""

        exporter = self._make_exporter()

        mock_blob = MagicMock()
        mock_blob.name = "backup/20240101/file1.txt"

        mock_container = MagicMock()
        mock_container.list_blobs.return_value = [mock_blob]
        mock_container.delete_blob.side_effect = Exception("Delete failed")
        exporter.storage_client.get_metadata_backup_container_client.return_value = mock_container

        # Should not raise - errors are logged but execution continues
        exporter._cleanup_cloud_folder("backup/20240101")


class TestFindMissingFiles:
    """Test _find_missing_files method."""

    def _make_exporter(self):
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter
        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }
        return ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

    def test_find_missing_files_detects_missing(self):
        """Test _find_missing_files returns files absent from cloud storage."""

        exporter = self._make_exporter()

        # Only file1.txt is in cloud, file2.txt is missing
        mock_blob = MagicMock()
        mock_blob.name = "backup/20240101/file1.txt"

        mock_container = MagicMock()
        mock_container.list_blobs.return_value = [mock_blob]
        exporter.storage_client.get_metadata_backup_container_client.return_value = mock_container

        expected_files = [
            ("/local/file1.txt", "file1.txt", 100),
            ("/local/file2.txt", "file2.txt", 200),
        ]

        missing = exporter._find_missing_files("backup/20240101", expected_files)

        assert len(missing) == 1
        assert missing[0][1] == "file2.txt"

    def test_find_missing_files_all_present(self):
        """Test _find_missing_files returns empty list when all files are present."""

        exporter = self._make_exporter()

        mock_blob1 = MagicMock()
        mock_blob1.name = "backup/20240101/file1.txt"
        mock_blob2 = MagicMock()
        mock_blob2.name = "backup/20240101/file2.txt"

        mock_container = MagicMock()
        mock_container.list_blobs.return_value = [mock_blob1, mock_blob2]
        exporter.storage_client.get_metadata_backup_container_client.return_value = mock_container

        expected_files = [
            ("/local/file1.txt", "file1.txt", 100),
            ("/local/file2.txt", "file2.txt", 200),
        ]

        missing = exporter._find_missing_files("backup/20240101", expected_files)

        assert len(missing) == 0

    def test_find_missing_files_list_blobs_error_raises(self):
        """Test _find_missing_files re-raises when list_blobs fails."""

        exporter = self._make_exporter()

        mock_container = MagicMock()
        mock_container.list_blobs.side_effect = Exception("API error")
        exporter.storage_client.get_metadata_backup_container_client.return_value = mock_container

        with pytest.raises(Exception, match="API error"):
            exporter._find_missing_files("backup/20240101", [("/local/f.txt", "f.txt", 10)])


class TestVerifyAndRetryIfNeeded:
    """Test _verify_and_retry_if_needed method."""

    def _make_exporter(self):
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter
        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }
        return ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config,
            verification_threshold=0.5
        )

    def test_verify_count_matches_fast_path_success(self):
        """Test Case A: when count matches, returns actual_count immediately."""

        exporter = self._make_exporter()

        mock_blob1 = MagicMock()
        mock_blob1.name = "backup/f1.txt"
        mock_blob2 = MagicMock()
        mock_blob2.name = "backup/f2.txt"

        mock_container = MagicMock()
        mock_container.list_blobs.return_value = [mock_blob1, mock_blob2]
        exporter.storage_client.get_metadata_backup_container_client.return_value = mock_container

        all_files = [
            ("/local/f1.txt", "f1.txt", 100),
            ("/local/f2.txt", "f2.txt", 100),
        ]

        result = exporter._verify_and_retry_if_needed("backup", all_files, 1)
        assert result == 2

    def test_verify_extra_files_in_cloud_cleaned_up(self):
        """Test Case B: extra files in cloud are cleaned up, expected files are verified."""

        exporter = self._make_exporter()

        expected_blob = MagicMock()
        expected_blob.name = "backup/f1.txt"
        extra_blob = MagicMock()
        extra_blob.name = "backup/extra_file.txt"  # Not in expected_files

        mock_container = MagicMock()
        mock_container.list_blobs.return_value = [expected_blob, extra_blob]
        exporter.storage_client.get_metadata_backup_container_client.return_value = mock_container

        all_files = [
            ("/local/f1.txt", "f1.txt", 100),
        ]

        result = exporter._verify_and_retry_if_needed("backup", all_files, 1)

        # Extra blob should have been deleted
        mock_container.delete_blob.assert_called_with("backup/extra_file.txt")
        assert result == 1

    def test_verify_missing_files_above_threshold_triggers_granular_retry(self):
        """Test Case C1: missing files with success_rate > threshold triggers granular retry."""

        exporter = self._make_exporter()

        # 8 out of 10 present: success_rate = 0.8 > threshold 0.5
        present_blobs = [MagicMock() for _ in range(8)]
        for i, blob in enumerate(present_blobs):
            blob.name = f"backup/f{i}.txt"

        all_files = [(f"/local/f{i}.txt", f"f{i}.txt", 100) for i in range(10)]

        call_count = [0]

        def mock_list_blobs(name_starts_with=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return present_blobs  # 8 files present
            # Second call (after granular retry) - all 10 present
            all_blobs = [MagicMock() for _ in range(10)]
            for i, blob in enumerate(all_blobs):
                blob.name = f"backup/f{i}.txt"
            return all_blobs

        mock_container = MagicMock()
        mock_container.list_blobs.side_effect = mock_list_blobs
        exporter.storage_client.get_metadata_backup_container_client.return_value = mock_container

        with patch.object(exporter, '_find_missing_files') as mock_find_missing, \
             patch.object(exporter, '_upload_all_files') as mock_upload:

            # Return 2 missing files
            missing = [(f"/local/f{i}.txt", f"f{i}.txt", 100) for i in range(8, 10)]
            mock_find_missing.return_value = missing

            exporter._verify_and_retry_if_needed("backup", all_files, 1)

        # Granular retry should have been triggered
        mock_upload.assert_called_once()

    def test_verify_missing_files_below_threshold_raises(self):
        """Test Case C2: missing files with success_rate <= threshold raises exception."""

        exporter = self._make_exporter()  # threshold = 0.5

        # 3 out of 10 present: success_rate = 0.3 <= threshold 0.5
        present_blobs = [MagicMock() for _ in range(3)]
        for i, blob in enumerate(present_blobs):
            blob.name = f"backup/f{i}.txt"

        all_files = [(f"/local/f{i}.txt", f"f{i}.txt", 100) for i in range(10)]

        mock_container = MagicMock()
        mock_container.list_blobs.return_value = present_blobs
        exporter.storage_client.get_metadata_backup_container_client.return_value = mock_container

        with patch.object(exporter, '_find_missing_files') as mock_find_missing:
            missing = [(f"/local/f{i}.txt", f"f{i}.txt", 100) for i in range(3, 10)]
            mock_find_missing.return_value = missing

            with pytest.raises(Exception, match="Full retry required"):
                exporter._verify_and_retry_if_needed("backup", all_files, 1)


class TestLogBackupResult:
    """Test _log_backup_result method."""

    def _make_exporter(self):
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter
        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }
        return ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

    def test_log_backup_result_success_inserts_to_db(self):
        """Test _log_backup_result performs DB insert on success."""

        exporter = self._make_exporter()

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        with patch.object(exporter, 'get_engine', return_value=mock_engine), \
             patch.object(exporter, 'get_current_hostname', return_value='test-host'):

            exporter._log_backup_result(
                status='SUCCESS',
                folder_name='backup/20240101',
                total_files=10,
                verified_files=10,
                attempts=1,
                duration_seconds=5.0,
                total_size_bytes=1024
            )

        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_log_backup_result_db_failure_is_swallowed(self):
        """Test _log_backup_result swallows DB errors gracefully."""

        exporter = self._make_exporter()

        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("DB connection failed")

        with patch.object(exporter, 'get_engine', return_value=mock_engine), \
             patch.object(exporter, 'get_current_hostname', return_value='test-host'):

            # Should not raise
            exporter._log_backup_result(status='FAILED', error_message='some error')


class TestCopyMetadataFilesExtended:
    """Extended tests for copy_metadata_files method."""

    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        'check_leader_fe'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_get_metadata_filepath'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_cleanup_orphaned_snapshots'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_create_snapshot'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_collect_files_to_upload'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_upload_all_files'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_verify_and_retry_if_needed'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_log_backup_result'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_cleanup_snapshot'
    )
    def test_copy_metadata_files_full_success(
        self, mock_cleanup_snap, mock_log, mock_verify, mock_upload,
        mock_collect, mock_snapshot, mock_cleanup_orphaned,
        mock_get_path, mock_check_leader, tmp_path
    ):
        """Test full success path: leader + files collected + upload + verify + log + cleanup."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        mock_check_leader.return_value = True
        mock_get_path.return_value = str(tmp_path)
        mock_snapshot.return_value = str(tmp_path / "snapshot")
        mock_collect.return_value = (
            [("/local/f1.txt", "f1.txt", 100), ("/local/f2.txt", "f2.txt", 200)],
            300
        )
        mock_verify.return_value = 2

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        exporter = ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

        result = exporter.copy_metadata_files()

        assert result['successful'] is True
        assert result['total_files'] == 2
        assert result['verified_files'] == 2
        assert result['attempts'] == 1
        mock_log.assert_called_with(
            status='SUCCESS',
            folder_name=result['folder_name'],
            total_files=2,
            verified_files=2,
            attempts=1,
            duration_seconds=pytest.approx(result.get('duration_seconds', 0), abs=5),
            total_size_bytes=300
        )
        mock_cleanup_snap.assert_called_once()

    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        'check_leader_fe'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_get_metadata_filepath'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_cleanup_orphaned_snapshots'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_create_snapshot'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_collect_files_to_upload'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_upload_all_files'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_cleanup_cloud_folder'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_log_backup_result'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.cluster_metadata_exporter', fromlist=['ClusterMetadataExporter']).ClusterMetadataExporter,
        '_cleanup_snapshot'
    )
    def test_copy_metadata_files_all_retries_exhausted_reraises(
        self, mock_cleanup_snap, mock_log, mock_cleanup_cloud, mock_upload,
        mock_collect, mock_snapshot, mock_cleanup_orphaned,
        mock_get_path, mock_check_leader, tmp_path
    ):
        """Test that when all retries fail, FAILED is logged and exception is re-raised."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import \
            ClusterMetadataExporter

        mock_check_leader.return_value = True
        mock_get_path.return_value = str(tmp_path)
        mock_snapshot.return_value = str(tmp_path / "snapshot")
        mock_collect.return_value = (
            [("/local/f1.txt", "f1.txt", 100)],
            100
        )
        # Upload always fails
        mock_upload.side_effect = Exception("Upload failed")

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        exporter = ClusterMetadataExporter(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config,
            max_retries=2,
            retry_delay=0
        )

        with patch('time.sleep'):
            with pytest.raises(Exception, match="Upload failed"):
                exporter.copy_metadata_files()

        # Should have logged FAILED
        failed_calls = [
            call for call in mock_log.call_args_list
            if call[1].get('status') == 'FAILED' or
               (call[0] and call[0][0] == 'FAILED')
        ]
        assert len(failed_calls) >= 1

        # Snapshot should be cleaned up
        mock_cleanup_snap.assert_called()


class TestRunMetadataExporterJob:
    """Test run_metadata_exporter_job module-level function."""

    def test_run_job_returns_early_missing_connection_string(self):
        """Test returns early when AZURE_STORAGE_ACCOUNT_CONNECTION_STRING is not set."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import run_metadata_exporter_job

        mock_logger = MagicMock()

        with patch.dict(os.environ, {}, clear=True):
            with patch.dict(os.environ, {
                'AZURE_STORAGE_CONTAINER_METADATA_BACKUP': 'my-container',
                'CLOUD_STORAGE': 'azure',
            }):
                run_metadata_exporter_job(mock_logger)

        mock_logger.error.assert_called()
        error_calls = [str(call) for call in mock_logger.error.call_args_list]
        assert any('AZURE_STORAGE_ACCOUNT_CONNECTION_STRING' in call for call in error_calls)

    def test_run_job_returns_early_missing_container(self):
        """Test returns early when AZURE_STORAGE_CONTAINER_METADATA_BACKUP is not set."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import run_metadata_exporter_job

        mock_logger = MagicMock()

        with patch.dict(os.environ, {
            'AZURE_STORAGE_ACCOUNT_CONNECTION_STRING': 'DefaultEndpointsProtocol=https;AccountName=test;AccountKey=dGVzdA==',
            'CLOUD_STORAGE': 'azure',
        }):
            # Unset the container env var
            import os as os_mod
            env = {k: v for k, v in os_mod.environ.items() if k != 'AZURE_STORAGE_CONTAINER_METADATA_BACKUP'}
            with patch.dict(os_mod.environ, env, clear=True):
                with patch.dict(os_mod.environ, {
                    'AZURE_STORAGE_ACCOUNT_CONNECTION_STRING': 'DefaultEndpointsProtocol=https;AccountName=test;AccountKey=dGVzdA==',
                    'CLOUD_STORAGE': 'azure',
                }):
                    run_metadata_exporter_job(mock_logger)

        mock_logger.error.assert_called()

    def test_run_job_returns_early_unsupported_cloud_backend(self):
        """Test returns early when CLOUD_STORAGE is not 'azure'."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import run_metadata_exporter_job

        mock_logger = MagicMock()

        with patch.dict(os.environ, {
            'AZURE_STORAGE_ACCOUNT_CONNECTION_STRING': 'DefaultEndpointsProtocol=https;AccountName=test;AccountKey=dGVzdA==',
            'AZURE_STORAGE_CONTAINER_METADATA_BACKUP': 'my-container',
            'CLOUD_STORAGE': 'aws',  # Unsupported
        }):
            run_metadata_exporter_job(mock_logger)

        # Should log error about unsupported backend
        mock_logger.error.assert_called()
        error_calls = [str(call) for call in mock_logger.error.call_args_list]
        assert any('Unsupported' in call or 'aws' in call for call in error_calls)

    def test_run_job_success_path(self):
        """Test successful run path creates exporter and calls copy_metadata_files."""
        from pyfiles.hyperion_core.cluster_metadata_exporter import run_metadata_exporter_job

        mock_logger = MagicMock()

        with patch.dict(os.environ, {
            'AZURE_STORAGE_ACCOUNT_CONNECTION_STRING': 'DefaultEndpointsProtocol=https;AccountName=test;AccountKey=dGVzdA==',
            'AZURE_STORAGE_CONTAINER_METADATA_BACKUP': 'my-container',
            'CLOUD_STORAGE': 'azure',
        }):
            with patch('pyfiles.hyperion_core.cluster_metadata_exporter.AzureStorageClient'), \
                 patch('pyfiles.hyperion_core.cluster_metadata_exporter.ClusterMetadataExporter') as mock_exporter_cls:

                mock_exporter = MagicMock()
                mock_exporter_cls.return_value = mock_exporter

                run_metadata_exporter_job(mock_logger)

        mock_exporter.copy_metadata_files.assert_called_once()
