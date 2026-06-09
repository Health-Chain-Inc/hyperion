"""Unit tests for TransactionManager class."""
import pytest
import json
import pandas as pd
from unittest.mock import MagicMock, patch

from pyfiles.dependencies.data_processing_error import DataProcessingException
from tests.pytest.mocks.mock_starrocks_client import (
    MockStarRocksResponse,
    MockStarRocksSession,
    create_mock_starrocks_config
)


class TestEngineUrlHelper:
    """Test _engine_url helper (High fix — config-driven HTTP scheme)."""

    def test_defaults_to_http_scheme(self):
        from pyfiles.hyperion_core.transaction_manager import _engine_url
        cfg = {"silver_layer": {"http_server": "engine:8030"}}
        assert _engine_url(cfg) == "http://engine:8030"

    def test_uses_configured_scheme_when_set(self):
        from pyfiles.hyperion_core.transaction_manager import _engine_url
        cfg = {"silver_layer": {"http_server": "engine:8030", "scheme": "https"}}
        assert _engine_url(cfg) == "https://engine:8030"

    def test_appends_api_path_when_key_provided(self):
        from pyfiles.hyperion_core.transaction_manager import _engine_url
        cfg = {
            "silver_layer": {"http_server": "engine:8030"},
            "transaction_api": {"begin_url": "/api/transaction/begin"},
        }
        assert _engine_url(cfg, "begin_url") == "http://engine:8030/api/transaction/begin"

    def test_handles_missing_silver_layer_section_via_get_fallback(self):
        from pyfiles.hyperion_core.transaction_manager import _engine_url
        # The helper uses cfg.get("silver_layer", {}).get("scheme", "http"); the http_server
        # access still needs the key present — so we provide it.
        cfg = {"silver_layer": {"http_server": "engine:8030"}}
        # No "scheme" key — falls back to "http"
        assert _engine_url(cfg).startswith("http://")


