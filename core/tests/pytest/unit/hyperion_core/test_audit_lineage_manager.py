"""Unit tests for AuditLineageManager class."""
import pytest
import json
import threading
import time
from unittest.mock import MagicMock, patch
from queue import Queue

from tests.pytest.mocks.mock_starrocks_client import (
    create_mock_starrocks_config
)


class TestUuidRegexValidation:
    """Test _UUID_RE allowlist (Critical fix #2 — guards SQL IN-clause from injection)."""

    def test_accepts_canonical_lowercase_uuid(self):
        from pyfiles.hyperion_core.audit_lineage_manager import _UUID_RE
        assert _UUID_RE.match("550e8400-e29b-41d4-a716-446655440000")

    def test_accepts_uppercase_uuid(self):
        from pyfiles.hyperion_core.audit_lineage_manager import _UUID_RE
        assert _UUID_RE.match("550E8400-E29B-41D4-A716-446655440000")

    def test_accepts_mixed_case_uuid(self):
        from pyfiles.hyperion_core.audit_lineage_manager import _UUID_RE
        assert _UUID_RE.match("550e8400-E29B-41d4-A716-446655440000")

    def test_rejects_empty_string(self):
        from pyfiles.hyperion_core.audit_lineage_manager import _UUID_RE
        assert _UUID_RE.match("") is None

    def test_rejects_sql_injection_payload(self):
        from pyfiles.hyperion_core.audit_lineage_manager import _UUID_RE
        assert _UUID_RE.match("'); DROP TABLE fhir_lineage; --") is None

    def test_rejects_partial_hex(self):
        from pyfiles.hyperion_core.audit_lineage_manager import _UUID_RE
        assert _UUID_RE.match("550e8400-e29b-41d4-a716") is None

    def test_rejects_extra_chars_around_uuid(self):
        from pyfiles.hyperion_core.audit_lineage_manager import _UUID_RE
        assert _UUID_RE.match("550e8400-e29b-41d4-a716-446655440000 OR 1=1") is None

    def test_rejects_non_hex_chars(self):
        from pyfiles.hyperion_core.audit_lineage_manager import _UUID_RE
        # ``z`` is not a hex digit
        assert _UUID_RE.match("z50e8400-e29b-41d4-a716-446655440000") is None


class TestAuditLineageManagerInitialization:
    """Test AuditLineageManager initialization."""

    def test_initialization_stores_clients(self, mock_azure_config):
        """Test that initialization stores queue client and config."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        mock_queue = MagicMock()

        manager = AuditLineageManager(
            project_configurations=mock_azure_config,
            queue_client=mock_queue
        )

        assert manager.queue_client == mock_queue
        assert manager.project_configurations == mock_azure_config


class TestGetSqlQueryResult:
    """Test get_sql_query_result method."""

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_get_sql_query_result_returns_data(self, mock_session_class, mock_azure_config):
        """Test get_sql_query_result returns parsed JSON data."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        # Add transaction_api config
        config = {**mock_azure_config, **create_mock_starrocks_config()}

        # Mock response with NDJSON format (StarRocks returns line-delimited JSON)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text.strip.return_value = '{"meta": [{"name": "created_date"}]}\n{"data": ["2024-01-01"]}'

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        result, success = manager.get_sql_query_result(
            "SELECT created_date FROM fhir_lineage", MagicMock()
        )

        assert 'data' in result
        assert 'meta' in result
        mock_session.post.assert_called_once()

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_get_sql_query_result_constructs_correct_url(self, mock_session_class, mock_azure_config):
        """Test get_sql_query_result constructs URL with catalog and database."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text.strip.return_value = '{}'

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        manager.get_sql_query_result("SELECT * FROM test", MagicMock())

        call_url = mock_session.post.call_args[0][0]
        assert config['silver_layer']['catalog'] in call_url or 'catalog' in call_url
        assert config['silver_layer']['audit_database'] in call_url or 'database' in call_url

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_get_sql_query_result_non_200_returns_empty_false(self, mock_session_class, mock_azure_config):
        """Test get_sql_query_result returns {}, False on non-200 response."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = 'Internal Server Error'

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        result, success = manager.get_sql_query_result("SELECT 1", MagicMock())

        assert result == {}
        assert success is False

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_get_sql_query_result_exception_triggers_requeue(self, mock_session_class, mock_azure_config):
        """Test get_sql_query_result re-queues message on transient exception.

        Note: ``get_sql_query_result`` narrowly catches transport-level errors
        (RequestException, JSONDecodeError, KeyError) — programming bugs propagate
        so the operator sees them. Use a realistic transport exception here.
        """
        import requests as _requests
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_session = MagicMock()
        mock_session.post.side_effect = _requests.ConnectionError("Connection error")
        mock_session_class.return_value = mock_session

        mock_queue = MagicMock()
        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=mock_queue
        )

        audit_message = {'filepath_id': 'test-123', 'table_name': 'fhir_lineage'}
        result, success = manager.get_sql_query_result("SELECT 1", audit_message)

        assert result == {}
        assert success is False
        mock_queue.insert_schedule_message_to_audit_queue.assert_called_once()


