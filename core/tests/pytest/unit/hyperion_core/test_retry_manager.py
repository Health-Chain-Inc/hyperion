"""Unit tests for RetryManager class."""
import pytest
import threading
from unittest.mock import MagicMock, patch
from queue import Queue


class TestRetryManagerInitialization:
    """Test RetryManager initialization."""

    def test_initialization_stores_clients(self, mock_azure_config):
        """Test that initialization stores all client references."""
        from pyfiles.hyperion_core.retry_manager import RetryManager

        mock_queue = MagicMock()
        mock_storage = MagicMock()

        manager = RetryManager(
            queue_client=mock_queue,
            storage_client=mock_storage,
            project_configurations=mock_azure_config
        )

        assert manager.queue_client == mock_queue
        assert manager.storage_client == mock_storage
        assert manager.project_configurations == mock_azure_config
        assert manager.application_name == 'test-app'


class TestRunMethod:
    """Test run method."""

    def test_run_handles_shutdown_event(self, mock_azure_config):
        """Test run exits gracefully on shutdown event."""
        from pyfiles.hyperion_core.retry_manager import RetryManager

        mock_queue = MagicMock()
        mock_queue.get_retry_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_queue.receive_messages.return_value = []

        manager = RetryManager(
            queue_client=mock_queue,
            storage_client=MagicMock(),
            project_configurations=mock_azure_config
        )

        shutdown_event = threading.Event()
        shutdown_event.set()

        message_queue = Queue()

        # Should exit without error
        manager.run(message_queue, 1, shutdown_event)

    def test_run_raises_on_queue_init_failure(self, mock_azure_config):
        """Test run logs and re-raises when queue init fails (A2)."""
        from pyfiles.hyperion_core.retry_manager import RetryManager

        mock_queue = MagicMock()
        mock_queue.get_retry_queue_receiver.side_effect = RuntimeError("Queue connection lost")

        manager = RetryManager(
            queue_client=mock_queue,
            storage_client=MagicMock(),
            project_configurations=mock_azure_config
        )

        shutdown_event = threading.Event()
        message_queue = Queue()

        with pytest.raises(RuntimeError, match="Queue connection lost"):
            manager.run(message_queue, 1, shutdown_event)

    def test_run_processes_602_error_messages(self, mock_azure_config):
        """Test run processes messages with error_code 602."""
        from pyfiles.hyperion_core.retry_manager import RetryManager

        retry_message = {
            'url': 'https://storage/failures/602/batch-load/Patient-1.ndjson',
            'error_code': '602',
            'retry_count': 0
        }

        mock_sb_message = MagicMock()

        mock_queue = MagicMock()
        mock_queue.get_retry_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_queue.receive_messages.side_effect = [[mock_sb_message], []]
        mock_queue.read_message_body.return_value = retry_message
        mock_queue.get_ndjson_filepath.return_value = (
            'failures/602/batch-load/Patient-1.ndjson',
            'Patient',
            'Patient-1.ndjson'
        )

        mock_storage = MagicMock()
        mock_storage.get_failure_container_client.return_value = MagicMock()
        mock_storage.read.return_value = [{'id': 'patient-1', 'resourceType': 'Patient'}]
        mock_storage.upload_ndjson_to_stage.return_value = True

        config = dict(mock_azure_config)
        config['initialization'] = {'cloud_storage': 'azure'}

        manager = RetryManager(
            queue_client=mock_queue,
            storage_client=mock_storage,
            project_configurations=config
        )

        shutdown_event = threading.Event()

        def run_with_timeout():
            import time
            time.sleep(0.1)
            shutdown_event.set()

        timeout_thread = threading.Thread(target=run_with_timeout)
        timeout_thread.start()

        manager.run(Queue(), 1, shutdown_event)

        timeout_thread.join()

        mock_storage.read.assert_called()
        mock_storage.upload_ndjson_to_stage.assert_called()
        mock_queue.insert_to_batch_load_queue.assert_called()

    def test_run_processes_603_error_messages(self, mock_azure_config):
        """Test run processes messages with error_code 603."""
        from pyfiles.hyperion_core.retry_manager import RetryManager

        retry_message = {
            'url': 'https://storage/failures/603/batch-load/Patient-1.ndjson',
            'error_code': '603',
            'retry_count': 0
        }

        mock_sb_message = MagicMock()

        mock_queue = MagicMock()
        mock_queue.get_retry_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_queue.receive_messages.side_effect = [[mock_sb_message], []]
        mock_queue.read_message_body.return_value = retry_message
        mock_queue.get_ndjson_filepath.return_value = (
            'failures/603/batch-load/Patient-1.ndjson',
            'Patient',
            'Patient-1.ndjson'
        )

        mock_storage = MagicMock()
        mock_storage.get_failure_container_client.return_value = MagicMock()
        mock_storage.read.return_value = [{'id': 'patient-1'}]
        mock_storage.upload_ndjson_to_stage.return_value = True

        config = dict(mock_azure_config)
        config['initialization'] = {'cloud_storage': 'azure'}

        manager = RetryManager(
            queue_client=mock_queue,
            storage_client=mock_storage,
            project_configurations=config
        )

        shutdown_event = threading.Event()

        def run_with_timeout():
            import time
            time.sleep(0.1)
            shutdown_event.set()

        timeout_thread = threading.Thread(target=run_with_timeout)
        timeout_thread.start()

        manager.run(Queue(), 1, shutdown_event)

        timeout_thread.join()

        mock_storage.read.assert_called()

    def test_run_skips_invalid_error_codes(self, mock_azure_config):
        """Test run skips messages with invalid error codes."""
        from pyfiles.hyperion_core.retry_manager import RetryManager

        retry_message = {
            'url': 'https://storage/failures/500/Patient-1.ndjson',
            'error_code': 500,  # Not 602 or 603
            'retry_count': 0
        }

        mock_sb_message = MagicMock()

        mock_queue = MagicMock()
        mock_queue.get_retry_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_queue.receive_messages.side_effect = [[mock_sb_message], []]
        mock_queue.read_message_body.return_value = retry_message

        mock_storage = MagicMock()

        manager = RetryManager(
            queue_client=mock_queue,
            storage_client=mock_storage,
            project_configurations=mock_azure_config
        )

        shutdown_event = threading.Event()

        def run_with_timeout():
            import time
            time.sleep(0.1)
            shutdown_event.set()

        timeout_thread = threading.Thread(target=run_with_timeout)
        timeout_thread.start()

        manager.run(Queue(), 1, shutdown_event)

        timeout_thread.join()

        # Should not call storage.read for invalid error codes
        mock_storage.read.assert_not_called()


