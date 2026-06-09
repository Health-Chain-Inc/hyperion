"""Unit tests for FHIRBatchExport class."""
import pytest
from unittest.mock import MagicMock, patch

from pyfiles.dependencies.data_processing_error import DataProcessingException
from tests.pytest.mocks.mock_fhir_responses import (
    MockFHIRResponse,
    create_mock_patient_bundle,
    create_mock_error_response
)


class TestFHIRBatchExportInitialization:
    """Test FHIRBatchExport initialization."""

    def test_initialization_stores_parameters(self, mock_azure_config):
        """Test that initialization stores all parameters."""
        from pyfiles.hyperion_core.fhir_batch_exporter import FHIRBatchExport

        mock_fhir = MagicMock()
        mock_fhir.get_fhir_batch_export_url.return_value = 'https://fhir.test/Patient'

        exporter = FHIRBatchExport(
            resource_type='Patient',
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-02T00:00:00Z',
            fhir_url=None,
            page_number=1,
            folder_name='batch-load/20240101',
            retry_count=0,
            retry_message=False,
            fhir_client=mock_fhir,
            storage_client=MagicMock(),
            queue_client=MagicMock()
        )

        assert exporter.resource_type == 'Patient'
        assert exporter.start_date == '2024-01-01T00:00:00Z'
        assert exporter.end_date == '2024-01-02T00:00:00Z'
        assert exporter.page_number == 1
        assert exporter.folder_name == 'batch-load/20240101'
        assert exporter.retry_count == 0

    def test_initialization_generates_url_when_none(self, mock_azure_config):
        """Test that initialization generates FHIR URL when none provided."""
        from pyfiles.hyperion_core.fhir_batch_exporter import FHIRBatchExport

        mock_fhir = MagicMock()
        mock_fhir.get_fhir_batch_export_url.return_value = 'https://fhir.test/Patient?_lastUpdated=ge2024-01-01'

        exporter = FHIRBatchExport(
            resource_type='Patient',
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-02T00:00:00Z',
            fhir_url=None,  # Should trigger URL generation
            page_number=1,
            folder_name='batch-load/20240101',
            retry_count=0,
            retry_message=False,
            fhir_client=mock_fhir,
            storage_client=MagicMock(),
            queue_client=MagicMock()
        )

        mock_fhir.get_fhir_batch_export_url.assert_called_once_with('Patient', '2024-01-01T00:00:00Z', '2024-01-02T00:00:00Z')
        assert 'Patient' in exporter.fhir_url

    def test_initialization_uses_provided_url(self, mock_azure_config):
        """Test that initialization uses provided URL when available."""
        from pyfiles.hyperion_core.fhir_batch_exporter import FHIRBatchExport

        mock_fhir = MagicMock()
        provided_url = 'https://fhir.test/Patient?custom=param'

        exporter = FHIRBatchExport(
            resource_type='Patient',
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-02T00:00:00Z',
            fhir_url=provided_url,
            page_number=1,
            folder_name='batch-load/20240101',
            retry_count=0,
            retry_message=False,
            fhir_client=mock_fhir,
            storage_client=MagicMock(),
            queue_client=MagicMock()
        )

        assert exporter.fhir_url == provided_url
        mock_fhir.get_fhir_batch_export_url.assert_not_called()


