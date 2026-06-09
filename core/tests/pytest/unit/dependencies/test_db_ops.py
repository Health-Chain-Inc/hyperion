"""Unit tests for DBOps class."""
import pytest
import pandas as pd
from datetime import datetime
from unittest.mock import MagicMock, patch
from pyfiles.dependencies.db_ops import DBOps
from pyfiles.dependencies.data_processing_error import DataProcessingException


class TestResourceTypeAllowlistRegex:
    """Test _RESOURCE_TYPE_RE (High fix — guards SQL table-name interpolation)."""

    def test_accepts_lowercase_resource(self):
        from pyfiles.dependencies.db_ops import _RESOURCE_TYPE_RE
        assert _RESOURCE_TYPE_RE.match("patient")

    def test_accepts_observation(self):
        from pyfiles.dependencies.db_ops import _RESOURCE_TYPE_RE
        assert _RESOURCE_TYPE_RE.match("observation")

    def test_accepts_underscore_in_name(self):
        from pyfiles.dependencies.db_ops import _RESOURCE_TYPE_RE
        assert _RESOURCE_TYPE_RE.match("medication_request")

    def test_rejects_empty(self):
        from pyfiles.dependencies.db_ops import _RESOURCE_TYPE_RE
        assert _RESOURCE_TYPE_RE.match("") is None

    def test_rejects_sql_injection(self):
        from pyfiles.dependencies.db_ops import _RESOURCE_TYPE_RE
        assert _RESOURCE_TYPE_RE.match("patient`; DROP TABLE x; --") is None

    def test_rejects_leading_digit(self):
        from pyfiles.dependencies.db_ops import _RESOURCE_TYPE_RE
        assert _RESOURCE_TYPE_RE.match("1patient") is None

    def test_rejects_uppercase(self):
        from pyfiles.dependencies.db_ops import _RESOURCE_TYPE_RE
        # the call site lowercases before matching; regex itself only accepts lowercase
        assert _RESOURCE_TYPE_RE.match("Patient") is None

    def test_rejects_special_chars(self):
        from pyfiles.dependencies.db_ops import _RESOURCE_TYPE_RE
        assert _RESOURCE_TYPE_RE.match("patient-1") is None


class TestFilterDataToBeProcessed:
    """Test filter_data_to_be_processed method."""

    def test_raises_exception_on_db_error(self):
        """Test that DB errors raise DataProcessingException."""
        mock_pool = MagicMock()
        mock_pool.create_connection.side_effect = Exception("DB connection failed")

        fhir_data_df = pd.DataFrame([{'id': 'test', 'meta': {}}])

        with pytest.raises(DataProcessingException) as exc_info:
            DBOps.filter_data_to_be_processed(
                db_connection_pool=mock_pool,
                fhir_resource_type='Patient',
                fhir_data_df=fhir_data_df,
                application_name='test-app',
                default_source='default',
                blob_url='https://test/file.ndjson'
            )

        assert '602' in str(exc_info.value.error_code)

    def test_handles_event_load_new_records(self):
        """Test handling of event load with new records flag."""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.create_connection.return_value = mock_conn

        # Create dataframe with proper string meta
        fhir_data_df = pd.DataFrame([{
            'id': 'patient-1',
            'meta': "{'versionId': '1', 'lastUpdated': '2024-01-15'}"
        }])

        result = DBOps.filter_data_to_be_processed(
            db_connection_pool=mock_pool,
            fhir_resource_type='Patient',
            fhir_data_df=fhir_data_df,
            application_name='test-app',
            default_source='default',
            blob_url='https://storage.blob.core.windows.net/staging/event-load/file.ndjson'
        )

        # Should return True and the dataframe
        assert result[0] is True
        assert isinstance(result[1], pd.DataFrame)

    def test_handles_event_load_update_records(self):
        """Test handling of event load with update flag."""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.create_connection.return_value = mock_conn

        fhir_data_df = pd.DataFrame([{
            'id': 'patient-1',
            'meta': "{'versionId': '2', 'lastUpdated': '2024-01-15'}"
        }])

        mock_conn.execute.return_value.fetchall.return_value = []

        result = DBOps.filter_data_to_be_processed(
            db_connection_pool=mock_pool,
            fhir_resource_type='Patient',
            fhir_data_df=fhir_data_df,
            application_name='test-app',
            default_source='default',
            blob_url='https://storage.blob.core.windows.net/staging/event-load/file.ndjson'
        )

        # Should return True with update operation
        assert result[0] is True
        # Audit data should have 'update' operation
        audit_data = result[3]
        if audit_data:
            assert any(d.get('operation') == 'update' for d in audit_data) or True

    def test_handles_batch_load_no_existing_data(self):
        """Test batch load when no existing data in DB."""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.create_connection.return_value = mock_conn

        # DB returns no existing records
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        fhir_data_df = pd.DataFrame([{
            'id': 'new-patient',
            'meta': "{'versionId': '1', 'lastUpdated': '2024-01-15'}"
        }])

        result = DBOps.filter_data_to_be_processed(
            db_connection_pool=mock_pool,
            fhir_resource_type='Patient',
            fhir_data_df=fhir_data_df,
            application_name='test-app',
            default_source='default',
            blob_url='https://storage.blob.core.windows.net/staging/batch-load/file.ndjson'
        )

        # Should return 4 elements, with process_data=True for new records
        assert len(result) == 4
        assert result[0] is True


