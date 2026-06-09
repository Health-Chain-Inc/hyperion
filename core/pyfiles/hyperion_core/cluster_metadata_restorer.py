import concurrent.futures
import datetime
import hashlib
import json
import os
import re
import shutil
import time
from typing import Dict

from sqlalchemy import text

from pyfiles.adapters.storage_clients import AzureStorageClient
from pyfiles.hyperion_core.sidecar_init import SidecarInit


# Read files in 8 MB chunks when computing MD5. Metadata files can be hundreds of MB,
# and ``open(...).read()`` would otherwise materialize the entire file in memory.
_HASH_CHUNK_BYTES = 8 * 1024 * 1024


def _hash_file_md5(path: str) -> bytes:
    """Compute the MD5 digest of a file by streaming it in 8 MB chunks.

    Avoids reading the whole file into memory; safe for the multi-hundred-MB
    metadata blobs that this restorer handles.
    """
    md5_hasher = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_HASH_CHUNK_BYTES), b""):
            md5_hasher.update(chunk)
    return md5_hasher.digest()


class MetadataRestorerError(Exception):
    """Raised when a metadata-restorer step fails (no backup found, MD5 mismatch,
    invalid staging structure, etc.). Subclass of Exception so callers can
    disambiguate restore failures from generic runtime errors."""