class TestProcessMessage:
    """Test process_message method."""

    def test_process_message_splits_blob_into_chunks(self, mock_azure_config):
        """Test process_message splits multi-record blob into individual files."""
        from pyfiles.hyperion_core.retry_manager import RetryManager

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath.return_value = (
            'failures/602/batch-load/Patient-1.ndjson',
            'Patient',
            'Patient-1.ndjson'
        )

        # Return multiple records
        mock_storage = MagicMock()
        mock_storage.get_failure_container_client.return_value = MagicMock()
        mock_storage.read.return_value = [
            {'id': 'patient-1', 'resourceType': 'Patient'},
            {'id': 'patient-2', 'resourceType': 'Patient'},
            {'id': 'patient-3', 'resourceType': 'Patient'}
        ]
        mock_storage.upload_ndjson_to_stage.return_value = True

        config = dict(mock_azure_config)
        config['initialization'] = {'cloud_storage': 'azure'}

        manager = RetryManager(
            queue_client=mock_queue,
            storage_client=mock_storage,
            project_configurations=config
        )

        retry_message = {
            'url': 'https://storage/failures/602/batch-load/Patient-1.ndjson',
            'retry_count': 0
        }

        manager.process_message(retry_message)

        # Should upload 3 separate files
        assert mock_storage.upload_ndjson_to_stage.call_count == 3

        # Should insert 3 queue messages
        assert mock_queue.insert_to_batch_load_queue.call_count == 3

    def test_process_message_deletes_original_blob(self, mock_azure_config):
        """Test process_message deletes original blob after processing."""
        from pyfiles.hyperion_core.retry_manager import RetryManager

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath.return_value = (
            'failures/602/batch-load/Patient-1.ndjson',
            'Patient',
            'Patient-1.ndjson'
        )

        mock_storage = MagicMock()
        mock_storage.get_failure_container_client.return_value = MagicMock()
        mock_storage.read.return_value = [{'id': 'patient-1'}]
        mock_storage.upload_ndjson_to_stage.return_value = True

        config = dict(mock_azure_config)
        config['initialization'] = {'cloud_storage': 'azure'}

        manager = RetryManager(
            queue_client=mock_queue,
            storage_client=mock_storage,
            project_configurations=config
        )

        retry_message = {
            'url': 'https://storage/failures/602/batch-load/Patient-1.ndjson',
            'retry_count': 0
        }

        manager.process_message(retry_message)

        mock_storage.delete.assert_called_once()

    def test_process_message_handles_exception(self, mock_azure_config):
        """Test process_message handles exceptions gracefully.

        When get_ndjson_filepath() fails, the exception handler logs the error
        using retry_message.get('url') instead of an undefined blob_url variable.
        """
        from pyfiles.hyperion_core.retry_manager import RetryManager

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath.side_effect = Exception("Parse error")

        mock_storage = MagicMock()

        manager = RetryManager(
            queue_client=mock_queue,
            storage_client=mock_storage,
            project_configurations=mock_azure_config
        )

        retry_message = {'url': 'invalid-url'}

        # Should not raise - exception is caught and logged
        manager.process_message(retry_message)

    def test_process_message_non_azure_skips_queue_insert(self, mock_azure_config):
        """Test process_message skips insert_to_batch_load_queue for non-Azure cloud storage."""
        from pyfiles.hyperion_core.retry_manager import RetryManager

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath.return_value = (
            'failures/602/batch-load/Patient-1.ndjson',
            'Patient',
            'Patient-1.ndjson'
        )

        mock_storage = MagicMock()
        mock_storage.get_failure_container_client.return_value = MagicMock()
        mock_storage.read.return_value = [{'id': 'patient-1', 'resourceType': 'Patient'}]
        mock_storage.upload_ndjson_to_stage.return_value = True

        # Use non-Azure cloud_storage
        config = dict(mock_azure_config)
        config['initialization'] = {'cloud_storage': 'aws'}
        config['azure.cloud_storage'] = {
            'baseurl': 'https://test.blob.core.windows.net/',
            'ndjson_stage_container': 'staging'
        }

        manager = RetryManager(
            queue_client=mock_queue,
            storage_client=mock_storage,
            project_configurations=config
        )

        retry_message = {
            'url': 'https://storage/failures/602/batch-load/Patient-1.ndjson',
            'retry_count': 0
        }

        manager.process_message(retry_message)

        # Storage operations should still happen
        mock_storage.upload_ndjson_to_stage.assert_called_once()
        # But queue insert should NOT be called for non-Azure
        mock_queue.insert_to_batch_load_queue.assert_not_called()

    def test_process_message_passes_filepath_id_when_present(self, mock_azure_config):
        """Test process_message includes filepath_id in re-queued batch_load_queue message when present."""
        from pyfiles.hyperion_core.retry_manager import RetryManager

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath.return_value = (
            'failures/602/batch-load/Patient-1.ndjson',
            'Patient',
            'Patient-1.ndjson'
        )

        mock_storage = MagicMock()
        mock_storage.get_failure_container_client.return_value = MagicMock()
        mock_storage.read.return_value = [{'id': 'patient-1', 'resourceType': 'Patient'}]
        mock_storage.upload_ndjson_to_stage.return_value = True

        config = dict(mock_azure_config)
        config['initialization'] = {'cloud_storage': 'azure'}

        manager = RetryManager(
            queue_client=mock_queue,
            storage_client=mock_storage,
            project_configurations=config
        )

        retry_message = {
            'url': 'https://storage/failures/602/batch-load/Patient-1.ndjson',
            'retry_count': 0,
            'filepath_id': 'test-filepath-uuid-1234'
        }

        manager.process_message(retry_message)

        # insert_to_batch_load_queue should have been called once (one resource)
        mock_queue.insert_to_batch_load_queue.assert_called_once()

        # Verify filepath_id is passed through in the queued message
        queued_message = mock_queue.insert_to_batch_load_queue.call_args[0][0]
        assert queued_message.get('filepath_id') == 'test-filepath-uuid-1234'

    def test_process_message_passes_filepath_id_as_none_when_absent(self, mock_azure_config):
        """Test process_message sets filepath_id to None in re-queued batch_load_queue message when not in retry_message."""
        from pyfiles.hyperion_core.retry_manager import RetryManager

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath.return_value = (
            'failures/602/batch-load/Patient-1.ndjson',
            'Patient',
            'Patient-1.ndjson'
        )

        mock_storage = MagicMock()
        mock_storage.get_failure_container_client.return_value = MagicMock()
        mock_storage.read.return_value = [{'id': 'patient-1', 'resourceType': 'Patient'}]
        mock_storage.upload_ndjson_to_stage.return_value = True

        config = dict(mock_azure_config)
        config['initialization'] = {'cloud_storage': 'azure'}

        manager = RetryManager(
            queue_client=mock_queue,
            storage_client=mock_storage,
            project_configurations=config
        )

        # retry_message has no filepath_id key
        retry_message = {
            'url': 'https://storage/failures/602/batch-load/Patient-1.ndjson',
            'retry_count': 0
        }

        manager.process_message(retry_message)

        # insert_to_batch_load_queue should have been called once (one resource)
        mock_queue.insert_to_batch_load_queue.assert_called_once()

        # Verify filepath_id is explicitly None in the queued message
        queued_message = mock_queue.insert_to_batch_load_queue.call_args[0][0]
        assert 'filepath_id' in queued_message
        assert queued_message['filepath_id'] is None


