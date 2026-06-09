"""Unit tests for CoreLoadProcessor class."""
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from queue import Queue
import threading

from pyfiles.dependencies.data_processing_error import DataProcessingException


@pytest.fixture(autouse=True)
def reset_core_load_processor_state():
    """Reset CoreLoadProcessor class-level state before each test to prevent pollution."""
    from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor
    CoreLoadProcessor._deletion_attributes = None
    CoreLoadProcessor.get_fhir_structure.cache_clear()
    yield
    CoreLoadProcessor._deletion_attributes = None
    CoreLoadProcessor.get_fhir_structure.cache_clear()


class TestCoreLoadProcessorInitialization:
    """Test CoreLoadProcessor class initialization."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    def test_initialization_stores_clients(self, mock_get_schema, mock_json_reader,
                                           mock_azure_config):
        """Test that initialization stores all client references."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {'Patient': {}}
        mock_json_reader.return_value = {'Patient': {'identifier': []}}

        mock_queue = MagicMock()
        mock_storage = MagicMock()
        mock_fhir = MagicMock()
        mock_db_pool = MagicMock()

        processor = CoreLoadProcessor(
            queue_client=mock_queue,
            storage_client=mock_storage,
            fhir_client=mock_fhir,
            project_configurations=mock_azure_config,
            db_connection_pool=mock_db_pool
        )

        assert processor.queue_client == mock_queue
        assert processor.storage_client == mock_storage
        assert processor.fhir_client == mock_fhir
        assert processor.db_connection_pool == mock_db_pool
        assert processor.application_name == 'test-app'

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    def test_initialization_loads_fhir_schema(self, mock_json_reader, mock_azure_config):
        """Test that initialization loads the FHIR schema via get_fhir_structure."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_json_reader.return_value = {}
        mock_schema = {'Patient': {'fields': []}, 'Observation': {'fields': []}}

        # Patch get_fhir_structure directly since it's cached with hermes decorator
        with patch.object(CoreLoadProcessor, 'get_fhir_structure', return_value=mock_schema):
            processor = CoreLoadProcessor(
                queue_client=MagicMock(),
                storage_client=MagicMock(),
                fhir_client=MagicMock(),
                project_configurations=mock_azure_config,
                db_connection_pool=MagicMock()
            )

            assert processor.resource_structure == mock_schema

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    def test_initialization_loads_deletion_attributes(self, mock_get_schema, mock_json_reader,
                                                      mock_azure_config):
        """Test that deletion attributes are lazy-loaded via get_deletion_attributes()."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_deletion_attrs = {'Patient': {'identifier': []}}
        mock_json_reader.return_value = mock_deletion_attrs

        CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        # Deletion attributes are lazy-loaded; trigger loading explicitly
        result = CoreLoadProcessor.get_deletion_attributes()

        mock_json_reader.assert_called_once_with("schema/deletion_attributes.json")
        assert result == mock_deletion_attrs


