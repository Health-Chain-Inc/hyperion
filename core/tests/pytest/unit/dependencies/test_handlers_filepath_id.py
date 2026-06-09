"""Unit tests for Handlers filepath_id helper methods and PipelineErrorCode enum."""
import uuid


class TestGenerateBatchFilepathId:
    """Test Handlers.generate_batch_filepath_id static method."""

    def test_returns_valid_uuid_string(self):
        """Test that the return value is a valid UUID string."""
        from pyfiles.dependencies.handlers import Handlers

        blob_url = "https://storage.blob.core.windows.net/staging/batch-load/20240101/Patient-1.ndjson"
        result = Handlers.generate_batch_filepath_id(blob_url)

        # Should not raise — a valid UUID parses without error
        parsed = uuid.UUID(result)
        assert str(parsed) == result

    def test_same_input_produces_same_output(self):
        """Test that the same blob URL always produces the same filepath_id (deterministic)."""
        from pyfiles.dependencies.handlers import Handlers

        blob_url = "https://storage.blob.core.windows.net/staging/batch-load/20240101/Patient-1.ndjson"
        result_1 = Handlers.generate_batch_filepath_id(blob_url)
        result_2 = Handlers.generate_batch_filepath_id(blob_url)

        assert result_1 == result_2

    def test_different_urls_produce_different_ids(self):
        """Test that different blob URLs produce different filepath_ids."""
        from pyfiles.dependencies.handlers import Handlers

        url_a = "https://storage.blob.core.windows.net/staging/batch-load/20240101/Patient-1.ndjson"
        url_b = "https://storage.blob.core.windows.net/staging/batch-load/20240101/Observation-2.ndjson"

        result_a = Handlers.generate_batch_filepath_id(url_a)
        result_b = Handlers.generate_batch_filepath_id(url_b)

        assert result_a != result_b

    def test_output_matches_direct_uuid5_computation(self):
        """Test that output exactly matches uuid.uuid5(NAMESPACE_DNS, blob_url)."""
        from pyfiles.dependencies.handlers import Handlers

        blob_url = "https://storage.blob.core.windows.net/staging/batch-load/20240101/Patient-1.ndjson"
        expected = str(uuid.uuid5(uuid.NAMESPACE_DNS, blob_url))
        result = Handlers.generate_batch_filepath_id(blob_url)

        assert result == expected

    def test_output_is_version_5_uuid(self):
        """Test that the returned UUID is version 5."""
        from pyfiles.dependencies.handlers import Handlers

        blob_url = "https://storage.blob.core.windows.net/staging/batch-load/20240101/Patient-1.ndjson"
        result = Handlers.generate_batch_filepath_id(blob_url)

        assert uuid.UUID(result).version == 5


