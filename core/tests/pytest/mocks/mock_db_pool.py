"""Mock implementations for database connection pool."""
from typing import Dict, List, Optional


class MockCursor:
    """Mock database cursor."""

    def __init__(self, results: Optional[List[tuple]] = None):
        self._results = results or []
        self._index = 0
        self.description = None
        self.rowcount = len(self._results)
        self.executed_queries = []

    def execute(self, query: str, params: tuple = None):
        self.executed_queries.append((query, params))
        return self

    def executemany(self, query: str, params_list: List[tuple]):
        for params in params_list:
            self.executed_queries.append((query, params))
        return self

    def fetchone(self):
        if self._index < len(self._results):
            result = self._results[self._index]
            self._index += 1
            return result
        return None

    def fetchall(self):
        return self._results

    def fetchmany(self, size: int = 1):
        results = self._results[self._index:self._index + size]
        self._index += size
        return results

    def close(self):
        pass


class MockConnection:
    """Mock database connection."""

    def __init__(self, results: Optional[List[tuple]] = None):
        self._results = results
        self._cursor = None
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        self._cursor = MockCursor(self._results)
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class MockConnectionPool:
    """Mock database connection pool."""

    def __init__(self, results: Optional[List[tuple]] = None):
        self._results = results
        self.connections_created = 0
        self.connections_released = 0

    def get_connection(self):
        self.connections_created += 1
        return MockConnection(self._results)

    def release_connection(self, conn):
        self.connections_released += 1

    def close_all(self):
        pass


class MockDBOps:
    """Mock implementation of DBOps for testing."""

    def __init__(self):
        self.inserted_data = []
        self.deleted_data = []
        self.queried_data = []
        self.executed_queries = []

    def insert_dataframe(self, dataframe, table_name: str, database: str = None):
        """Record DataFrame insert operation."""
        self.inserted_data.append({
            'table_name': table_name,
            'database': database,
            'row_count': len(dataframe),
            'columns': list(dataframe.columns)
        })
        return True

    def delete_records(self, table_name: str, condition: str, params: tuple = None):
        """Record delete operation."""
        self.deleted_data.append({
            'table_name': table_name,
            'condition': condition,
            'params': params
        })
        return True

    def execute_query(self, query: str, params: tuple = None):
        """Record query execution."""
        self.executed_queries.append({
            'query': query,
            'params': params
        })
        return []

    def select(self, query: str, params: tuple = None) -> List[Dict]:
        """Return mock query results."""
        self.queried_data.append({
            'query': query,
            'params': params
        })
        return []
