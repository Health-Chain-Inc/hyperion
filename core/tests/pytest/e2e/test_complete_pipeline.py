"""End-to-end tests for complete data processing pipeline.

These tests verify the complete flow of data through multiple components,
testing component integration without going through the message loop.
"""
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch

from pyfiles.dependencies.data_processing_error import DataProcessingException


@pytest.mark.e2e
@pytest.mark.slow
class TestCompletePipeline:
    """End-to-end tests for full data pipeline."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.DBOps.filter_data_to_be_processed')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.create_pandas_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.Normalizer')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.commit_transaction')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_patient_resource_full_pipeline(
        self, mock_rename, mock_process_df, mock_commit, mock_tx_block,
        mock_normalizer_class, mock_create_df, mock_filter_data,
        mock_get_schema, mock_json_reader,
        e2e_config, complete_patient_bundle
    ):
        """
        Complete flow: FHIR Patient data -> get_processed_data ->
        Normalizer -> Streamloader -> Commit

        Verifies:
        - Patient data is filtered for duplicates
        - Normalizer is called with correct data
        - Streamloader commits patient and identifier tables
        """
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        # Setup schema and deletion attributes
        mock_get_schema.return_value = {
            'Patient': {'fields': ['id', 'name', 'gender', 'birthDate', 'identifier']}
        }
        mock_json_reader.return_value = {'Patient': ['identifier', 'name', 'address']}

        # Create input dataframe
        patient_df = pd.DataFrame(complete_patient_bundle)
        mock_create_df.return_value = patient_df

        # Setup filtering - returns new data to process
        array_counts_df = pd.DataFrame({
            'id': ['e2e-patient-001', 'e2e-patient-002'],
            'identifier_max_array_size_db': [3, 1],
            'codeableconcept_max_array_size_db': [0, 0],
            'reference_max_array_size_db': [0, 0]
        })
        mock_filter_data.return_value = (
            True,  # process_data
            patient_df,
            array_counts_df,
            [{
                'filepath_id': 'batch-load/20240115/Patient-1.ndjson',
                'resource_type': 'Patient',
                'record_count': 2
            }]
        )

        # Setup normalizer to return patient and identifier data
        mock_normalizer_instance = MagicMock()
        normalized_data = {
            'patient': pd.DataFrame({
                'id': ['e2e-patient-001', 'e2e-patient-002'],
                'name_family': ['TestFamily', 'AnotherPatient'],
                'gender': ['male', 'female'],
                'birthdate': ['1980-01-15', '1990-06-20'],
                'meta_versionid': ['1', '1']
            }),
            'identifier_source': pd.DataFrame({
                'id': ['e2e-patient-001', 'e2e-patient-002'],
                'identifier_source': ['TestSource', 'TestSource']
            })
        }
        mock_normalizer_instance.run.return_value = normalized_data
        mock_normalizer_class.return_value = mock_normalizer_instance

        # Setup transaction manager - two tables succeed
        mock_tx_block.side_effect = [
            (True, 'tx-patient', 'patient'),
            (True, 'tx-identifier', 'identifier_source')
        ]

        # Setup dataframe processing
        mock_process_df.return_value = pd.DataFrame({'id': ['e2e-patient-001', 'e2e-patient-002']})

        config = e2e_config.copy()
        config['silver_layer']['is_transaction'] = 'True'

        # Create processor
        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=config,
            db_connection_pool=MagicMock()
        )

        # Step 1: Get processed data (filtering)
        process_data, fhir_df, array_counts, audit_json = processor.get_processed_data(
            fhir_data=complete_patient_bundle,
            fhir_resource_type='Patient',
            blob_url='https://test.blob.core.windows.net/staging/batch-load/Patient-1.ndjson',
        )

        # Verify filtering results
        assert process_data is True, "Should have data to process"
        assert len(fhir_df) == 2, "Should have 2 patient records"
        mock_filter_data.assert_called_once()

        # Step 2: Normalize the data
        result = processor.normalizer(
            fhir_id='Patient-1.ndjson',
            fhir_resource_type='Patient',
            process_data=True,
            fhir_data_df=fhir_df
        )

        # Verify normalizer was called correctly
        assert result is not None, "Normalizer should return data"
        assert 'patient' in result, "Should have patient table"
        assert 'identifier_source' in result, "Should have identifier table"
        mock_normalizer_class.assert_called_once()
        assert mock_normalizer_class.call_args[0][1] == 'Patient'

        # Step 3: Streamload the normalized data
        processor.streamloader(
            filename='Patient-1.ndjson',
            resource_data_dictionary=result,
            complex_dtypes={},
            array_counts_df=array_counts
        )

        # Verify both tables were committed
        assert mock_commit.call_count == 2, "Both patient and identifier tables should be committed"

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.DBOps.filter_data_to_be_processed')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.create_pandas_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.Normalizer')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.commit_transaction')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_observation_resource_full_pipeline(
        self, mock_rename, mock_process_df, mock_commit, mock_tx_block,
        mock_normalizer_class, mock_create_df, mock_filter_data,
        mock_get_schema, mock_json_reader,
        e2e_config, complete_observation_bundle
    ):
        """Complete flow for Observation -> measurement table."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {'Observation': {'fields': []}}
        mock_json_reader.return_value = {'Observation': ['code', 'category']}

        obs_df = pd.DataFrame(complete_observation_bundle)
        mock_create_df.return_value = obs_df

        mock_filter_data.return_value = (
            True, obs_df, pd.DataFrame(),
            [{'filepath_id': 'Observation-1.ndjson', 'resource_type': 'Observation'}]
        )

        mock_normalizer_instance = MagicMock()
        mock_normalizer_instance.run.return_value = {
            'measurement': pd.DataFrame({
                'id': ['e2e-obs-001'],
                'status': ['final'],
                'value_quantity_value': [72]
            })
        }
        mock_normalizer_class.return_value = mock_normalizer_instance

        mock_tx_block.return_value = (True, 'tx-obs', 'measurement')
        mock_process_df.return_value = pd.DataFrame({'id': ['e2e-obs-001']})

        config = e2e_config.copy()
        config['silver_layer']['is_transaction'] = 'True'

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=config,
            db_connection_pool=MagicMock()
        )

        # Step 1: Filter data
        process_data, fhir_df, array_counts, _ = processor.get_processed_data(
            fhir_data=complete_observation_bundle,
            fhir_resource_type='Observation',
            blob_url='https://test.blob.core.windows.net/staging/Observation-1.ndjson',
        )

        assert process_data is True

        # Step 2: Normalize
        result = processor.normalizer(
            fhir_id='Observation-1.ndjson',
            fhir_resource_type='Observation',
            process_data=True,
            fhir_data_df=fhir_df
        )

        assert result is not None
        assert 'measurement' in result
        # Verify resource type was passed to normalizer
        assert mock_normalizer_class.call_args[0][1] == 'Observation'

        # Step 3: Streamload
        processor.streamloader(
            filename='Observation-1.ndjson',
            resource_data_dictionary=result,
            complex_dtypes={},
            array_counts_df=array_counts
        )

        mock_commit.assert_called_once()

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.DBOps.filter_data_to_be_processed')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.create_pandas_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.Normalizer')
    def test_pipeline_error_recovery_and_audit(
        self, mock_normalizer_class, mock_create_df, mock_filter_data,
        mock_get_schema, mock_json_reader,
        e2e_config, complete_patient_bundle
    ):
        """
        Test pipeline handles errors gracefully and creates proper exception.
        """
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {'Patient': {}}
        mock_json_reader.return_value = {'Patient': []}

        patient_df = pd.DataFrame(complete_patient_bundle)
        mock_create_df.return_value = patient_df

        mock_filter_data.return_value = (
            True, patient_df, pd.DataFrame(), [{'filepath_id': 'test'}]
        )

        # Normalizer fails with schema validation error
        mock_normalizer_class.side_effect = ValueError("Schema validation failed")

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=e2e_config,
            db_connection_pool=MagicMock()
        )

        # Step 1: Filter succeeds
        process_data, fhir_df, _, _ = processor.get_processed_data(
            fhir_data=complete_patient_bundle,
            fhir_resource_type='Patient',
            blob_url='https://test.blob.core.windows.net/staging/Patient-1.ndjson',
        )

        assert process_data is True

        # Step 2: Normalizer fails - should be wrapped in DataProcessingException
        with pytest.raises(DataProcessingException) as exc_info:
            processor.normalizer(
                fhir_id='Patient-1.ndjson',
                fhir_resource_type='Patient',
                process_data=True,
                fhir_data_df=fhir_df
            )

        # Verify error code 602 for normalization failure
        assert exc_info.value.error_code == '602'
        assert 'Schema validation failed' in str(exc_info.value.errors)

        # Verify the exception can be used to create audit trail
        mock_storage = MagicMock()
        mock_storage.copy_ndjson_to_failure.return_value = "602/Patient-1.ndjson"

        reject_path, _ = exc_info.value.data_processing_error(
            fhir_event_message={'url': 'https://test/Patient-1.ndjson'},
            filename='Patient-1.ndjson',
            storage_client=mock_storage
        )

        assert '602' in reject_path
        mock_storage.copy_ndjson_to_failure.assert_called_once()


