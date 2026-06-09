"""Unit tests for FHIREventProcessor class."""
import pytest
import threading
from unittest.mock import MagicMock, patch
from queue import Queue

from pyfiles.dependencies.data_processing_error import DataProcessingException


class TestFHIREventProcessorInitialization:
    """Test FHIREventProcessor initialization."""

    def test_initialization_stores_all_clients(self, mock_azure_config):
        """Test that initialization stores all client references."""
        from pyfiles.hyperion_core.fhir_event_processor import FHIREventProcessor

        mock_storage = MagicMock()
        mock_queue = MagicMock()
        mock_fhir = MagicMock()

        processor = FHIREventProcessor(
            configurations=mock_azure_config,
            storage_client=mock_storage,
            queue_client=mock_queue,
            fhir_client=mock_fhir
        )

        assert processor.project_configurations == mock_azure_config
        assert processor.storage_client == mock_storage
        assert processor.queue_client == mock_queue
        assert processor.fhir_client == mock_fhir

    def test_initialization_sets_application_name(self, mock_azure_config):
        """Test that initialization sets application name from enum."""
        from pyfiles.hyperion_core.fhir_event_processor import FHIREventProcessor
        from pyfiles.dependencies.enum import ApplicationEnums

        processor = FHIREventProcessor(
            configurations=mock_azure_config,
            storage_client=MagicMock(),
            queue_client=MagicMock(),
            fhir_client=MagicMock()
        )

        assert processor.application_name == ApplicationEnums.EVENT_LOAD_EXPORTER.value


