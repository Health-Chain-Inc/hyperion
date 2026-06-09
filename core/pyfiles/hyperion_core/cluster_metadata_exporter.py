import concurrent.futures
import datetime
import hashlib
import os
import re
import shutil
import signal
import threading
import time
import uuid
from typing import Dict, List, Tuple

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from azure.storage.blob import ContentSettings
from sqlalchemy import text

from pyfiles.adapters.storage_clients import AzureStorageClient
from pyfiles.hyperion_core.sidecar_init import SidecarInit


class MetadataExporterError(Exception):
    """Raised when a metadata-exporter step fails (upload, MD5 verification,
    parallel-batch failure). Subclass of Exception so callers can disambiguate
    exporter failures from generic runtime errors."""


# Module-level handle to the currently-running exporter, set by ``run_metadata_exporter_job``.
# ``_shutdown_handler`` reads this to clean up an in-flight snapshot on SIGTERM/SIGINT.
# Must be defined at module scope so the handler doesn't NameError if a signal
# arrives before the first cron firing.
active_exporter = None


class ClusterMetadataExporter(SidecarInit):
    """Exports cluster metadata files to cloud storage with atomic retry mechanism."""


    _SENSITIVE_PATTERNS = [
        re.compile(r'AccountKey=[^;]+;?', re.IGNORECASE),
        re.compile(r'DefaultEndpointsProtocol=https?;[^"\']*AccountKey=[^;]+;?[^"\'\s]*', re.IGNORECASE),
        re.compile(r'SharedAccessSignature=[^;]+;?', re.IGNORECASE),
    ]

    @staticmethod
    def _sanitize_error_message(message: str) -> str:
        """Strip Azure connection strings and account keys from error messages."""
        sanitized = str(message)
        for pattern in ClusterMetadataExporter._SENSITIVE_PATTERNS:
            sanitized = pattern.sub('[REDACTED]', sanitized)
        return sanitized

    def __init__(self, storage_client, logger_config, project_configurations, max_retries: int = 3, retry_delay: int = 2, checkpoint_wait: int = 10, verification_threshold: float = None):
        """
        Initialize the metadata exporter.

        Args:
            storage_client: Storage client for uploading files
            logger_config: Logger instance
            max_retries: Maximum number of retry attempts for failed batch uploads
            retry_delay: Base delay in seconds between retries
            checkpoint_wait: Seconds to wait after triggering checkpoint before snapshot
            verification_threshold: Success rate threshold for granular retry (0.0-1.0)
                                  If success_rate > threshold: granular retry
                                  If success_rate <= threshold: full retry
                                  Default: Read from VERIFICATION_THRESHOLD env var, or 0.5 (50%)
        """
        self.storage_client = storage_client
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.checkpoint_wait = checkpoint_wait

        # Read verification_threshold from environment variable if not provided
        if verification_threshold is None:
            threshold_env = os.getenv('VERIFICATION_THRESHOLD', '0.5')
            try:
                self.verification_threshold = float(threshold_env)
                if not 0.0 <= self.verification_threshold <= 1.0:
                    raise ValueError(f"VERIFICATION_THRESHOLD must be between 0.0 and 1.0, got {self.verification_threshold}")
            except ValueError as e:
                raise ValueError(f"Invalid VERIFICATION_THRESHOLD value: {threshold_env}. Must be a float between 0.0 and 1.0") from e
        else:
            self.verification_threshold = verification_threshold

        self.temp_snapshot_dir = None
        super().__init__(logger_config, project_configurations)

    @staticmethod
    def _create_foldername() -> str:
        """
        Create a UTC timestamp-based folder name.

        Returns:
            str: Folder name in YYYYMMDDHHMMSS format (UTC)
        """
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")

    @staticmethod
    def _get_metadata_filepath() -> str:
        """
        Get and validate the metadata folder path from environment variables.

        Returns:
            str: Validated metadata folder path

        Raises:
            ValueError: If FE_META_FOLDER_PATH is not set
            FileNotFoundError: If the specified path does not exist
        """
        metadata_path = os.getenv('FE_META_FOLDER_PATH')
        if not metadata_path:
            raise ValueError("FE_META_FOLDER_PATH environment variable is not set")
        if not os.path.exists(metadata_path):
            raise FileNotFoundError(f"Metadata path does not exist: {metadata_path}")
        return metadata_path

    def _check_disk_space(self, metadata_path: str, multiplier: float = 1.5) -> None:
        """Check if sufficient disk space is available for creating a snapshot."""
        total_size = 0
        for dirpath, _, filenames in os.walk(metadata_path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if os.path.isfile(filepath):
                    total_size += os.path.getsize(filepath)

        required_space = int(total_size * multiplier)
        disk_usage = shutil.disk_usage(metadata_path)
        available_space = disk_usage.free

        if available_space < required_space:
            raise OSError(
                f"Insufficient disk space for snapshot. "
                f"Required: {required_space / (1024**2):.2f} MB, "
                f"Available: {available_space / (1024**2):.2f} MB"
            )

        self.logger.info(
            "Disk space check passed. Required: %.2f MB, Available: %.2f MB",
            required_space / (1024**2), available_space / (1024**2)
        )

    def _create_snapshot(self, metadata_path: str) -> str:
        """
        Create a snapshot of the metadata directory.

        Args:
            metadata_path: Source metadata directory path

        Returns:
            str: Path to the snapshot directory

        Raises:
            Exception: If snapshot creation fails
        """
        timestamp = self._create_foldername()
        snapshot_dir = os.path.join(
            metadata_path,
            f".metadata_snapshot_{timestamp}"
        )

        def ignore_snapshots(directory, contents):
            return [c for c in contents if c.startswith('.metadata_snapshot_')]

        try:
            self._check_disk_space(metadata_path)
            self.logger.info("Creating snapshot: %s -> %s", metadata_path, snapshot_dir)

            shutil.copytree(
                metadata_path,
                snapshot_dir,
                symlinks=False,
                ignore_dangling_symlinks=True,
                dirs_exist_ok=False,
                ignore=ignore_snapshots
            )

            self.logger.info("Snapshot created successfully at: %s", snapshot_dir)
            return snapshot_dir

        except Exception as e:
            self.logger.error("Failed to create snapshot: %s",
                              self._sanitize_error_message(str(e)))
            if os.path.exists(snapshot_dir):
                try:
                    shutil.rmtree(snapshot_dir)
                except Exception as cleanup_error:  # pylint: disable=broad-except
                    self.logger.error("Failed to cleanup partial snapshot: %s",
                                    self._sanitize_error_message(str(cleanup_error)))
            raise

    def _cleanup_snapshot(self, snapshot_path: str) -> None:
        """
        Remove the snapshot directory.

        Args:
            snapshot_path: Path to the snapshot directory to remove
        """
        if not snapshot_path or not os.path.exists(snapshot_path):
            return

        try:
            self.logger.info("Cleaning up snapshot: %s", snapshot_path)
            shutil.rmtree(snapshot_path)
            self.logger.info("Snapshot cleaned up successfully")
        except Exception as e:  # pylint: disable=broad-except
            self.logger.error("Failed to cleanup snapshot %s: %s",
                            snapshot_path, self._sanitize_error_message(str(e)))

    def _cleanup_orphaned_snapshots(self, metadata_path: str) -> int:
        """
        Clean up any orphaned snapshot directories from previous runs.

        Orphaned snapshots can occur if the process was killed or crashed
        before cleanup could complete. This method finds and removes any
        directories matching the pattern `.metadata_snapshot_*`.

        Args:
            metadata_path: The metadata directory to scan for orphaned snapshots

        Returns:
            int: Number of orphaned snapshots cleaned up
        """
        cleaned_count = 0

        try:
            for entry in os.listdir(metadata_path):
                if entry.startswith('.metadata_snapshot_'):
                    orphan_path = os.path.join(metadata_path, entry)
                    if os.path.isdir(orphan_path):
                        try:
                            self.logger.warning(
                                "Found orphaned snapshot from previous run: %s. Cleaning up...",
                                orphan_path
                            )
                            shutil.rmtree(orphan_path)
                            cleaned_count += 1
                            self.logger.info("Orphaned snapshot cleaned up: %s", orphan_path)
                        except Exception as e:  # pylint: disable=broad-except
                            self.logger.error(
                                "Failed to cleanup orphaned snapshot %s: %s",
                                orphan_path, self._sanitize_error_message(str(e))
                            )

            if cleaned_count > 0:
                self.logger.info("Cleaned up %d orphaned snapshot(s)", cleaned_count)

        except Exception as e:  # pylint: disable=broad-except
            self.logger.error(
                "Error scanning for orphaned snapshots: %s",
                self._sanitize_error_message(str(e))
            )

        return cleaned_count

    def _validate_snapshot(self, snapshot_path: str) -> Dict[str, int]:
        """
        Validate that a snapshot contains the expected metadata structure.

        Checks:
            - image/ subdirectory exists
            - image/ROLE file exists
            - At least one image.* checkpoint file in image/
            - bdb/ subdirectory exists
            - At least one file inside bdb/

        Args:
            snapshot_path: Path to the snapshot directory

        Returns:
            dict: Counts with keys 'image_checkpoint_files' and 'bdb_files'

        Raises:
            FileNotFoundError: If any required structure is missing
        """
        missing = []

        image_dir = os.path.join(snapshot_path, "image")
        bdb_dir = os.path.join(snapshot_path, "bdb")

        # Check image/ subdirectory
        if not os.path.isdir(image_dir):
            missing.append("image/ subdirectory not found")
        else:
            # Check image/ROLE file
            if not os.path.isfile(os.path.join(image_dir, "ROLE")):
                missing.append("image/ROLE file not found")

            # Check for at least one image.* checkpoint file
            image_checkpoint_files = [
                f for f in os.listdir(image_dir)
                if os.path.isfile(os.path.join(image_dir, f)) and f.startswith("image.")
            ]
            if not image_checkpoint_files:
                missing.append("No image.* checkpoint files found in image/")

        # Check bdb/ subdirectory
        if not os.path.isdir(bdb_dir):
            missing.append("bdb/ subdirectory not found")
        else:
            bdb_files = [
                f for f in os.listdir(bdb_dir)
                if os.path.isfile(os.path.join(bdb_dir, f))
            ]
            if not bdb_files:
                missing.append("No files found inside bdb/")

        if missing:
            raise FileNotFoundError(
                "Snapshot validation failed: " + "; ".join(missing)
            )

        return {
            "image_checkpoint_files": len(image_checkpoint_files),
            "bdb_files": len(bdb_files),
        }

    def _collect_files_to_upload(self, snapshot_path: str) -> Tuple[List[Tuple[str, str, int]], int]:
        """
        Collect all files that need to be uploaded from the snapshot.

        Args:
            snapshot_path: Snapshot directory path

        Returns:
            Tuple of (files_list, total_bytes) where files_list contains
            (local_path, relative_path, file_size) tuples
        """
        files_to_upload = []
        total_bytes = 0

        try:
            for root, _, files in os.walk(snapshot_path):
                for file in files:
                    local_path = os.path.join(root, file)

                    if not os.path.isfile(local_path):
                        self.logger.warning("Skipping non-file: %s", local_path)
                        continue

                    if not os.access(local_path, os.R_OK):
                        self.logger.warning("Skipping unreadable file: %s", local_path)
                        continue

                    file_size = os.path.getsize(local_path)
                    relative_path = os.path.relpath(local_path, snapshot_path)
                    files_to_upload.append((local_path, relative_path, file_size))
                    total_bytes += file_size

            self.logger.info("Collected %d files (%.2f MB) from snapshot",
                           len(files_to_upload), total_bytes / (1024 * 1024))

        except Exception as e:
            self.logger.error("Error collecting files: %s",
                              self._sanitize_error_message(str(e)))
            raise

        return files_to_upload, total_bytes

    def _upload_single_file(self, local_path: str, blob_path: str) -> None:
        """
        Upload a single file to storage with MD5 integrity verification.
        Files larger than 10MB are streamed to avoid memory issues.

        Args:
            local_path: Local file path to upload
            blob_path: Destination blob path in storage

        Raises:
            Exception: If upload fails for any reason
        """
        self.logger.debug("Uploading %s -> %s", local_path, blob_path)

        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"File disappeared before upload: {local_path}")

        large_file_threshold = 10 * 1024 * 1024  # 10MB

        try:
            file_size = os.path.getsize(local_path)

            if file_size > large_file_threshold:
                # Stream large files to avoid loading entirely into memory
                self.logger.debug("Streaming large file (%d bytes): %s", file_size, local_path)

                # Compute MD5 in chunks
                md5_hasher = hashlib.md5(usedforsecurity=False)
                with open(local_path, "rb") as f:
                    for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
                        md5_hasher.update(chunk)
                md5_hash = md5_hasher.digest()
                content_settings = ContentSettings(content_md5=md5_hash)

                # Stream upload
                upload_timeout = int(os.getenv('METADATA_EXPORTER_UPLOAD_TIMEOUT', '600'))
                with open(local_path, "rb") as data:
                    self.storage_client.get_metadata_backup_container_client().upload_blob(
                        name=blob_path,
                        data=data,
                        overwrite=True,
                        content_settings=content_settings,
                        length=file_size,
                        timeout=upload_timeout
                    )
            else:
                # Small files: load into memory (original behavior)
                with open(local_path, "rb") as data:
                    file_bytes = data.read()

                md5_hash = hashlib.md5(file_bytes, usedforsecurity=False).digest()
                content_settings = ContentSettings(content_md5=md5_hash)

                upload_timeout = int(os.getenv('METADATA_EXPORTER_UPLOAD_TIMEOUT', '600'))
                self.storage_client.get_metadata_backup_container_client().upload_blob(
                    name=blob_path,
                    data=file_bytes,
                    overwrite=True,
                    content_settings=content_settings,
                    timeout=upload_timeout
                )
        except IOError as e:
            self.logger.error("IO error reading file %s: %s",
                              local_path, self._sanitize_error_message(str(e)))
            raise
        except Exception as e:
            self.logger.error("Upload error for file %s: %s",
                              local_path, self._sanitize_error_message(str(e)))
            raise

    def _upload_all_files(self, folder_name: str, files_to_upload: List[Tuple[str, str, int]],
                          total_bytes: int) -> None:
        """
        Upload all files in parallel using a thread pool.

        Args:
            folder_name: Destination folder name in storage
            files_to_upload: List of (local_path, relative_path, file_size) tuples
            total_bytes: Total size of all files in bytes

        Raises:
            Exception: If any file upload fails
        """
        uploaded_files = []
        uploaded_bytes = 0
        bytes_since_last_log = 0
        files_since_last_log = 0
        failed = False
        start_time = time.monotonic()

        # Log every 100MB or 100 files, whichever comes first
        log_bytes_interval = 100 * 1024 * 1024  # 100 MB
        log_files_interval = 100

        max_workers = int(os.getenv('METADATA_EXPORTER_UPLOAD_WORKERS', '16'))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_info = {}
            for local_path, relative_path, file_size in files_to_upload:
                blob_path = f"{folder_name}/{relative_path}"
                future = executor.submit(self._upload_single_file, local_path, blob_path)
                future_to_info[future] = (blob_path, file_size)

            for future in concurrent.futures.as_completed(future_to_info):
                blob_path, file_size = future_to_info[future]
                try:
                    future.result()
                    uploaded_files.append(blob_path)
                    uploaded_bytes += file_size
                    bytes_since_last_log += file_size
                    files_since_last_log += 1

                    # Log progress every 100MB or 100 files
                    if bytes_since_last_log >= log_bytes_interval or files_since_last_log >= log_files_interval:
                        elapsed = time.monotonic() - start_time
                        speed_mbps = (uploaded_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                        percent = (uploaded_bytes / total_bytes * 100) if total_bytes > 0 else 0
                        eta_seconds = ((total_bytes - uploaded_bytes) / (uploaded_bytes / elapsed)) if uploaded_bytes > 0 and elapsed > 0 else 0

                        self.logger.info(
                            "Upload progress: %d/%d files (%.1f%%), %.2f/%.2f MB, %.2f MB/s, ETA: %.0fs",
                            len(uploaded_files), len(files_to_upload), percent,
                            uploaded_bytes / (1024 * 1024), total_bytes / (1024 * 1024),
                            speed_mbps, eta_seconds
                        )
                        bytes_since_last_log = 0
                        files_since_last_log = 0
                        time.monotonic()

                except Exception as e:
                    failed = True
                    self.logger.error("Upload failed for %s: %s",
                                    blob_path, self._sanitize_error_message(str(e)))
                    # Cancel remaining futures
                    for f in future_to_info:
                        f.cancel()
                    break

        if failed:
            self.logger.error("Upload failed at file %d/%d (%.2f MB uploaded)",
                            len(uploaded_files), len(files_to_upload),
                            uploaded_bytes / (1024 * 1024))
            self._cleanup_uploaded_files(uploaded_files)
            raise MetadataExporterError(f"Parallel upload failed after {len(uploaded_files)}/{len(files_to_upload)} files")

        elapsed = time.monotonic() - start_time
        speed_mbps = (uploaded_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0
        self.logger.info("Successfully uploaded all %d files (%.2f MB) in %.1fs (%.2f MB/s)",
                        len(uploaded_files), uploaded_bytes / (1024 * 1024), elapsed, speed_mbps)

    def _cleanup_uploaded_files(self, uploaded_files: List[str]) -> None:
        """
        Delete uploaded files in case of batch failure.

        Args:
            uploaded_files: List of blob paths that were successfully uploaded
        """
        if not uploaded_files:
            return

        self.logger.warning("Cleaning up %d partially uploaded files", len(uploaded_files))

        container_client = self.storage_client.get_metadata_backup_container_client()
        cleanup_failed = []

        for blob_path in uploaded_files:
            try:
                container_client.delete_blob(blob_path)
                self.logger.debug("Deleted: %s", blob_path)
            except Exception as e:  # pylint: disable=broad-except
                self.logger.error("Failed to delete blob %s: %s",
                                  blob_path, self._sanitize_error_message(str(e)))
                cleanup_failed.append(blob_path)

        if cleanup_failed:
            self.logger.error("Failed to cleanup %d files: %s",
                            len(cleanup_failed), cleanup_failed)

    def _cleanup_cloud_folder(self, folder_name: str) -> None:
        """
        Delete all objects in the specified cloud storage folder.
        Cloud-agnostic: works for both Azure Blob Storage and AWS S3.

        Args:
            folder_name: The folder prefix to clean up
        """
        try:
            container_client = self.storage_client.get_metadata_backup_container_client()

            # List all blobs with the folder prefix
            blobs_to_delete = list(container_client.list_blobs(name_starts_with=folder_name))

            if not blobs_to_delete:
                self.logger.info("No objects found in folder %s to clean up", folder_name)
                return

            # Delete each blob
            deleted_count = 0
            for blob in blobs_to_delete:
                try:
                    container_client.delete_blob(blob.name)
                    deleted_count += 1
                except Exception as e:  # pylint: disable=broad-except
                    self.logger.error("Failed to delete blob %s: %s",
                                    blob.name, self._sanitize_error_message(str(e)))

            self.logger.info("Cleaned up %d/%d objects from folder: %s",
                           deleted_count, len(blobs_to_delete), folder_name)

        except Exception as e:  # pylint: disable=broad-except
            self.logger.error("Error during cloud folder cleanup for %s: %s",
                            folder_name, self._sanitize_error_message(str(e)))

    def _find_missing_files(self, folder_name: str, expected_files: List[Tuple[str, str, int]]) -> List[Tuple[str, str, int]]:
        """
        Find which files are missing from cloud storage.

        Args:
            folder_name: The cloud storage folder to check
            expected_files: List of (local_path, relative_path, file_size) tuples that should exist

        Returns:
            List of (local_path, relative_path, file_size) tuples for missing files
        """
        try:
            container_client = self.storage_client.get_metadata_backup_container_client()

            # Get list of actual blobs in cloud storage
            actual_blobs = set()
            for blob in container_client.list_blobs(name_starts_with=folder_name):
                # Remove the folder prefix to get relative path
                relative_path = blob.name[len(folder_name):].lstrip('/')
                actual_blobs.add(relative_path)

            # Find which expected files are missing
            missing_files = []
            for local_path, relative_path, file_size in expected_files:
                if relative_path not in actual_blobs:
                    missing_files.append((local_path, relative_path, file_size))

            return missing_files

        except Exception as e:
            self.logger.error("Error finding missing files: %s",
                            self._sanitize_error_message(str(e)))
            raise

    def _verify_and_retry_if_needed(self, folder_name: str,
                                   all_files: List[Tuple[str, str, int]],
                                   attempt: int) -> int:
        """
        Verify uploaded files using count-based verification with smart retry.

        Trust cloud provider's upload-time MD5 validation (Azure/S3 both support this).
        Use fast count-based verification with granular retry for efficiency.

        Args:
            folder_name: The backup folder in cloud storage
            all_files: Original list of (local_path, relative_path, file_size) tuples
            attempt: Current retry attempt number

        Returns:
            int: Number of verified files

        Raises:
            Exception: If verification fails (triggers retry in outer loop)
        """
        try:
            container_client = self.storage_client.get_metadata_backup_container_client()

            # Count files
            expected_count = len(all_files)
            actual_blobs = list(container_client.list_blobs(name_starts_with=folder_name))
            actual_count = len(actual_blobs)

            self.logger.info("Verification: Expected=%d, Actual=%d files in folder %s",
                           expected_count, actual_count, folder_name)

            # Case A: Counts match - SUCCESS (fast path)
            if actual_count == expected_count:
                self.logger.info("✓ Count verification passed: %d files", actual_count)
                return actual_count

            # Case B: Extra files in cloud (M > N)
            if actual_count > expected_count:
                self.logger.warning("Extra files detected in cloud storage: expected=%d, actual=%d",
                                  expected_count, actual_count)

                # Build set of expected blob paths
                expected_blob_paths = set(f"{folder_name}/{rel_path}" for _, rel_path, _ in all_files)

                # Find and cleanup extra files
                extra_files = []
                verified_count = 0
                for blob in actual_blobs:
                    if blob.name in expected_blob_paths:
                        verified_count += 1
                    else:
                        extra_files.append(blob.name)

                # Cleanup orphaned files
                for extra_blob in extra_files:
                    try:
                        container_client.delete_blob(extra_blob)
                        self.logger.info("Deleted orphaned file: %s", extra_blob)
                    except Exception as e:  # pylint: disable=broad-except
                        self.logger.error("Failed to delete orphaned file %s: %s",
                                        extra_blob, self._sanitize_error_message(str(e)))

                # Check if all expected files are present
                if verified_count == expected_count:
                    self.logger.info("✓ All %d expected files verified after cleanup", verified_count)
                    return verified_count

                # Some expected files are still missing, fall through to Case C logic
                self.logger.warning("After cleanup: %d/%d expected files present",
                                  verified_count, expected_count)
                actual_count = verified_count

            # Case C: Missing files (M < N)
            missing_files = self._find_missing_files(folder_name, all_files)
            missing_count = len(missing_files)
            success_rate = actual_count / expected_count if expected_count > 0 else 0.0

            self.logger.warning("Missing %d files (success rate: %.1f%%, threshold: %.1f%%)",
                              missing_count, success_rate * 100, self.verification_threshold * 100)

            # Log sample of missing files (up to 10)
            sample_size = min(10, len(missing_files))
            if sample_size > 0:
                sample_missing = [rel_path for _, rel_path, _ in missing_files[:sample_size]]
                self.logger.warning("Sample missing files: %s", sample_missing)

            # Granular retry if >50% succeeded
            if success_rate > self.verification_threshold:
                self.logger.info("Success rate %.1f%% > threshold %.1f%% - attempting granular retry",
                               success_rate * 100, self.verification_threshold * 100)

                # Upload only missing files to same folder
                self.logger.info("Uploading %d missing files to existing folder", missing_count)
                missing_bytes = sum(file_size for _, _, file_size in missing_files)
                self._upload_all_files(folder_name, missing_files, missing_bytes)

                # Recursively verify again
                return self._verify_and_retry_if_needed(folder_name, all_files, attempt)

            # Full retry needed (success rate <= threshold)
            self.logger.error("Success rate %.1f%% <= threshold %.1f%% - full retry needed",
                            success_rate * 100, self.verification_threshold * 100)
            raise MetadataExporterError(
                f"Verification failed: {actual_count}/{expected_count} files present. "
                f"Success rate {success_rate:.1%} <= threshold {self.verification_threshold:.1%}. "
                f"Full retry required."
            )

        except Exception as e:
            self.logger.error("Verification failed on attempt %d: %s",
                            attempt, self._sanitize_error_message(str(e)))
            raise

    def _log_backup_result(self, status: str, folder_name: str = None,
                           total_files: int = None, verified_files: int = None,
                           attempts: int = None, error_message: str = None,
                           duration_seconds: float = None, total_size_bytes: int = None) -> None:
        """
        Log backup result to metadata_backup_log table.

        Args:
            status: 'SUCCESS' or 'FAILED'
            folder_name: Destination folder name in storage
            total_files: Number of files uploaded
            verified_files: Number of files verified after upload
            attempts: Number of upload attempts made
            error_message: Error message if failed (will be sanitized)
            duration_seconds: Duration of the backup in seconds
            total_size_bytes: Total size of all files in bytes
        """
        try:
            hostname = self.get_current_hostname() or 'unknown'
            sanitized_error = self._sanitize_error_message(error_message) if error_message else None

            engine = self.get_engine()
            with engine.connect() as conn:
                conn.execute(
                    text(
                        "INSERT INTO _hyperion_audit_.metadata_backup_log "
                        "(id, hostname, backup_timestamp, status, folder_name, total_files, verified_files, attempts, error_message, duration_seconds, total_size_bytes) "
                        "VALUES (:id, :hostname, :backup_timestamp, :status, :folder_name, :total_files, :verified_files, :attempts, :error_message, :duration_seconds, :total_size_bytes)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "hostname": hostname,
                        "backup_timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                        "status": status,
                        "folder_name": folder_name,
                        "total_files": total_files,
                        "verified_files": verified_files,
                        "attempts": attempts,
                        "error_message": sanitized_error[:2048] if sanitized_error else None,
                        "duration_seconds": duration_seconds,
                        "total_size_bytes": total_size_bytes,
                    }
                )
                conn.commit()
            self.logger.info("Backup result logged to metadata_backup_log: status=%s, verified_files=%s",
                           status, verified_files)
        except Exception as e:  # pylint: disable=broad-except
            self.logger.error("Failed to log backup result to DB: %s",
                              self._sanitize_error_message(str(e)))

    def copy_metadata_files(self) -> Dict[str, any]:
        """
        Copy metadata files to storage with atomic all-or-nothing behavior.
        Creates a snapshot first to ensure consistency during upload.

        Returns:
            dict: Summary containing:
                - total_files: Total number of files processed
                - successful: True if all files uploaded successfully
                - attempts: Number of attempts made
                - folder_name: Destination folder name

        Raises:
            ValueError: If configuration is invalid
            FileNotFoundError: If metadata path doesn't exist
            Exception: If all retry attempts fail
        """

        if not self.check_leader_fe():
            self.logger.info("Skipping backup: this FE is not the leader")
            return None

        start_time = time.monotonic()
        metadata_path = self._get_metadata_filepath()

        # Clean up any orphaned snapshots from previous runs before starting
        self._cleanup_orphaned_snapshots(metadata_path)

        snapshot_path = None
        last_exception = None
        backup_succeeded = False

        # Create snapshot once for all retry attempts
        try:
            snapshot_path = self._create_snapshot(metadata_path)
            self.temp_snapshot_dir = snapshot_path

            # Collect files from snapshot
            all_files, total_bytes = self._collect_files_to_upload(snapshot_path)

            if not all_files:
                self.logger.warning("No files found to upload in snapshot")
                duration = time.monotonic() - start_time
                self._log_backup_result(
                    status='SUCCESS', total_files=0, verified_files=0,
                    attempts=0, duration_seconds=duration, total_size_bytes=0
                )
                # Cleanup snapshot for empty case
                if snapshot_path:
                    self._cleanup_snapshot(snapshot_path)
                    self.temp_snapshot_dir = None
                return {
                    'total_files': 0,
                    'verified_files': 0,
                    'successful': True,
                    'attempts': 0,
                    'folder_name': None
                }

            # Initial folder name and files to upload
            folder_name = self._create_foldername()
            files_to_upload = all_files.copy()

            # Attempt upload with retries
            for attempt in range(1, self.max_retries + 1):
                try:
                    self.logger.info("Starting upload attempt %d/%d to folder: %s",
                                attempt, self.max_retries, folder_name)

                    # Upload files (all files on first attempt, only failed files on retry)
                    files_to_upload_bytes = sum(file_size for _, _, file_size in files_to_upload)
                    self._upload_all_files(folder_name, files_to_upload, files_to_upload_bytes)

                    # Verify and retry missing files if needed
                    verified_count = self._verify_and_retry_if_needed(
                        folder_name, all_files, attempt
                    )

                    # Success! All files verified
                    duration = time.monotonic() - start_time
                    result = {
                        'total_files': len(all_files),
                        'verified_files': verified_count,
                        'successful': True,
                        'attempts': attempt,
                        'folder_name': folder_name
                    }
                    self.logger.info("Upload and verification completed successfully: %s", result)
                    self._log_backup_result(
                        status='SUCCESS',
                        folder_name=folder_name,
                        total_files=len(all_files),
                        verified_files=verified_count,
                        attempts=attempt,
                        duration_seconds=duration,
                        total_size_bytes=total_bytes
                    )

                    # Mark success and cleanup snapshot NOW (safe after verification)
                    backup_succeeded = True
                    if snapshot_path:
                        self._cleanup_snapshot(snapshot_path)
                        self.temp_snapshot_dir = None

                    return result

                except Exception as e:  # pylint: disable=broad-except
                    last_exception = e
                    self.logger.error("Attempt %d/%d failed: %s",
                                    attempt, self.max_retries,
                                    self._sanitize_error_message(str(e)))

                    if attempt < self.max_retries:
                        # Cleanup cloud folder and retry with new folder
                        self._cleanup_cloud_folder(folder_name)
                        folder_name = self._create_foldername()
                        files_to_upload = all_files.copy()  # Reset to all files

                        sleep_time = self.retry_delay * attempt
                        self.logger.info("Retrying entire upload in %d seconds with new folder: %s",
                                       sleep_time, folder_name)
                        time.sleep(sleep_time)

            # All attempts failed
            duration = time.monotonic() - start_time
            self._log_backup_result(
                status='FAILED',
                folder_name=folder_name,
                total_files=len(all_files),
                verified_files=0,
                attempts=self.max_retries,
                error_message=str(last_exception),
                duration_seconds=duration,
                total_size_bytes=0
            )
            raise last_exception

        except Exception as e:
            # Catch early failures (snapshot creation, file collection, etc.)
            # Only log if we haven't already logged (last_exception is None)
            if last_exception is None:
                duration = time.monotonic() - start_time
                self._log_backup_result(
                    status='FAILED',
                    attempts=0,
                    error_message=str(e),
                    duration_seconds=duration,
                    total_size_bytes=0
                )
            raise

        finally:
            # Cleanup snapshot on failure (free disk space)
            # Note: On success, snapshot is already cleaned up above
            if snapshot_path and not backup_succeeded:
                self._cleanup_snapshot(snapshot_path)
                self.temp_snapshot_dir = None

def run_metadata_exporter_job(logger):
    """
    Run the metadata exporter job.

    Args:
        logger: Logger instance
    """
    global active_exporter
    try:

        logger.info("Starting Cluster Metadata Exporter job")
        project_configurations = {
            "azure.cloud_storage":
            {
                "connection_string": os.getenv('AZURE_STORAGE_ACCOUNT_CONNECTION_STRING'),
                "metadata_backup_container": os.getenv('AZURE_STORAGE_CONTAINER_METADATA_BACKUP'),
            },
            "query_server": os.getenv('SILVER_LAYER_QUERY_SERVER'),
            "username": os.getenv('SILVER_LAYER_ROOT_USERNAME'),
            "root_password": os.getenv('SILVER_LAYER_ROOT_PASSWORD')
        }

        # Validate required environment variables
        if not os.getenv('AZURE_STORAGE_ACCOUNT_CONNECTION_STRING'):
            logger.error("AZURE_STORAGE_ACCOUNT_CONNECTION_STRING not set")
            return

        if not os.getenv('AZURE_STORAGE_CONTAINER_METADATA_BACKUP'):
            logger.error("AZURE_STORAGE_CONTAINER_METADATA_BACKUP not set")
            return

        if os.getenv('CLOUD_STORAGE') == 'azure':
            storage_client = AzureStorageClient(project_configurations)
        else:
            logger.error("Unsupported CLOUD_STORAGE backend: %s",
                        os.getenv('CLOUD_STORAGE'))
            return

        exporter = ClusterMetadataExporter(storage_client, logger, project_configurations)
        active_exporter = exporter
        exporter.copy_metadata_files()

    except Exception as e:  # pylint: disable=broad-except
        logger.exception("Metadata exporter job failed: %s",
                         ClusterMetadataExporter._sanitize_error_message(str(e)))
    finally:
        active_exporter = None


if __name__ == "__main__":
    logger = None
    shutdown_event = threading.Event()

    def _shutdown_handler(signum, frame):
        signal_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        if logger:
            logger.info("Received %s, initiating graceful shutdown...", signal_name)

        # Clean up active snapshot immediately before shutdown
        if active_exporter and active_exporter.temp_snapshot_dir:
            if logger:
                logger.info("Cleaning up active snapshot before shutdown: %s",
                           active_exporter.temp_snapshot_dir)
            try:
                shutil.rmtree(active_exporter.temp_snapshot_dir)
                if logger:
                    logger.info("Active snapshot cleaned up successfully")
            except Exception as e:  # pylint: disable=broad-except
                if logger:
                    logger.error("Failed to cleanup active snapshot: %s", str(e))

        shutdown_event.set()

    try:
        logger = ClusterMetadataExporter.setup_logger(
            name='cluster_metadata_exporter_logger',
            filename=f'{os.getenv("FE_LOG_PATH")}/cluster_metadata_exporter.log',
            level=os.getenv('LOG_LEVEL', 'INFO'),
            rotate=True
        )

        # Validate cron expression
        cron_expression = os.getenv("CLUSTER_METADATA_EXPORTER_CRON_EXPRESSION")
        if not cron_expression:
            logger.error("CLUSTER_METADATA_EXPORTER_CRON_EXPRESSION not set")
            raise ValueError("CLUSTER_METADATA_EXPORTER_CRON_EXPRESSION is required")

        signal.signal(signal.SIGTERM, _shutdown_handler)
        signal.signal(signal.SIGINT, _shutdown_handler)

        scheduler = BackgroundScheduler(timezone=datetime.UTC)
        scheduler.add_job(
            run_metadata_exporter_job,
            CronTrigger.from_crontab(cron_expression),
            id="cluster_metadata_exporter",
            misfire_grace_time=300,
            max_instances=1,
            coalesce=True,
            args=[logger]
        )

        logger.info("Cluster Metadata Exporter cron job sidecar started")
        logger.info("Cron expression: %s", cron_expression)
        scheduler.start()

        shutdown_event.wait()
        logger.info("Shutdown event received, stopping scheduler...")
        scheduler.shutdown(wait=True)
        logger.info("Scheduler stopped, exiting.")

    except KeyboardInterrupt:
        # Handled by SIGINT handler, but catch here to prevent traceback
        pass
    except Exception as e:
        if logger:
            logger.exception("Fatal error: %s",
                             ClusterMetadataExporter._sanitize_error_message(str(e)))
        raise