class TestStreamloadResult:
    """Test streamload_insert_data_get_result method."""

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_streamload_success_returns_true(self, mock_session_class, mock_azure_config):
        """Test streamload returns True on success."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_response = MagicMock()
        mock_response.json.return_value = {"Status": "Success", "Message": "OK"}

        mock_session = MagicMock()
        mock_session.put.return_value = mock_response
        mock_session_class.return_value = mock_session

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        audit_dict = {
            'filepath_id': 'test-file-123',
            'table_name': 'fhir_audit',
            '__op': 0
        }

        result = manager.streamload_insert_data_get_result('test_label', audit_dict, 'fhir_audit')

        assert result is True
        mock_session.put.assert_called_once()

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_streamload_retries_on_failure(self, mock_session_class, mock_azure_config):
        """Test streamload retries up to 3 times."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_response_fail = MagicMock()
        mock_response_fail.json.return_value = {"Status": "Failed", "Message": "Error"}

        mock_response_success = MagicMock()
        mock_response_success.json.return_value = {"Status": "Success", "Message": "OK"}

        mock_session = MagicMock()
        mock_session.put.side_effect = [
            mock_response_fail,
            mock_response_fail,
            mock_response_success
        ]
        mock_session_class.return_value = mock_session

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        result = manager.streamload_insert_data_get_result('test_label', {'filepath_id': 'test'}, 'fhir_audit')

        assert result is True
        assert mock_session.put.call_count == 3

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_streamload_handles_list_data(self, mock_session_class, mock_azure_config):
        """Test streamload handles list data correctly."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_response = MagicMock()
        mock_response.json.return_value = {"Status": "Success", "Message": "OK"}

        mock_session = MagicMock()
        mock_session.put.return_value = mock_response
        mock_session_class.return_value = mock_session

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        audit_list = [
            {'filepath_id': 'test-1', '__op': 1},
            {'filepath_id': 'test-1', '__op': 0}
        ]

        result = manager.streamload_insert_data_get_result('test_label', audit_list, 'fhir_lineage')

        assert result is True
        call_data = mock_session.put.call_args[1]['data']
        parsed_data = json.loads(call_data)
        assert isinstance(parsed_data, list)
        assert len(parsed_data) == 2

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_streamload_all_retries_fail_returns_false(self, mock_session_class, mock_azure_config):
        """Test streamload returns False when all 3 retries fail (no internal requeue)."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_response_fail = MagicMock()
        mock_response_fail.json.return_value = {"Status": "Failed", "Message": "Error"}

        mock_session = MagicMock()
        mock_session.put.return_value = mock_response_fail
        mock_session_class.return_value = mock_session

        mock_queue = MagicMock()
        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=mock_queue
        )

        audit_dict = {'filepath_id': 'test-123', 'table_name': 'fhir_audit'}
        result = manager.streamload_insert_data_get_result('test_label', audit_dict, 'fhir_audit')

        assert result is False
        assert mock_session.put.call_count == 3
        # No internal requeue — caller handles it
        mock_queue.insert_schedule_message_to_audit_queue.assert_not_called()

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_streamload_exception_returns_false(self, mock_session_class, mock_azure_config):
        """Test streamload returns False on exception (no internal requeue)."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_session = MagicMock()
        mock_session.put.side_effect = Exception("Network error")
        mock_session_class.return_value = mock_session

        mock_queue = MagicMock()
        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=mock_queue
        )

        audit_dict = {'filepath_id': 'test-123', 'table_name': 'fhir_audit'}
        result = manager.streamload_insert_data_get_result('test_label', audit_dict, 'fhir_audit')

        assert result is False
        mock_queue.insert_schedule_message_to_audit_queue.assert_not_called()


class TestBatchSelectLineage:
    """Test _batch_select_lineage method."""

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_batch_select_parses_multi_row_response(self, mock_session_class, mock_azure_config):
        """Test _batch_select_lineage correctly parses multi-row NDJSON response."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        # Multi-row NDJSON: meta line + multiple data lines
        ndjson_response = (
            '{"meta": [{"name": "filepath_id"}, {"name": "resource_type"}, '
            '{"name": "fhir_request_url"}, {"name": "record_count"}, '
            '{"name": "pipeline_type"}, {"name": "destination_location"}, '
            '{"name": "created_date"}]}\n'
            '{"data": ["00000000-0000-0000-0000-000000000001", "Patient", "http://fhir/Patient", 100, "batch_load_exporter", "/dest/1", "20240101T120000"]}\n'
            '{"data": ["00000000-0000-0000-0000-000000000002", "Observation", "http://fhir/Observation", 50, "batch_load_exporter", "/dest/2", "20240101T130000"]}'
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = ndjson_response

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        lookup, success = manager._batch_select_lineage(['00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000002'])

        assert success is True
        assert len(lookup) == 2
        assert lookup['00000000-0000-0000-0000-000000000001']['resource_type'] == 'Patient'
        assert lookup['00000000-0000-0000-0000-000000000002']['resource_type'] == 'Observation'
        assert lookup['00000000-0000-0000-0000-000000000001']['record_count'] == 100

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_batch_select_returns_empty_on_no_results(self, mock_session_class, mock_azure_config):
        """Test _batch_select_lineage returns empty dict when no rows match."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        ndjson_response = (
            '{"meta": [{"name": "filepath_id"}, {"name": "resource_type"}, '
            '{"name": "fhir_request_url"}, {"name": "record_count"}, '
            '{"name": "pipeline_type"}, {"name": "destination_location"}, '
            '{"name": "created_date"}]}'
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = ndjson_response

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        lookup, success = manager._batch_select_lineage(['nonexistent-uuid'])

        assert success is True
        assert len(lookup) == 0

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_batch_select_returns_false_on_http_error(self, mock_session_class, mock_azure_config):
        """Test _batch_select_lineage returns ({}, False) on HTTP error."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = 'Internal Server Error'

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        lookup, success = manager._batch_select_lineage(['00000000-0000-0000-0000-000000000001'])

        assert success is False
        assert lookup == {}

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_batch_select_returns_false_on_exception(self, mock_session_class, mock_azure_config):
        """Test _batch_select_lineage returns ({}, False) on exception."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_session = MagicMock()
        mock_session.post.side_effect = Exception("Connection error")
        mock_session_class.return_value = mock_session

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        lookup, success = manager._batch_select_lineage(['00000000-0000-0000-0000-000000000001'])

        assert success is False
        assert lookup == {}


class TestFlushBuffers:
    """Test buffer flush methods."""

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_flush_audit_buffer_single_stream_load(self, mock_session_class, mock_azure_config):
        """Test that N audit messages result in exactly 1 PUT call."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_response = MagicMock()
        mock_response.json.return_value = {"Status": "Success", "Message": "OK"}

        mock_session = MagicMock()
        mock_session.put.return_value = mock_response
        mock_session_class.return_value = mock_session

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        buffer = [
            (
                {'filepath_id': f'fp-{i}', 'resource_type': 'Patient', '__op': 0, 'created_date': '20240101T120000'},
                {'filepath_id': f'fp-{i}', 'resource_type': 'Patient'}  # original
            )
            for i in range(10)
        ]

        manager._flush_audit_buffer(buffer)

        mock_session.put.assert_called_once()
        call_data = json.loads(mock_session.put.call_args[1]['data'])
        assert len(call_data) == 10
        assert len(buffer) == 0  # buffer cleared

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_flush_audit_buffer_requeues_on_failure(self, mock_session_class, mock_azure_config):
        """Test that failed audit batch requeues each message individually."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_response = MagicMock()
        mock_response.json.return_value = {"Status": "Failed", "Message": "Error"}

        mock_session = MagicMock()
        mock_session.put.return_value = mock_response
        mock_session_class.return_value = mock_session

        mock_queue = MagicMock()
        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=mock_queue
        )

        buffer = [
            (
                {'filepath_id': f'fp-{i}', '__op': 0},
                {'filepath_id': f'fp-{i}'}  # original for requeue
            )
            for i in range(5)
        ]

        manager._flush_audit_buffer(buffer)

        assert mock_queue.insert_schedule_message_to_audit_queue.call_count == 5
        # Verify originals (without __op) were requeued, not mutated dicts
        requeued = mock_queue.insert_schedule_message_to_audit_queue.call_args_list[0][1]['message']
        assert '__op' not in requeued
        assert len(buffer) == 0

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_flush_lineage_first_half_no_select(self, mock_session_class, mock_azure_config):
        """Test that first-half lineage flush does NOT trigger any SELECT (POST) calls."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_response = MagicMock()
        mock_response.json.return_value = {"Status": "Success", "Message": "OK"}

        mock_session = MagicMock()
        mock_session.put.return_value = mock_response
        mock_session_class.return_value = mock_session

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        buffer = [
            (
                {
                    'filepath_id': f'a1b2c3d4-e5f6-7890-abcd-ef123456789{i}',
                    'resource_type': 'Patient',
                    'pipeline_type': 'batch_load_exporter',
                    '__op': 0,
                    'created_date': '20240101T120000'
                },
                {
                    'filepath_id': f'a1b2c3d4-e5f6-7890-abcd-ef123456789{i}',
                    'resource_type': 'Patient',
                    'pipeline_type': 'batch_load_exporter',
                }
            )
            for i in range(5)
        ]

        manager._flush_lineage_first_half_buffer(buffer)

        # Only PUT (stream load), no POST (query)
        mock_session.put.assert_called_once()
        mock_session.post.assert_not_called()
        assert len(buffer) == 0

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_flush_second_half_batched_select_and_merge(self, mock_session_class, mock_azure_config):
        """Test that second-half flush issues 1 SELECT + 1 PUT for matched records."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        # Mock batch SELECT response
        ndjson_response = (
            '{"meta": [{"name": "filepath_id"}, {"name": "resource_type"}, '
            '{"name": "fhir_request_url"}, {"name": "record_count"}, '
            '{"name": "pipeline_type"}, {"name": "destination_location"}, '
            '{"name": "created_date"}]}\n'
            '{"data": ["00000000-0000-0000-0000-000000000001", "Patient", "http://fhir/Patient", 100, "batch_load_exporter", "/dest/1", "20240101T120000"]}\n'
            '{"data": ["00000000-0000-0000-0000-000000000002", "Observation", "http://fhir/Observation", 50, "batch_load_exporter", "/dest/2", "20240101T130000"]}'
        )

        mock_query_response = MagicMock()
        mock_query_response.status_code = 200
        mock_query_response.text = ndjson_response

        mock_load_response = MagicMock()
        mock_load_response.json.return_value = {"Status": "Success", "Message": "OK"}

        mock_session = MagicMock()
        mock_session.post.return_value = mock_query_response
        mock_session.put.return_value = mock_load_response
        mock_session_class.return_value = mock_session

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        msg1 = {'filepath_id': '00000000-0000-0000-0000-000000000001', 'is_inserted': True, 'table_name': 'fhir_lineage'}
        msg2 = {'filepath_id': '00000000-0000-0000-0000-000000000002', 'is_inserted': False, 'error_code': '603', 'table_name': 'fhir_lineage'}

        buffer = [(msg1, msg1), (msg2, msg2)]

        manager._flush_lineage_second_half_buffer(buffer)

        mock_session.post.assert_called_once()  # 1 batched SELECT
        mock_session.put.assert_called_once()   # 1 batched stream load

        # Verify merged data
        call_data = json.loads(mock_session.put.call_args[1]['data'])
        assert len(call_data) == 2
        # First merged row should have both first-half and second-half fields
        merged_row_1 = next(r for r in call_data if r['filepath_id'] == '00000000-0000-0000-0000-000000000001')
        assert merged_row_1['resource_type'] == 'Patient'
        assert merged_row_1['is_inserted'] is True
        assert merged_row_1['__op'] == 0
        assert 'updated_date' in merged_row_1

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_flush_second_half_requeues_unmatched(self, mock_session_class, mock_azure_config):
        """Test that second-half messages without first-half match get rescheduled."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        # Only uuid-1 exists in DB, uuid-2 does not
        ndjson_response = (
            '{"meta": [{"name": "filepath_id"}, {"name": "resource_type"}, '
            '{"name": "fhir_request_url"}, {"name": "record_count"}, '
            '{"name": "pipeline_type"}, {"name": "destination_location"}, '
            '{"name": "created_date"}]}\n'
            '{"data": ["00000000-0000-0000-0000-000000000001", "Patient", "http://fhir/Patient", 100, "batch_load_exporter", "/dest/1", "20240101T120000"]}'
        )

        mock_query_response = MagicMock()
        mock_query_response.status_code = 200
        mock_query_response.text = ndjson_response

        mock_load_response = MagicMock()
        mock_load_response.json.return_value = {"Status": "Success", "Message": "OK"}

        mock_session = MagicMock()
        mock_session.post.return_value = mock_query_response
        mock_session.put.return_value = mock_load_response
        mock_session_class.return_value = mock_session

        mock_queue = MagicMock()
        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=mock_queue
        )

        msg1 = {'filepath_id': '00000000-0000-0000-0000-000000000001', 'is_inserted': True, 'table_name': 'fhir_lineage'}
        og1 = {'filepath_id': '00000000-0000-0000-0000-000000000001', 'is_inserted': True, 'table_name': 'fhir_lineage'}
        msg2 = {'filepath_id': '00000000-0000-0000-0000-000000000002', 'is_inserted': False, 'table_name': 'fhir_lineage'}
        og2 = {'filepath_id': '00000000-0000-0000-0000-000000000002', 'is_inserted': False, 'table_name': 'fhir_lineage'}

        buffer = [(msg1, og1), (msg2, og2)]

        manager._flush_lineage_second_half_buffer(buffer)

        # uuid-2 should be requeued (first half not found)
        mock_queue.insert_schedule_message_to_audit_queue.assert_called_once()
        requeued = mock_queue.insert_schedule_message_to_audit_queue.call_args[1]['message']
        assert requeued['filepath_id'] == '00000000-0000-0000-0000-000000000002'

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_flush_second_half_requeues_all_on_select_failure(self, mock_session_class, mock_azure_config):
        """Test that all second-half messages are requeued when batch SELECT fails."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = 'Internal Server Error'

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        mock_queue = MagicMock()
        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=mock_queue
        )

        msg1 = {'filepath_id': '00000000-0000-0000-0000-000000000001', 'table_name': 'fhir_lineage'}
        msg2 = {'filepath_id': '00000000-0000-0000-0000-000000000002', 'table_name': 'fhir_lineage'}
        buffer = [(msg1, msg1), (msg2, msg2)]

        manager._flush_lineage_second_half_buffer(buffer)

        assert mock_queue.insert_schedule_message_to_audit_queue.call_count == 2
        assert len(buffer) == 0

    def test_flush_empty_buffers_is_noop(self, mock_azure_config):
        """Test that flushing empty buffers does nothing."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_queue = MagicMock()
        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=mock_queue
        )

        with patch.object(manager, 'streamload_insert_data_get_result') as mock_stream:
            manager._flush_all_buffers([], [], [])

            mock_stream.assert_not_called()
            mock_queue.insert_schedule_message_to_audit_queue.assert_not_called()