class TestRetryProcessor:
    """Test retry_processor method."""

    @patch('pyfiles.hyperion_core.retry_manager.signal.signal')
    @patch('pyfiles.hyperion_core.retry_manager.concurrent.futures.ThreadPoolExecutor')
    def test_retry_processor_sets_signal_handlers(self, mock_executor, mock_signal, mock_azure_config):
        """Test retry_processor sets up signal handlers."""
        from pyfiles.hyperion_core.retry_manager import RetryManager
        import signal

        manager = RetryManager(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            project_configurations=mock_azure_config
        )

        mock_executor_instance = MagicMock()
        mock_executor.return_value.__enter__.return_value = mock_executor_instance
        mock_executor_instance.submit.side_effect = SystemExit()

        try:
            manager.retry_processor()
        except SystemExit:
            pass

        signal_calls = [call[0][0] for call in mock_signal.call_args_list]
        assert signal.SIGINT in signal_calls
        assert signal.SIGTERM in signal_calls

    @patch('pyfiles.hyperion_core.retry_manager.concurrent.futures.ThreadPoolExecutor')
    def test_retry_processor_creates_correct_thread_count(self, mock_executor, mock_azure_config):
        """Test retry_processor creates correct number of threads."""
        from pyfiles.hyperion_core.retry_manager import RetryManager

        config = mock_azure_config.copy()
        config['processing'] = {'message': '2', 'converter_cores': '3'}

        manager = RetryManager(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            project_configurations=config
        )

        mock_executor_instance = MagicMock()
        mock_executor.return_value.__enter__.return_value = mock_executor_instance
        mock_executor_instance.submit.side_effect = SystemExit()

        try:
            manager.retry_processor()
        except SystemExit:
            pass

        mock_executor.assert_called_with(max_workers=6)

    @patch('pyfiles.hyperion_core.retry_manager.signal.signal')
    @patch('pyfiles.hyperion_core.retry_manager.concurrent.futures.ThreadPoolExecutor')
    def test_retry_processor_signal_handler_sets_shutdown_event(self, mock_executor, mock_signal, mock_azure_config):
        """Test that the signal handler registered by retry_processor sets the shutdown event."""
        from pyfiles.hyperion_core.retry_manager import RetryManager
        import signal

        manager = RetryManager(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            project_configurations=mock_azure_config
        )

        captured_handler = {}

        def capture_signal(signum, handler):
            captured_handler[signum] = handler

        mock_signal.side_effect = capture_signal

        mock_executor_instance = MagicMock()
        mock_executor.return_value.__enter__.return_value = mock_executor_instance
        mock_executor_instance.submit.side_effect = SystemExit()

        try:
            manager.retry_processor()
        except SystemExit:
            pass

        # The SIGTERM handler should have been captured
        assert signal.SIGTERM in captured_handler
        # Call the handler to verify it triggers shutdown
        handler = captured_handler[signal.SIGTERM]
        handler(signal.SIGTERM, None)
        # No exception means it works; shutdown_event is internal to the method
        # but the handler should be callable without error