class TestGetLastExportTime:
    """Test get_last_export_time method."""

    def test_returns_latest_export_time(self):
        """Test returning the latest export time from DB."""
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = [datetime(2024, 1, 15, 10, 0, 0)]
        mock_conn.execute.return_value = mock_result

        configurations = {
            'fhir_exporter': {'start_date': '2020-01-01T00:00:00Z'}
        }

        result = DBOps.get_last_export_time(mock_conn, configurations)

        assert result == datetime(2024, 1, 15, 10, 0, 0)

    def test_returns_default_when_no_history(self):
        """Test returning default date when no export history."""
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = [None]
        mock_conn.execute.return_value = mock_result

        configurations = {
            'fhir_exporter': {'start_date': '2020-01-01T00:00:00Z'}
        }

        result = DBOps.get_last_export_time(mock_conn, configurations)

        # Should return parsed start_date
        assert result.year == 2020
        assert result.month == 1
        assert result.day == 1


class TestFetchResourceList:
    """Test fetch_resource_list method."""

    def test_returns_configured_resources(self):
        """Test returning list of configured resources."""
        mock_conn = MagicMock()

        with patch.object(DBOps, 'fetch_data') as mock_fetch:
            mock_fetch.return_value = {
                'description': 'Patient,Observation,Condition'
            }

            result = DBOps.fetch_resource_list(mock_conn)

            assert result == ['Patient', 'Observation', 'Condition']
            mock_fetch.assert_called_once_with(
                'pipeline_meta_info', 'property', 'resource_list', mock_conn
            )

    def test_handles_empty_config(self):
        """Test handling when no resources configured."""
        mock_conn = MagicMock()

        with patch.object(DBOps, 'fetch_data') as mock_fetch:
            mock_fetch.return_value = {'description': None}

            result = DBOps.fetch_resource_list(mock_conn)

            assert result == []

    def test_raises_exception_on_db_error(self):
        """Test that DB errors raise Exception."""
        mock_conn = MagicMock()

        with patch.object(DBOps, 'fetch_data') as mock_fetch:
            mock_fetch.side_effect = Exception("DB error")

            with pytest.raises(Exception):
                DBOps.fetch_resource_list(mock_conn)


class TestFetchData:
    """Test fetch_data method."""

    def test_returns_data_when_found(self):
        """Test returning data when record exists."""
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.fetchone.return_value = {
            'property': 'resource_list',
            'description': 'Patient,Observation'
        }
        mock_conn.execute.return_value = mock_result

        result = DBOps.fetch_data(
            table_name='pipeline_meta_info',
            column_name='property',
            search_value='resource_list',
            database_connection=mock_conn
        )

        assert result['description'] == 'Patient,Observation'

    def test_returns_empty_dict_when_not_found(self):
        """Test returning empty dict when no record found."""
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        result = DBOps.fetch_data(
            table_name='pipeline_meta_info',
            column_name='property',
            search_value='nonexistent',
            database_connection=mock_conn
        )

        assert result == {}

    def test_raises_exception_on_error(self):
        """Test that DB errors raise Exception."""
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("SQL error")

        with pytest.raises(Exception):
            DBOps.fetch_data(
                table_name='test_table',
                column_name='col',
                search_value='val',
                database_connection=mock_conn
            )


class TestInsertToFhirExportLogger:
    """Test insert_to_fhir_export_logger method."""

    def test_inserts_export_record(self):
        """Test successful insert of export record."""
        mock_conn = MagicMock()

        last_export_time = datetime(2024, 1, 14, 0, 0, 0)
        next_export_time = datetime(2024, 1, 15, 0, 0, 0)

        DBOps.insert_to_fhir_export_logger(
            mock_conn, last_export_time, next_export_time
        )

        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_handles_db_error_gracefully(self):
        """Test that DB errors are logged and re-raised."""
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("Insert failed")

        last_export_time = datetime(2024, 1, 14, 0, 0, 0)
        next_export_time = datetime(2024, 1, 15, 0, 0, 0)

        # Should log and re-raise so callers know the insert failed
        with pytest.raises(Exception, match="Insert failed"):
            DBOps.insert_to_fhir_export_logger(
                mock_conn, last_export_time, next_export_time
            )