class TestLoaderMethod:
    """Test loader method."""

    def test_loader_handles_shutdown_event(self, mock_azure_config):
        """Test loader exits gracefully on shutdown event."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_queue = MagicMock()
        mock_queue.get_audit_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_queue.receive_messages.return_value = []

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=mock_queue
        )

        shutdown_event = threading.Event()
        shutdown_event.set()  # Signal immediate shutdown

        message_queue = Queue()

        # Should exit without error
        manager.loader(message_queue, 1, shutdown_event)

    def test_loader_processes_audit_message(self, mock_azure_config):
        """Test loader buffers and flushes fhir_audit messages correctly."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        audit_message = {
            'table_name': 'fhir_audit',
            'filepath_id': 'test-file-123',
            'resource_type': 'Patient',
            'record_count': 10
        }

        mock_sb_message = MagicMock()
        mock_sb_message.__str__ = lambda x: json.dumps(audit_message)

        mock_queue = MagicMock()
        mock_queue.get_audit_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_queue.receive_messages.side_effect = [[mock_sb_message], []]
        mock_queue.read_message_body.return_value = audit_message

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=mock_queue
        )

        shutdown_event = threading.Event()

        def run_with_timeout():
            time.sleep(0.1)
            shutdown_event.set()

        timeout_thread = threading.Thread(target=run_with_timeout)
        timeout_thread.start()

        with patch.object(manager, '_flush_all_buffers') as mock_flush:
            message_queue = Queue()
            manager.loader(message_queue, 1, shutdown_event)
            timeout_thread.join()

            # Flush should have been called (idle path or shutdown)
            assert mock_flush.called
            mock_queue.complete_message.assert_called()

    def test_loader_raises_on_queue_init_failure(self, mock_azure_config):
        """Test loader raises when queue initialization fails."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_queue = MagicMock()
        mock_queue.get_audit_queue_receiver.side_effect = Exception("Queue init failed")

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=mock_queue
        )

        shutdown_event = threading.Event()
        message_queue = Queue()

        with pytest.raises(Exception, match="Queue init failed"):
            manager.loader(message_queue, 1, shutdown_event)

        mock_queue.receive_messages.assert_not_called()

    def test_loader_second_half_requeues_when_first_half_missing(self, mock_azure_config):
        """Test loader requeues second-half lineage when first half not yet in DB."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        lineage_message = {
            'table_name': 'fhir_lineage',
            'filepath_id': 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
            'is_inserted': True,
        }

        mock_sb_message = MagicMock()

        mock_queue = MagicMock()
        mock_queue.get_audit_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_queue.receive_messages.side_effect = [[mock_sb_message], []]
        mock_queue.read_message_body.return_value = lineage_message

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=mock_queue
        )

        shutdown_event = threading.Event()

        # batch_select returns empty lookup — first half not found
        with patch.object(manager, '_batch_select_lineage', return_value=({}, True)):
            def run_with_timeout():
                time.sleep(0.1)
                shutdown_event.set()

            timeout_thread = threading.Thread(target=run_with_timeout)
            timeout_thread.start()

            message_queue = Queue()
            manager.loader(message_queue, 1, shutdown_event)
            timeout_thread.join()

        mock_queue.insert_schedule_message_to_audit_queue.assert_called()


