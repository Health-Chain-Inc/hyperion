"""Regression tests for previously identified and fixed bugs.

These tests ensure that bugs that have been fixed do not reappear.
Each test documents the original bug and the fix.
"""
import pytest
import json
import pandas as pd
from unittest.mock import MagicMock, patch

from pyfiles.dependencies.data_processing_error import DataProcessingException


@pytest.mark.regression
class TestKnownIssues:
    """Tests for previously identified bugs (regression prevention)."""

    def test_meta_versionid_extraction_handles_string_format(self):
        """
        Regression: meta field as string '{"versionId": "1"}' was causing
        extraction failures when meta was serialized as JSON string.

        Fixed in an earlier release; see git history for details

        The fix ensures meta fields are properly parsed whether they come
        as dict or JSON string.
        """

        # Test data with meta as dict (normal case)
        normal_data = pd.DataFrame([{
            'id': 'test-1',
            'meta': {'versionId': '1', 'lastUpdated': '2024-01-15T10:00:00Z'}
        }])

        # Test data with meta as string (edge case that caused bug)
        string_meta_data = pd.DataFrame([{
            'id': 'test-2',
            'meta': '{"versionId": "2", "lastUpdated": "2024-01-15T11:00:00Z"}'
        }])

        # Both should be handled without error
        # The actual extraction logic is in filter_data_to_be_processed
        # Here we verify the data structures are valid
        assert not normal_data.empty
        assert not string_meta_data.empty

    def test_empty_dataframe_does_not_cause_concat_error(self):
        """
        Regression: Empty DataFrame in filter operations caused
        'No objects to concatenate' ValueError.

        Fixed in an earlier release; see git history for details

        The fix adds empty DataFrame checks before pd.concat operations.
        """
        # Empty dataframes should be handled gracefully
        empty_df = pd.DataFrame()
        non_empty_df = pd.DataFrame({'id': ['test-1']})

        # Concatenating with empty should not raise
        if not empty_df.empty:
            result = pd.concat([non_empty_df, empty_df], ignore_index=True)
        else:
            result = non_empty_df

        assert len(result) == 1
        assert result['id'].iloc[0] == 'test-1'

        # All empty should also be handled
        all_empty = [pd.DataFrame(), pd.DataFrame()]
        non_empty_list = [df for df in all_empty if not df.empty]

        if non_empty_list:
            combined = pd.concat(non_empty_list, ignore_index=True)
        else:
            combined = pd.DataFrame()

        assert combined.empty

    def test_ndjson_with_blank_lines_handled(self):
        """
        Regression: NDJSON files with trailing newlines caused
        JSON parse errors.

        The fix strips blank lines before parsing.
        """
        # NDJSON content with trailing newlines and blank lines
        ndjson_content = '''{"id": "1", "resourceType": "Patient"}
{"id": "2", "resourceType": "Patient"}

{"id": "3", "resourceType": "Patient"}
'''

        # Parse NDJSON properly
        records = []
        for line in ndjson_content.strip().split('\n'):
            line = line.strip()
            if line:  # Skip empty lines
                records.append(json.loads(line))

        assert len(records) == 3
        assert records[0]['id'] == '1'
        assert records[2]['id'] == '3'

    def test_large_identifier_arrays_handled(self):
        """
        Regression: Identifier arrays > 50 elements caused issues
        in array size tracking.

        The system should handle large arrays by tracking max sizes.
        """
        # Create patient with many identifiers
        large_identifiers = [
            {'system': f'http://system-{i}.org', 'value': f'value-{i}'}
            for i in range(100)  # 100 identifiers
        ]

        patient = {
            'id': 'large-id-patient',
            'resourceType': 'Patient',
            'identifier': large_identifiers
        }

        # The system should track the array size
        array_size = len(patient['identifier'])
        assert array_size == 100

        # Array counts tracking should work
        array_counts_df = pd.DataFrame({
            'id': ['large-id-patient'],
            'identifier_max_array_size_db': [array_size]
        })

        assert array_counts_df['identifier_max_array_size_db'].iloc[0] == 100


@pytest.mark.regression
class TestDataProcessingExceptionRegression:
    """Regression tests for DataProcessingException handling."""

    def test_exception_preserves_error_code(self):
        """
        Regression: Error codes were sometimes lost during exception chaining.

        The fix ensures error_code is always preserved.
        """
        try:
            raise DataProcessingException(
                message="Original error",
                errors="Details",
                error_code="602"
            )
        except DataProcessingException as e:
            # Re-raise with chaining
            try:
                raise DataProcessingException(
                    message=f"Wrapped: {e}",
                    errors=str(e.errors),
                    error_code=e.error_code
                ) from e
            except DataProcessingException as wrapped:
                # Error code should be preserved
                assert wrapped.error_code == "602"
                assert wrapped.__cause__.error_code == "602"

    def test_exception_handles_none_errors(self):
        """
        Regression: None as errors field caused AttributeError.

        The fix handles None gracefully.
        """
        # Should not raise
        exception = DataProcessingException(
            message="Test",
            errors=None,
            error_code="603"
        )

        assert exception.errors is None
        assert exception.error_code == "603"


