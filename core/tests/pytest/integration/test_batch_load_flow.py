"""Integration tests for batch load processing flow."""
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch

from pyfiles.dependencies.data_processing_error import DataProcessingException


@pytest.mark.integration
class TestBatchLoadFlow:
    """Integration tests for batch load processing."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_lineage_message')
    def test_batch_with_all_duplicates_skips_normalization(
        self, mock_lineage, mock_get_schema, mock_json_reader,
        mock_azure_config, sample_fhir_patient
    ):
        """Test when DB already has all records (all duplicates)."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {'Patient': {}}
        mock_json_reader.return_value = {'Patient': []}
        mock_lineage.return_value = {'filepath_id': 'test', 'is_inserted': True}

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        # Test that normalizer returns None when process_data is False
        result = processor.normalizer(
            fhir_id='Patient-1.ndjson',
            fhir_resource_type='Patient',
            process_data=False,  # All duplicates
            fhir_data_df=pd.DataFrame([sample_fhir_patient])
        )

        assert result is None

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.Normalizer')
    def test_batch_processes_data_when_flag_true(
        self, mock_normalizer_class, mock_get_schema, mock_json_reader,
        mock_azure_config, sample_fhir_patient
    ):
        """Test normalizer is called when process_data is True."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {'Patient': {'fields': []}}
        mock_json_reader.return_value = {'Patient': []}

        mock_normalizer_instance = MagicMock()
        mock_normalizer_instance.run.return_value = {
            'patient': pd.DataFrame({'id': ['test-patient-123']})
        }
        mock_normalizer_class.return_value = mock_normalizer_instance

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        result = processor.normalizer(
            fhir_id='Patient-1.ndjson',
            fhir_resource_type='Patient',
            process_data=True,
            fhir_data_df=pd.DataFrame([sample_fhir_patient])
        )

        assert result is not None
        assert 'patient' in result
        mock_normalizer_class.assert_called_once()

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.Normalizer')
    def test_normalizer_error_raises_data_processing_exception(
        self, mock_normalizer_class, mock_get_schema, mock_json_reader,
        mock_azure_config, sample_fhir_patient
    ):
        """Test normalization errors are wrapped in DataProcessingException."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {'Patient': {}}
        mock_json_reader.return_value = {'Patient': []}

        mock_normalizer_class.side_effect = ValueError("Invalid data format")

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


