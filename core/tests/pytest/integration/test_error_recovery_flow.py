"""Integration tests for error recovery and failure handling flows."""
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch

from pyfiles.dependencies.data_processing_error import DataProcessingException


@pytest.mark.integration
class TestErrorRecoveryFlow:
    """Integration tests for failure handling and recovery."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.Normalizer')
    def test_normalizer_error_raises_602(
        self, mock_normalizer_class, mock_get_schema, mock_json_reader,
        mock_azure_config, sample_fhir_patient
    ):
        """Test normalization errors are wrapped with error code 602."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {'Patient': {}}
        mock_json_reader.return_value = {'Patient': []}

        mock_normalizer_class.side_effect = ValueError("Invalid FHIR format")

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        with pytest.raises(DataProcessingException) as exc_info:
            processor.normalizer(
                fhir_id='Patient-1.ndjson',
                fhir_resource_type='Patient',
                process_data=True,
                fhir_data_df=pd.DataFrame([sample_fhir_patient])
            )

        assert exc_info.value.error_code == '602'

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_streamload_error_raises_603(
        self, mock_rename, mock_process_df, mock_tx_block,
        mock_get_schema, mock_json_reader, mock_azure_config
    ):
        """Test DB insert failures are wrapped with error code 603."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        mock_process_df.return_value = pd.DataFrame({'id': ['test-1']})
        mock_tx_block.side_effect = Exception("DB connection failed")

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
                array_counts_df=pd.DataFrame()
            )

        assert exc_info.value.error_code == '603'


@pytest.mark.integration
class TestTransactionRollbackFlow:
    """Integration tests for transaction rollback scenarios."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.rollback_transaction')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_rollback_all_tables_on_any_failure(
        self, mock_rename, mock_process_df, mock_rollback,
        mock_tx_block, mock_get_schema, mock_json_reader,
        mock_azure_config
    ):
        """Test all tables are rolled back when any one fails."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        # Three tables: first two succeed, third fails
        mock_tx_block.side_effect = [
            (True, 'tx-patient', 'patient'),
            (True, 'tx-identifier', 'identifier_source'),
            (False, 'tx-address', 'address')  # This one fails
        ]

        mock_process_df.return_value = pd.DataFrame({'id': ['test-1']})

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
            'patient': pd.DataFrame({'id': ['test-1']}),
            'identifier_source': pd.DataFrame({'id': ['test-1']}),
            'address': pd.DataFrame({'id': ['test-1']})
        }

        with pytest.raises(DataProcessingException) as exc_info:
            processor.streamloader(
                filename='Patient-1.ndjson',
                resource_data_dictionary=resource_data,
                complex_dtypes={},
                array_counts_df=pd.DataFrame()
            )

        assert '603' in str(exc_info.value.error_code)
        # All three should be rolled back
        assert mock_rollback.call_count == 3

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.commit_transaction')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_no_rollback_when_all_succeed(
        self, mock_rename, mock_process_df, mock_commit,
        mock_tx_block, mock_get_schema, mock_json_reader,
        mock_azure_config
    ):
        """Test no rollback when all tables succeed."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        mock_tx_block.side_effect = [
            (True, 'tx-patient', 'patient'),
            (True, 'tx-identifier', 'identifier_source')
        ]

        mock_process_df.return_value = pd.DataFrame({'id': ['test-1']})

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
            'patient': pd.DataFrame({'id': ['test-1']}),
            'identifier_source': pd.DataFrame({'id': ['test-1']})
        }

        # Should not raise
        processor.streamloader(
            filename='Patient-1.ndjson',
            resource_data_dictionary=resource_data,
            complex_dtypes={},
            array_counts_df=pd.DataFrame()
        )

        # All should be committed
        assert mock_commit.call_count == 2


@pytest.mark.integration
class TestDataProcessingExceptionHandling:
    """Integration tests for DataProcessingException handling."""

    def test_data_processing_error_method_copies_to_failure(self):
        """Test data_processing_error copies blob to failure container."""
        exception = DataProcessingException(
            message="Processing failed",
            errors="Error details",
            error_code="602"
        )

        mock_storage = MagicMock()
        mock_storage.copy_ndjson_to_failure.return_value = "602/batch-load/Patient-1.ndjson"

        fhir_event_message = {
            "url": "https://test.blob.core.windows.net/staging/batch-load/Patient-1.ndjson"
        }

        reject_filepath, blob_url = exception.data_processing_error(
            fhir_event_message=fhir_event_message,
            filename="Patient-1.ndjson",
            storage_client=mock_storage
        )

        mock_storage.copy_ndjson_to_failure.assert_called_once_with(
            filename="Patient-1.ndjson",
            blob_url="https://test.blob.core.windows.net/staging/batch-load/Patient-1.ndjson",
            error_code="602"
        )
        assert reject_filepath == "602/batch-load/Patient-1.ndjson"

    def test_exception_preserves_original_error_info(self):
        """Test exception preserves error details."""
        original_error = ValueError("Original error")

        try:
            raise original_error
        except ValueError as e:
            exception = DataProcessingException(
                message="Wrapped error",
                errors=str(e),
                error_code="602"
            )

        assert exception.errors == "Original error"
        assert exception.error_code == "602"


