"""Unit tests for FHIRBatchProcessor class."""
import pytest
import json
import threading
from unittest.mock import MagicMock, patch
from queue import Queue


class TestFHIRBatchProcessorInitialization:
    """Test FHIRBatchProcessor initialization."""

    def test_initialization_stores_all_clients(self, mock_azure_config):
        """Test that initialization stores all client references."""
        from pyfiles.hyperion_core.fhir_batch_processor import FHIRBatchProcessor

        mock_storage = MagicMock()
        mock_queue = MagicMock()
        mock_fhir = MagicMock()

        processor = FHIRBatchProcessor(
            project_configurations=mock_azure_config,
            storage_client=mock_storage,
            queue_client=mock_queue,
            fhir_client=mock_fhir
        )

        assert processor.project_configurations == mock_azure_config
        assert processor.storage_client == mock_storage
        assert processor.queue_client == mock_queue
        assert processor.fhir_client == mock_fhir


class TestProcessFhirMessage:
    """Test process_fhir_message method."""

    def test_process_fhir_message_handles_shutdown_event(self, mock_azure_config):
        """Test process_fhir_message exits gracefully on shutdown."""
        from pyfiles.hyperion_core.fhir_batch_processor import FHIRBatchProcessor

        mock_queue = MagicMock()
        mock_queue.get_parameter_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_queue.receive_messages.return_value = []

        processor = FHIRBatchProcessor(
            project_configurations=mock_azure_config,
            storage_client=MagicMock(),
            queue_client=mock_queue,
            fhir_client=MagicMock()
        )

        shutdown_event = threading.Event()
        shutdown_event.set()

        message_queue = Queue()

        # Should exit without error
        processor.process_fhir_message(message_queue, 1, shutdown_event)

    @patch('pyfiles.hyperion_core.fhir_batch_processor.FHIRBatchExport')
    def test_process_fhir_message_creates_exporter(self, mock_exporter_class, mock_azure_config):
        """Test process_fhir_message creates FHIRBatchExport with correct params."""
        from pyfiles.hyperion_core.fhir_batch_processor import FHIRBatchProcessor

        # Create mock message
        batch_message = {
            'resource_type': 'Patient',
            'start_time': '2024-01-01T00:00:00Z',
            'end_time': '2024-01-02T00:00:00Z',
            'fhir_url': None,
            'page_number': 1,
            'folder_name': 'batch-load/20240101',
            'retry_count': 0,
            'retry_message': False
        }

        mock_sb_message = MagicMock()
        mock_sb_message.__str__ = lambda x: json.dumps(batch_message)

        mock_queue = MagicMock()
        mock_queue.get_parameter_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_queue.receive_messages.side_effect = [[mock_sb_message], []]
        mock_queue.read_message_body.return_value = batch_message

        mock_storage = MagicMock()
        mock_fhir = MagicMock()

        mock_exporter_instance = MagicMock()
        mock_exporter_class.return_value = mock_exporter_instance

        processor = FHIRBatchProcessor(
            project_configurations=mock_azure_config,
            storage_client=mock_storage,
            queue_client=mock_queue,
            fhir_client=mock_fhir
        )

        shutdown_event = threading.Event()

        def run_with_timeout():
            import time
            time.sleep(0.1)
            shutdown_event.set()

        timeout_thread = threading.Thread(target=run_with_timeout)
        timeout_thread.start()

        message_queue = Queue()
        processor.process_fhir_message(message_queue, 1, shutdown_event)

        timeout_thread.join()

        # Verify FHIRBatchExport was created
        mock_exporter_class.assert_called_once()
        call_kwargs = mock_exporter_class.call_args[1]
        assert call_kwargs['resource_type'] == 'Patient'
        assert call_kwargs['start_date'] == '2024-01-01T00:00:00Z'
        assert call_kwargs['end_date'] == '2024-01-02T00:00:00Z'

    @patch('pyfiles.hyperion_core.fhir_batch_processor.FHIRBatchExport')
    def test_process_fhir_message_completes_message(self, mock_exporter_class, mock_azure_config):
        """Test process_fhir_message completes the queue message."""
        from pyfiles.hyperion_core.fhir_batch_processor import FHIRBatchProcessor

        batch_message = {
            'resource_type': 'Patient',
            'start_time': '2024-01-01T00:00:00Z',
            'end_time': '2024-01-02T00:00:00Z'
        }

        mock_sb_message = MagicMock()

        mock_queue = MagicMock()
        mock_queue.get_parameter_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_queue.receive_messages.side_effect = [[mock_sb_message], []]
        mock_queue.read_message_body.return_value = batch_message

        processor = FHIRBatchProcessor(
            project_configurations=mock_azure_config,
            storage_client=MagicMock(),
            queue_client=mock_queue,
            fhir_client=MagicMock()
        )

        shutdown_event = threading.Event()

        def run_with_timeout():
            import time
            time.sleep(0.1)
            shutdown_event.set()

        timeout_thread = threading.Thread(target=run_with_timeout)
        timeout_thread.start()

        processor.process_fhir_message(Queue(), 1, shutdown_event)

        timeout_thread.join()

        mock_queue.complete_message.assert_called()


