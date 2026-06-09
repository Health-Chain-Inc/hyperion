"""Integration tests for event-driven processing flow."""
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch


@pytest.mark.integration
class TestEventLoadFlow:
    """Integration tests for event-driven processing."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.Normalizer')
    def test_new_event_calls_normalizer(
        self, mock_normalizer_class, mock_get_schema, mock_json_reader,
        mock_azure_config, sample_fhir_patient
    ):
        """Test event processing calls normalizer when process_data is True."""
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

        # New event - process_data is True
        result = processor.normalizer(
            fhir_id='Patient-p1.ndjson',
            fhir_resource_type='Patient',
            process_data=True,
            fhir_data_df=pd.DataFrame([sample_fhir_patient])
        )

        assert result is not None
        mock_normalizer_class.assert_called_once()

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    def test_event_with_lower_version_skips_normalization(
        self, mock_get_schema, mock_json_reader,
        mock_azure_config, sample_fhir_patient
    ):
        """Test version comparison logic - lower version events are skipped."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {'Patient': {}}
        mock_json_reader.return_value = {'Patient': []}

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        # Event has lower version than DB - process_data is False
        result = processor.normalizer(
            fhir_id='Patient-p1.ndjson',
            fhir_resource_type='Patient',
            process_data=False,  # Simulating lower version
            fhir_data_df=pd.DataFrame([sample_fhir_patient])
        )

        assert result is None


@pytest.mark.integration
class TestEventLoadDataProcessing:
    """Integration tests for event load data processing."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.DBOps.filter_data_to_be_processed')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.create_pandas_dataframe')
    def test_get_processed_data_with_event_update_flag(
        self, mock_create_df, mock_filter_data,
        mock_get_schema, mock_json_reader,
        mock_azure_config, sample_fhir_patient
    ):
        """Test get_processed_data passes event_load_is_update correctly."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        patient_df = pd.DataFrame([sample_fhir_patient])
        mock_create_df.return_value = patient_df

        mock_filter_data.return_value = (
            True, patient_df, pd.DataFrame(),
            [{'filepath_id': 'test'}]
        )

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        # Test with event-load URL
        processor.get_processed_data(
            fhir_data=[sample_fhir_patient],
            fhir_resource_type='Patient',
            blob_url='https://test.blob.core.windows.net/staging/event-load/Patient-p1.ndjson'
        )

        # Verify filter_data_to_be_processed was called
        mock_filter_data.assert_called_once()

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.DBOps.filter_data_to_be_processed')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.create_pandas_dataframe')
    def test_get_processed_data_with_new_event(
        self, mock_create_df, mock_filter_data,
        mock_get_schema, mock_json_reader,
        mock_azure_config, sample_fhir_patient
    ):
        """Test get_processed_data for new events."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        patient_df = pd.DataFrame([sample_fhir_patient])
        mock_create_df.return_value = patient_df

        mock_filter_data.return_value = (
            True, patient_df, pd.DataFrame(),
            [{'filepath_id': 'test', 'operation': 'new'}]
        )

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        # Test with event-load URL (new event)
        process_data, _, _, _ = processor.get_processed_data(
            fhir_data=[sample_fhir_patient],
            fhir_resource_type='Patient',
            blob_url='https://test.blob.core.windows.net/staging/event-load/Patient-p1.ndjson'
        )

        assert process_data is True
        mock_filter_data.assert_called_once()


@pytest.mark.integration
class TestEventLoadStreamloading:
    """Integration tests for event load streamloading."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.commit_transaction')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_streamloader_commits_event_data(
        self, mock_rename, mock_process_df, mock_commit,
        mock_tx_block, mock_get_schema, mock_json_reader,
        mock_azure_config
    ):
        """Test streamloader commits event data successfully."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        mock_tx_block.return_value = (True, 'tx-event', 'patient')
        mock_process_df.return_value = pd.DataFrame({'id': ['event-patient-1']})

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
            'patient': pd.DataFrame({'id': ['event-patient-1']})
        }

        processor.streamloader(
            filename='Patient-event-1.ndjson',
            resource_data_dictionary=resource_data,
            complex_dtypes={},
            array_counts_df=pd.DataFrame()
        )

        mock_commit.assert_called_once()


@pytest.mark.integration
class TestGetProcessedDataEventLoadWithRealDBOps:
    """Integration tests for event-load path with real DBOps.filter_data_to_be_processed."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.create_pandas_dataframe')
    def test_get_processed_data_event_new_v1(
        self, mock_create_df, mock_get_schema, mock_json_reader, mock_azure_config
    ):
        """Event-load URL + versionId=1 → bypasses DB entirely, process_data=True, audit 'new'."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        fhir_df = pd.DataFrame([{
            'id': 'patient-p1',
            'meta': "{'versionId': '1', 'lastUpdated': '2024-01-15'}"
        }])
        mock_create_df.return_value = fhir_df

        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.create_connection.return_value = mock_conn

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=mock_pool
        )

        process_data, _, _, audit_json = processor.get_processed_data(
            fhir_data=[{'id': 'patient-p1', 'meta': {'versionId': '1'}}],
            fhir_resource_type='Patient',
            blob_url='https://test.blob.core.windows.net/staging/event-load/Patient-p1.ndjson'
        )

        assert process_data is True
        assert len(audit_json) > 0
        assert all(d.get('operation') == 'new' for d in audit_json)
        # DB should not have been queried (early return for v1)
        mock_conn.execute.assert_not_called()

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.create_pandas_dataframe')
    def test_get_processed_data_event_update_v2(
        self, mock_create_df, mock_get_schema, mock_json_reader, mock_azure_config
    ):
        """Event-load URL + versionId=2, DB empty → process_data=True, audit 'update'."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        fhir_df = pd.DataFrame([{
            'id': 'patient-p1',
            'meta': "{'versionId': '2', 'lastUpdated': '2024-01-15'}"
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
            fhir_data=[{'id': 'patient-p1', 'meta': {'versionId': '2'}}],
            fhir_resource_type='Patient',
            blob_url='https://test.blob.core.windows.net/staging/event-load/Patient-p1.ndjson'
        )

        assert process_data is True
        assert len(audit_json) > 0
        assert all(d.get('operation') == 'update' for d in audit_json)