class TestGenerateEventFilepathId:
    """Test Handlers.generate_event_filepath_id static method."""

    def test_returns_valid_uuid_string(self):
        """Test that the return value is a valid UUID string."""
        from pyfiles.dependencies.handlers import Handlers

        fhir_id = "patient-abc-123"
        version_id = "1"
        result = Handlers.generate_event_filepath_id(fhir_id, version_id)

        parsed = uuid.UUID(result)
        assert str(parsed) == result

    def test_same_inputs_produce_same_output(self):
        """Test that the same (fhir_id, version_id) always produces the same filepath_id."""
        from pyfiles.dependencies.handlers import Handlers

        fhir_id = "patient-abc-123"
        version_id = "1"
        result_1 = Handlers.generate_event_filepath_id(fhir_id, version_id)
        result_2 = Handlers.generate_event_filepath_id(fhir_id, version_id)

        assert result_1 == result_2

    def test_different_fhir_ids_produce_different_ids(self):
        """Test that different fhir_ids produce different filepath_ids (same version_id)."""
        from pyfiles.dependencies.handlers import Handlers

        version_id = "1"
        result_a = Handlers.generate_event_filepath_id("patient-abc-123", version_id)
        result_b = Handlers.generate_event_filepath_id("observation-xyz-456", version_id)

        assert result_a != result_b

    def test_different_version_ids_produce_different_ids(self):
        """Test that different version_ids produce different filepath_ids (same fhir_id)."""
        from pyfiles.dependencies.handlers import Handlers

        fhir_id = "patient-abc-123"
        result_v1 = Handlers.generate_event_filepath_id(fhir_id, "1")
        result_v2 = Handlers.generate_event_filepath_id(fhir_id, "2")

        assert result_v1 != result_v2

    def test_output_matches_direct_uuid5_computation(self):
        """Test that output exactly matches uuid.uuid5(NAMESPACE_DNS, fhir_id + version_id)."""
        from pyfiles.dependencies.handlers import Handlers

        fhir_id = "patient-abc-123"
        version_id = "1"
        expected = str(uuid.uuid5(uuid.NAMESPACE_DNS, fhir_id + version_id))
        result = Handlers.generate_event_filepath_id(fhir_id, version_id)

        assert result == expected

    def test_output_is_version_5_uuid(self):
        """Test that the returned UUID is version 5."""
        from pyfiles.dependencies.handlers import Handlers

        result = Handlers.generate_event_filepath_id("patient-abc-123", "1")

        assert uuid.UUID(result).version == 5

    def test_accepts_non_string_inputs_via_str_coercion(self):
        """Test that numeric fhir_id and version_id are coerced to str before hashing."""
        from pyfiles.dependencies.handlers import Handlers

        fhir_id = 12345
        version_id = 7
        expected = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(fhir_id) + str(version_id)))
        result = Handlers.generate_event_filepath_id(fhir_id, version_id)

        assert result == expected


class TestPipelineErrorCode:
    """Test PipelineErrorCode enum values."""

    def test_blob_read_failed_value(self):
        """Test BLOB_READ_FAILED has value '601'."""
        from pyfiles.dependencies.enum import PipelineErrorCode

        assert PipelineErrorCode.BLOB_READ_FAILED.value == "601"

    def test_normalization_failed_value(self):
        """Test NORMALIZATION_FAILED has value '602'."""
        from pyfiles.dependencies.enum import PipelineErrorCode

        assert PipelineErrorCode.NORMALIZATION_FAILED.value == "602"

    def test_insertion_failed_value(self):
        """Test INSERTION_FAILED has value '603'."""
        from pyfiles.dependencies.enum import PipelineErrorCode

        assert PipelineErrorCode.INSERTION_FAILED.value == "603"

    def test_unexpected_error_value(self):
        """Test UNEXPECTED_ERROR has value '699'."""
        from pyfiles.dependencies.enum import PipelineErrorCode

        assert PipelineErrorCode.UNEXPECTED_ERROR.value == "699"

    def test_all_four_members_exist(self):
        """Test that PipelineErrorCode has exactly four members."""
        from pyfiles.dependencies.enum import PipelineErrorCode

        members = list(PipelineErrorCode)
        assert len(members) == 4

    def test_lookup_by_value(self):
        """Test that each error code value can be used to look up the enum member."""
        from pyfiles.dependencies.enum import PipelineErrorCode

        assert PipelineErrorCode("601") is PipelineErrorCode.BLOB_READ_FAILED
        assert PipelineErrorCode("602") is PipelineErrorCode.NORMALIZATION_FAILED
        assert PipelineErrorCode("603") is PipelineErrorCode.INSERTION_FAILED
        assert PipelineErrorCode("699") is PipelineErrorCode.UNEXPECTED_ERROR

    def test_is_enum_instance(self):
        """Test that PipelineErrorCode members are Enum instances."""
        from pyfiles.dependencies.enum import PipelineErrorCode
        from enum import Enum

        assert isinstance(PipelineErrorCode.BLOB_READ_FAILED, Enum)
        assert isinstance(PipelineErrorCode.NORMALIZATION_FAILED, Enum)
        assert isinstance(PipelineErrorCode.INSERTION_FAILED, Enum)
        assert isinstance(PipelineErrorCode.UNEXPECTED_ERROR, Enum)