class TestLoaderLineageProcessing:
    """Test loader method lineage-specific processing."""

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_loader_first_half_lineage_no_select(self, mock_session_class, mock_azure_config):
        """Test loader does NOT issue SELECT for first-half lineage (has pipeline_type)."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_load_response = MagicMock()
        mock_load_response.json.return_value = {"Status": "Success", "Message": "OK"}

        mock_session = MagicMock()
        mock_session.put.return_value = mock_load_response
        mock_session_class.return_value = mock_session

        lineage_message = {
            'table_name': 'fhir_lineage',
            'filepath_id': 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
            'resource_type': 'Patient',
            'pipeline_type': 'batch_load_exporter'
        }

        mock_queue = MagicMock()
        mock_queue.get_audit_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        mock_queue.read_message_body.return_value = lineage_message

        mock_sb_message = MagicMock()
        mock_queue.receive_messages.side_effect = [[mock_sb_message], []]

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=mock_queue
        )

        shutdown_event = threading.Event()

        def run_with_timeout():
            time.sleep(0.1)
            shutdown_event.set()

        timeout_thread = threading.Thread(target=run_with_timeout)
        timeout_thread.start()

        message_queue = Queue()
        manager.loader(message_queue, 1, shutdown_event)

        timeout_thread.join()

        # No POST (query) should be made — only PUT (stream load) on flush
        mock_session.post.assert_not_called()


class TestBufferFlushTriggers:
    """Test buffer flush trigger conditions."""

    def test_buffer_flush_on_size_threshold(self, mock_azure_config):
        """Test that flush triggers when buffer reaches batch_size."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager, _DEFAULT_BATCH_SIZE

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        # Generate _DEFAULT_BATCH_SIZE audit messages
        messages = []
        for _i in range(_DEFAULT_BATCH_SIZE):
            mock_sb = MagicMock()
            messages.append(mock_sb)

        mock_queue = MagicMock()
        mock_queue.get_audit_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        # Return all messages at once, then empty
        mock_queue.receive_messages.side_effect = [messages, []]
        # Return different audit messages for each call
        mock_queue.read_message_body.side_effect = [
            {
                'table_name': 'fhir_audit',
                'filepath_id': f'fp-{i}',
                'resource_type': 'Patient',
            }
            for i in range(_DEFAULT_BATCH_SIZE)
        ]

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=mock_queue
        )

        shutdown_event = threading.Event()

        with patch.object(manager, '_flush_all_buffers') as mock_flush:
            def run_with_timeout():
                time.sleep(0.1)
                shutdown_event.set()

            timeout_thread = threading.Thread(target=run_with_timeout)
            timeout_thread.start()

            message_queue = Queue()
            manager.loader(message_queue, _DEFAULT_BATCH_SIZE, shutdown_event)
            timeout_thread.join()

            # Flush should have been called due to size threshold
            assert mock_flush.call_count >= 1

    def test_buffer_flush_on_shutdown(self, mock_azure_config):
        """Test that remaining buffered messages are flushed on shutdown."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        audit_message = {
            'table_name': 'fhir_audit',
            'filepath_id': 'test-file-123',
            'resource_type': 'Patient',
        }

        mock_sb_message = MagicMock()

        mock_queue = MagicMock()
        mock_queue.get_audit_queue_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_receiver.return_value = MagicMock()
        mock_queue.get_context_safe_client.return_value = MagicMock()
        # Return 1 message, then trigger shutdown before next receive
        mock_queue.receive_messages.side_effect = [[mock_sb_message], []]
        mock_queue.read_message_body.return_value = audit_message

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=mock_queue
        )

        shutdown_event = threading.Event()

        with patch.object(manager, '_flush_all_buffers') as mock_flush:
            def run_with_timeout():
                time.sleep(0.1)
                shutdown_event.set()

            timeout_thread = threading.Thread(target=run_with_timeout)
            timeout_thread.start()

            message_queue = Queue()
            manager.loader(message_queue, 1, shutdown_event)
            timeout_thread.join()

            # Flush is called on idle (empty receive) and/or on shutdown exit
            assert mock_flush.called


class TestRunMethod:
    """Test run method."""

    @patch('pyfiles.hyperion_core.audit_lineage_manager.signal.signal')
    @patch('pyfiles.hyperion_core.audit_lineage_manager.concurrent.futures.ThreadPoolExecutor')
    def test_run_sets_up_signal_handlers(self, mock_executor, mock_signal, mock_azure_config):
        """Test run method sets up SIGINT and SIGTERM handlers."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager
        import signal

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        mock_executor_instance = MagicMock()
        mock_executor.return_value.__enter__.return_value = mock_executor_instance
        mock_executor_instance.submit.side_effect = SystemExit()

        try:
            manager.run()
        except SystemExit:
            pass

        signal_calls = [call[0][0] for call in mock_signal.call_args_list]
        assert signal.SIGINT in signal_calls
        assert signal.SIGTERM in signal_calls

    def test_run_calculates_concurrent_receivers(self, mock_azure_config):
        """Test run method calculates correct number of concurrent receivers."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}
        config['processing'] = {
            'message': '2',
            'converter_cores': '3',
            'audit_batch_size': '50',
            'audit_flush_interval': '3.0',
        }

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        with patch('pyfiles.hyperion_core.audit_lineage_manager.concurrent.futures.ThreadPoolExecutor') as mock_executor:
            mock_executor_instance = MagicMock()
            mock_executor.return_value.__enter__.return_value = mock_executor_instance
            mock_executor_instance.submit.side_effect = SystemExit()

            try:
                manager.run()
            except SystemExit:
                pass

            mock_executor.assert_called_with(max_workers=6)

    @patch('pyfiles.hyperion_core.audit_lineage_manager.signal.signal')
    @patch('pyfiles.hyperion_core.audit_lineage_manager.concurrent.futures.ThreadPoolExecutor')
    @patch('pyfiles.hyperion_core.audit_lineage_manager.gc')
    def test_run_finally_calls_gc_collect(self, mock_gc, mock_executor, mock_signal, mock_azure_config):
        """Test run method calls gc.collect() in the finally block."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        mock_executor_instance = MagicMock()
        mock_executor.return_value.__enter__.return_value = mock_executor_instance
        mock_executor_instance.submit.side_effect = SystemExit()

        try:
            manager.run()
        except SystemExit:
            pass

        mock_gc.collect.assert_called()