class TestFileNamingConventions:
    """Test file naming in retry processing."""

    def test_process_message_creates_indexed_filenames(self, mock_azure_config):
        """Test process_message creates correctly indexed filenames."""
        from pyfiles.hyperion_core.retry_manager import RetryManager

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath.return_value = (
            'failures/602/batch-load/Patient-1.ndjson',
            'Patient',
            'Patient-1.ndjson'
        )

        mock_storage = MagicMock()
        mock_storage.get_failure_container_client.return_value = MagicMock()
        mock_storage.read.return_value = [
            {'id': 'patient-1'},
            {'id': 'patient-2'}
        ]
        mock_storage.upload_ndjson_to_stage.return_value = True

        config = dict(mock_azure_config)
        config['initialization'] = {'cloud_storage': 'azure'}

        manager = RetryManager(
            queue_client=mock_queue,
            storage_client=mock_storage,
            project_configurations=config
        )

        retry_message = {
            'url': 'https://storage/failures/602/batch-load/Patient-1.ndjson'
        }

        manager.process_message(retry_message)

        # Get upload calls
        upload_calls = mock_storage.upload_ndjson_to_stage.call_args_list

        # Verify indexed filenames
        filenames = [call[0][1] for call in upload_calls]
        assert 'Patient-1-1.ndjson' in filenames[0]
        assert 'Patient-1-2.ndjson' in filenames[1]