@pytest.mark.integration
class TestEmptyDataframeHandling:
    """Integration tests for empty dataframe handling."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_skips_empty_dataframe_in_streamloader(
        self, mock_rename, mock_process_df, mock_tx_block,
        mock_get_schema, mock_json_reader, mock_azure_config
    ):
        """Test streamloader skips empty dataframes."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        # Return empty dataframe
        mock_process_df.return_value = pd.DataFrame()

        config = mock_azure_config.copy()
        config['silver_layer']['is_transaction'] = 'False'

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=config,
            db_connection_pool=MagicMock()
        )

        resource_data = {'patient': pd.DataFrame({'id': []})}  # Empty

        # Should not raise
        processor.streamloader(
            filename='Patient-1.ndjson',
            resource_data_dictionary=resource_data,
            complex_dtypes={},
            array_counts_df=pd.DataFrame()
        )

        # Transaction block should not be called for empty dataframe
        mock_tx_block.assert_not_called()


@pytest.mark.integration
class TestNormalizationToStreamloadErrorChain:
    """Integration tests for the normalizer → streamloader error propagation chain."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.Normalizer')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_full_normalization_to_streamload_error_chain(
        self, mock_rename, mock_process_df, mock_tx_block,
        mock_normalizer_class, mock_get_schema, mock_json_reader,
        mock_azure_config, sample_fhir_patient
    ):
        """Normalizer succeeds then streamloader's transaction_block raises → 603 propagates."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {'Patient': {}}
        mock_json_reader.return_value = {'Patient': []}

        mock_normalizer_instance = MagicMock()
        mock_normalizer_instance.run.return_value = {
            'patient': pd.DataFrame({'id': ['patient-1']})
        }
        mock_normalizer_class.return_value = mock_normalizer_instance

        mock_process_df.return_value = pd.DataFrame({'id': ['patient-1']})
        mock_tx_block.side_effect = DataProcessingException(
            'Transaction failed', 'DB error', '603'
        )

        config = mock_azure_config.copy()
        config['silver_layer']['is_transaction'] = 'True'

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=config,
            db_connection_pool=MagicMock()
        )

        result = processor.normalizer(
            fhir_id='Patient-1.ndjson',
            fhir_resource_type='Patient',
            process_data=True,
            fhir_data_df=pd.DataFrame([sample_fhir_patient])
        )

        assert result is not None

        with pytest.raises(DataProcessingException) as exc_info:
            processor.streamloader(
                filename='Patient-1.ndjson',
                resource_data_dictionary=result,
                complex_dtypes={},
                array_counts_df=pd.DataFrame()
            )

        assert exc_info.value.error_code == '603'

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    def test_audit_and_lineage_queued_on_normalizer_failure(
        self, mock_get_schema, mock_json_reader, mock_azure_config
    ):
        """process_load_messages: normalizer raises → insert_to_reject_queue and insert_to_audit_queue called."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor
        from queue import Queue
        import threading

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        mock_queue = MagicMock()
        mock_storage = MagicMock()
        mock_storage.copy_ndjson_to_failure.return_value = '602/batch-load/Patient-1.ndjson'

        shutdown_event = threading.Event()

        def receive_side_effect(*args, **kwargs):
            shutdown_event.set()
            return [MagicMock()]

        mock_queue.receive_messages.side_effect = receive_side_effect
        mock_queue.read_message_body.return_value = {
            'url': 'https://test.blob.core.windows.net/staging/batch-load/Patient-1.ndjson',
            'retry_count': 0
        }
        mock_queue.get_ndjson_filepath.return_value = (
            'https://test.blob.core.windows.net/staging/batch-load/Patient-1.ndjson',
            'Patient',
            'Patient-1.ndjson'
        )
        mock_storage.read.return_value = [{'id': 'p1', 'meta': {'versionId': '1'}}]

        config = mock_azure_config.copy()
        config['default_value']['is_audit'] = 'False'
        config['initialization'] = {'cloud_storage': 'azure'}

        processor = CoreLoadProcessor(
            queue_client=mock_queue,
            storage_client=mock_storage,
            fhir_client=MagicMock(),
            project_configurations=config,
            db_connection_pool=MagicMock()
        )

        audit_json = [{'filepath_id': 'test-fp-id', 'operation': 'new'}]
        with patch.object(processor, 'get_processed_data', return_value=(
            True, pd.DataFrame(), pd.DataFrame(), audit_json
        )):
            with patch.object(processor, 'normalizer', side_effect=DataProcessingException(
                'Normalization failed', 'Schema error', '602'
            )):
                processor.process_load_messages(Queue(), 1, shutdown_event)

        mock_queue.insert_to_reject_queue.assert_called_once()
        mock_queue.insert_to_audit_queue.assert_called_once()
