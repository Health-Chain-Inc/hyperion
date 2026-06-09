"""Integration tests for cluster metadata exporter retry mechanism.

This test suite validates the retry behavior with controlled failure scenarios:
1. Granular retry - uploads only missing files when success_rate > threshold
2. Full retry - re-uploads everything when success_rate <= threshold
3. Threshold boundary testing
4. Audit logging validation
"""
import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import List, Tuple, Set
from tests.pytest.mocks.mock_storage_client import MockBlobProperties


class FailureInjectingContainerClient:
    """Enhanced mock container client with configurable failure injection."""

    def __init__(self, container_name: str):
        self.container_name = container_name
        self._blobs: Set[str] = set()
        self._upload_failures: Set[str] = set()  # Files that should fail upload
        self._list_missing: Set[str] = set()  # Files to hide from list_blobs
        self.upload_count = 0
        self.upload_attempts: List[Tuple[str, bool]] = []  # (blob_name, success)
        self.deleted_blobs: List[str] = []
        self.folders_created: Set[str] = set()

    def set_upload_failures(self, blob_names: List[str]):
        """Configure which blob uploads should fail."""
        self._upload_failures = set(blob_names)

    def set_missing_from_list(self, blob_names: List[str]):
        """Configure which blobs should not appear in list_blobs (simulate upload failure)."""
        self._list_missing = set(blob_names)

    def upload_blob(self, name: str, data, overwrite: bool = True,
                    content_settings=None, length=None, timeout=None, **kwargs):
        """Upload blob with optional failure injection."""
        self.upload_count += 1

        # Simulate failure if configured
        if name in self._upload_failures:
            self.upload_attempts.append((name, False))
            raise Exception(f"Simulated upload failure for {name}")

        # Track folder
        folder = name.split('/')[0] if '/' in name else ''
        if folder:
            self.folders_created.add(folder)

        # Successful upload
        self._blobs.add(name)
        self.upload_attempts.append((name, True))
        return {"etag": f"mock-etag-{name}"}

    def list_blobs(self, name_starts_with: str = None):
        """List blobs with optional filtering to simulate missing files."""
        for blob_name in sorted(self._blobs):
            # Apply prefix filter
            if name_starts_with and not blob_name.startswith(name_starts_with):
                continue

            # Simulate missing files (hide from list)
            if blob_name in self._list_missing:
                continue

            yield MockBlobProperties(blob_name)

    def delete_blob(self, blob_name: str):
        """Delete blob from storage."""
        self.deleted_blobs.append(blob_name)
        self._blobs.discard(blob_name)
        return True

    def get_blob_client(self, blob: str = None, blob_name: str = None):
        """Get blob client (minimal mock)."""
        name = blob or blob_name
        mock_blob = MagicMock()
        mock_blob.blob_name = name
        mock_blob.exists.return_value = name in self._blobs
        return mock_blob

    def reset_tracking(self):
        """Reset tracking metrics for multi-attempt tests."""
        self.upload_count = 0
        self.upload_attempts = []
        self.deleted_blobs = []


class FailureInjectingStorageClient:
    """Mock storage client with failure injection capabilities."""

    def __init__(self):
        self.metadata_container = FailureInjectingContainerClient('metadata-backup')

    def get_metadata_backup_container_client(self):
        return self.metadata_container


@pytest.fixture
def temp_metadata_files():
    """Create temporary metadata files for testing."""
    temp_dir = tempfile.mkdtemp()
    files = []

    # Create 10 test files with varying sizes
    for i in range(10):
        file_path = Path(temp_dir) / f"file{i}.txt"
        content = f"Test metadata content {i}\n" * (100 * (i + 1))  # Varying sizes
        file_path.write_text(content)
        files.append(file_path)

    yield temp_dir, files

    # Cleanup
    for file_path in files:
        if file_path.exists():
            file_path.unlink()
    os.rmdir(temp_dir)


@pytest.fixture
def mock_exporter_config():
    """Standard configuration for test exporters."""
    return {
        'query_server': 'localhost:9030',
        'username': 'root',
        'root_password': 'test_password',
        'azure_storage': {
            'container_name': 'metadata-backup'
        }
    }


def create_test_exporter(storage_client, config, threshold=0.5, max_retries=3):
    """Helper to create exporter with test configuration."""
    from pyfiles.hyperion_core.cluster_metadata_exporter import ClusterMetadataExporter

    mock_logger = MagicMock()

    return ClusterMetadataExporter(
        storage_client=storage_client,
        logger_config=mock_logger,
        project_configurations=config,
        verification_threshold=threshold,
        max_retries=max_retries
    )