class TestGetProcessedData:
    """Test get_processed_data method."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.DBOps.filter_data_to_be_processed')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.create_pandas_dataframe')
    def test_get_processed_data_returns_tuple(self, mock_create_df, mock_filter_data,
                                              mock_get_schema, mock_json_reader,
                                              mock_azure_config, sample_fhir_patient):
        """Test that get_processed_data returns expected tuple."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        # Mock the filter_data_to_be_processed response
        mock_df = pd.DataFrame([sample_fhir_patient])
        mock_create_df.return_value = mock_df
        mock_filter_data.return_value = (
            True,  # process_data
            mock_df,  # fhir_data_df
            pd.DataFrame(),  # array_counts_df
            {'audit': 'data'}  # audit_data_json
        )

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        result = processor.get_processed_data(
            fhir_data=[sample_fhir_patient],
            fhir_resource_type='Patient',
            blob_url='https://test.blob.core.windows.net/staging/Patient-1.ndjson'
        )

        assert isinstance(result, tuple)
        assert len(result) == 4
        process_data, fhir_df, array_counts, audit_json = result
        assert process_data is True
        assert isinstance(fhir_df, pd.DataFrame)

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.DBOps.filter_data_to_be_processed')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.create_pandas_dataframe')
    def test_get_processed_data_duplicate_returns_false(self, mock_create_df, mock_filter_data,
                                                        mock_get_schema, mock_json_reader,
                                                        mock_azure_config, sample_fhir_patient):
        """Test that duplicate data returns process_data=False."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        mock_df = pd.DataFrame([sample_fhir_patient])
        mock_create_df.return_value = mock_df

        # Simulate duplicate data
        mock_filter_data.return_value = (
            False,  # process_data - no new data
            mock_df,
            pd.DataFrame(),
            {'audit': 'data'}
        )

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        process_data, _, _, _ = processor.get_processed_data(
            fhir_data=[sample_fhir_patient],
            fhir_resource_type='Patient',
            blob_url='https://test.blob.core.windows.net/staging/Patient-1.ndjson'
        )

        assert process_data is False


class TestNormalizer:
    """Test normalizer method."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.Normalizer')
    def test_normalizer_processes_data_when_flag_true(self, mock_normalizer_class,
                                                      mock_get_schema, mock_json_reader,
                                                      mock_azure_config, sample_fhir_patient):
        """Test normalizer processes data when process_data is True."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {'Patient': {}}
        mock_json_reader.return_value = {}

        # Mock Normalizer instance and run method
        mock_normalizer_instance = MagicMock()
        mock_normalizer_instance.run.return_value = {
            'patient': pd.DataFrame([{'id': 'test-123'}])
        }
        mock_normalizer_class.return_value = mock_normalizer_instance

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        fhir_df = pd.DataFrame([sample_fhir_patient])
        result = processor.normalizer(
            filepath_id='test-file-123',
            fhir_resource_type='Patient',
            process_data=True,
            fhir_data_df=fhir_df
        )

        assert result is not None
        assert 'patient' in result
        mock_normalizer_class.assert_called_once()
        mock_normalizer_instance.run.assert_called_once()

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    def test_normalizer_returns_none_when_flag_false(self, mock_get_schema, mock_json_reader,
                                                     mock_azure_config, sample_fhir_patient):
        """Test normalizer returns None when process_data is False."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        fhir_df = pd.DataFrame([sample_fhir_patient])
        result = processor.normalizer(
            filepath_id='test-file-123',
            fhir_resource_type='Patient',
            process_data=False,
            fhir_data_df=fhir_df
        )

        assert result is None

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.Normalizer')
    def test_normalizer_raises_exception_on_error(self, mock_normalizer_class,
                                                  mock_get_schema, mock_json_reader,
                                                  mock_azure_config, sample_fhir_patient):
        """Test normalizer raises DataProcessingException on error."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        # Mock Normalizer to raise an exception
        mock_normalizer_class.side_effect = Exception("Normalization error")

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        fhir_df = pd.DataFrame([sample_fhir_patient])

        with pytest.raises(DataProcessingException) as exc_info:
            processor.normalizer(
                filepath_id='test-file-123',
                fhir_resource_type='Patient',
                process_data=True,
                fhir_data_df=fhir_df
            )

        assert '602' in str(exc_info.value.error_code)


class TestStreamloader:
    """Test streamloader method."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_streamloader_processes_dataframes(self, mock_rename, mock_process_df,
                                               mock_tx_block, mock_get_schema,
                                               mock_json_reader, mock_azure_config):
        """Test streamloader processes each dataframe in dictionary."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        # Mock process_dataframe to return a non-empty dataframe
        processed_df = pd.DataFrame({'id': ['test-1'], 'name': ['Test']})
        mock_process_df.return_value = processed_df

        # Mock transaction_block to return success without transaction
        mock_tx_block.return_value = (True, None, None)

        # Disable transactions for this test
        config = mock_azure_config.copy()
        config['silver_layer']['is_transaction'] = 'False'

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=config,
            db_connection_pool=MagicMock()
        )

        resource_data = {
            'patient': pd.DataFrame({'id': ['test-1'], 'name': ['Test']})
        }
        complex_dtypes = {'patient': {'identifier': []}}

        # Should not raise
        processor.streamloader(
            filename='Patient-1.ndjson',
            resource_data_dictionary=resource_data,
            complex_dtypes=complex_dtypes,
            array_counts_df=pd.DataFrame(),
            filepath_id='test-fp-123'
        )

        mock_tx_block.assert_called_once()

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    def test_streamloader_skips_empty_dataframe(self, mock_process_df,
                                                mock_get_schema, mock_json_reader,
                                                mock_azure_config):
        """Test streamloader skips empty dataframes."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        # Return empty dataframe
        mock_process_df.return_value = pd.DataFrame()

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        resource_data = {
            'patient': pd.DataFrame({'id': []})
        }
        complex_dtypes = {}

        # Should not raise - empty df is skipped
        processor.streamloader(
            filename='Patient-1.ndjson',
            resource_data_dictionary=resource_data,
            complex_dtypes=complex_dtypes,
            array_counts_df=pd.DataFrame(),
            filepath_id='test-fp-123'
        )

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.commit_transaction')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_streamloader_commits_transaction_on_success(self, mock_rename, mock_process_df,
                                                         mock_commit, mock_tx_block,
                                                         mock_get_schema, mock_json_reader,
                                                         mock_azure_config):
        """Test streamloader commits transaction when all prepared."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        processed_df = pd.DataFrame({'id': ['test-1']})
        mock_process_df.return_value = processed_df

        # Enable transactions and return prepared state
        mock_tx_block.return_value = (True, 'test_label', 'patient')

        config = mock_azure_config.copy()
        config['silver_layer']['is_transaction'] = 'True'

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=config,
            db_connection_pool=MagicMock()
        )

        resource_data = {
            'patient': pd.DataFrame({'id': ['test-1']})
        }

        processor.streamloader(
            filename='Patient-1.ndjson',
            resource_data_dictionary=resource_data,
            complex_dtypes={},
            array_counts_df=pd.DataFrame(),
            filepath_id='test-fp-123'
        )

        mock_commit.assert_called_once()

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.rollback_transaction')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_streamloader_rollback_on_prepare_failure(self, mock_rename, mock_process_df,
                                                      mock_rollback, mock_tx_block,
                                                      mock_get_schema, mock_json_reader,
                                                      mock_azure_config):
        """Test streamloader rolls back when prepare fails."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        processed_df = pd.DataFrame({'id': ['test-1']})
        mock_process_df.return_value = processed_df

        # Return not prepared state
        mock_tx_block.return_value = (False, 'test_label', 'patient')

        config = mock_azure_config.copy()
        config['silver_layer']['is_transaction'] = 'True'

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=config,
            db_connection_pool=MagicMock()
        )

        resource_data = {
            'patient': pd.DataFrame({'id': ['test-1']})
        }

        with pytest.raises(DataProcessingException):
            processor.streamloader(
                filename='Patient-1.ndjson',
                resource_data_dictionary=resource_data,
                complex_dtypes={},
                array_counts_df=pd.DataFrame(),
                filepath_id='test-fp-123'
            )

        mock_rollback.assert_called_once()