class TestFhirPull:
    """Test fhirpull method."""

    @patch('pyfiles.hyperion_core.fhir_batch_exporter.requests.Session')
    def test_fhirpull_success(self, mock_session_class, mock_azure_config):
        """Test successful FHIR data pull."""
        from pyfiles.hyperion_core.fhir_batch_exporter import FHIRBatchExport

        # Mock FHIR response with patient bundle
        mock_response = create_mock_patient_bundle(count=2, has_next=False)

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_batch_export_url.return_value = 'https://fhir.test/Patient'

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {
            'url': 'https://storage/staging/Patient-1.ndjson',
            'request_time': '2024-01-01T00:00:00'
        }

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'False'}

        exporter = FHIRBatchExport(
            resource_type='Patient',
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-02T00:00:00Z',
            fhir_url=None,
            page_number=1,
            folder_name='batch-load/20240101',
            retry_count=0,
            retry_message=False,
            fhir_client=mock_fhir,
            storage_client=mock_storage,
            queue_client=mock_queue
        )

        exporter.fhirpull(config)

        mock_storage.upload_ndjson_to_stage.assert_called_once()
        mock_queue.insert_to_batch_load_queue.assert_called_once()

    @patch('pyfiles.hyperion_core.fhir_batch_exporter.requests.Session')
    def test_fhirpull_handles_pagination(self, mock_session_class, mock_azure_config):
        """Test fhirpull follows pagination links."""
        from pyfiles.hyperion_core.fhir_batch_exporter import FHIRBatchExport

        # First response with next link, second without
        first_response = create_mock_patient_bundle(
            count=2, has_next=True, next_url='https://fhir.test/Patient?page=2'
        )
        second_response = create_mock_patient_bundle(count=2, has_next=False)

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.side_effect = [first_response, second_response]
        mock_fhir.get_fhir_batch_export_url.return_value = 'https://fhir.test/Patient'

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {
            'url': 'https://storage/staging/Patient-1.ndjson',
            'request_time': '2024-01-01T00:00:00'
        }

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'False'}

        exporter = FHIRBatchExport(
            resource_type='Patient',
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-02T00:00:00Z',
            fhir_url=None,
            page_number=1,
            folder_name='batch-load/20240101',
            retry_count=0,
            retry_message=False,
            fhir_client=mock_fhir,
            storage_client=mock_storage,
            queue_client=mock_queue
        )

        exporter.fhirpull(config)

        # Should have called get twice (for both pages)
        assert mock_fhir.fhir_get_request.call_count == 2
        assert mock_storage.upload_ndjson_to_stage.call_count == 2

    @patch('pyfiles.hyperion_core.fhir_batch_exporter.requests.Session')
    def test_fhirpull_handles_401_reauthentication(self, mock_session_class, mock_azure_config):
        """Test fhirpull reauthenticates on 401 response."""
        from pyfiles.hyperion_core.fhir_batch_exporter import FHIRBatchExport

        # First response is 401, second is success
        response_401 = MockFHIRResponse(status_code=401, text='Unauthorized')
        response_success = create_mock_patient_bundle(count=2, has_next=False)

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer new_token'}
        mock_fhir.fhir_get_request.side_effect = [response_401, response_success]
        mock_fhir.get_fhir_batch_export_url.return_value = 'https://fhir.test/Patient'

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {
            'url': 'https://storage/staging/Patient-1.ndjson'
        }

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'False'}

        exporter = FHIRBatchExport(
            resource_type='Patient',
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-02T00:00:00Z',
            fhir_url=None,
            page_number=1,
            folder_name='batch-load/20240101',
            retry_count=0,
            retry_message=False,
            fhir_client=mock_fhir,
            storage_client=mock_storage,
            queue_client=mock_queue
        )

        exporter.fhirpull(config)

        # Should have called authentication twice (initial + reauth)
        assert mock_fhir.authentication.call_count >= 2

    @patch('pyfiles.hyperion_core.fhir_batch_exporter.requests.Session')
    def test_fhirpull_raises_on_error_response(self, mock_session_class, mock_azure_config):
        """Test fhirpull raises DataProcessingException on error."""
        from pyfiles.hyperion_core.fhir_batch_exporter import FHIRBatchExport

        error_response = create_mock_error_response(status_code=500)

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = error_response
        mock_fhir.get_fhir_batch_export_url.return_value = 'https://fhir.test/Patient'

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}

        exporter = FHIRBatchExport(
            resource_type='Patient',
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-02T00:00:00Z',
            fhir_url=None,
            page_number=1,
            folder_name='batch-load/20240101',
            retry_count=0,
            retry_message=False,
            fhir_client=mock_fhir,
            storage_client=MagicMock(),
            queue_client=MagicMock()
        )

        with pytest.raises(DataProcessingException):
            exporter.fhirpull(config)


class TestRunMethod:
    """Test run method."""

    @patch('pyfiles.hyperion_core.fhir_batch_exporter.requests.Session')
    def test_run_calls_fhirpull(self, mock_session_class, mock_azure_config):
        """Test run method invokes fhirpull."""
        from pyfiles.hyperion_core.fhir_batch_exporter import FHIRBatchExport

        mock_response = create_mock_patient_bundle(count=1, has_next=False)

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_batch_export_url.return_value = 'https://fhir.test/Patient'

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {'url': 'test'}

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'False'}

        exporter = FHIRBatchExport(
            resource_type='Patient',
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-02T00:00:00Z',
            fhir_url=None,
            page_number=1,
            folder_name='batch-load/20240101',
            retry_count=0,
            retry_message=False,
            fhir_client=mock_fhir,
            storage_client=mock_storage,
            queue_client=mock_queue
        )

        exporter.run(config)

        mock_fhir.fhir_get_request.assert_called()

    @patch('pyfiles.hyperion_core.fhir_batch_exporter.Handlers.create_exporter_parameter_message')
    @patch('pyfiles.hyperion_core.fhir_batch_exporter.requests.Session')
    def test_run_handles_dataprocessingexception_with_retry(self, mock_session_class, mock_create_msg, mock_azure_config):
        """Test run method handles DataProcessingException and calls fhirpullerror."""
        from pyfiles.hyperion_core.fhir_batch_exporter import FHIRBatchExport
        from pyfiles.dependencies.data_processing_error import DataProcessingException

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        # run() only catches DataProcessingException, not plain Exception
        mock_fhir.authentication.side_effect = DataProcessingException("Auth failed", {}, "401")
        mock_fhir.get_fhir_batch_export_url.return_value = 'https://fhir.test/Patient'

        mock_storage = MagicMock()
        mock_queue = MagicMock()

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}

        exporter = FHIRBatchExport(
            resource_type='Patient',
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-02T00:00:00Z',
            fhir_url=None,
            page_number=1,
            folder_name='batch-load/20240101',
            retry_count=0,
            retry_message=False,
            fhir_client=mock_fhir,
            storage_client=mock_storage,
            queue_client=mock_queue
        )

        # run should catch DataProcessingException and call error handler
        exporter.run(config)

        mock_create_msg.assert_called_once()