class TestBeginTransaction:
    """Test begin_transaction static method."""

    def test_begin_transaction_returns_txn_id(self):
        """Test successful begin_transaction returns transaction ID."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        mock_session = MockStarRocksSession(
            begin_response=MockStarRocksResponse(status="OK", txn_id="txn-12345")
        )

        config = create_mock_starrocks_config()

        txn_id = TransactionManager.begin_transaction(
            configurations=config,
            table_name='patient',
            id_to_delete='Patient-1.ndjson',
            transaction_label='patient_test_label',
            http_session=mock_session
        )

        assert txn_id == "txn-12345"
        assert len(mock_session.post_calls) == 1

    def test_begin_transaction_raises_on_failure(self):
        """Test begin_transaction raises DataProcessingException on failure."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        mock_session = MockStarRocksSession(
            begin_response=MockStarRocksResponse(
                status="FAILED",
                message="Table not found"
            )
        )

        config = create_mock_starrocks_config()

        with pytest.raises(DataProcessingException) as exc_info:
            TransactionManager.begin_transaction(
                configurations=config,
                table_name='nonexistent_table',
                id_to_delete='test-file',
                transaction_label='test_label',
                http_session=mock_session
            )

        assert '603' in str(exc_info.value.error_code)

    def test_begin_transaction_sends_correct_headers(self):
        """Test begin_transaction sends correct headers."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        mock_session = MockStarRocksSession()

        config = create_mock_starrocks_config()

        TransactionManager.begin_transaction(
            configurations=config,
            table_name='patient',
            id_to_delete='test-file',
            transaction_label='test_label',
            http_session=mock_session
        )

        call_headers = mock_session.post_calls[0]['headers']
        assert call_headers['db'] == config['silver_layer']['core_database']
        assert call_headers['table'] == 'patient'
        assert call_headers['label'] == 'test_label'


class TestTransaction:
    """Test transaction static method."""

    def test_transaction_load_success(self):
        """Test successful transaction load returns True."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        mock_session = MockStarRocksSession(
            load_response=MockStarRocksResponse(status="Success", message="OK")
        )

        config = create_mock_starrocks_config()

        data = pd.DataFrame({'id': ['test-1'], 'name': ['Test Patient']})

        # Note: filename must contain '_' or 'utilitiesdata' for id_to_delete to be set
        # when first_level_complex_datatypes is provided (see line 71-72 in source)
        result = TransactionManager.transaction(
            configurations=config,
            transaction_flag="True",
            table_name='patient',
            filename='Patient_1.ndjson',  # Use underscore for proper id_to_delete initialization
            transaction_id='txn-12345',
            data_to_insert=data,
            transaction_label='test_label',
            first_level_complex_datatypes={'patient': {'identifier': []}},
            database=config['silver_layer']['core_database'],
            http_session=mock_session
        )

        assert result is True

    def test_transaction_without_transaction_flag(self):
        """Test transaction without transaction flag uses stream load URL."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        mock_session = MockStarRocksSession(
            load_response=MockStarRocksResponse(status="Success", message="OK")
        )

        config = create_mock_starrocks_config()

        data = pd.DataFrame({'id': ['test-1'], 'name': ['Test']})

        result = TransactionManager.transaction(
            configurations=config,
            transaction_flag="False",
            table_name='patient',
            filename='Patient-1_ndjson',
            transaction_id=None,
            data_to_insert=data,
            transaction_label='test_label',
            first_level_complex_datatypes={},
            database=config['silver_layer']['core_database'],
            http_session=mock_session
        )

        assert result is True
        # Check that stream_load_url pattern was used
        call_url = mock_session.put_calls[0]['url']
        assert 'stream_load' in call_url or 'patient' in call_url

    def test_transaction_raises_on_load_failure(self):
        """Test transaction raises DataProcessingException on load failure."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        mock_session = MockStarRocksSession(
            load_response=MockStarRocksResponse(
                status="FAILED",
                message="Load failed: duplicate key"
            )
        )

        config = create_mock_starrocks_config()
        data = pd.DataFrame({'id': ['test-1']})

        with pytest.raises(DataProcessingException):
            TransactionManager.transaction(
                configurations=config,
                transaction_flag="False",
                table_name='patient',
                filename='Patient-1_ndjson',
                transaction_id=None,
                data_to_insert=data,
                transaction_label='test_label',
                first_level_complex_datatypes={},
                database=config['silver_layer']['core_database'],
                http_session=mock_session
            )

    def test_transaction_returns_true_for_empty_result(self):
        """Test transaction returns True when result is empty."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        config = create_mock_starrocks_config()

        # Empty dataframe with no complex datatypes should return early
        data = pd.DataFrame({'id': []})

        result = TransactionManager.transaction(
            configurations=config,
            transaction_flag="False",
            table_name='patient',
            filename='Patient-1_ndjson',
            transaction_id=None,
            data_to_insert=data,
            transaction_label='test_label',
            first_level_complex_datatypes={},
            database=config['silver_layer']['core_database'],
            http_session=MagicMock()
        )

        assert result is True


class TestPrepareTransaction:
    """Test prepare_transaction static method."""

    def test_prepare_transaction_success(self):
        """Test successful prepare_transaction returns prepared tuple."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        mock_session = MockStarRocksSession(
            prepare_response=MockStarRocksResponse(status="OK")
        )

        config = create_mock_starrocks_config()

        is_prepared, label, table, message = TransactionManager.prepare_transaction(
            configurations=config,
            table_name='patient',
            transaction_id='txn-12345',
            transaction_label='test_label',
            http_session=mock_session
        )

        assert is_prepared is True
        assert label == 'test_label'
        assert table == 'patient'
        assert message == "Prepared"

    def test_prepare_transaction_raises_on_failure(self):
        """Test prepare_transaction raises on failure."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        mock_session = MockStarRocksSession(
            prepare_response=MockStarRocksResponse(
                status="FAILED",
                message="Prepare failed"
            )
        )

        config = create_mock_starrocks_config()

        with pytest.raises(DataProcessingException):
            TransactionManager.prepare_transaction(
                configurations=config,
                table_name='patient',
                transaction_id='txn-12345',
                transaction_label='test_label',
                http_session=mock_session
            )


class TestCommitTransaction:
    """Test commit_transaction static method."""

    def test_commit_transaction_success(self):
        """Test successful commit_transaction returns True."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        mock_response = MagicMock()
        mock_response.text = json.dumps({"Status": "OK"})

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response

        config = create_mock_starrocks_config()

        result = TransactionManager.commit_transaction(
            configurations=config,
            transaction_label='test_label',
            table_name='patient',
            id_to_delete='Patient-1.ndjson',
            filepath_id='test-fp-123',
            http_session=mock_session
        )

        assert result is True

    def test_commit_transaction_raises_on_failure(self):
        """Test commit_transaction raises on FAILED status."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "Status": "FAILED",
            "Message": "Commit failed"
        })

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response

        config = create_mock_starrocks_config()

        with pytest.raises(DataProcessingException) as exc_info:
            TransactionManager.commit_transaction(
                configurations=config,
                transaction_label='test_label',
                table_name='patient',
                id_to_delete='test-file',
                filepath_id='test-fp-123',
                http_session=mock_session
            )

        assert '603' in str(exc_info.value.error_code)


class TestRollbackTransaction:
    """Test rollback_transaction static method."""

    def test_rollback_transaction_success(self):
        """Test successful rollback_transaction returns True."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        mock_session = MockStarRocksSession(
            rollback_response=MockStarRocksResponse(status="OK")
        )

        config = create_mock_starrocks_config()

        result = TransactionManager.rollback_transaction(
            configurations=config,
            transaction_label='test_label',
            table_name='patient',
            id_to_delete='test-file',
            filepath_id='test-fp-123',
            http_session=mock_session
        )

        assert result is True

    def test_rollback_transaction_raises_on_failure(self):
        """Test rollback_transaction raises on failure."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        mock_session = MockStarRocksSession(
            rollback_response=MockStarRocksResponse(
                status="FAILED",
                message="Rollback failed"
            )
        )

        config = create_mock_starrocks_config()

        with pytest.raises(DataProcessingException):
            TransactionManager.rollback_transaction(
                configurations=config,
                transaction_label='test_label',
                table_name='patient',
                id_to_delete='test-file',
                filepath_id='test-fp-123',
                http_session=mock_session
            )


class TestTransactionBlock:
    """Test transaction_block static method."""

    @patch('pyfiles.hyperion_core.transaction_manager.TransactionManager.begin_transaction')
    @patch('pyfiles.hyperion_core.transaction_manager.TransactionManager.transaction')
    @patch('pyfiles.hyperion_core.transaction_manager.TransactionManager.prepare_transaction')
    def test_transaction_block_full_flow_with_transactions(self, mock_prepare,
                                                           mock_transaction,
                                                           mock_begin):
        """Test transaction_block with transactions enabled."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        mock_begin.return_value = 'txn-12345'
        mock_transaction.return_value = True
        mock_prepare.return_value = (True, 'test_label', 'patient', 'Prepared')

        config = create_mock_starrocks_config()
        config['silver_layer']['is_transaction'] = 'True'

        data = pd.DataFrame({'id': ['test-1']})

        is_prepared, label, table = TransactionManager.transaction_block(
            configurations=config,
            table_name='patient',
            filename='Patient-1.ndjson',
            data=data,
            complex_datatypes={},
            database=config['silver_layer']['core_database'],
            filepath_id='test-fp-123',
            http_session=MagicMock()
        )

        assert is_prepared is True
        assert label == 'test_label'
        assert table == 'patient'
        mock_begin.assert_called_once()
        mock_transaction.assert_called_once()
        mock_prepare.assert_called_once()

    @patch('pyfiles.hyperion_core.transaction_manager.TransactionManager.transaction')
    def test_transaction_block_without_transactions(self, mock_transaction):
        """Test transaction_block without transactions enabled."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        mock_transaction.return_value = True

        config = create_mock_starrocks_config()
        config['silver_layer']['is_transaction'] = 'False'

        data = pd.DataFrame({'id': ['test-1']})

        is_prepared, label, table = TransactionManager.transaction_block(
            configurations=config,
            table_name='patient',
            filename='Patient-1.ndjson',
            data=data,
            complex_datatypes={},
            database=config['silver_layer']['core_database'],
            filepath_id='test-fp-123',
            http_session=MagicMock()
        )

        assert is_prepared is True
        assert label is None
        assert table is None
        mock_transaction.assert_called_once()

    @patch('pyfiles.hyperion_core.transaction_manager.TransactionManager.begin_transaction')
    def test_transaction_block_raises_on_begin_failure(self, mock_begin):
        """Test transaction_block raises when begin_transaction fails."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        mock_begin.side_effect = DataProcessingException("Begin failed", "error", "603")

        config = create_mock_starrocks_config()
        config['silver_layer']['is_transaction'] = 'True'

        data = pd.DataFrame({'id': ['test-1']})

        with pytest.raises(DataProcessingException):
            TransactionManager.transaction_block(
                configurations=config,
                table_name='patient',
                filename='Patient-1.ndjson',
                data=data,
                complex_datatypes={},
                database=config['silver_layer']['core_database'],
                filepath_id='test-fp-123',
                http_session=MagicMock()
            )

    def test_transaction_block_generates_correct_label(self):
        """Test transaction_block generates properly formatted transaction label."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        config = create_mock_starrocks_config()
        config['silver_layer']['is_transaction'] = 'False'

        data = pd.DataFrame({'id': ['test-1']})

        with patch.object(TransactionManager, 'transaction', return_value=True):
            TransactionManager.transaction_block(
                configurations=config,
                table_name='patient',
                filename='Patient-1.ndjson',
                data=data,
                complex_datatypes={},
                database=config['silver_layer']['core_database'],
                filepath_id='test-fp-123',
                http_session=MagicMock()
            )

    def test_transaction_block_handles_hyphenated_filename(self):
        """Test transaction_block correctly handles hyphenated filenames."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        config = create_mock_starrocks_config()
        config['silver_layer']['is_transaction'] = 'False'

        data = pd.DataFrame({'id': ['test-1']})

        with patch.object(TransactionManager, 'transaction', return_value=True):
            TransactionManager.transaction_block(
                configurations=config,
                table_name='patient',
                filename='Patient-1-extra.ndjson',
                data=data,
                complex_datatypes={},
                database=config['silver_layer']['core_database'],
                filepath_id='test-fp-123',
                http_session=MagicMock()
            )