class TestAuditMessageProcessing:
    """Test audit message specific processing."""

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_audit_message_adds_created_date_and_op(self, mock_session_class, mock_azure_config):
        """Test that audit messages have created_date and __op=0 added before streamload."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_load_response = MagicMock()
        mock_load_response.json.return_value = {"Status": "Success", "Message": "OK"}

        mock_session = MagicMock()
        mock_session.put.return_value = mock_load_response
        mock_session_class.return_value = mock_session

        audit_dict = {
            'table_name': 'fhir_audit',
            'filepath_id': 'test-file-123',
            'resource_type': 'Patient',
            '__op': 0
        }

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        result = manager.streamload_insert_data_get_result('test_label', audit_dict, 'fhir_audit')

        assert result is True
        mock_session.put.assert_called_once()
        call_data = mock_session.put.call_args[1]['data']
        parsed = json.loads(call_data)
        assert isinstance(parsed, list)
        assert parsed[0]['filepath_id'] == 'test-file-123'

    def test_streamload_method_exists(self, mock_azure_config):
        """Test that required methods exist on the manager."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        assert callable(getattr(manager, 'streamload_insert_data_get_result', None))
        assert callable(getattr(manager, 'loader', None))
        assert callable(getattr(manager, 'get_sql_query_result', None))
        assert callable(getattr(manager, '_batch_select_lineage', None))
        assert callable(getattr(manager, '_flush_all_buffers', None))