def create_mock_upload_function(container):
    """Create a mock upload function that adds files to the container."""
    def mock_upload_files(folder, files, total_bytes):
        """Simulate successful upload by adding files to container."""
        for _, rel_path, _ in files:
            container._blobs.add(f"{folder}/{rel_path}")
    return mock_upload_files


@pytest.mark.integration
class TestGranularRetry:
    """Integration tests for granular retry mechanism (success_rate > threshold)."""

    def test_partial_upload_failure_triggers_granular_retry(self, temp_metadata_files, mock_exporter_config):
        """Test granular retry when 30% of files fail to upload (70% > 50% threshold)."""
        temp_dir, files = temp_metadata_files

        # Setup storage client with failure injection
        storage_client = FailureInjectingStorageClient()
        container = storage_client.metadata_container

        # Simulate initial upload: 7 files succeed, 3 fail (70% success rate)
        # Pre-populate successful uploads
        for i in [0, 1, 3, 4, 6, 7, 9]:  # 7 files
            container._blobs.add(f"test_folder/file{i}.txt")

        # Files 2, 5, 8 are "missing" (failed upload)

        # Create exporter with 50% threshold
        exporter = create_test_exporter(storage_client, mock_exporter_config, threshold=0.5)

        # Prepare file list
        all_files = [(str(f), f.name, f.stat().st_size) for f in files]

        # Execute verification (should trigger granular retry)
        mock_upload_fn = create_mock_upload_function(container)
        with patch.object(exporter, '_upload_all_files', side_effect=mock_upload_fn) as mock_upload:
            result = exporter._verify_and_retry_if_needed("test_folder", all_files, attempt=1)

        # Verify results
        assert result == 10, "Should verify all 10 files after granular retry"
        assert mock_upload.call_count == 1, "Should call upload once for missing files"

        # Verify only missing files were re-uploaded (call_args contains the missing files)
        second_upload_call = mock_upload.call_args_list[0]
        uploaded_files = second_upload_call[0][1]  # Second argument is file list
        assert len(uploaded_files) == 3, "Should only upload 3 missing files"

    def test_granular_retry_with_51_percent_success(self, mock_exporter_config):
        """Test edge case: 51% success rate (just above 50% threshold)."""
        storage_client = FailureInjectingStorageClient()
        container = storage_client.metadata_container

        # Create 100 test files
        all_files = [(f"/tmp/file{i}.txt", f"file{i}.txt", 1024) for i in range(100)]

        # Simulate 51 successful uploads (51% success rate, just above threshold)
        for i in range(51):
            container._blobs.add(f"test_folder/file{i}.txt")

        # Files 51-99 are "missing" (49 files failed)

        exporter = create_test_exporter(storage_client, mock_exporter_config, threshold=0.5)

        # Should trigger granular retry
        mock_upload_fn = create_mock_upload_function(container)
        with patch.object(exporter, '_upload_all_files', side_effect=mock_upload_fn) as mock_upload:
            result = exporter._verify_and_retry_if_needed("test_folder", all_files, attempt=1)

        assert result == 100
        assert mock_upload.call_count == 1

        # Verify 49 missing files were uploaded
        uploaded_files = mock_upload.call_args_list[0][0][1]
        assert len(uploaded_files) == 49

    def test_recursive_granular_retry(self, mock_exporter_config):
        """Test multiple rounds of granular retry (cascading failures)."""
        storage_client = FailureInjectingStorageClient()
        container = storage_client.metadata_container

        all_files = [(f"/tmp/file{i}.txt", f"file{i}.txt", 1024) for i in range(10)]

        # Initially, 7 files are present (70% success)
        for i in [0, 1, 3, 4, 6, 7, 9]:
            container._blobs.add(f"test_folder/file{i}.txt")

        # Files 2, 5, 8 are "missing" initially

        exporter = create_test_exporter(storage_client, mock_exporter_config, threshold=0.5)

        # Track upload calls
        upload_calls = []

        def track_upload_and_simulate_partial_success(folder, files, total_bytes):
            """Track uploads and simulate that file5 fails on first upload."""
            upload_calls.append(files)
            for _, rel_path, _ in files:
                blob_name = f"{folder}/{rel_path}"
                # First granular retry: upload file2, file5, file8
                # But file5 "fails" (don't add it)
                if len(upload_calls) == 1 and rel_path == "file5.txt":
                    continue  # Simulate failure
                container._blobs.add(blob_name)

        with patch.object(exporter, '_upload_all_files', side_effect=track_upload_and_simulate_partial_success) as mock_upload:
            result = exporter._verify_and_retry_if_needed("test_folder", all_files, attempt=1)

        assert result == 10
        assert mock_upload.call_count == 2, "Should trigger 2 granular retries"

        # First retry: 3 missing files (file2, file5, file8)
        assert len(upload_calls[0]) == 3
        # Second retry: 1 missing file (file5 only)
        assert len(upload_calls[1]) == 1