@pytest.mark.integration
class TestBatchLoadWithTransactions:
    """Integration tests for batch processing with transactions."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.commit_transaction')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_commits_all_tables_in_transaction(
        self, mock_rename, mock_process_df, mock_commit,
        mock_tx_block, mock_get_schema, mock_json_reader,
        mock_azure_config
    ):
        """Test transaction commits across multiple tables."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        # Two tables succeed
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
            'identifier_source': pd.DataFrame({'id': ['test-1'], 'value': ['123']})
        }

        processor.streamloader(
            filename='Patient-1.ndjson',
            resource_data_dictionary=resource_data,
            complex_dtypes={},
            array_counts_df=pd.DataFrame()
        )

        # Both tables should be committed
        assert mock_commit.call_count == 2

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.rollback_transaction')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_rollback_on_partial_failure(
        self, mock_rename, mock_process_df, mock_rollback,
        mock_tx_block, mock_get_schema, mock_json_reader,
        mock_azure_config
    ):
        """Test rollback when one table fails to prepare."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        # First succeeds, second fails
        mock_tx_block.side_effect = [
            (True, 'tx-patient', 'patient'),
            (False, 'tx-identifier', 'identifier_source')
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
            'identifier_source': pd.DataFrame({'id': ['test-1'], 'value': ['123']})
        }

        with pytest.raises(DataProcessingException) as exc_info:
            processor.streamloader(
                filename='Patient-1.ndjson',
                resource_data_dictionary=resource_data,
                complex_dtypes={},
                array_counts_df=pd.DataFrame()
            )

        assert '603' in str(exc_info.value.error_code)
        assert mock_rollback.call_count == 2  # Both rolled back


@pytest.mark.integration
class TestBatchLoadDataFiltering:
    """Integration tests for data filtering in batch processing."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.DBOps.filter_data_to_be_processed')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.create_pandas_dataframe')
    def test_get_processed_data_returns_filter_results(
        self, mock_create_df, mock_filter_data,
        mock_get_schema, mock_json_reader,
        mock_azure_config, sample_fhir_patient
    ):
        """Test get_processed_data returns filter results correctly."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        patient_df = pd.DataFrame([sample_fhir_patient])
        mock_create_df.return_value = patient_df

        # Simulate filtering - only new records returned
        mock_filter_data.return_value = (
            True,  # Has new data
            patient_df,
            pd.DataFrame({'id': ['test-patient-123'], 'identifier_max_array_size_db': [2]}),
            [{'filepath_id': 'test', 'operation': 'new'}]
        )

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        process_data, fhir_df, array_counts, audit_json = processor.get_processed_data(
            fhir_data=[sample_fhir_patient],
            fhir_resource_type='Patient',
            blob_url='https://test.blob.core.windows.net/staging/Patient-1.ndjson'
        )

        assert process_data is True
        assert len(fhir_df) == 1
        mock_filter_data.assert_called_once()

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.DBOps.filter_data_to_be_processed')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.create_pandas_dataframe')
    def test_get_processed_data_handles_all_duplicates(
        self, mock_create_df, mock_filter_data,
        mock_get_schema, mock_json_reader,
        mock_azure_config, sample_fhir_patient
    ):
        """Test get_processed_data returns False when all duplicates."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        patient_df = pd.DataFrame([sample_fhir_patient])
        mock_create_df.return_value = patient_df

        # Simulate all duplicates
        mock_filter_data.return_value = (
            False,  # No new data
            patient_df,
            pd.DataFrame(),
            [{'filepath_id': 'test', 'operation': 'duplicate'}]
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


@pytest.mark.integration
class TestGetProcessedDataWithRealDBOps:
    """Integration tests for get_processed_data calling real DBOps.filter_data_to_be_processed."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.create_pandas_dataframe')
    def test_get_processed_data_new_batch_records(
        self, mock_create_df, mock_get_schema, mock_json_reader, mock_azure_config
    ):
        """Real DBOps: batch-load URL, DB empty → all new records, process_data=True, audit 'new'."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        fhir_df = pd.DataFrame([{
            'id': 'patient-1',
            'meta': "{'versionId': '1', 'lastUpdated': '2024-01-15'}"
        }])
        mock_create_df.return_value = fhir_df

        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.create_connection.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=mock_pool
        )

        process_data, _, _, audit_json = processor.get_processed_data(
            fhir_data=[{'id': 'patient-1', 'meta': {'versionId': '1'}}],
            fhir_resource_type='Patient',
            blob_url='https://test.blob.core.windows.net/staging/batch-load/Patient-1.ndjson'
        )

        assert process_data is True
        assert len(audit_json) > 0
        assert all(d.get('operation') == 'new' for d in audit_json)

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.create_pandas_dataframe')
    def test_get_processed_data_duplicate_batch_records(
        self, mock_create_df, mock_get_schema, mock_json_reader, mock_azure_config
    ):
        """Real DBOps: DB returns same version → duplicate, process_data=False, audit 'duplicate'."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        fhir_df = pd.DataFrame([{
            'id': 'patient-1',
            'meta': "{'versionId': '1', 'lastUpdated': '2024-01-15'}"
        }])
        mock_create_df.return_value = fhir_df

        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.create_connection.return_value = mock_conn
        # DB has version 1 (same as patient versionId=1) → duplicate
        mock_conn.execute.return_value.fetchall.return_value = [{
            'id': 'patient-1',
            'meta_versionid_db': 1,
            'codeableconcept_max_array_size_db': 0,
            'identifier_max_array_size_db': 0,
            'reference_max_array_size_db': 0
        }]

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=mock_pool
        )

        process_data, _, _, audit_json = processor.get_processed_data(
            fhir_data=[{'id': 'patient-1', 'meta': {'versionId': '1'}}],
            fhir_resource_type='Patient',
            blob_url='https://test.blob.core.windows.net/staging/batch-load/Patient-1.ndjson'
        )

        assert process_data is False
        assert all(d.get('operation') == 'duplicate' for d in audit_json)

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.create_pandas_dataframe')
    def test_get_processed_data_update_batch_records(
        self, mock_create_df, mock_get_schema, mock_json_reader, mock_azure_config
    ):
        """Real DBOps: DB returns lower version → update, process_data=True, audit 'update'."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        fhir_df = pd.DataFrame([{
            'id': 'patient-1',
            'meta': "{'versionId': '2', 'lastUpdated': '2024-01-15'}"
        }])
        mock_create_df.return_value = fhir_df

        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.create_connection.return_value = mock_conn
        # DB has version 1 (lower than patient versionId=2) → update
        mock_conn.execute.return_value.fetchall.return_value = [{
            'id': 'patient-1',
            'meta_versionid_db': 1,
            'codeableconcept_max_array_size_db': 0,
            'identifier_max_array_size_db': 0,
            'reference_max_array_size_db': 0
        }]

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=mock_pool
        )

        process_data, _, _, audit_json = processor.get_processed_data(
            fhir_data=[{'id': 'patient-1', 'meta': {'versionId': '2'}}],
            fhir_resource_type='Patient',
            blob_url='https://test.blob.core.windows.net/staging/batch-load/Patient-1.ndjson'
        )

        assert process_data is True
        assert all(d.get('operation') == 'update' for d in audit_json)