class TestProcessFhirEventMessage:
    """Test process_fhir_event_message method."""

    def test_process_fhir_event_message_handles_shutdown(self, mock_azure_config):
        """Test process_fhir_event_message exits gracefully on shutdown."""
        from pyfiles.hyperion_core.fhir_event_processor import FHIREventProcessor

        mock_queue = MagicMock()
        mock_queue.get_event_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_queue.receive_messages.return_value = []

        processor = FHIREventProcessor(
            configurations=mock_azure_config,
            storage_client=MagicMock(),
            queue_client=mock_queue,
            fhir_client=MagicMock()
        )

        shutdown_event = threading.Event()
        shutdown_event.set()

        message_queue = Queue()

        # Should exit without error
        processor.process_fhir_event_message(message_queue, 1, shutdown_event)

    @patch('pyfiles.hyperion_core.fhir_event_processor.FHIREventExporter')
    def test_process_fhir_event_message_creates_exporter(self, mock_exporter_class, mock_azure_config):
        """Test process_fhir_event_message creates FHIREventExporter."""
        from pyfiles.hyperion_core.fhir_event_processor import FHIREventProcessor

        event_message = {
            'resourceType': 'Patient',
            'id': 'patient-123',
            'action': 'create'
        }

        mock_sb_message = MagicMock()

        mock_queue = MagicMock()
        mock_queue.get_event_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_queue.receive_messages.side_effect = [[mock_sb_message], []]
        mock_queue.read_message_body.return_value = event_message

        mock_exporter_instance = MagicMock()
        mock_exporter_class.return_value = mock_exporter_instance

        processor = FHIREventProcessor(
            configurations=mock_azure_config,
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

        processor.process_fhir_event_message(Queue(), 1, shutdown_event)

        timeout_thread.join()

        mock_exporter_class.assert_called_once()
        mock_exporter_instance.run.assert_called_once()

    @patch('pyfiles.hyperion_core.fhir_event_processor.FHIREventExporter')
    def test_process_fhir_event_message_handles_data_processing_exception(self, mock_exporter_class, mock_azure_config):
        """Test process_fhir_event_message handles DataProcessingException."""
        from pyfiles.hyperion_core.fhir_event_processor import FHIREventProcessor

        event_message = {
            'resourceType': 'Patient',
            'id': 'patient-123'
        }

        mock_sb_message = MagicMock()

        mock_queue = MagicMock()
        mock_queue.get_event_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_queue.receive_messages.side_effect = [[mock_sb_message], []]
        mock_queue.read_message_body.return_value = event_message

        # Make exporter raise DataProcessingException
        mock_dpe = DataProcessingException("Test error", "error details", "500")
        mock_dpe.fhirpullerror = MagicMock()

        mock_exporter_instance = MagicMock()
        mock_exporter_instance.run.side_effect = mock_dpe
        mock_exporter_class.return_value = mock_exporter_instance

        processor = FHIREventProcessor(
            configurations=mock_azure_config,
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

        # Should not raise
        processor.process_fhir_event_message(Queue(), 1, shutdown_event)

        timeout_thread.join()

        # Verify fhirpullerror was called
        mock_dpe.fhirpullerror.assert_called_once()

    def test_process_fhir_event_message_completes_message(self, mock_azure_config):
        """Test process_fhir_event_message completes queue message."""
        from pyfiles.hyperion_core.fhir_event_processor import FHIREventProcessor

        mock_sb_message = MagicMock()

        mock_queue = MagicMock()
        mock_queue.get_event_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_queue.receive_messages.side_effect = [[mock_sb_message], []]
        mock_queue.read_message_body.return_value = {'resourceType': 'Patient', 'id': 'test'}

        with patch('pyfiles.hyperion_core.fhir_event_processor.FHIREventExporter'):
            processor = FHIREventProcessor(
                configurations=mock_azure_config,
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

            processor.process_fhir_event_message(Queue(), 1, shutdown_event)

            timeout_thread.join()

            mock_queue.complete_message.assert_called()


    def test_process_fhir_event_message_raises_on_unhandled_exception(self, mock_azure_config):
        """Test process_fhir_event_message logs and re-raises non-DPE exceptions (G1)."""
        from pyfiles.hyperion_core.fhir_event_processor import FHIREventProcessor

        mock_queue = MagicMock()
        # Queue init fails with a non-DPE exception
        mock_queue.get_event_queue_receiver.side_effect = RuntimeError("Queue connection lost")

        processor = FHIREventProcessor(
            configurations=mock_azure_config,
            storage_client=MagicMock(),
            queue_client=mock_queue,
            fhir_client=MagicMock()
        )

        shutdown_event = threading.Event()
        message_queue = Queue()

        # Should raise the exception (thread must not die silently)
        with pytest.raises(RuntimeError, match="Queue connection lost"):
            processor.process_fhir_event_message(message_queue, 1, shutdown_event)

    @patch('pyfiles.hyperion_core.fhir_event_processor.FHIREventExporter')
    def test_process_fhir_event_message_recovery_failure_does_not_kill_thread(self, mock_exporter_class, mock_azure_config):
        """Test that if DPE recovery (fhirpullerror) fails, thread continues processing (G2-event)."""
        from pyfiles.hyperion_core.fhir_event_processor import FHIREventProcessor

        event_message = {
            'resourceType': 'Patient',
            'id': 'patient-123'
        }

        mock_sb_message = MagicMock()

        mock_queue = MagicMock()
        mock_queue.get_event_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_queue.receive_messages.side_effect = [[mock_sb_message], []]
        mock_queue.read_message_body.return_value = event_message

        # Make exporter raise DPE, then make fhirpullerror also fail
        mock_dpe = DataProcessingException("Test error", "error details", "500")
        mock_dpe.fhirpullerror = MagicMock(side_effect=RuntimeError("storage down"))

        mock_exporter_instance = MagicMock()
        mock_exporter_instance.run.side_effect = mock_dpe
        mock_exporter_class.return_value = mock_exporter_instance

        processor = FHIREventProcessor(
            configurations=mock_azure_config,
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

        # Should NOT raise — recovery failure is caught, thread continues
        processor.process_fhir_event_message(Queue(), 1, shutdown_event)

        timeout_thread.join()


class TestFhirEventExporter:
    """Test fhir_event_exporter method."""

    @patch('pyfiles.hyperion_core.fhir_event_processor.signal.signal')
    @patch('pyfiles.hyperion_core.fhir_event_processor.concurrent.futures.ThreadPoolExecutor')
    def test_fhir_event_exporter_sets_signal_handlers(self, mock_executor, mock_signal, mock_azure_config):
        """Test fhir_event_exporter sets up signal handlers."""
        from pyfiles.hyperion_core.fhir_event_processor import FHIREventProcessor
        import signal

        processor = FHIREventProcessor(
            configurations=mock_azure_config,
            storage_client=MagicMock(),
            queue_client=MagicMock(),
            fhir_client=MagicMock()
        )

        mock_executor_instance = MagicMock()
        mock_executor.return_value.__enter__.return_value = mock_executor_instance
        mock_executor_instance.submit.side_effect = SystemExit()

        try:
            processor.fhir_event_exporter()
        except SystemExit:
            pass

        signal_calls = [call[0][0] for call in mock_signal.call_args_list]
        assert signal.SIGINT in signal_calls
        assert signal.SIGTERM in signal_calls

    @patch('pyfiles.hyperion_core.fhir_event_processor.concurrent.futures.ThreadPoolExecutor')
    def test_fhir_event_exporter_creates_correct_thread_count(self, mock_executor, mock_azure_config):
        """Test fhir_event_exporter creates correct number of threads."""
        from pyfiles.hyperion_core.fhir_event_processor import FHIREventProcessor

        config = mock_azure_config.copy()
        config['processing'] = {'message': '3', 'converter_cores': '2'}

        processor = FHIREventProcessor(
            configurations=config,
            storage_client=MagicMock(),
            queue_client=MagicMock(),
            fhir_client=MagicMock()
        )

        mock_executor_instance = MagicMock()
        mock_executor.return_value.__enter__.return_value = mock_executor_instance
        mock_executor_instance.submit.side_effect = SystemExit()

        try:
            processor.fhir_event_exporter()
        except SystemExit:
            pass

        mock_executor.assert_called_with(max_workers=6)