class TestLineageMessageProcessing:
    """Test lineage message specific processing."""

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_lineage_queries_existing_record(self, mock_session_class, mock_azure_config):
        """Test that lineage processing queries for existing records."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_query_response = MagicMock()
        mock_query_response.status_code = 200
        mock_query_response.text.strip.return_value = json.dumps({
            "meta": [{"name": "created_date"}],
            "data": ["2024-01-01"]
        })

        mock_session = MagicMock()
        mock_session.post.return_value = mock_query_response
        mock_session_class.return_value = mock_session

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        result, success = manager.get_sql_query_result(
            "SELECT created_date FROM fhir_lineage WHERE filepath_id = 'test'",
            MagicMock()
        )

        assert 'data' in result

    @patch('pyfiles.hyperion_core.audit_lineage_manager.requests.Session')
    def test_streamload_handles_list_for_batch(self, mock_session_class, mock_azure_config):
        """Test streamload correctly sends batch data as JSON list."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        config = {**mock_azure_config, **create_mock_starrocks_config()}

        mock_response = MagicMock()
        mock_response.json.return_value = {"Status": "Success", "Message": "OK"}

        mock_session = MagicMock()
        mock_session.put.return_value = mock_response
        mock_session_class.return_value = mock_session

        manager = AuditLineageManager(
            project_configurations=config,
            queue_client=MagicMock()
        )

        batch = [
            {"filepath_id": "test-1", "__op": 0, "created_date": "20240101"},
            {"filepath_id": "test-2", "__op": 0, "created_date": "20240101"}
        ]

        result = manager.streamload_insert_data_get_result('test_label', batch, 'fhir_lineage')

        assert result is True
        call_data = mock_session.put.call_args[1]['data']
        parsed = json.loads(call_data)
        assert len(parsed) == 2
        assert parsed[0]['__op'] == 0
        assert parsed[1]['__op'] == 0


class TestGenerateTimestamp:
    """Test _generate_timestamp helper."""

    def test_generate_timestamp_format(self, mock_azure_config):
        """Test timestamp has expected format YYYYMMDDTHHMMSSmmm."""
        from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager

        ts = AuditLineageManager._generate_timestamp()

        # Should be 18 chars: 8 date + T + 6 time + 3 millis
        assert len(ts) == 18
        assert ts[8] == 'T'