class TestProcessLoadMessages:
    """Test process_load_messages method."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    def test_process_load_messages_handles_empty_queue(self, mock_get_schema, mock_json_reader,
                                                       mock_azure_config):
        """Test process_load_messages handles empty message queue gracefully."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        mock_queue = MagicMock()
        mock_queue.get_batch_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()

        # Return empty array to exit loop
        mock_queue.receive_messages.return_value = []

        mock_storage = MagicMock()
        mock_storage.get_staging_container_client.return_value = MagicMock()

        processor = CoreLoadProcessor(
            queue_client=mock_queue,
            storage_client=mock_storage,
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        # Create shutdown event that triggers immediately
        shutdown_event = threading.Event()
        shutdown_event.set()

        message_queue = Queue()

        # Should not raise
        processor.process_load_messages(message_queue, 1, shutdown_event)


    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    def test_process_load_messages_raises_on_queue_init_failure(self, mock_get_schema,
                                                                mock_json_reader,
                                                                mock_azure_config):
        """Test process_load_messages logs and re-raises when queue init fails (A1)."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        mock_queue = MagicMock()
        mock_queue.get_batch_queue_receiver.side_effect = RuntimeError("Queue connection lost")

        processor = CoreLoadProcessor(
            queue_client=mock_queue,
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        shutdown_event = threading.Event()
        message_queue = Queue()

        with pytest.raises(RuntimeError, match="Queue connection lost"):
            processor.process_load_messages(message_queue, 1, shutdown_event)

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    def test_process_load_messages_raises_on_storage_init_failure(self, mock_get_schema,
                                                                  mock_json_reader,
                                                                  mock_azure_config):
        """Test process_load_messages re-raises when storage container client init fails."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        mock_queue = MagicMock()
        mock_queue.get_batch_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()

        mock_storage = MagicMock()
        mock_storage.get_staging_container_client.side_effect = RuntimeError("Storage unavailable")

        processor = CoreLoadProcessor(
            queue_client=mock_queue,
            storage_client=mock_storage,
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        shutdown_event = threading.Event()
        message_queue = Queue()

        with pytest.raises(RuntimeError, match="Storage unavailable"):
            processor.process_load_messages(message_queue, 1, shutdown_event)


class TestFhirConverterIntegration:
    """Integration-style tests for fhir_converter method."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.signal.signal')
    def test_fhir_converter_sets_up_signal_handlers(self, mock_signal, mock_get_schema,
                                                    mock_json_reader, mock_azure_config):
        """Test fhir_converter sets up SIGINT and SIGTERM handlers."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        # Patch the run method to avoid actual execution
        with patch.object(processor, 'run'):
            # Set up to exit immediately
            with patch('concurrent.futures.ThreadPoolExecutor') as mock_executor:
                mock_executor.return_value.__enter__.return_value.submit.return_value = MagicMock()
                mock_executor.return_value.__enter__.return_value.submit.side_effect = SystemExit()

                try:
                    processor.fhir_converter()
                except SystemExit:
                    pass

        # Verify signal handlers were registered
        assert mock_signal.call_count >= 2


class TestMessageProcessingLoop:
    """Test the main message processing loop."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    def test_processes_valid_ndjson_message(self, mock_get_schema, mock_json_reader,
                                            mock_azure_config, sample_fhir_patient):
        """Test processing a valid NDJSON message."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {'Patient': {}}
        mock_json_reader.return_value = {'Patient': []}

        mock_queue = MagicMock()
        mock_storage = MagicMock()
        mock_fhir = MagicMock()
        mock_db_pool = MagicMock()

        # Setup queue client to return one message then empty
        mock_message = MagicMock()
        mock_queue.receive_messages.side_effect = [[mock_message], []]
        mock_queue.read_message_body.return_value = {'url': 'test', 'retry_count': 0}
        mock_queue.get_ndjson_filepath.return_value = (
            'https://storage.blob.core.windows.net/staging/Patient-1.ndjson',
            'Patient',
            'Patient-1.ndjson'
        )
        mock_queue.get_batch_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()

        mock_storage.read.return_value = [sample_fhir_patient]
        mock_storage.get_staging_container_client.return_value = MagicMock()

        config = mock_azure_config.copy()
        config['default_value']['is_audit'] = 'False'
        config['default_value']['is_lineage'] = 'False'

        processor = CoreLoadProcessor(
            queue_client=mock_queue,
            storage_client=mock_storage,
            fhir_client=mock_fhir,
            project_configurations=config,
            db_connection_pool=mock_db_pool
        )

        # Mock the processing methods
        with patch.object(processor, 'get_processed_data') as mock_get_data:
            with patch.object(processor, 'normalizer') as mock_normalizer:
                with patch.object(processor, 'streamloader') as mock_streamloader:
                    mock_get_data.return_value = (True, pd.DataFrame([sample_fhir_patient]), pd.DataFrame(), [])
                    mock_normalizer.return_value = {'patient': pd.DataFrame()}
                    mock_streamloader.return_value = None

                    shutdown_event = threading.Event()
                    shutdown_event.set()  # Immediate shutdown

                    # Should not raise
                    processor.process_load_messages(Queue(), 1, shutdown_event)

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    def test_handles_malformed_message(self, mock_get_schema, mock_json_reader,
                                       mock_azure_config):
        """Test handling of malformed message data."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        mock_queue = MagicMock()
        mock_storage = MagicMock()

        # Return empty on receive to exit quickly
        mock_queue.receive_messages.return_value = []
        mock_queue.get_batch_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_storage.get_staging_container_client.return_value = MagicMock()

        processor = CoreLoadProcessor(
            queue_client=mock_queue,
            storage_client=mock_storage,
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        shutdown_event = threading.Event()
        shutdown_event.set()

        # Should not raise on malformed/empty messages
        processor.process_load_messages(Queue(), 1, shutdown_event)

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    def test_filters_duplicate_records(self, mock_get_schema, mock_json_reader,
                                       mock_azure_config, sample_fhir_patient):
        """Test that duplicate records are filtered."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        # Mock get_processed_data to return False (all duplicates)
        with patch.object(processor, 'get_processed_data') as mock_get_data:
            mock_get_data.return_value = (False, pd.DataFrame(), pd.DataFrame(), [])

            result = processor.normalizer(
                filepath_id='test-file',
                fhir_resource_type='Patient',
                process_data=False,
                fhir_data_df=pd.DataFrame([sample_fhir_patient])
            )

            assert result is None


class TestTransactionHandling:
    """Test transaction handling in streamloader."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.commit_transaction')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_commits_on_success(self, mock_rename, mock_process_df, mock_commit,
                                mock_tx_block, mock_get_schema, mock_json_reader,
                                mock_azure_config):
        """Test transaction commits on successful processing."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        processed_df = pd.DataFrame({'id': ['test-1'], 'data': ['value']})
        mock_process_df.return_value = processed_df
        mock_tx_block.return_value = (True, 'label-123', 'patient')

        config = mock_azure_config.copy()
        config['silver_layer']['is_transaction'] = 'True'

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=config,
            db_connection_pool=MagicMock()
        )

        resource_data = {'patient': pd.DataFrame({'id': ['test-1']})}

        processor.streamloader(
            filename='Patient-1.ndjson',
            resource_data_dictionary=resource_data,
            complex_dtypes={},
            array_counts_df=pd.DataFrame(),
            filepath_id='test-fp-123'
        )

        mock_commit.assert_called_once()

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.rollback_transaction')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_rollbacks_on_failure(self, mock_rename, mock_process_df, mock_rollback,
                                  mock_tx_block, mock_get_schema, mock_json_reader,
                                  mock_azure_config):
        """Test transaction rollback on failure."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        processed_df = pd.DataFrame({'id': ['test-1']})
        mock_process_df.return_value = processed_df
        mock_tx_block.return_value = (False, 'label-123', 'patient')  # Not prepared

        config = mock_azure_config.copy()
        config['silver_layer']['is_transaction'] = 'True'

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=config,
            db_connection_pool=MagicMock()
        )

        resource_data = {'patient': pd.DataFrame({'id': ['test-1']})}

        with pytest.raises(DataProcessingException):
            processor.streamloader(
                filename='Patient-1.ndjson',
                resource_data_dictionary=resource_data,
                complex_dtypes={},
                array_counts_df=pd.DataFrame(),
                filepath_id='test-fp-123'
            )

        mock_rollback.assert_called_once()

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_handles_partial_failure(self, mock_rename, mock_process_df,
                                     mock_tx_block, mock_get_schema, mock_json_reader,
                                     mock_azure_config):
        """Test handling partial failure in transaction."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        processed_df = pd.DataFrame({'id': ['test-1']})
        mock_process_df.return_value = processed_df
        mock_tx_block.side_effect = DataProcessingException("TX failed", "error", "603")

        config = mock_azure_config.copy()
        config['silver_layer']['is_transaction'] = 'True'

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=config,
            db_connection_pool=MagicMock()
        )

        resource_data = {'patient': pd.DataFrame({'id': ['test-1']})}

        with pytest.raises(DataProcessingException) as exc_info:
            processor.streamloader(
                filename='Patient-1.ndjson',
                resource_data_dictionary=resource_data,
                complex_dtypes={},
                array_counts_df=pd.DataFrame(),
                filepath_id='test-fp-123'
            )

        assert '603' in str(exc_info.value.error_code)


