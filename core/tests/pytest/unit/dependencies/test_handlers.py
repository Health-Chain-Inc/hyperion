"""Unit tests for Handlers class."""
import pytest
import json
from unittest.mock import patch, MagicMock
from pyfiles.dependencies.handlers import Handlers
from pyfiles.dependencies.enum import HyperionDBConnectionEnums


class TestJSONOperations:
    """Test JSON reading and writing utilities."""

    def test_json_reader_valid_file(self, tmp_path):
        """Test reading a valid JSON file."""
        test_data = {"key": "value", "number": 42}
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(test_data))

        result = Handlers.json_reader(str(json_file))
        assert result == test_data

    def test_json_reader_malformed_json_raises_prerequisite_error(self, tmp_path):
        """Malformed JSON content raises PrerequisiteError."""
        from pyfiles.dependencies.data_processing_error import PrerequisiteError

        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json {{")

        with pytest.raises(PrerequisiteError):
            Handlers.json_reader(str(bad_file))

    def test_json_reader_missing_file_raises_prerequisite_error(self):
        """Non-existent file path raises PrerequisiteError."""
        from pyfiles.dependencies.data_processing_error import PrerequisiteError

        with pytest.raises(PrerequisiteError):
            Handlers.json_reader('/nonexistent/path/to/missing.json')

    def test_json_reader_nested_data(self, tmp_path):
        """Test reading JSON with nested structures."""
        test_data = {
            "level1": {
                "level2": {
                    "value": "nested"
                }
            },
            "array": [1, 2, 3]
        }
        json_file = tmp_path / "nested.json"
        json_file.write_text(json.dumps(test_data))

        result = Handlers.json_reader(str(json_file))
        assert result["level1"]["level2"]["value"] == "nested"
        assert result["array"] == [1, 2, 3]


class TestSchemaLoading:
    """Test schema file loading."""

    def test_get_schema_file_fhir(self, schema_dir):
        """Test loading FHIR schema."""
        schema = Handlers.get_schema_file(str(schema_dir / "fhir.schema.json"))

        assert isinstance(schema, dict)
        assert len(schema) > 0
        assert "definitions" in schema


    def test_get_schema_file_not_found(self):
        """Test loading nonexistent schema raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            Handlers.get_schema_file("nonexistent/path/schema.json")

    def test_get_schema_file_invalid_json(self, tmp_path):
        """Test loading invalid JSON raises JSONDecodeError."""
        invalid_file = tmp_path / "invalid.json"
        invalid_file.write_text("not valid json {{{")

        with pytest.raises(json.JSONDecodeError):
            Handlers.get_schema_file(str(invalid_file))


class TestSilverLayerConnectionParameters:
    """Test silver layer connection parameter generation."""

    @pytest.fixture
    def configurations(self):
        """Sample configurations for testing."""
        return {
            'silver_layer': {
                'username': 'test_user',
                'password': 'test_pass',
                'query_server': 'localhost:9030',
                'catalog': 'default_catalog',
                'core_database': 'core_db',
                'audit_database': 'audit_db',
                
            }
        }

    def test_get_core_db_connection(self, configurations):
        """Test getting core database connection string."""
        result = Handlers.get_silver_layer_connection_parameters(
            configurations,
            HyperionDBConnectionEnums.CORE_DB_CONNECTION.value
        )

        assert "test_user:test_pass@" in result
        assert "localhost:9030" in result
        assert "core_db" in result

    def test_get_audit_db_connection(self, configurations):
        """Test getting audit database connection string."""
        result = Handlers.get_silver_layer_connection_parameters(
            configurations,
            HyperionDBConnectionEnums.AUDIT_DB_CONNECTION.value
        )

        assert "test_user:test_pass@" in result
        assert "audit_db" in result


class TestMessageCreation:
    """Test queue message creation utilities."""

    def test_create_exporter_parameter_message_structure(self):
        """Test exporter parameter message has required fields."""
        result = Handlers.create_exporter_parameter_message(
            resource_type="Patient",
            start_time="2024-01-01T00:00:00",
            end_time="2024-01-01T12:00:00",
            page_number=1,
            fhir_url="https://fhir.example.com/Patient",
            retry_count=0,
            retry_message=False
        )

        assert result["resource_type"] == "Patient"
        assert result["start_time"] == "2024-01-01T00:00:00"
        assert result["end_time"] == "2024-01-01T12:00:00"
        assert result["page_number"] == 1
        assert result["fhir_url"] == "https://fhir.example.com/Patient"
        assert result["retry_count"] == 0
        assert result["retry_message"] is False
        assert "request_time" in result
        assert "folder_name" in result

    def test_create_exporter_parameter_message_folder_format(self):
        """Test that folder_name is formatted correctly."""
        result = Handlers.create_exporter_parameter_message(
            resource_type="Observation",
            start_time="2024-01-15T00:00:00",
            end_time="2024-01-15T12:30:45",
            page_number=5,
            fhir_url="https://fhir.example.com",
            retry_count=0,
            retry_message=False
        )

        # Folder name should have colons and dashes removed
        assert ":" not in result["folder_name"]
        assert "-" not in result["folder_name"]


class TestLineageMessage:
    """Test lineage message creation."""

    def test_get_lineage_message_from_dict(self):
        """Test creating lineage message from dict."""
        audit_message = {"filepath_id": "test-file-123", "other_field": "ignored"}

        result = Handlers.get_lineage_message(
            audit_message=audit_message,
            is_insert=True,
            retry_count=1,
            error_code="E001",
            reject_location="/path/to/reject"
        )

        assert result["filepath_id"] == "test-file-123"
        assert result["is_inserted"] is True
        assert result["retry_count"] == 1
        assert result["error_code"] == "E001"
        assert result["reject_location"] == "/path/to/reject"
        assert "other_field" not in result

    def test_get_lineage_message_from_list(self):
        """Test creating lineage message from list."""
        audit_messages = [
            {"filepath_id": "file-1", "extra": "data1"},
            {"filepath_id": "file-2", "extra": "data2"}
        ]

        result = Handlers.get_lineage_message(
            audit_message=audit_messages,
            is_insert=False,
            retry_count=2,
            error_code=None,
            reject_location=None
        )

        # Should use first message's filepath_id
        assert result["filepath_id"] == "file-1"
        assert result["is_inserted"] is False


class TestIsInsertFlag:
    """Test is_insert flag handling."""

    def test_is_insert_flag_dict(self):
        """Test setting is_insert flag on dict."""
        message = {"filepath_id": "test-123", "other": "data"}

        result = Handlers.is_insert_flag(message, True)

        assert result["filepath_id"] == "test-123"
        assert result["is_inserted"] is True
        assert "other" not in result

    def test_is_insert_flag_list(self):
        """Test setting is_insert flag on list."""
        messages = [
            {"filepath_id": "file-1"},
            {"filepath_id": "file-2"}
        ]

        result = Handlers.is_insert_flag(messages, False)

        # Returns first message with flag
        assert result["filepath_id"] == "file-1"
        assert result["is_inserted"] is False


class TestAddRetryCount:
    """Test retry count addition."""

    def test_add_retry_count_dict(self):
        """Test adding retry count to dict."""
        message = {"key": "value"}

        result = Handlers.add_retry_count(message, 3)

        assert result["retry_count"] == 3

    def test_add_retry_count_list(self):
        """Test adding retry count to list of messages."""
        messages = [{"key": "val1"}, {"key": "val2"}]

        result = Handlers.add_retry_count(messages, 5)

        assert result[0]["retry_count"] == 5
        assert result[1]["retry_count"] == 5


class TestConvertEmptyStringsToNull:
    """Test empty string to null conversion."""

    def test_convert_empty_strings_simple(self):
        """Test converting empty strings in simple dict."""
        data = {"name": "John", "middle": "", "last": "Doe"}

        result = Handlers.convert_empty_strings_to_null(data)

        assert result["name"] == "John"
        assert result["middle"] is None
        assert result["last"] == "Doe"

    def test_convert_empty_strings_nested(self):
        """Test converting empty strings in nested structure."""
        data = {
            "level1": {
                "value": "",
                "nested": {
                    "empty": ""
                }
            }
        }

        result = Handlers.convert_empty_strings_to_null(data)

        assert result["level1"]["value"] is None
        assert result["level1"]["nested"]["empty"] is None

    def test_convert_empty_strings_in_list(self):
        """Test converting empty strings in list."""
        data = {"items": ["value", "", "another"]}

        result = Handlers.convert_empty_strings_to_null(data)

        assert result["items"][0] == "value"
        assert result["items"][1] is None
        assert result["items"][2] == "another"

    def test_convert_empty_strings_preserves_non_empty(self):
        """Test that non-empty values are preserved."""
        data = {"num": 42, "bool": False, "zero": 0}

        result = Handlers.convert_empty_strings_to_null(data)

        assert result["num"] == 42
        assert result["bool"] is False
        assert result["zero"] == 0


class TestFillValues:
    """Test fill_values function."""

    def test_fill_values_array_integer(self):
        """Test filling None for NaN in integer array."""
        data = [1.0, float('nan'), 3.0]

        result = Handlers.fill_values(data, "ARRAY<INTEGER>")

        assert result[0] == 1
        assert result[1] is None
        assert result[2] == 3

    def test_fill_values_nested_array_integer(self):
        """Test filling None for NaN in nested integer array."""
        data = [[1.0, float('nan')], [3.0, 4.0]]

        result = Handlers.fill_values(data, "ARRAY<ARRAY<INTEGER>>")

        assert result[0][0] == 1
        assert result[0][1] is None
        assert result[1][0] == 3
        assert result[1][1] == 4

    def test_fill_values_none_data(self):
        """Test that None data returns unchanged."""
        result = Handlers.fill_values(None, "ARRAY<INTEGER>")
        assert result is None

    def test_fill_values_unknown_type(self):
        """Test that unknown type returns data unchanged."""
        data = ["a", "b", "c"]

        result = Handlers.fill_values(data, "UNKNOWN_TYPE")

        assert result == ["a", "b", "c"]


class TestExtractIdentifierSource:
    """Test identifier source extraction."""

    def test_extract_identifier_source_found(self):
        """Test extracting source from identifier list."""
        identifier_str = "[{'system': 'urn:Source', 'value': 'TestSource'}, {'system': 'http://other', 'value': 'Other'}]"

        result = Handlers.extract_identifier_source(identifier_str, "DefaultSource")

        assert result == "TestSource"

    def test_extract_identifier_source_not_found(self):
        """Test default returned when source not found."""
        identifier_str = "[{'system': 'http://other', 'value': 'Other'}]"

        result = Handlers.extract_identifier_source(identifier_str, "DefaultSource")

        assert result == "DefaultSource"

    def test_extract_identifier_source_invalid_syntax(self):
        """Test invalid syntax returns None."""
        result = Handlers.extract_identifier_source("invalid{{{", "Default")

        assert result is None

    def test_extract_identifier_source_empty_list(self):
        """Test empty list returns default."""
        result = Handlers.extract_identifier_source("[]", "DefaultSource")

        assert result == "DefaultSource"


class TestRunTimeCheck:
    """Test runtime check function."""

    @pytest.fixture
    def configurations(self):
        """Sample configurations with time interval."""
        return {
            'fhir_exporter': {
                'time_interval': '15'
            }
        }

    @patch('pyfiles.dependencies.handlers.datetime')
    def test_run_time_check_at_interval(self, mock_datetime, configurations):
        """Test run_time_check returns True at interval."""
        mock_now = MagicMock()
        mock_now.minute = 15  # 15 % 15 == 0
        mock_datetime.now.return_value = mock_now

        result = Handlers.run_time_check(configurations)

        assert result is True

    @patch('pyfiles.dependencies.handlers.datetime')
    def test_run_time_check_at_interval_minus_one(self, mock_datetime, configurations):
        """Test run_time_check returns True at interval-1."""
        mock_now = MagicMock()
        mock_now.minute = 14  # 14 % 15 == 14, and 14 == 15-1
        mock_datetime.now.return_value = mock_now

        result = Handlers.run_time_check(configurations)

        assert result is True

    @patch('pyfiles.dependencies.handlers.datetime')
    def test_run_time_check_not_at_interval(self, mock_datetime, configurations):
        """Test run_time_check returns False not at interval."""
        mock_now = MagicMock()
        mock_now.minute = 7  # 7 % 15 != 0 and 7 != 14
        mock_datetime.now.return_value = mock_now

        result = Handlers.run_time_check(configurations)

        assert result is False


class TestLoggingConfiguration:
    """Test logging configuration."""

    def test_logging_configuration_basic(self, tmp_path):
        """Test basic logging configuration."""
        # This test mainly checks that the function runs without errors
        excluded = ["test_file.py"]

        # Call without file logging
        Handlers.logging_configuration(excluded, "INFO")

        # If we get here without exception, the test passes

    def test_logging_configuration_with_file(self, tmp_path):
        """Test logging configuration with file output."""
        log_file = tmp_path / "test.log"
        excluded = []

        Handlers.logging_configuration(excluded, "DEBUG", log_file=str(log_file))

        # Verify log file was created (or would be created on first write)
        # The actual file might not exist until something is logged

    def test_logging_configuration_different_levels(self):
        """Test logging configuration with different levels."""
        # Test different log levels don't raise errors
        for level in ["INFO", "DEBUG", "ERROR", "WARNING"]:
            Handlers.logging_configuration([], level)