@pytest.mark.e2e
@pytest.mark.slow
class TestMultiResourcePipeline:
    """E2E tests for processing multiple resource types."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.DBOps.filter_data_to_be_processed')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.create_pandas_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.Normalizer')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.commit_transaction')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_sequential_resource_processing(
        self, mock_rename, mock_process_df, mock_commit, mock_tx_block,
        mock_normalizer_class, mock_create_df, mock_filter_data,
        mock_get_schema, mock_json_reader,
        e2e_config, complete_patient_bundle, complete_observation_bundle
    ):
        """Test processing Patient then Observation sequentially."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {'Patient': {}, 'Observation': {}}
        mock_json_reader.return_value = {'Patient': [], 'Observation': []}

        patient_df = pd.DataFrame(complete_patient_bundle)
        obs_df = pd.DataFrame(complete_observation_bundle)

        # Setup to return different dataframes for each call
        mock_create_df.side_effect = [patient_df, obs_df]

        mock_filter_data.side_effect = [
            (True, patient_df, pd.DataFrame(), [{'filepath_id': 'Patient-1'}]),
            (True, obs_df, pd.DataFrame(), [{'filepath_id': 'Observation-1'}])
        ]

        # Normalizer returns different results based on call
        mock_normalizer_instance = MagicMock()
        mock_normalizer_instance.run.side_effect = [
            {'patient': pd.DataFrame({'id': ['p1']})},
            {'measurement': pd.DataFrame({'id': ['o1']})}
        ]
        mock_normalizer_class.return_value = mock_normalizer_instance

        mock_tx_block.return_value = (True, 'tx', 'table')
        mock_process_df.return_value = pd.DataFrame({'id': ['test']})

        config = e2e_config.copy()
        config['silver_layer']['is_transaction'] = 'True'

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=config,
            db_connection_pool=MagicMock()
        )

        # Process Patient
        process_data, fhir_df, _, _ = processor.get_processed_data(
            fhir_data=complete_patient_bundle,
            fhir_resource_type='Patient',
            blob_url='https://test/Patient-1.ndjson',
        )
        patient_result = processor.normalizer(
            fhir_id='Patient-1.ndjson',
            fhir_resource_type='Patient',
            process_data=True,
            fhir_data_df=fhir_df
        )
        processor.streamloader(
            filename='Patient-1.ndjson',
            resource_data_dictionary=patient_result,
            complex_dtypes={},
            array_counts_df=pd.DataFrame()
        )

        # Process Observation
        process_data, fhir_df, _, _ = processor.get_processed_data(
            fhir_data=complete_observation_bundle,
            fhir_resource_type='Observation',
            blob_url='https://test/Observation-1.ndjson',
        )
        obs_result = processor.normalizer(
            fhir_id='Observation-1.ndjson',
            fhir_resource_type='Observation',
            process_data=True,
            fhir_data_df=fhir_df
        )
        processor.streamloader(
            filename='Observation-1.ndjson',
            resource_data_dictionary=obs_result,
            complex_dtypes={},
            array_counts_df=pd.DataFrame()
        )

        # Verify both were processed
        assert mock_normalizer_class.call_count == 2
        # Patient called first, then Observation
        calls = mock_normalizer_class.call_args_list
        assert calls[0][0][1] == 'Patient'
        assert calls[1][0][1] == 'Observation'

        # Both committed
        assert mock_commit.call_count == 2

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.DBOps.filter_data_to_be_processed')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.create_pandas_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.Normalizer')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.rollback_transaction')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_transaction_rollback_on_second_table_failure(
        self, mock_rename, mock_process_df, mock_rollback, mock_tx_block,
        mock_normalizer_class, mock_create_df, mock_filter_data,
        mock_get_schema, mock_json_reader,
        e2e_config, complete_patient_bundle
    ):
        """Test that when second table fails, both are rolled back."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {'Patient': {}}
        mock_json_reader.return_value = {'Patient': []}

        patient_df = pd.DataFrame(complete_patient_bundle)
        mock_create_df.return_value = patient_df

        mock_filter_data.return_value = (True, patient_df, pd.DataFrame(), [{}])

        mock_normalizer_instance = MagicMock()
        mock_normalizer_instance.run.return_value = {
            'patient': pd.DataFrame({'id': ['p1']}),
            'identifier_source': pd.DataFrame({'id': ['p1']})
        }
        mock_normalizer_class.return_value = mock_normalizer_instance

        # First table succeeds, second fails
        mock_tx_block.side_effect = [
            (True, 'tx-patient', 'patient'),
            (False, 'tx-identifier', 'identifier_source')
        ]
        mock_process_df.return_value = pd.DataFrame({'id': ['p1']})

        config = e2e_config.copy()
        config['silver_layer']['is_transaction'] = 'True'

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=config,
            db_connection_pool=MagicMock()
        )

        # Filter and normalize
        _, fhir_df, _, _ = processor.get_processed_data(
            fhir_data=complete_patient_bundle,
            fhir_resource_type='Patient',
            blob_url='https://test/Patient-1.ndjson',
        )
        result = processor.normalizer(
            fhir_id='Patient-1.ndjson',
            fhir_resource_type='Patient',
            process_data=True,
            fhir_data_df=fhir_df
        )

        # Streamloader should fail and rollback
        with pytest.raises(DataProcessingException) as exc_info:
            processor.streamloader(
                filename='Patient-1.ndjson',
                resource_data_dictionary=result,
                complex_dtypes={},
                array_counts_df=pd.DataFrame()
            )

        assert exc_info.value.error_code == '603'
        # Both tables should be rolled back
        assert mock_rollback.call_count == 2


@pytest.mark.e2e
@pytest.mark.slow
class TestFullBatchPipelineNewRecords:
    """E2E test: real DBOps with mocked DB → all-new records → normalizer → streamloader → commit."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.create_pandas_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.Normalizer')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.commit_transaction')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_full_batch_pipeline_new_records(
        self, mock_rename, mock_process_df, mock_commit, mock_tx_block,
        mock_normalizer_class, mock_create_df,
        mock_get_schema, mock_json_reader,
        e2e_config, complete_patient_bundle
    ):
        """
        End-to-end: real DBOps.filter_data_to_be_processed (mocked DB returning all-new),
        then normalizer() and streamloader() → both patient and identifier tables committed.
        """
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {'Patient': {}}
        mock_json_reader.return_value = {'Patient': []}

        # Real DBOps will receive this DataFrame from create_pandas_dataframe
        patient_df = pd.DataFrame([{
            'id': 'e2e-patient-001',
            'meta': "{'versionId': '1', 'lastUpdated': '2024-01-15T10:00:00Z'}"
        }])
        mock_create_df.return_value = patient_df

        # DB pool returns empty fetchall → all records are new
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.create_connection.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        # Normalizer returns patient + identifier tables
        mock_normalizer_instance = MagicMock()
        mock_normalizer_instance.run.return_value = {
            'patient': pd.DataFrame({'id': ['e2e-patient-001'], 'gender': ['male']}),
            'identifier_source': pd.DataFrame({
                'id': ['e2e-patient-001'],
                'identifier_source': ['TestSource']
            })
        }
        mock_normalizer_class.return_value = mock_normalizer_instance

        mock_tx_block.side_effect = [
            (True, 'tx-patient', 'patient'),
            (True, 'tx-identifier', 'identifier_source')
        ]
        mock_process_df.return_value = pd.DataFrame({'id': ['e2e-patient-001']})

        config = e2e_config.copy()
        config['silver_layer']['is_transaction'] = 'True'

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=config,
            db_connection_pool=mock_pool
        )

        # Step 1: Filter — real DBOps, mocked DB → all new
        process_data, fhir_df, array_counts, audit_json = processor.get_processed_data(
            fhir_data=complete_patient_bundle[:1],
            fhir_resource_type='Patient',
            blob_url='https://test.blob.core.windows.net/staging/batch-load/Patient-1.ndjson'
        )

        assert process_data is True
        assert all(d.get('operation') == 'new' for d in audit_json)
        mock_conn.execute.assert_called_once()  # DB was queried

        # Step 2: Normalize
        result = processor.normalizer(
            fhir_id='Patient-1.ndjson',
            fhir_resource_type='Patient',
            process_data=process_data,
            fhir_data_df=fhir_df
        )

        assert result is not None
        assert 'patient' in result
        assert 'identifier_source' in result
        mock_normalizer_class.assert_called_once()

        # Step 3: Streamload → commit both tables
        processor.streamloader(
            filename='Patient-1.ndjson',
            resource_data_dictionary=result,
            complex_dtypes={},
            array_counts_df=array_counts
        )

        assert mock_commit.call_count == 2