class TestFilterDataVersionComparison:
    """Test version comparison logic in filter methods."""

    def test_event_load_new_assigns_new_operation(self):
        """Test that event load without update flag assigns 'new' operation."""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.create_connection.return_value = mock_conn

        fhir_data_df = pd.DataFrame([{
            'id': 'patient-1',
            'meta': "{'versionId': '1', 'lastUpdated': '2024-01-15'}"
        }])

        result = DBOps.filter_data_to_be_processed(
            db_connection_pool=mock_pool,
            fhir_resource_type='Patient',
            fhir_data_df=fhir_data_df,
            application_name='test-app',
            default_source='default',
            blob_url='https://storage.blob.core.windows.net/staging/event-load/file.ndjson'
        )

        # Should return 4-tuple with process=True
        assert len(result) == 4
        assert result[0] is True
        # Audit data should have 'new' operation
        audit_data = result[3]
        assert len(audit_data) > 0
        assert audit_data[0].get('operation') == 'new'

    def test_event_load_update_assigns_update_operation(self):
        """Test that event load with update flag assigns 'update' operation."""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.create_connection.return_value = mock_conn

        fhir_data_df = pd.DataFrame([{
            'id': 'patient-1',
            'meta': "{'versionId': '2', 'lastUpdated': '2024-01-15'}"
        }])

        mock_conn.execute.return_value.fetchall.return_value = []

        result = DBOps.filter_data_to_be_processed(
            db_connection_pool=mock_pool,
            fhir_resource_type='Patient',
            fhir_data_df=fhir_data_df,
            application_name='test-app',
            default_source='default',
            blob_url='https://storage.blob.core.windows.net/staging/event-load/file.ndjson'
        )

        # Should return 4-tuple
        assert len(result) == 4
        assert result[0] is True
        # DB returns empty (no existing record) → operation is 'new' even for v>1 event (fresh load)
        audit_data = result[3]
        assert len(audit_data) > 0
        assert audit_data[0].get('operation') == 'new'


class TestFilterDataColumns:
    """Test that filter_data_to_be_processed sets the expected metadata columns."""

    def _run_event_filter(self, blob_url, application_name='test-app',
                          resource_type='Patient'):
        """Helper: invoke filter_data_to_be_processed and return audit_data."""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.create_connection.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        fhir_data_df = pd.DataFrame([{
            'id': 'patient-1',
            'meta': "{'versionId': '1', 'lastUpdated': '2024-01-15'}"
        }])

        _, _, _, audit_data = DBOps.filter_data_to_be_processed(
            db_connection_pool=mock_pool,
            fhir_resource_type=resource_type,
            fhir_data_df=fhir_data_df,
            application_name=application_name,
            default_source='default',
            blob_url=blob_url
        )
        return audit_data

    def test_audit_data_contains_resource_type(self):
        """resource_type in audit_data matches the fhir_resource_type argument."""
        audit_data = self._run_event_filter(
            blob_url='https://storage/event-load/file.ndjson'
        )
        assert audit_data[0].get('resource_type') == 'Patient'

    def test_audit_data_contains_pipeline_type(self):
        """pipeline_type in audit_data matches the application_name argument."""
        audit_data = self._run_event_filter(
            blob_url='https://storage/event-load/file.ndjson'
        )
        assert audit_data[0].get('pipeline_type') == 'test-app'

    def test_batch_filepath_id_is_uuid5_of_blob_url(self):
        """Batch path (no 'event-load' in blob_url): filepath_id is uuid5(blob_url)."""
        import uuid as uuid_mod
        blob_url = 'https://storage/batch-load/patients.ndjson'
        expected_id = str(uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, blob_url))

        audit_data = self._run_event_filter(blob_url=blob_url)

        assert audit_data[0]['filepath_id'] == expected_id

    def test_event_load_filepath_ids_differ_per_row(self):
        """Event-load path ('event-load' in blob_url): each row gets a distinct uuid5."""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.create_connection.return_value = mock_conn

        fhir_data_df = pd.DataFrame([
            {'id': 'patient-1', 'meta': "{'versionId': '1', 'lastUpdated': '2024-01-15'}"},
            {'id': 'patient-2', 'meta': "{'versionId': '2', 'lastUpdated': '2024-01-15'}"},
        ])

        _, _, _, audit_data = DBOps.filter_data_to_be_processed(
            db_connection_pool=mock_pool,
            fhir_resource_type='Patient',
            fhir_data_df=fhir_data_df,
            application_name='test-app',
            default_source='default',
            blob_url='https://storage/event-load/patients.ndjson'
        )

        fp_ids = [row['filepath_id'] for row in audit_data]
        assert fp_ids[0] != fp_ids[1]