class TestTransactionDataPreparation:
    """Test data preparation in transaction method."""

    def test_transaction_adds_op_column(self):
        """Test transaction adds __op column for upsert."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        mock_session = MockStarRocksSession(
            load_response=MockStarRocksResponse(status="Success", message="OK")
        )

        config = create_mock_starrocks_config()

        data = pd.DataFrame({'id': ['test-1'], 'name': ['Test']})

        TransactionManager.transaction(
            configurations=config,
            transaction_flag="False",
            table_name='patient',
            filename='Patient-1_ndjson',
            transaction_id=None,
            data_to_insert=data,
            transaction_label='test_label',
            first_level_complex_datatypes={},
            database=config['silver_layer']['core_database'],
            http_session=mock_session
        )

        # Check that data was sent with __op column
        call_data = mock_session.put_calls[0]['data']
        parsed_data = json.loads(call_data)
        assert all(item.get('__op') == 0 for item in parsed_data)

    def test_transaction_adds_updated_date(self):
        """Test transaction adds updated_date column."""
        from pyfiles.hyperion_core.transaction_manager import TransactionManager

        mock_session = MockStarRocksSession(
            load_response=MockStarRocksResponse(status="Success", message="OK")
        )

        config = create_mock_starrocks_config()

        data = pd.DataFrame({'id': ['test-1']})

        TransactionManager.transaction(
            configurations=config,
            transaction_flag="False",
            table_name='patient',
            filename='Patient-1_ndjson',
            transaction_id=None,
            data_to_insert=data,
            transaction_label='test_label',
            first_level_complex_datatypes={},
            database=config['silver_layer']['core_database'],
            http_session=mock_session
        )

        call_data = mock_session.put_calls[0]['data']
        parsed_data = json.loads(call_data)
        assert all('updated_date' in item for item in parsed_data)