class ClusterMetadataRestorer(SidecarInit):
    """Restores cluster metadata files from cloud storage backup."""

    _SENSITIVE_PATTERNS = [
        re.compile(r'AccountKey=[^;]+;?', re.IGNORECASE),
        re.compile(r'DefaultEndpointsProtocol=https?;[^"\']*AccountKey=[^;]+;?[^"\'\s]*', re.IGNORECASE),
        re.compile(r'SharedAccessSignature=[^;]+;?', re.IGNORECASE),
    ]

    @staticmethod
    def _sanitize_error_message(message: str) -> str:
        """Strip Azure connection strings and account keys from error messages."""
        sanitized = str(message)
        for pattern in ClusterMetadataRestorer._SENSITIVE_PATTERNS:
            sanitized = pattern.sub('[REDACTED]', sanitized)
        return sanitized

    def __init__(self, storage_client, logger_config, project_configurations,
                 max_retries: int = 3, retry_delay: int = 2):
        """
        Initialize the metadata restorer.

        Args:
            storage_client: Storage client for downloading files
            logger_config: Logger instance
            project_configurations: DB credentials, storage config
            max_retries: Maximum number of retry attempts for failed downloads
            retry_delay: Base delay in seconds between retries
        """
        self.storage_client = storage_client
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        super().__init__(logger_config, project_configurations)

    def _get_latest_successful_backup(self) -> Dict:
        """
        Query the backup audit log to find the latest successful backup.

        Returns:
            dict: {
                'folder_name': str,
                'total_files': int,
                'backup_timestamp': datetime,
                'hostname': str
            }

        Raises:
            Exception: If no successful backup found
        """
        engine = self.get_engine()
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT folder_name, total_files, backup_timestamp, hostname "
                "FROM _hyperion_audit_.metadata_backup_log "
                "WHERE status = 'SUCCESS' "
                "ORDER BY backup_timestamp DESC "
                "LIMIT 1"
            ))
            row = result.fetchone()

        if not row:
            raise MetadataRestorerError("No successful backup found in metadata_backup_log")

        return {
            'folder_name': row[0],
            'total_files': row[1],
            'backup_timestamp': row[2],
            'hostname': row[3]
        }

    def _create_staging_directory(self) -> str:
        """
        Create a unique staging directory for this restore attempt.

        Returns:
            str: Path to staging directory

        Raises:
            Exception: If cannot create directory
        """
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
        staging_path = f"/tmp/.metadata_restore_staging_{timestamp}"

        os.makedirs(staging_path, exist_ok=True)
        self.logger.info("Created staging directory: %s", staging_path)

        return staging_path

    def _check_disk_space(self, path: str, metadata_path: str = None) -> None:
        """
        Verify sufficient disk space for metadata download and restore.

        Args:
            path: Directory path to check
            metadata_path: Existing metadata path to estimate size

        Raises:
            Exception: If insufficient disk space
        """
        # Get filesystem stats (cross-platform)
        disk_usage = shutil.disk_usage(path)
        available_bytes = disk_usage.free
        available_gb = available_bytes / (1024**3)

        # Get metadata path size (if exists, for size estimation)
        metadata_size_bytes = 0
        if metadata_path and os.path.exists(metadata_path):
            for root, _dirs, files in os.walk(metadata_path):
                for f in files:
                    fp = os.path.join(root, f)
                    if os.path.exists(fp):
                        metadata_size_bytes += os.path.getsize(fp)

        metadata_size_gb = metadata_size_bytes / (1024**3)

        # Need: staging (metadata size) + backup (metadata size) + safety margin (1.5x)
        required_gb = metadata_size_gb * 3.5 if metadata_size_gb > 0 else 1.0

        self.logger.info(
            "Disk space: %.2f GB available, %.2f GB required "
            "(metadata: %.2f GB, safety margin: 3.5x)",
            available_gb, required_gb, metadata_size_gb
        )

        if available_gb < required_gb:
            raise MetadataRestorerError(
                f"Insufficient disk space: {available_gb:.2f} GB available, "
                f"{required_gb:.2f} GB required"
            )

    def _download_single_file(self, blob_name: str, local_path: str,
                             skip_if_valid: bool = False) -> bool:
        """
        Download a single file from cloud storage with MD5 verification.
        Supports resume - skips download if file exists and MD5 matches.

        Args:
            blob_name: Full blob path in cloud storage
            local_path: Destination local file path
            skip_if_valid: If True, skip download if file exists with valid MD5

        Returns:
            bool: True if file was downloaded, False if skipped (already valid)

        Raises:
            Exception: If download or MD5 verification fails
        """
        container_client = self.storage_client.get_metadata_backup_container_client()
        blob_client = container_client.get_blob_client(blob_name)

        # Resume logic: Check if file already exists and is valid
        if skip_if_valid and os.path.exists(local_path):
            try:
                # Get blob properties (size + MD5)
                blob_props = blob_client.get_blob_properties()
                expected_md5 = blob_props.content_settings.content_md5

                # CRITICAL: MD5 must be available for verification
                if not expected_md5:
                    self.logger.warning(
                        "No MD5 available for %s, will re-download", blob_name
                    )
                    os.remove(local_path)  # Remove file without MD5
                else:
                    # Fast check: Compare file size first
                    local_size = os.path.getsize(local_path)
                    if local_size != blob_props.size:
                        self.logger.debug(
                            "Size mismatch for %s: local=%d, cloud=%d, re-downloading",
                            blob_name, local_size, blob_props.size
                        )
                        os.remove(local_path)  # Remove incomplete file
                    else:
                        # Thorough check: Verify MD5 (streamed in chunks)
                        local_md5 = _hash_file_md5(local_path)

                        if local_md5 == expected_md5:
                            self.logger.debug("Skipping valid file: %s", blob_name)
                            return False  # File is valid, skip download
                        else:
                            self.logger.warning(
                                "MD5 mismatch for %s, re-downloading", blob_name
                            )
                            os.remove(local_path)  # Remove corrupt file

            except Exception as e:
                self.logger.warning(
                    "Error checking existing file %s: %s, will re-download",
                    blob_name, str(e)
                )
                if os.path.exists(local_path):
                    os.remove(local_path)

        # Create parent directories (thread-safe with exist_ok=True)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        # Download file
        download_timeout = int(os.getenv('METADATA_RESTORER_DOWNLOAD_TIMEOUT', '600'))
        with open(local_path, 'wb') as f:
            download_stream = blob_client.download_blob(timeout=download_timeout)
            f.write(download_stream.readall())

        # CRITICAL: Verify MD5 after download (mandatory, not optional)
        expected_md5 = download_stream.properties.content_settings.content_md5
        if not expected_md5:
            raise MetadataRestorerError(
                f"No MD5 available for {blob_name} - cannot verify integrity"
            )

        local_md5 = _hash_file_md5(local_path)

        if local_md5 != expected_md5:
            raise MetadataRestorerError(
                f"MD5 mismatch for {blob_name}: "
                f"expected {expected_md5.hex()}, got {local_md5.hex()}"
            )

        self.logger.debug("Downloaded and verified: %s -> %s", blob_name, local_path)
        return True  # File was downloaded

    def _download_all_files(self, folder_name: str, staging_path: str,
                           resume: bool = False) -> Dict[str, int]:
        """
        Download all files from cloud storage folder to staging directory.
        Supports resumable downloads - on retry, skips already-valid files.

        Args:
            folder_name: Cloud storage folder name (e.g., "20260213120000")
            staging_path: Local staging directory path
            resume: If True, skip files that already exist with valid MD5

        Returns:
            dict: {
                'downloaded': int,  # Newly downloaded files
                'skipped': int,     # Already-valid files skipped
                'total': int        # downloaded + skipped
            }

        Raises:
            Exception: If download fails
        """
        container_client = self.storage_client.get_metadata_backup_container_client()

        # List all blobs in folder
        blobs = list(container_client.list_blobs(name_starts_with=folder_name))
        if not blobs:
            raise MetadataRestorerError(f"No files found in cloud folder: {folder_name}")

        total_blob_count = len(blobs)
        downloaded_count = 0
        skipped_count = 0
        total_processed = 0  # Initialize before loop for exception handler

        self.logger.info("Starting download: %d files total (resume=%s)",
                        total_blob_count, resume)

        # Parallel download with ThreadPoolExecutor
        max_workers = int(os.getenv('METADATA_RESTORER_DOWNLOAD_WORKERS', '16'))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_blob = {}
            for blob in blobs:
                # Extract relative path (remove folder prefix)
                relative_path = blob.name[len(folder_name):].lstrip('/')
                local_path = os.path.join(staging_path, relative_path)

                future = executor.submit(
                    self._download_single_file,
                    blob.name,
                    local_path,
                    skip_if_valid=resume  # Enable resume logic
                )
                future_to_blob[future] = blob.name

            for future in concurrent.futures.as_completed(future_to_blob):
                blob_name = future_to_blob[future]
                try:
                    was_downloaded = future.result()  # Returns bool
                    if was_downloaded:
                        downloaded_count += 1
                    else:
                        skipped_count += 1

                    # Progress logging (every 100 files)
                    total_processed = downloaded_count + skipped_count
                    if total_processed % 100 == 0:
                        self.logger.info(
                            "Progress: %d/%d files (%d new, %d skipped)",
                            total_processed, total_blob_count,
                            downloaded_count, skipped_count
                        )

                except Exception as e:
                    self.logger.error("Download failed for %s: %s", blob_name, str(e))
                    # Cancel remaining downloads
                    for f in future_to_blob:
                        f.cancel()
                    # Update total_processed for error message
                    total_processed = downloaded_count + skipped_count
                    raise MetadataRestorerError(
                        f"Parallel download failed at {total_processed}/{total_blob_count} "
                        f"({downloaded_count} downloaded, {skipped_count} skipped)"
                    ) from e

        total_files = downloaded_count + skipped_count

        # CRITICAL: Verify file count matches blob list
        if total_files != total_blob_count:
            raise MetadataRestorerError(
                f"File count mismatch: expected {total_blob_count}, "
                f"got {total_files} (downloaded={downloaded_count}, skipped={skipped_count})"
            )

        self.logger.info(
            "Download complete: %d downloaded, %d skipped, %d total",
            downloaded_count, skipped_count, total_files
        )

        return {
            'downloaded': downloaded_count,
            'skipped': skipped_count,
            'total': total_files
        }

    def _validate_restored_metadata(self, staging_path: str,
                                    expected_file_count: int) -> Dict[str, int]:
        """
        Validate the downloaded metadata structure and file count.
        Reuses validation logic from exporter's _validate_snapshot().

        Args:
            staging_path: Path to staging directory
            expected_file_count: Expected total files (from cloud blob list)

        Returns:
            dict: {
                'image_checkpoint_files': int,
                'bdb_files': int,
                'total_files': int
            }

        Raises:
            Exception: If validation fails
        """
        # Check for image/ subdirectory
        image_dir = os.path.join(staging_path, 'image')
        if not os.path.isdir(image_dir):
            raise MetadataRestorerError(f"Missing image/ directory in {staging_path}")

        # Check for image/ROLE file
        role_file = os.path.join(image_dir, 'ROLE')
        if not os.path.isfile(role_file):
            raise MetadataRestorerError(f"Missing image/ROLE file in {staging_path}")

        # Check for at least one image.* checkpoint file
        image_checkpoints = [
            f for f in os.listdir(image_dir)
            if f.startswith('image.') and os.path.isfile(os.path.join(image_dir, f))
        ]
        if not image_checkpoints:
            raise MetadataRestorerError(f"No image checkpoint files found in {image_dir}")

        # Check for bdb/ subdirectory
        bdb_dir = os.path.join(staging_path, 'bdb')
        if not os.path.isdir(bdb_dir):
            raise MetadataRestorerError(f"Missing bdb/ directory in {staging_path}")

        # Check for at least one file inside bdb/
        bdb_files = [
            f for f in os.listdir(bdb_dir)
            if os.path.isfile(os.path.join(bdb_dir, f))
        ]
        if not bdb_files:
            raise MetadataRestorerError(f"No files found in {bdb_dir}")

        # Count all files recursively
        total_files = 0
        for _root, _dirs, files in os.walk(staging_path):
            total_files += len(files)

        # CRITICAL: Verify total file count matches expected
        if total_files != expected_file_count:
            raise MetadataRestorerError(
                f"File count mismatch after validation: "
                f"expected {expected_file_count}, found {total_files} in staging"
            )

        self.logger.info(
            "Validation passed: %d image checkpoints, %d bdb files, %d total files",
            len(image_checkpoints), len(bdb_files), total_files
        )

        return {
            'image_checkpoint_files': len(image_checkpoints),
            'bdb_files': len(bdb_files),
            'total_files': total_files
        }

    def _check_fe_is_stopped(self) -> bool:
        """Check if the engine FE is stopped before restore.

        CRITICAL: FE must be stopped before restoring metadata to prevent corruption.

        Note on PID-only check: ``os.kill(pid, 0)`` returns success if *any* process
        exists at that PID, including a reused PID for an unrelated process. If the FE
        process exited and the OS later assigned the same PID to e.g. a shell, this
        check would report "running" incorrectly and abort the restore. For OSS
        deployments where a stronger guarantee is needed, replace with a
        ``psutil.Process(pid).name()`` check that verifies the process command
        matches an FE binary, or rely on a more authoritative orchestrator signal
        (Kubernetes pod state, systemd unit status).

        Returns:
            bool: True if FE is stopped, False if still running.
        """
        # Check if FE process is running
        fe_pid_file = os.getenv('FE_PID_FILE', '/opt/starrocks/fe/bin/fe.pid')
        if os.path.exists(fe_pid_file):
            with open(fe_pid_file, 'r', encoding='utf-8') as f:
                pid = int(f.read().strip())

            # Check if process exists
            try:
                os.kill(pid, 0)  # Signal 0 checks if process exists
                return False  # Process still running
            except OSError:
                return True  # Process not running

        return True  # No PID file, assume stopped

    def _backup_existing_metadata(self, metadata_path: str) -> str:
        """
        Create a backup of existing metadata before restore (safety measure).

        Args:
            metadata_path: Path to FE metadata directory

        Returns:
            str: Path to backup directory

        Raises:
            Exception: If backup creation fails
        """
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
        backup_path = f"{metadata_path}.pre_restore_backup_{timestamp}"

        self.logger.info("Creating pre-restore backup: %s -> %s",
                         metadata_path, backup_path)

        shutil.copytree(metadata_path, backup_path)

        self.logger.info("Pre-restore backup created at: %s", backup_path)
        return backup_path

    def _restore_metadata(self, staging_path: str, metadata_path: str) -> None:
        """
        Replace FE metadata with restored files.

        Simple approach: Delete existing, then atomic rename staging to metadata.
        Pre-restore backup already created as safety net for disaster recovery.

        Args:
            staging_path: Path to validated staging directory
            metadata_path: Destination FE metadata directory

        Raises:
            Exception: If restore fails (triggers retry in main loop)
        """
        # Remove existing metadata
        if os.path.exists(metadata_path):
            self.logger.info("Removing existing metadata: %s", metadata_path)
            shutil.rmtree(metadata_path)

        # Move staging to metadata path (atomic operation)
        self.logger.info("Restoring metadata: %s -> %s", staging_path, metadata_path)
        os.rename(staging_path, metadata_path)  # Atomic rename

        self.logger.info("Metadata restored successfully to: %s", metadata_path)

    def _cleanup_staging(self, staging_path: str) -> None:
        """
        Remove the staging directory.

        Args:
            staging_path: Path to the staging directory to remove
        """
        if not staging_path or not os.path.exists(staging_path):
            return

        try:
            self.logger.info("Cleaning up staging: %s", staging_path)
            shutil.rmtree(staging_path)
            self.logger.info("Staging cleaned up successfully")
        except Exception as e:  # pylint: disable=broad-except
            self.logger.error("Failed to cleanup staging %s: %s",
                            staging_path, self._sanitize_error_message(str(e)))

    def _write_restore_summary(self, result: Dict) -> None:
        """
        Write restore summary to marker file for quick status check.
        Main logging already done to cluster_metadata_restorer.log.

        Args:
            result: Dict with restore metrics
        """
        summary_file = "/tmp/.last_metadata_restore.json"

        try:
            with open(summary_file, 'w') as f:
                json.dump(result, f, indent=2, default=str)
            self.logger.info("Wrote restore summary to: %s", summary_file)
        except Exception as e:
            # Don't fail restore if summary file write fails
            self.logger.warning("Failed to write summary file: %s", str(e))

    def restore_metadata(self) -> Dict:
        """
        Restore cluster metadata from latest successful backup.

        Workflow:
            1. Check FE is stopped (critical safety check)
            2. Query latest successful backup from audit log
            3. Create staging directory
            4. Download all files from cloud storage
            5. Validate downloaded metadata structure
            6. Backup existing metadata (safety measure)
            7. Restore metadata (atomic move)
            8. Cleanup staging directory
            9. Log restore result

        Returns:
            dict: {
                'source_folder_name': str,
                'source_backup_timestamp': datetime,
                'total_files': int,
                'verified_files': int,
                'successful': bool,
                'attempts': int
            }

        Raises:
            Exception: If restore fails
        """
        start_time = time.monotonic()
        staging_path = None
        attempt = 0

        try:
            # Step 1: Safety check - FE must be stopped
            if not self._check_fe_is_stopped():
                raise MetadataRestorerError(
                    "Engine FE is still running. "
                    "Stop FE before restoring metadata to prevent corruption."
                )

            # Step 2: Find latest successful backup
            backup_info = self._get_latest_successful_backup()
            folder_name = backup_info['folder_name']
            self.logger.info("Found latest backup: %s (from %s)",
                             folder_name, backup_info['backup_timestamp'])

            # Step 3: Create staging directory
            staging_path = self._create_staging_directory()

            # Check disk space before download
            metadata_path = os.getenv('FE_META_FOLDER_PATH')
            self._check_disk_space(staging_path, metadata_path)

            # Step 4: Download all files (with retry and resume)
            download_result = None
            for attempt in range(1, self.max_retries + 1):
                try:
                    self.logger.info("Download attempt %d/%d", attempt, self.max_retries)

                    # Enable resume on retry attempts (skips already-valid files)
                    resume = (attempt > 1)
                    if resume:
                        self.logger.info(
                            "Resuming download - will skip already-valid files"
                        )

                    # Download with resume support
                    download_result = self._download_all_files(
                        folder_name,
                        staging_path,
                        resume=resume
                    )

                    self.logger.info(
                        "Download succeeded: %d total files "
                        "(%d downloaded, %d skipped)",
                        download_result['total'],
                        download_result['downloaded'],
                        download_result['skipped']
                    )
                    break  # Success, exit retry loop

                except Exception as e:
                    if attempt < self.max_retries:
                        sleep_time = self.retry_delay * attempt
                        self.logger.warning(
                            "Download failed (attempt %d/%d), will resume in %ds: %s",
                            attempt, self.max_retries, sleep_time, str(e)
                        )
                        time.sleep(sleep_time)
                        # Keep staging directory for resume
                    else:
                        self.logger.error(
                            "Download failed after %d attempts", self.max_retries
                        )
                        self._cleanup_staging(staging_path)
                        raise

            # Step 5: Validate downloaded structure and file count
            validation_result = self._validate_restored_metadata(
                staging_path,
                expected_file_count=download_result['total']
            )
            self.logger.info("Validation passed: %s", validation_result)

            # Step 6: Backup existing metadata (safety)
            if os.path.exists(metadata_path):
                self._backup_existing_metadata(metadata_path)

            # Step 7: Restore metadata (atomic move)
            self._restore_metadata(staging_path, metadata_path)
            staging_path = None  # Moved, don't cleanup

            # Step 8: Log success and write summary
            duration = time.monotonic() - start_time
            total_files = download_result['total']
            result = {
                'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'hostname': self.get_current_hostname(),
                'status': 'SUCCESS',
                'source_folder_name': folder_name,
                'source_backup_timestamp': backup_info['backup_timestamp'].isoformat(),
                'total_files': total_files,
                'verified_files': total_files,
                'attempts': attempt,
                'duration_seconds': duration,
                'error_message': None
            }

            self.logger.info("Restore completed successfully: %s", result)
            self._write_restore_summary(result)

            return result

        except Exception as e:
            # Log failure and write summary
            duration = time.monotonic() - start_time
            error_msg = self._sanitize_error_message(str(e))

            result = {
                'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'hostname': self.get_current_hostname(),
                'status': 'FAILED',
                'source_folder_name': None,
                'source_backup_timestamp': None,
                'total_files': 0,
                'verified_files': 0,
                'attempts': attempt if attempt > 0 else self.max_retries,
                'duration_seconds': duration,
                'error_message': error_msg
            }

            self.logger.error("Restore failed: %s", result)
            self._write_restore_summary(result)

            raise

        finally:
            # Cleanup staging on failure
            if staging_path and os.path.exists(staging_path):
                self._cleanup_staging(staging_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Restore engine FE metadata')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be restored without restoring')
    args = parser.parse_args()

    logger = ClusterMetadataRestorer.setup_logger(
        name='cluster_metadata_restorer_logger',
        filename=f'{os.getenv("FE_LOG_PATH")}/cluster_metadata_restorer.log',
        level=os.getenv('LOG_LEVEL', 'INFO'),
        rotate=True
    )

    project_configurations = {
        "azure.cloud_storage": {
            "connection_string": os.getenv('AZURE_STORAGE_ACCOUNT_CONNECTION_STRING'),
            "metadata_backup_container": os.getenv('AZURE_STORAGE_CONTAINER_METADATA_BACKUP'),
        },
        "query_server": os.getenv('SILVER_LAYER_QUERY_SERVER'),
        "username": os.getenv('SILVER_LAYER_ROOT_USERNAME'),
        "root_password": os.getenv('SILVER_LAYER_ROOT_PASSWORD')
    }

    storage_client = AzureStorageClient(project_configurations)
    restorer = ClusterMetadataRestorer(storage_client, logger, project_configurations)

    if args.dry_run:
        backup_info = restorer._get_latest_successful_backup()
        logger.info("Would restore from: %s", backup_info)
    else:
        result = restorer.restore_metadata()
        logger.info("Restore result: %s", result)