class TestFhirExporter:
    """Test fhir_exporter method."""

    @patch('pyfiles.hyperion_core.fhir_batch_processor.signal.signal')
    @patch('pyfiles.hyperion_core.fhir_batch_processor.concurrent.futures.ThreadPoolExecutor')
    def test_fhir_exporter_sets_signal_handlers(self, mock_executor, mock_signal, mock_azure_config):
        """Test fhir_exporter sets up signal handlers."""
        from pyfiles.hyperion_core.fhir_batch_processor import FHIRBatchProcessor
        import signal

        processor = FHIRBatchProcessor(
            project_configurations=mock_azure_config,
            storage_client=MagicMock(),
            queue_client=MagicMock(),
            fhir_client=MagicMock()
        )

        mock_executor_instance = MagicMock()
        mock_executor.return_value.__enter__.return_value = mock_executor_instance
        mock_executor_instance.submit.side_effect = SystemExit()

        try:
            processor.fhir_exporter()
        except SystemExit:
            pass

        signal_calls = [call[0][0] for call in mock_signal.call_args_list]
        assert signal.SIGINT in signal_calls
        assert signal.SIGTERM in signal_calls

    @patch('pyfiles.hyperion_core.fhir_batch_processor.concurrent.futures.ThreadPoolExecutor')
    def test_fhir_exporter_creates_correct_thread_count(self, mock_executor, mock_azure_config):
        """Test fhir_exporter creates correct number of threads."""
        from pyfiles.hyperion_core.fhir_batch_processor import FHIRBatchProcessor

        config = mock_azure_config.copy()
        config['processing'] = {'message': '2', 'converter_cores': '4'}

        processor = FHIRBatchProcessor(
            project_configurations=config,
            storage_client=MagicMock(),
            queue_client=MagicMock(),
            fhir_client=MagicMock()
        )

        mock_executor_instance = MagicMock()
        mock_executor.return_value.__enter__.return_value = mock_executor_instance
        mock_executor_instance.submit.side_effect = SystemExit()

        try:
            processor.fhir_exporter()
        except SystemExit:
            pass

        mock_executor.assert_called_with(max_workers=8)


class TestExceptionHandling:
    """Test exception handling in FHIRBatchProcessor."""

    @patch('pyfiles.hyperion_core.fhir_batch_processor.FHIRBatchExport')
    def test_process_fhir_message_handles_exception(self, mock_exporter_class, mock_azure_config):
        """Test process_fhir_message logs exceptions without crashing."""
        from pyfiles.hyperion_core.fhir_batch_processor import FHIRBatchProcessor

        mock_exporter_class.side_effect = Exception("Test exception")

        batch_message = {'resource_type': 'Patient'}
        mock_sb_message = MagicMock()

        mock_queue = MagicMock()
        mock_queue.get_parameter_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_queue.receive_messages.side_effect = [[mock_sb_message], []]
        mock_queue.read_message_body.return_value = batch_message

        processor = FHIRBatchProcessor(
            project_configurations=mock_azure_config,
            storage_client=MagicMock(),
            queue_client=mock_queue,
            fhir_client=MagicMock()
        )

        shutdown_event = threading.Event()

        def run_with_timeout():
            import time
            time.sleep(0.1)
            shutdown_event.set()

        timeout_thread = threading.Thread(target=run_with_timeout)
        timeout_thread.start()

        # Should re-raise so fhir_exporter() detects the dead thread via FIRST_COMPLETED
        with pytest.raises(Exception, match="Test exception"):
            processor.process_fhir_message(Queue(), 1, shutdown_event)

        timeout_thread.join()