class TestLineageTracking:
    """Test lineage tracking functionality."""

    @patch('pyfiles.hyperion_core.fhir_batch_exporter.requests.Session')
    def test_fhirpull_inserts_lineage_when_enabled(self, mock_session_class, mock_azure_config):
        """Test fhirpull creates lineage record when is_lineage is True."""
        from pyfiles.hyperion_core.fhir_batch_exporter import FHIRBatchExport

        mock_response = create_mock_patient_bundle(count=2, has_next=False)

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_batch_export_url.return_value = 'https://fhir.test/Patient'

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {
            'url': 'https://storage/staging/Patient-1.ndjson'
        }

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'True'}

        exporter = FHIRBatchExport(
            resource_type='Patient',
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-02T00:00:00Z',
            fhir_url=None,
            page_number=1,
            folder_name='batch-load/20240101',
            retry_count=0,
            retry_message=False,
            fhir_client=mock_fhir,
            storage_client=mock_storage,
            queue_client=mock_queue
        )

        exporter.fhirpull(config)

        # Verify lineage was inserted
        mock_queue.insert_to_audit_queue.assert_called()
        lineage_call = mock_queue.insert_to_audit_queue.call_args
        assert lineage_call[0][1] == 'fhir_lineage'

    @patch('pyfiles.hyperion_core.fhir_batch_exporter.requests.Session')
    def test_fhirpull_skips_lineage_when_disabled(self, mock_session_class, mock_azure_config):
        """Test fhirpull does not create lineage when is_lineage is False."""
        from pyfiles.hyperion_core.fhir_batch_exporter import FHIRBatchExport

        mock_response = create_mock_patient_bundle(count=2, has_next=False)

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_batch_export_url.return_value = 'https://fhir.test/Patient'

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {
            'url': 'https://storage/staging/Patient-1.ndjson'
        }

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'False'}

        exporter = FHIRBatchExport(
            resource_type='Patient',
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-02T00:00:00Z',
            fhir_url=None,
            page_number=1,
            folder_name='batch-load/20240101',
            retry_count=0,
            retry_message=False,
            fhir_client=mock_fhir,
            storage_client=mock_storage,
            queue_client=mock_queue
        )

        exporter.fhirpull(config)

        # Verify insert_to_audit_queue was NOT called
        mock_queue.insert_to_audit_queue.assert_not_called()

    @patch('pyfiles.hyperion_core.fhir_batch_exporter.requests.Session')
    def test_lineage_filepath_id_matches_handler(self, mock_session_class, mock_azure_config):
        """Test that lineage data filepath_id matches Handlers.generate_batch_filepath_id(url)."""
        from pyfiles.hyperion_core.fhir_batch_exporter import FHIRBatchExport
        from pyfiles.dependencies.handlers import Handlers

        mock_response = create_mock_patient_bundle(count=2, has_next=False)

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        url = 'https://storage/staging/Patient-1.ndjson'

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_batch_export_url.return_value = 'https://fhir.test/Patient'

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {
            'url': url,
            'request_time': '2024-01-01T00:00:00'
        }

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'True'}

        exporter = FHIRBatchExport(
            resource_type='Patient',
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-02T00:00:00Z',
            fhir_url=None,
            page_number=1,
            folder_name='batch-load/20240101',
            retry_count=0,
            retry_message=False,
            fhir_client=mock_fhir,
            storage_client=mock_storage,
            queue_client=mock_queue
        )

        exporter.fhirpull(config)

        # Verify lineage was inserted
        mock_queue.insert_to_audit_queue.assert_called()
        lineage_call_args = mock_queue.insert_to_audit_queue.call_args

        # The first positional argument is the lineage data dict
        lineage_data = lineage_call_args[0][0]
        expected_filepath_id = Handlers.generate_batch_filepath_id(url)
        assert lineage_data['filepath_id'] == expected_filepath_id

    @patch('pyfiles.hyperion_core.fhir_batch_exporter.requests.Session')
    def test_queue_message_contains_filepath_id_when_lineage_enabled(self, mock_session_class, mock_azure_config):
        """Test that message sent to insert_to_batch_load_queue contains a filepath_id key."""
        from pyfiles.hyperion_core.fhir_batch_exporter import FHIRBatchExport

        mock_response = create_mock_patient_bundle(count=2, has_next=False)

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_batch_export_url.return_value = 'https://fhir.test/Patient'

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {
            'url': 'https://storage/staging/Patient-1.ndjson',
            'request_time': '2024-01-01T00:00:00'
        }

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'True'}

        exporter = FHIRBatchExport(
            resource_type='Patient',
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-02T00:00:00Z',
            fhir_url=None,
            page_number=1,
            folder_name='batch-load/20240101',
            retry_count=0,
            retry_message=False,
            fhir_client=mock_fhir,
            storage_client=mock_storage,
            queue_client=mock_queue
        )

        exporter.fhirpull(config)

        mock_queue.insert_to_batch_load_queue.assert_called_once()
        queue_call_args = mock_queue.insert_to_batch_load_queue.call_args
        # First positional argument is the exporter_message dict
        exporter_message = queue_call_args[0][0]
        assert 'filepath_id' in exporter_message