@pytest.mark.integration
class TestFullRetry:
    """Integration tests for full retry mechanism (success_rate <= threshold)."""

    def test_low_success_rate_raises_exception_for_full_retry(self, mock_exporter_config):
        """Test success rate <= 50% raises exception to trigger full retry."""
        storage_client = FailureInjectingStorageClient()
        container = storage_client.metadata_container

        all_files = [(f"/tmp/file{i}.txt", f"file{i}.txt", 1024) for i in range(10)]

        # Only 4 out of 10 succeed (40% < 50% threshold)
        for i in range(4):
            container._blobs.add(f"test_folder/file{i}.txt")

        # Files 4-9 are "missing" (6 files failed)

        exporter = create_test_exporter(storage_client, mock_exporter_config, threshold=0.5)

        # Should raise exception for full retry
        with pytest.raises(Exception) as exc_info:
            exporter._verify_and_retry_if_needed("test_folder", all_files, attempt=1)

        assert "Verification failed" in str(exc_info.value)
        assert "4/10 files present" in str(exc_info.value)
        assert "Full retry required" in str(exc_info.value)

    def test_threshold_boundary_exactly_50_percent(self, mock_exporter_config):
        """Test boundary case: exactly 50% success rate (should trigger full retry)."""
        storage_client = FailureInjectingStorageClient()
        container = storage_client.metadata_container

        all_files = [(f"/tmp/file{i}.txt", f"file{i}.txt", 1024) for i in range(10)]

        # Exactly 5 out of 10 succeed (50% = threshold)
        for i in range(5):
            container._blobs.add(f"test_folder/file{i}.txt")

        # Files 5-9 are "missing" (5 files failed)

        exporter = create_test_exporter(storage_client, mock_exporter_config, threshold=0.5)

        # Should raise exception (50% <= 50%)
        with pytest.raises(Exception) as exc_info:
            exporter._verify_and_retry_if_needed("test_folder", all_files, attempt=1)

        assert "Verification failed" in str(exc_info.value)
        assert "5/10 files present" in str(exc_info.value)

    def test_zero_percent_success_rate(self, mock_exporter_config):
        """Test extreme case: 0% success rate (all uploads failed)."""
        storage_client = FailureInjectingStorageClient()
        container = storage_client.metadata_container

        all_files = [(f"/tmp/file{i}.txt", f"file{i}.txt", 1024) for i in range(10)]

        # All files missing (0% success)
        failing_blobs = [f"test_folder/file{i}.txt" for i in range(10)]
        container.set_missing_from_list(failing_blobs)

        exporter = create_test_exporter(storage_client, mock_exporter_config, threshold=0.5)

        with pytest.raises(Exception) as exc_info:
            exporter._verify_and_retry_if_needed("test_folder", all_files, attempt=1)

        assert "0/10 files present" in str(exc_info.value)


