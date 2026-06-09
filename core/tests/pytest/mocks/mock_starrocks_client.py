"""Mock implementations for StarRocks HTTP API client."""
import json
from typing import Dict, Optional, Any


class MockStarRocksResponse:
    """Mock HTTP response from StarRocks."""

    def __init__(self, status: str = "OK", message: str = "Success",
                 data: Optional[Dict] = None, status_code: int = 200,
                 txn_id: Optional[str] = None):
        self._status = status
        self._message = message
        self._data = data or {}
        self.status_code = status_code
        self._txn_id = txn_id

    def json(self):
        response = {
            "Status": self._status,
            "Message": self._message,
        }
        if self._txn_id:
            response["TxnId"] = self._txn_id
        if self._data:
            response.update(self._data)
        return response

    def text(self):
        return json.dumps(self.json())


class MockStarRocksSession:
    """Mock requests.Session for StarRocks HTTP API calls."""

    def __init__(self,
                 begin_response: Optional[MockStarRocksResponse] = None,
                 load_response: Optional[MockStarRocksResponse] = None,
                 prepare_response: Optional[MockStarRocksResponse] = None,
                 commit_response: Optional[MockStarRocksResponse] = None,
                 rollback_response: Optional[MockStarRocksResponse] = None,
                 query_response: Optional[MockStarRocksResponse] = None):
        self._begin_response = begin_response or MockStarRocksResponse(
            status="OK", txn_id="mock-txn-12345"
        )
        self._load_response = load_response or MockStarRocksResponse(
            status="Success", message="OK"
        )
        self._prepare_response = prepare_response or MockStarRocksResponse(
            status="OK"
        )
        self._commit_response = commit_response or MockStarRocksResponse(
            status="OK"
        )
        self._rollback_response = rollback_response or MockStarRocksResponse(
            status="OK"
        )
        self._query_response = query_response or MockStarRocksResponse(
            status="OK",
            data={"meta": [], "data": []}
        )

        self.post_calls = []
        self.put_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def post(self, url: str, headers: Dict = None, data: Any = None,
             json: Any = None, auth: tuple = None, timeout: int = None):
        self.post_calls.append({
            'url': url,
            'headers': headers,
            'data': data,
            'json': json,
            'auth': auth
        })

        if '/transaction/begin' in url or 'begin' in url.lower():
            return self._begin_response
        elif '/transaction/prepare' in url or 'prepare' in url.lower():
            return self._prepare_response
        elif '/transaction/commit' in url or 'commit' in url.lower():
            return self._commit_response
        elif '/transaction/rollback' in url or 'rollback' in url.lower():
            return self._rollback_response
        elif '/query' in url or '/api/v1/catalogs' in url:
            return self._query_response
        return self._load_response

    def put(self, url: str, headers: Dict = None, data: Any = None,
            auth: tuple = None, timeout: int = None, allow_redirects: bool = True,
            **_kwargs):
        self.put_calls.append({
            'url': url,
            'headers': headers,
            'data': data,
            'auth': auth,
            'allow_redirects': allow_redirects,
        })
        return self._load_response


class MockTransactionManager:
    """Mock implementation of TransactionManager for testing."""

    def __init__(self):
        self.begun_transactions = []
        self.committed_transactions = []
        self.rolled_back_transactions = []
        self.prepared_transactions = []

    @staticmethod
    def begin_transaction(configurations, table_name, id_to_delete, transaction_label, http_session):
        """Mock begin transaction."""
        return "mock-txn-12345"

    @staticmethod
    def transaction(configurations, transaction_flag, table_name, filename,
                   transaction_id, data_to_insert, transaction_label,
                   first_level_complex_datatypes, database, http_session):
        """Mock transaction load."""
        return True

    @staticmethod
    def prepare_transaction(configurations, table_name, transaction_id, transaction_label, http_session):
        """Mock prepare transaction."""
        return True, transaction_label, table_name, "Prepared"

    @staticmethod
    def commit_transaction(configurations, transaction_label, table_name, id_to_delete, filepath_id, http_session):
        """Mock commit transaction."""
        return True

    @staticmethod
    def rollback_transaction(configurations, transaction_label, table_name, id_to_delete, filepath_id, http_session):
        """Mock rollback transaction."""
        return True

    @staticmethod
    def transaction_block(configurations, table_name, filename, data, complex_datatypes, database, filepath_id, http_session):
        """Mock transaction block - returns success by default."""
        if configurations.get("silver_layer", {}).get("is_transaction") == "True":
            return True, f"{table_name}_{filename}_mock_label", table_name
        return True, None, None


def create_mock_starrocks_config():
    """Create a mock configuration for StarRocks."""
    return {
        'silver_layer': {
            'username': 'test_user',
            'password': 'test_password',
            'query_server': 'localhost:9030',
            'http_server': 'localhost:8030',
            'catalog': 'default_catalog',
            'core_database': 'test_core_db',
            'audit_database': 'test_audit_db',
            'is_transaction': 'True'
        },
        'transaction_api': {
            'begin_url': '/api/transaction/begin',
            'load_url': '/api/transaction/load',
            'prepare_url': '/api/transaction/prepare',
            'commit_url': '/api/transaction/commit',
            'rollback_url': '/api/transaction/rollback',
            'stream_load_url': '/api/silver_layer_database/table_name/_stream_load',
            'sql_query_url': '/api/v1/catalogs/catalog_name/databases/database_name/sql'
        }
    }