class TestFilepathIdInQueueMessage:
    """Test filepath_id is included in queue messages after a successful fhirpull."""

    @patch('pyfiles.hyperion_core.fhir_batch_exporter.requests.Session')
    def test_fhirpull_queue_message_includes_filepath_id(self, mock_session_class, mock_azure_config):
        """Test that after a successful fhirpull, insert_to_batch_load_queue receives a filepath_id."""
        from pyfiles.hyperion_core.fhir_batch_exporter import FHIRBatchExport

        mock_response = create_mock_patient_bundle(count=2, has_next=False)

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_batch_export_url.return_value = 'https://fhir.test/Patient'

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {
            'url': 'https://storage/staging/Patient-1.ndjson',
            'request_time': '2024-01-01T00:00:00'
        }

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'False'}

        exporter = FHIRBatchExport(
            resource_type='Patient',
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-02T00:00:00Z',
            fhir_url=None,
            page_number=1,
            folder_name='batch-load/20240101',
            retry_count=0,
            retry_message=False,
            fhir_client=mock_fhir,
            storage_client=mock_storage,
            queue_client=mock_queue
        )

        exporter.fhirpull(config)

        mock_queue.insert_to_batch_load_queue.assert_called_once()
        queue_call_args = mock_queue.insert_to_batch_load_queue.call_args
        exporter_message = queue_call_args[0][0]
        assert 'filepath_id' in exporter_message

    @patch('pyfiles.hyperion_core.fhir_batch_exporter.requests.Session')
    def test_fhirpull_filepath_id_is_valid_uuid5(self, mock_session_class, mock_azure_config):
        """Test that the filepath_id in the queue message is a valid UUID5 string."""
        import uuid
        from pyfiles.hyperion_core.fhir_batch_exporter import FHIRBatchExport
        from pyfiles.dependencies.handlers import Handlers

        mock_response = create_mock_patient_bundle(count=2, has_next=False)

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        blob_url = 'https://storage/staging/Patient-1.ndjson'

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_batch_export_url.return_value = 'https://fhir.test/Patient'

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {
            'url': blob_url,
            'request_time': '2024-01-01T00:00:00'
        }

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'False'}

        exporter = FHIRBatchExport(
            resource_type='Patient',
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-02T00:00:00Z',
            fhir_url=None,
            page_number=1,
            folder_name='batch-load/20240101',
            retry_count=0,
            retry_message=False,
            fhir_client=mock_fhir,
            storage_client=mock_storage,
            queue_client=mock_queue
        )

        exporter.fhirpull(config)

        mock_queue.insert_to_batch_load_queue.assert_called_once()
        queue_call_args = mock_queue.insert_to_batch_load_queue.call_args
        exporter_message = queue_call_args[0][0]

        filepath_id = exporter_message['filepath_id']

        # Verify it is a valid UUID string
        parsed = uuid.UUID(filepath_id)
        assert parsed.version == 5

        # Verify it matches what Handlers.generate_batch_filepath_id produces for the blob url
        assert filepath_id == Handlers.generate_batch_filepath_id(blob_url)