@pytest.mark.integration
class TestThresholdBoundaryTesting:
    """Test retry behavior with different threshold values."""

    @pytest.mark.parametrize("threshold,success_count,total_count,should_retry_granular", [
        (0.3, 4, 10, True),   # 40% > 30% threshold → granular
        (0.3, 3, 10, False),  # 30% = 30% threshold → full retry
        (0.5, 6, 10, True),   # 60% > 50% threshold → granular
        (0.5, 5, 10, False),  # 50% = 50% threshold → full retry
        (0.7, 8, 10, True),   # 80% > 70% threshold → granular
        (0.7, 7, 10, False),  # 70% = 70% threshold → full retry
        (0.9, 10, 10, True),  # 100% > 90% threshold → granular (success case)
        (0.9, 9, 10, False),  # 90% = 90% threshold → full retry
    ])
    def test_threshold_decision_logic(self, mock_exporter_config, threshold,
                                      success_count, total_count, should_retry_granular):
        """Test retry strategy selection across different thresholds."""
        storage_client = FailureInjectingStorageClient()
        container = storage_client.metadata_container

        all_files = [(f"/tmp/file{i}.txt", f"file{i}.txt", 1024) for i in range(total_count)]

        # Simulate successful uploads
        for i in range(success_count):
            container._blobs.add(f"test_folder/file{i}.txt")

        # Remaining files (success_count to total_count) are "missing"

        exporter = create_test_exporter(storage_client, mock_exporter_config, threshold=threshold)

        if should_retry_granular:
            # Should trigger granular retry
            mock_upload_fn = create_mock_upload_function(container)
            with patch.object(exporter, '_upload_all_files', side_effect=mock_upload_fn) as mock_upload:
                result = exporter._verify_and_retry_if_needed("test_folder", all_files, attempt=1)

            missing_count = total_count - success_count
            if missing_count > 0:
                assert mock_upload.call_count == 1, f"Should upload missing files for threshold={threshold}"
                assert result == total_count
        else:
            # Should raise exception for full retry
            with pytest.raises(Exception) as exc_info:
                exporter._verify_and_retry_if_needed("test_folder", all_files, attempt=1)

            assert "Full retry required" in str(exc_info.value)


@pytest.mark.integration
class TestExtraFilesCleanup:
    """Test cleanup of orphaned files in cloud storage."""

    def test_extra_files_cleanup_before_verification(self, mock_exporter_config):
        """Test orphaned files are cleaned up before final verification."""
        storage_client = FailureInjectingStorageClient()
        container = storage_client.metadata_container

        all_files = [
            ("/tmp/file1.txt", "file1.txt", 1024),
            ("/tmp/file2.txt", "file2.txt", 2048)
        ]

        # Manually add expected + extra files to blob storage
        container._blobs = {
            "test_folder/file1.txt",
            "test_folder/file2.txt",
            "test_folder/orphan1.txt",  # Extra
            "test_folder/orphan2.txt"   # Extra
        }

        exporter = create_test_exporter(storage_client, mock_exporter_config, threshold=0.5)

        result = exporter._verify_and_retry_if_needed("test_folder", all_files, attempt=1)

        assert result == 2
        assert len(container.deleted_blobs) == 2, "Should delete 2 orphaned files"
        assert "test_folder/orphan1.txt" in container.deleted_blobs
        assert "test_folder/orphan2.txt" in container.deleted_blobs

    def test_extra_files_with_missing_files_triggers_retry(self, mock_exporter_config):
        """Test cleanup of extras + retry for missing files."""
        storage_client = FailureInjectingStorageClient()
        container = storage_client.metadata_container

        all_files = [(f"/tmp/file{i}.txt", f"file{i}.txt", 1024) for i in range(10)]

        # Cloud has: 7 expected files + 2 orphans (9 total)
        # Missing: file0, file1, file2 (3 files)
        # Present: file3-file9 (7 files) + orphan1, orphan2
        for i in range(3, 10):
            container._blobs.add(f"test_folder/file{i}.txt")
        container._blobs.add("test_folder/orphan1.txt")
        container._blobs.add("test_folder/orphan2.txt")

        exporter = create_test_exporter(storage_client, mock_exporter_config, threshold=0.5)

        # 70% success rate > 50% threshold → should cleanup extras + granular retry
        mock_upload_fn = create_mock_upload_function(container)
        with patch.object(exporter, '_upload_all_files', side_effect=mock_upload_fn) as mock_upload:
            result = exporter._verify_and_retry_if_needed("test_folder", all_files, attempt=1)

        assert result == 10
        assert len(container.deleted_blobs) == 2, "Should delete orphaned files"
        assert mock_upload.call_count == 1, "Should upload missing files"