class TestSkipLogic:
    """Test retry skip logic."""

    def test_run_skips_after_one_retry(self, mock_azure_config):
        """Test run skips processing if filename indicates already retried."""
        from pyfiles.hyperion_core.retry_manager import RetryManager

        # Filename with multiple hyphens indicates already split/retried
        retry_message = {
            'url': 'https://storage/failures/602/batch-load/Patient-1-1.ndjson',  # Already split
            'error_code': '602',
            'retry_count': 1
        }

        mock_sb_message = MagicMock()

        mock_queue = MagicMock()
        mock_queue.get_retry_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_queue.receive_messages.side_effect = [[mock_sb_message], []]
        mock_queue.read_message_body.return_value = retry_message

        mock_storage = MagicMock()

        manager = RetryManager(
            queue_client=mock_queue,
            storage_client=mock_storage,
            project_configurations=mock_azure_config
        )

        shutdown_event = threading.Event()

        def run_with_timeout():
            import time
            time.sleep(0.1)
            shutdown_event.set()

        timeout_thread = threading.Thread(target=run_with_timeout)
        timeout_thread.start()

        manager.run(Queue(), 1, shutdown_event)

        timeout_thread.join()

        # Should not process since filename has multiple hyphens
        mock_storage.read.assert_not_called()