class TestErrorRecovery:
    """Test error recovery mechanisms."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.Normalizer')
    def test_normalizer_error_raises_exception(self, mock_normalizer_class,
                                               mock_get_schema, mock_json_reader,
                                               mock_azure_config, sample_fhir_patient):
        """Test normalizer errors are propagated as DataProcessingException."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        mock_normalizer_class.side_effect = DataProcessingException(
            "Normalization failed", "error", "602"
        )

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        fhir_df = pd.DataFrame([sample_fhir_patient])

        with pytest.raises(DataProcessingException) as exc_info:
            processor.normalizer(
                filepath_id='test-file',
                fhir_resource_type='Patient',
                process_data=True,
                fhir_data_df=fhir_df
            )

        assert '602' in str(exc_info.value.error_code)

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    def test_logs_processing_errors(self, mock_get_schema, mock_json_reader,
                                    mock_azure_config):
        """Test that processing errors are logged."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor
        import logging

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        # Test that normalizer logs when process_data is False
        with patch.object(logging, 'info') as mock_log:
            result = processor.normalizer(
                fhir_resource_type='Patient',
                process_data=False,
                fhir_data_df=pd.DataFrame(),
                filepath_id='test-file'
            )

            assert result is None
            mock_log.assert_called()


class TestShutdownHandling:
    """Test graceful shutdown handling."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    def test_graceful_shutdown_on_sigterm(self, mock_get_schema, mock_json_reader,
                                          mock_azure_config):
        """Test graceful shutdown when SIGTERM is received."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        mock_queue = MagicMock()
        mock_queue.receive_messages.return_value = []
        mock_queue.get_batch_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()

        mock_storage = MagicMock()
        mock_storage.get_staging_container_client.return_value = MagicMock()

        processor = CoreLoadProcessor(
            queue_client=mock_queue,
            storage_client=mock_storage,
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        # Create shutdown event and set it immediately
        shutdown_event = threading.Event()
        shutdown_event.set()

        # Should exit cleanly without processing
        processor.process_load_messages(Queue(), 1, shutdown_event)

        # Verify the loop exited due to shutdown event
        assert shutdown_event.is_set()

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    def test_completes_in_progress_work(self, mock_get_schema, mock_json_reader,
                                        mock_azure_config):
        """Test that processor can handle shutdown event cleanly."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {'Patient': {}}
        mock_json_reader.return_value = {'Patient': []}

        mock_queue = MagicMock()
        mock_storage = MagicMock()

        # Return empty immediately to exit cleanly
        mock_queue.receive_messages.return_value = []
        mock_queue.get_batch_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()

        mock_storage.get_staging_container_client.return_value = MagicMock()

        processor = CoreLoadProcessor(
            queue_client=mock_queue,
            storage_client=mock_storage,
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        shutdown_event = threading.Event()
        shutdown_event.set()  # Immediate shutdown

        # Should complete without error
        processor.process_load_messages(Queue(), 1, shutdown_event)

        # Verify shutdown was respected
        assert shutdown_event.is_set()


class TestRunMethod:
    """Test the run method."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    def test_run_calls_process_load_messages(self, mock_get_schema, mock_json_reader,
                                              mock_azure_config):
        """Test that run method calls process_load_messages."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        with patch.object(processor, 'process_load_messages') as mock_process:
            message_queue = Queue()
            shutdown_event = threading.Event()

            processor.run(message_queue, 5, shutdown_event)

            mock_process.assert_called_once_with(message_queue, 5, shutdown_event)


class TestGetFhirStructureLRUCache:
    """Verify that get_fhir_structure reuses its LRU cache."""

    def test_second_call_with_same_argument_does_not_reload_schema(self):
        """Schema file is read only once; a second call with the same path returns the cached object."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        CoreLoadProcessor.get_fhir_structure.cache_clear()
        try:
            with patch(
                'pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file'
            ) as mock_schema:
                mock_schema.return_value = {'Patient': {}}

                result1 = CoreLoadProcessor.get_fhir_structure('schema/fhir.schema.json')
                result2 = CoreLoadProcessor.get_fhir_structure('schema/fhir.schema.json')

                mock_schema.assert_called_once()
                assert result1 is result2
        finally:
            CoreLoadProcessor.get_fhir_structure.cache_clear()


class TestFhirConverterFinally:
    """Verify gc.collect() is called in the finally block of fhir_converter."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.signal.signal')
    @patch('pyfiles.hyperion_core.core_load_processor.gc')
    def test_gc_collect_called_when_threads_finish(
        self, mock_gc, mock_signal, mock_get_schema, mock_json_reader, mock_azure_config
    ):
        """gc.collect() is always invoked in the fhir_converter finally block."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        # Patch run() so submitted threads finish immediately
        with patch.object(processor, 'run', return_value=None):
            processor.fhir_converter()

        mock_gc.collect.assert_called()