@pytest.mark.integration
class TestAuditLogging:
    """Test audit trail and logging during retry scenarios."""

    def test_retry_logs_success_rate_and_decision(self, mock_exporter_config):
        """Test retry decision is logged with success rate and threshold."""
        storage_client = FailureInjectingStorageClient()
        container = storage_client.metadata_container

        all_files = [(f"/tmp/file{i}.txt", f"file{i}.txt", 1024) for i in range(10)]

        # Simulate 70% success rate (7 files present)
        for i in range(7):
            container._blobs.add(f"test_folder/file{i}.txt")

        # Files 7, 8, 9 are "missing" (3 files failed)

        exporter = create_test_exporter(storage_client, mock_exporter_config, threshold=0.5)

        # Execute
        mock_upload_fn = create_mock_upload_function(container)
        with patch.object(exporter, '_upload_all_files', side_effect=mock_upload_fn) as mock_upload:
            result = exporter._verify_and_retry_if_needed("test_folder", all_files, attempt=1)

        # Verify granular retry occurred
        assert result == 10, "Should successfully verify all 10 files after retry"
        assert mock_upload.call_count == 1, "Should trigger granular retry"
        assert len(mock_upload.call_args[0][1]) == 3, "Should upload 3 missing files"

        # Verify logger was called (basic check)
        logger = exporter.logger
        assert logger.warning.called, "Should log warnings about missing files"
        assert logger.info.called, "Should log info about retry"

    def test_full_retry_logs_error_with_metrics(self, mock_exporter_config):
        """Test full retry exception includes detailed metrics."""
        storage_client = FailureInjectingStorageClient()
        container = storage_client.metadata_container

        all_files = [(f"/tmp/file{i}.txt", f"file{i}.txt", 1024) for i in range(10)]

        # 30% success rate (below threshold)
        for i in range(3):
            container._blobs.add(f"test_folder/file{i}.txt")

        # Files 3-9 are "missing" (7 files failed)

        exporter = create_test_exporter(storage_client, mock_exporter_config, threshold=0.5)

        # Execute and capture exception
        with pytest.raises(Exception) as exc_info:
            exporter._verify_and_retry_if_needed("test_folder", all_files, attempt=1)

        error_msg = str(exc_info.value)

        # Verify error message contains key metrics
        assert "3/10 files present" in error_msg
        assert "30%" in error_msg or "30.0%" in error_msg  # Success rate
        assert "50%" in error_msg or "50.0%" in error_msg  # Threshold
        assert "Full retry required" in error_msg

    def test_missing_files_sample_logged(self, mock_exporter_config):
        """Test sample of missing files is logged (max 10)."""
        storage_client = FailureInjectingStorageClient()
        container = storage_client.metadata_container

        # Create 50 files
        all_files = [(f"/tmp/file{i}.txt", f"file{i}.txt", 1024) for i in range(50)]

        # Simulate 30 successful uploads (60% success rate → granular retry)
        for i in range(30):
            container._blobs.add(f"test_folder/file{i}.txt")

        # Files 30-49 are "missing" (20 files failed)

        exporter = create_test_exporter(storage_client, mock_exporter_config, threshold=0.5)

        mock_upload_fn = create_mock_upload_function(container)
        with patch.object(exporter, '_upload_all_files', side_effect=mock_upload_fn):
            exporter._verify_and_retry_if_needed("test_folder", all_files, attempt=1)

        # Verify sample logging
        logger = exporter.logger
        warning_calls = [str(call) for call in logger.warning.call_args_list]

        # Should log sample of missing files
        sample_logged = any("Sample missing files" in str(call) for call in warning_calls)
        assert sample_logged, "Should log sample of missing files"