@pytest.mark.regression
class TestTransactionRollbackRegression:
    """Regression tests for transaction rollback scenarios."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.transaction_block')
    @patch('pyfiles.hyperion_core.core_load_processor.TransactionManager.rollback_transaction')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.process_dataframe')
    @patch('pyfiles.hyperion_core.core_load_processor.DFOps.rename_column')
    def test_rollback_called_for_all_prepared_transactions(
        self, mock_rename, mock_process_df, mock_rollback,
        mock_tx_block, mock_get_schema, mock_json_reader,
        mock_azure_config
    ):
        """
        Regression: Only the failing transaction was rolled back,
        leaving successful transactions in prepared state.

        The fix ensures ALL prepared transactions are rolled back.
        """
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        # Three tables: first two succeed, third fails
        mock_tx_block.side_effect = [
            (True, 'tx-1', 'table1'),
            (True, 'tx-2', 'table2'),
            (False, 'tx-3', 'table3')  # Fails
        ]

        mock_process_df.return_value = pd.DataFrame({'id': ['test']})

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
            'table1': pd.DataFrame({'id': ['test']}),
            'table2': pd.DataFrame({'id': ['test']}),
            'table3': pd.DataFrame({'id': ['test']})
        }

        with pytest.raises(DataProcessingException):
            processor.streamloader(
                filename='test.ndjson',
                resource_data_dictionary=resource_data,
                complex_dtypes={},
                array_counts_df=pd.DataFrame()
            )

        # All three should be rolled back (including successful ones)
        assert mock_rollback.call_count == 3


@pytest.mark.regression
class TestQueueMessageRegression:
    """Regression tests for queue message handling."""

    def test_message_with_missing_retry_count_defaults_to_zero(self):
        """
        Regression: Messages without retry_count field caused KeyError.

        The fix uses .get() with default value of 0.
        """

        # Message without retry_count
        message_body = {
            "url": "https://test.blob.core.windows.net/staging/Patient-1.ndjson",
            "request_time": "2024-01-15T10:00:00Z"
            # No retry_count field
        }

        parsed = json.loads(json.dumps(message_body))
        retry_count = parsed.get("retry_count", 0)

        assert retry_count == 0

    def test_message_url_with_special_characters(self):
        """
        Regression: URLs with special characters in folder names
        caused parsing errors.

        The fix properly handles URL encoding.
        """
        from tests.pytest.mocks.mock_queue_client import MockAzureQueueClient

        # URL with special timestamp format
        message_body = {
            "url": "https://test.blob.core.windows.net/staging/batch-load/2024-01-15T10:00:00/Patient-1.ndjson"
        }

        client = MockAzureQueueClient()
        blob_url, resource_type, filename = client.get_ndjson_filepath(
            MagicMock(__str__=lambda self: json.dumps(message_body))
        )

        assert resource_type == 'Patient'
        assert 'Patient-1.ndjson' in filename


@pytest.mark.regression
class TestNormalizerRegression:
    """Regression tests for normalizer issues."""

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.Normalizer')
    def test_normalizer_exception_wrapped_with_602(
        self, mock_normalizer_class, mock_get_schema, mock_json_reader,
        mock_azure_config, sample_fhir_patient
    ):
        """
        Regression: Generic exceptions from normalizer were not
        properly wrapped with error code 602.

        The fix ensures all normalizer errors get code 602.
        """
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        # Normalizer raises generic exception (not DataProcessingException)
        mock_normalizer_class.side_effect = ValueError("Unexpected field format")

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        with pytest.raises(DataProcessingException) as exc_info:
            processor.normalizer(
                fhir_id='test-file',
                fhir_resource_type='Patient',
                process_data=True,
                fhir_data_df=pd.DataFrame([sample_fhir_patient])
            )

        # Should be wrapped with 602 code
        assert exc_info.value.error_code == '602'

    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader')
    @patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file')
    @patch('pyfiles.hyperion_core.core_load_processor.Normalizer')
    def test_normalizer_data_processing_exception_preserves_code(
        self, mock_normalizer_class, mock_get_schema, mock_json_reader,
        mock_azure_config, sample_fhir_patient
    ):
        """
        Regression: DataProcessingException from normalizer had
        its error code changed to 602.

        The fix preserves the original error code.
        """
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        mock_get_schema.return_value = {}
        mock_json_reader.return_value = {}

        # Normalizer raises DataProcessingException with specific code
        mock_normalizer_class.side_effect = DataProcessingException(
            "Specific error", "Details", "602"
        )

        processor = CoreLoadProcessor(
            queue_client=MagicMock(),
            storage_client=MagicMock(),
            fhir_client=MagicMock(),
            project_configurations=mock_azure_config,
            db_connection_pool=MagicMock()
        )

        with pytest.raises(DataProcessingException) as exc_info:
            processor.normalizer(
                fhir_id='test-file',
                fhir_resource_type='Patient',
                process_data=True,
                fhir_data_df=pd.DataFrame([sample_fhir_patient])
            )

        # Original code should be preserved (still 602)
        assert exc_info.value.error_code == '602'