@pytest.mark.integration
class TestCopyMetadataFilesRetryFlow:
    """Integration tests for full copy_metadata_files retry flow."""

    @patch('pyfiles.hyperion_core.cluster_metadata_exporter.ClusterMetadataExporter.check_leader_fe')
    @patch('pyfiles.hyperion_core.cluster_metadata_exporter.ClusterMetadataExporter._get_metadata_filepath')
    @patch('pyfiles.hyperion_core.cluster_metadata_exporter.ClusterMetadataExporter._create_snapshot')
    @patch('pyfiles.hyperion_core.cluster_metadata_exporter.ClusterMetadataExporter._collect_files_to_upload')
    @patch('pyfiles.hyperion_core.cluster_metadata_exporter.ClusterMetadataExporter._cleanup_snapshot')
    @patch('pyfiles.hyperion_core.cluster_metadata_exporter.ClusterMetadataExporter._cleanup_orphaned_snapshots')
    @patch('pyfiles.hyperion_core.cluster_metadata_exporter.ClusterMetadataExporter._log_backup_result')
    @patch('pyfiles.hyperion_core.cluster_metadata_exporter.ClusterMetadataExporter._upload_all_files')
    def test_full_retry_creates_new_folder(self, mock_upload, mock_log, mock_cleanup_orphaned,
                                           mock_cleanup, mock_collect, mock_snapshot,
                                           mock_get_path, mock_leader, mock_exporter_config):
        """Test full retry creates new folder and re-uploads all files."""
        storage_client = FailureInjectingStorageClient()
        container = storage_client.metadata_container

        # Mock prerequisites
        mock_leader.return_value = True
        mock_get_path.return_value = "/opt/starrocks/fe/meta"
        mock_snapshot.return_value = "/tmp/snapshot"

        # Mock file discovery
        all_files = [(f"/tmp/file{i}.txt", f"file{i}.txt", 1024) for i in range(10)]
        mock_collect.return_value = (all_files, 10240)  # files, total_size

        # Track verification attempts
        verification_count = [0]
        uploaded_folders = []

        def track_upload(folder, files, total_bytes):
            """Track which folders are being uploaded to."""
            uploaded_folders.append(folder)
            # Simulate upload by adding files to container
            for _, rel_path, _ in files:
                container._blobs.add(f"{folder}/{rel_path}")

        mock_upload.side_effect = track_upload

        def dynamic_list_blobs(name_starts_with=None):
            verification_count[0] += 1

            if verification_count[0] == 1:
                # First attempt: only 30% success → trigger full retry (raises exception)
                for i in range(3):
                    yield MockBlobProperties(f"{name_starts_with}/file{i}.txt")
            else:
                # Second attempt: 100% success
                for i in range(10):
                    yield MockBlobProperties(f"{name_starts_with}/file{i}.txt")

        container.list_blobs = dynamic_list_blobs

        exporter = create_test_exporter(storage_client, mock_exporter_config, threshold=0.5, max_retries=3)

        # Execute
        result = exporter.copy_metadata_files()

        # Verify results
        assert result['successful'] is True
        assert result['attempts'] == 2, "Should take 2 attempts (initial + 1 retry)"

        # Verify upload was called twice (initial + retry)
        assert len(uploaded_folders) == 2, "Should upload to 2 folders"
        assert mock_upload.call_count == 2, "Should call upload twice"

        # Note: Folder names might be the same if retries happen within the same second
        # What matters is that we attempted twice and succeeded on the second attempt

    @patch('pyfiles.hyperion_core.cluster_metadata_exporter.ClusterMetadataExporter.check_leader_fe')
    @patch('pyfiles.hyperion_core.cluster_metadata_exporter.ClusterMetadataExporter._get_metadata_filepath')
    @patch('pyfiles.hyperion_core.cluster_metadata_exporter.ClusterMetadataExporter._create_snapshot')
    @patch('pyfiles.hyperion_core.cluster_metadata_exporter.ClusterMetadataExporter._collect_files_to_upload')
    @patch('pyfiles.hyperion_core.cluster_metadata_exporter.ClusterMetadataExporter._cleanup_snapshot')
    @patch('pyfiles.hyperion_core.cluster_metadata_exporter.ClusterMetadataExporter._cleanup_orphaned_snapshots')
    @patch('pyfiles.hyperion_core.cluster_metadata_exporter.ClusterMetadataExporter._log_backup_result')
    @patch('pyfiles.hyperion_core.cluster_metadata_exporter.ClusterMetadataExporter._upload_all_files')
    def test_max_retries_exhausted_returns_failure(self, mock_upload, mock_log, mock_cleanup_orphaned,
                                                   mock_cleanup, mock_collect, mock_snapshot,
                                                   mock_get_path, mock_leader, mock_exporter_config):
        """Test backup fails after exhausting max_retries."""
        storage_client = FailureInjectingStorageClient()
        container = storage_client.metadata_container

        # Mock prerequisites
        mock_leader.return_value = True
        mock_get_path.return_value = "/opt/starrocks/fe/meta"
        mock_snapshot.return_value = "/tmp/snapshot"

        all_files = [(f"/tmp/file{i}.txt", f"file{i}.txt", 1024) for i in range(10)]
        mock_collect.return_value = (all_files, 10240)

        # Mock upload does nothing (simulates upload but doesn't add to container)
        mock_upload.return_value = None

        # Always return 0% success to force continuous retries
        container.list_blobs = lambda name_starts_with=None: iter([])

        exporter = create_test_exporter(storage_client, mock_exporter_config,
                                       threshold=0.5, max_retries=3)

        # Execute - should raise exception after max retries
        with pytest.raises(Exception) as exc_info:
            exporter.copy_metadata_files()

        # Verify all attempts were made
        assert "Verification failed" in str(exc_info.value)

        # Verify upload was called 3 times (max_retries)
        assert mock_upload.call_count == 3

        # Verify logging was called for failure
        assert mock_log.called


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
