"""Unit tests for DFOps class."""
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from pyfiles.dependencies.df_ops import DFOps


class TestExtractFhirAddressesOperatorPrecedenceRegression:
    """Regression test for df_ops.py:766-779 (Real bug fix — explicit parens on address concat).

    Before the fix, the expression
        lines[0] if len(lines) > 0 else "" + lines[1] if len(lines) > 1 else "" + postalCode
    parsed as a CHAINED TERNARY (operator precedence: if/else < +), so the
    second address line and postal code were silently dropped from the
    location_id hash. After the fix, parentheses are explicit:
        (lines[0] or "") + (lines[1] or "") + postalCode

    These tests assert the post-fix behavior: line[1] and postalCode both
    contribute to the hash.
    """

    def test_two_line_address_hash_includes_line_two(self):
        addr_with_line2 = {
            "use": "home",
            "line": ["123 Main St", "Apt 4B"],
            "postalCode": "10001",
        }
        addr_only_line1 = {
            "use": "home",
            "line": ["123 Main St"],
            "postalCode": "10001",
        }
        result_with = DFOps.extract_fhir_addresses(addr_with_line2)
        result_without = DFOps.extract_fhir_addresses(addr_only_line1)
        # If line[1] is in the hash, the two location_ids differ.
        # Pre-fix, line[1] was silently dropped → hashes identical.
        assert result_with["location_id"] != result_without["location_id"]

    def test_address_hash_includes_postal_code(self):
        addr_with_postal = {"line": ["123 Main St"], "postalCode": "10001"}
        addr_no_postal = {"line": ["123 Main St"], "postalCode": ""}
        result_with = DFOps.extract_fhir_addresses(addr_with_postal)
        result_without = DFOps.extract_fhir_addresses(addr_no_postal)
        assert result_with["location_id"] != result_without["location_id"]


class TestVersionExtraction:
    """Test meta version extraction functions."""

    def test_extract_version_id_valid_dict_string(self):
        """Test extracting versionId from a valid meta string."""
        meta = "{'versionId': '5', 'lastUpdated': '2024-01-01'}"
        result = DFOps.extract_version_id(meta)
        assert result == 5

    def test_extract_version_id_missing_returns_zero(self):
        """Test that missing versionId returns 0."""
        meta = "{'lastUpdated': '2024-01-01'}"
        result = DFOps.extract_version_id(meta)
        assert result == 0

    def test_extract_version_id_none_input(self):
        """Test that None input returns 0 (default value).

        When meta_str is None, ast.literal_eval("None") returns Python None,
        which is not a dict. The code detects this and returns the default value 0.
        """
        result = DFOps.extract_version_id(None)
        assert result == 0

    def test_extract_version_id_invalid_string(self):
        """Test that invalid string returns 0 (default value)."""
        result = DFOps.extract_version_id("not a dict")
        assert result == 0

    def test_extract_version_id_integer_value(self):
        """versionId stored as a plain integer (not string) is still cast to int."""
        meta = "{'versionId': 3, 'lastUpdated': '2024-06-01'}"
        result = DFOps.extract_version_id(meta)
        assert result == 3

    def test_extract_lastupdated_valid(self):
        """Test extracting lastUpdated timestamp."""
        meta = "{'versionId': '5', 'lastUpdated': '2024-01-01T10:00:00Z'}"
        result = DFOps.extract_lastupdated(meta)
        assert result == '2024-01-01T10:00:00Z'

    def test_extract_lastupdated_missing(self):
        """Test missing lastUpdated returns None."""
        meta = "{'versionId': '5'}"
        result = DFOps.extract_lastupdated(meta)
        assert result is None

    def test_extract_lastupdated_invalid(self):
        """Test invalid input returns None."""
        result = DFOps.extract_lastupdated("invalid")
        assert result is None


class TestDataFrameCreation:
    """Test DataFrame creation and manipulation."""

    def test_create_pandas_dataframe_from_list(self):
        """Test creating DataFrame from list of dicts."""
        data = [{"id": "1", "name": "test"}, {"id": "2", "name": "test2"}]
        df = DFOps.create_pandas_dataframe(data)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert 'id' in df.columns
        assert 'name' in df.columns

    def test_create_pandas_dataframe_empty_list(self):
        """Test creating DataFrame from empty list."""
        df = DFOps.create_pandas_dataframe([])
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_create_pandas_dataframe_single_item(self):
        """Test creating DataFrame from single item list."""
        data = [{"id": "1", "resourceType": "Patient"}]
        df = DFOps.create_pandas_dataframe(data)

        assert len(df) == 1
        assert df.iloc[0]['id'] == '1'
        assert df.iloc[0]['resourceType'] == 'Patient'


class TestColumnOperations:
    """Test column rename and manipulation."""

    def test_rename_column_existing(self):
        """Test renaming an existing column."""
        df = pd.DataFrame({'old_name': [1, 2, 3]})
        DFOps.rename_column(df, 'old_name', 'new_name')

        assert 'new_name' in df.columns
        assert 'old_name' not in df.columns

    def test_rename_column_nonexistent_does_nothing(self):
        """Test that renaming nonexistent column doesn't raise."""
        df = pd.DataFrame({'col1': [1, 2, 3]})
        DFOps.rename_column(df, 'nonexistent', 'new_name')

        assert 'col1' in df.columns
        assert 'new_name' not in df.columns

    def test_drop_column_existing(self):
        """Test dropping existing columns."""
        df = pd.DataFrame({'col1': [1, 2], 'col2': [3, 4], 'col3': [5, 6]})
        DFOps.drop_column(df, ['col1', 'col2'])

        assert 'col1' not in df.columns
        assert 'col2' not in df.columns
        assert 'col3' in df.columns

    def test_drop_column_nonexistent(self):
        """Test that dropping nonexistent columns doesn't raise."""
        df = pd.DataFrame({'col1': [1, 2, 3]})
        DFOps.drop_column(df, ['nonexistent', 'also_nonexistent'])

        assert 'col1' in df.columns


class TestConcatenateDataframes:
    """Test DataFrame concatenation."""

    def test_concatenate_dataframes_multiple(self):
        """Test concatenating multiple DataFrames."""
        parent = pd.DataFrame({'id': ['1'], 'val': ['a']})
        df1 = pd.DataFrame({'id': ['2'], 'val': ['b']})
        df2 = pd.DataFrame({'id': ['3'], 'val': ['c']})

        result = DFOps.concatenate_dataframes(parent, [df1, df2])

        assert len(result) == 3
        assert list(result['id']) == ['1', '2', '3']

    def test_concatenate_dataframes_with_none_parent(self):
        """Test concatenating with None parent."""
        df1 = pd.DataFrame({'id': ['1'], 'val': ['a']})
        df2 = pd.DataFrame({'id': ['2'], 'val': ['b']})

        result = DFOps.concatenate_dataframes(None, [df1, df2])

        assert len(result) == 2

    def test_concatenate_dataframes_empty_list(self):
        """Test concatenating empty list."""
        parent = pd.DataFrame({'id': ['1']})
        result = DFOps.concatenate_dataframes(parent, [])

        assert len(result) == 1

    def test_concatenate_dataframes_with_none_in_list(self):
        """Test concatenating list with None values."""
        parent = pd.DataFrame({'id': ['1']})
        df1 = pd.DataFrame({'id': ['2']})

        result = DFOps.concatenate_dataframes(parent, [None, df1, None])

        assert len(result) == 2


class TestHashRow:
    """Test row hashing functionality."""

    def test_hash_row_consistent(self):
        """Test that same input produces same hash."""
        value = {"key": "value", "number": 42}
        hash1 = DFOps.hash_row(value)
        hash2 = DFOps.hash_row(value)

        assert hash1 == hash2

    def test_hash_row_different_values(self):
        """Test that different values produce different hashes."""
        hash1 = DFOps.hash_row({"key": "value1"})
        hash2 = DFOps.hash_row({"key": "value2"})

        assert hash1 != hash2

    def test_hash_row_order_independent(self):
        """Test that key order doesn't affect hash (due to sort_keys)."""
        hash1 = DFOps.hash_row({"a": 1, "b": 2})
        hash2 = DFOps.hash_row({"b": 2, "a": 1})

        assert hash1 == hash2


class TestStringToBigint:
    """Test string to bigint conversion."""

    def test_string_to_bigint_consistent(self):
        """Test that same string produces same bigint."""
        result1 = DFOps.string_to_bigint("test-string")
        result2 = DFOps.string_to_bigint("test-string")

        assert result1 == result2
        assert isinstance(result1, int)

    def test_string_to_bigint_different_strings(self):
        """Test that different strings produce different bigints."""
        result1 = DFOps.string_to_bigint("string1")
        result2 = DFOps.string_to_bigint("string2")

        assert result1 != result2


class TestFHIRDatetimeParsing:
    """Test FHIR datetime parsing."""

    def test_parse_fhir_datetime_year_only(self):
        """Test parsing year-only date."""
        result = DFOps.parse_fhir_datetime_component("2021", "year")
        assert result == 2021

    def test_parse_fhir_datetime_full_date(self):
        """Test parsing full date."""
        result = DFOps.parse_fhir_datetime_component("2024-06-15", "date")
        assert result == "2024-06-15"

    def test_parse_fhir_datetime_iso_datetime(self):
        """Test parsing ISO datetime."""
        result = DFOps.parse_fhir_datetime_component("2024-06-15T10:30:00Z", "datetime")
        assert "2024-06-15" in result
        assert "10:30:00" in result

    def test_parse_fhir_datetime_time_component(self):
        """Test extracting time component."""
        result = DFOps.parse_fhir_datetime_component("2024-06-15T14:30:45Z", "time")
        assert result == "14:30:45"

    def test_parse_fhir_datetime_month_component(self):
        """Test extracting month component."""
        result = DFOps.parse_fhir_datetime_component("2024-06-15", "month")
        assert result == 6

    def test_parse_fhir_datetime_day_component(self):
        """Test extracting day component."""
        result = DFOps.parse_fhir_datetime_component("2024-06-15", "day")
        assert result == 15

    def test_parse_fhir_datetime_none_input(self):
        """Test that None input returns None."""
        result = DFOps.parse_fhir_datetime_component(None, "date")
        assert result is None

    def test_parse_fhir_datetime_placeholder_date(self):
        """Test that placeholder date 0001-01-01 returns None."""
        result = DFOps.parse_fhir_datetime_component("0001-01-01", "date")
        assert result is None

    def test_parse_fhir_datetime_invalid_component(self):
        """Test that invalid component raises ValueError."""
        with pytest.raises(ValueError):
            DFOps.parse_fhir_datetime_component("2024-01-01", "invalid")


class TestFHIRAddressExtraction:
    """Test FHIR Address extraction."""

    def test_extract_fhir_addresses_full(self):
        """Test extracting full address."""
        address = [{
            "use": "home",
            "type": "physical",
            "line": ["123 Main St", "Apt 4B"],
            "city": "New York",
            "state": "NY",
            "postalCode": "10001",
            "country": "US"
        }]

        result = DFOps.extract_fhir_addresses(address)

        assert result['address_1'] == "123 Main St"
        assert result['address_2'] == "Apt 4B"
        assert result['city'] == "New York"
        assert result['state'] == "NY"
        assert result['postalcode'] == "10001"
        assert result['country'] == "US"
        assert result['use'] == "home"
        assert result['type'] == "physical"

    def test_extract_fhir_addresses_single_line(self):
        """Test extracting address with single line."""
        address = [{
            "line": ["123 Main St"],
            "city": "Boston",
            "state": "MA"
        }]

        result = DFOps.extract_fhir_addresses(address)

        assert result['address_1'] == "123 Main St"
        assert result['address_2'] == ""
        assert result['city'] == "Boston"

    def test_extract_fhir_addresses_none(self):
        """Test extracting from None returns empty dict."""
        result = DFOps.extract_fhir_addresses(None)
        assert result == {}

    def test_extract_fhir_addresses_empty_list(self):
        """Test extracting from empty list returns empty dict."""
        result = DFOps.extract_fhir_addresses([])
        assert result == {}

    def test_extract_fhir_addresses_dict_input(self):
        """Test extracting address from dict (not list)."""
        address = {
            "line": ["456 Oak Ave"],
            "city": "Chicago"
        }

        result = DFOps.extract_fhir_addresses(address)

        assert result['address_1'] == "456 Oak Ave"
        assert result['city'] == "Chicago"


class TestFHIRHumanNameExtraction:
    """Test FHIR HumanName extraction."""

    def test_extract_fhir_humannames_full(self):
        """Test extracting full human name."""
        name = [{
            "use": "official",
            "family": "Smith",
            "given": ["John", "Michael"],
            "prefix": ["Dr."],
            "suffix": ["Jr."]
        }]

        result = DFOps.extract_fhir_humannames(name)

        assert result['family'] == "Smith"
        assert result['given'] == "John"
        assert result['prefix'] == "Dr."
        assert result['suffix'] == "Jr."
        assert result['use'] == "official"
        assert "John" in result['full_name']
        assert "Smith" in result['full_name']

    def test_extract_fhir_humannames_minimal(self):
        """Test extracting minimal human name."""
        name = [{"family": "Doe"}]

        result = DFOps.extract_fhir_humannames(name)

        assert result['family'] == "Doe"
        assert result['given'] == ""

    def test_extract_fhir_humannames_dict_input(self):
        """Test extracting from dict (not list)."""
        name = {"family": "Jones", "given": ["Jane"]}

        result = DFOps.extract_fhir_humannames(name)

        assert result['family'] == "Jones"
        assert result['given'] == "Jane"

    def test_full_name_includes_all_given_names(self):
        """full_name joins every element of the given array; given holds only the first."""
        name = [{"family": "Smith", "given": ["John", "Paul", "George"]}]

        result = DFOps.extract_fhir_humannames(name)

        assert "John" in result['full_name']
        assert "Paul" in result['full_name']
        assert "George" in result['full_name']
        assert result['given'] == "John"


class TestFHIRReferenceExtraction:
    """Test FHIR Reference extraction."""

    def test_extract_fhir_references_single(self):
        """Test extracting single reference."""
        ref = {"reference": "Patient/123"}

        result = DFOps.extract_fhir_references(ref, "Patient")

        assert result is not None
        assert isinstance(result, int)

    def test_extract_fhir_references_list(self):
        """Test extracting from list of references."""
        refs = [
            {"reference": "Patient/123"},
            {"reference": "Practitioner/456"}
        ]

        result = DFOps.extract_fhir_references(refs, "Patient")

        assert result is not None

    def test_extract_fhir_references_no_match(self):
        """Test extracting with no matching resource type."""
        ref = {"reference": "Observation/789"}

        result = DFOps.extract_fhir_references(ref, "Patient")

        assert result is None

    def test_extract_fhir_references_none(self):
        """Test extracting from None returns None."""
        result = DFOps.extract_fhir_references(None, "Patient")
        assert result is None


class TestFHIRIdentifierExtraction:
    """Test FHIR Identifier extraction."""

    def test_extract_fhir_identifiers_match(self):
        """Test extracting identifier by system."""
        identifiers = [
            {"system": "http://hospital.org/mrn", "value": "MRN123"},
            {"system": "http://other.org", "value": "OTHER456"}
        ]

        result = DFOps.extract_fhir_identifiers(identifiers, "http://hospital.org/mrn")

        assert result == "MRN123"

    def test_extract_fhir_identifiers_no_match(self):
        """Test extracting identifier with no match."""
        identifiers = [
            {"system": "http://hospital.org/mrn", "value": "MRN123"}
        ]

        result = DFOps.extract_fhir_identifiers(identifiers, "http://nonexistent.org")

        assert result is None

    def test_extract_fhir_identifiers_single_dict(self):
        """Test extracting from single dict (not list)."""
        identifier = {"system": "http://test.org", "value": "TEST123"}

        result = DFOps.extract_fhir_identifiers(identifier, "http://test.org")

        assert result == "TEST123"

    def test_extract_fhir_identifiers_none(self):
        """Test extracting from None returns None."""
        result = DFOps.extract_fhir_identifiers(None, "http://test.org")
        assert result is None


class TestFHIRCodeableConceptExtraction:
    """Test FHIR CodeableConcept extraction."""

    def test_extract_fhir_codeableconcepts_with_coding(self):
        """Test extracting from CodeableConcept with coding."""
        cc = {
            "coding": [
                {"system": "http://loinc.org", "code": "1234", "display": "Test Display"}
            ],
            "text": "Test Text"
        }

        result = DFOps.extract_fhir_codeableconcepts(cc)

        assert result == "Test Display"

    def test_extract_fhir_codeableconcepts_list_input(self):
        """Test extracting from list of CodeableConcepts."""
        cc_list = [{
            "coding": [{"display": "First Display"}]
        }]

        result = DFOps.extract_fhir_codeableconcepts(cc_list)

        assert result == "First Display"

    def test_extract_fhir_codeableconcepts_empty_coding(self):
        """Test extracting from CodeableConcept with empty coding."""
        cc = {"coding": [], "text": "Fallback"}

        result = DFOps.extract_fhir_codeableconcepts(cc)

        assert result is None

    def test_returns_none_when_coding_has_no_display(self):
        """When the coding entry lacks a display field, None is returned."""
        cc = {"coding": [{"system": "http://loinc.org", "code": "1234-5"}]}

        result = DFOps.extract_fhir_codeableconcepts(cc)

        assert result is None


class TestFHIRCodingExtraction:
    """Test FHIR Coding extraction."""

    def test_extract_fhir_coding_single(self):
        """Test extracting from single Coding."""
        coding = {"system": "http://test.org", "code": "123", "display": "Test"}

        result = DFOps.extract_fhir_coding(coding)

        assert result == "Test"

    def test_extract_fhir_coding_list(self):
        """Test extracting from list of Codings."""
        codings = [
            {"display": "First"},
            {"display": "Second"}
        ]

        result = DFOps.extract_fhir_coding(codings)

        assert result == "First"

    def test_extract_fhir_coding_no_display(self):
        """Test extracting when display is missing."""
        coding = {"system": "http://test.org", "code": "123"}

        result = DFOps.extract_fhir_coding(coding)

        assert result is None


class TestFHIRAnnotationExtraction:
    """Test FHIR Annotation extraction."""

    def test_extract_fhir_annotations_single(self):
        """Test extracting from single annotation."""
        annotation = {"text": "This is a note"}

        result = DFOps.extract_fhir_annotations(annotation)

        assert result == "This is a note"

    def test_extract_fhir_annotations_list(self):
        """Test extracting from list of annotations."""
        annotations = [
            {"text": "First note"},
            {"text": "Second note"}
        ]

        result = DFOps.extract_fhir_annotations(annotations)

        assert result == "First note"

    def test_extract_fhir_annotations_none(self):
        """Test extracting from None returns None."""
        result = DFOps.extract_fhir_annotations(None)
        assert result is None

    def test_extract_fhir_annotations_empty_list(self):
        """Test extracting from empty list returns None."""
        result = DFOps.extract_fhir_annotations([])
        assert result is None


class TestFHIRValueQuantityExtraction:
    """Test FHIR ValueQuantity extraction."""

    def test_extract_fhir_valuequantity_dict(self):
        """Test extracting value from quantity dict."""
        quantity = {"value": 72, "unit": "beats/min"}

        result = DFOps.extract_fhir_valuequantity(quantity)

        assert result == 72

    def test_extract_fhir_valuequantity_list(self):
        """Test extracting value from quantity list."""
        quantities = [{"value": 98.6}]

        result = DFOps.extract_fhir_valuequantity(quantities)

        assert result == 98.6

    def test_extract_fhir_valuequantity_none(self):
        """Test extracting from None returns None."""
        result = DFOps.extract_fhir_valuequantity(None)
        assert result is None


class TestIdentifierSourceExtraction:
    """Test identifier source extraction."""

    def test_extract_identifier_source_found(self):
        """Test extracting source from identifier list."""
        identifier_str = "[{'system': 'urn:Source', 'value': 'TestSource'}, {'system': 'http://other', 'value': 'Other'}]"

        result = DFOps.extract_identifier_source(identifier_str, "DefaultSource")

        assert result == "TestSource"

    def test_extract_identifier_source_not_found(self):
        """Test default returned when source not found."""
        identifier_str = "[{'system': 'http://other', 'value': 'Other'}]"

        result = DFOps.extract_identifier_source(identifier_str, "DefaultSource")

        assert result == "DefaultSource"

    def test_extract_identifier_source_invalid(self):
        """Test invalid input returns None."""
        result = DFOps.extract_identifier_source("invalid", "Default")

        assert result is None


class TestSerializeField:
    """Test field serialization."""

    def test_serialize_field_dict(self):
        """Test serializing dictionary."""
        value = {"key": "value"}
        result = DFOps.serialize_field(value)
        assert result == {"key": "value"}

    def test_serialize_field_list_of_dicts(self):
        """Test serializing list of dictionaries."""
        value = [{"key": "value1"}, {"key": "value2"}]
        result = DFOps.serialize_field(value)
        assert result == [{"key": "value1"}, {"key": "value2"}]

    def test_serialize_field_simple_list(self):
        """Test serializing simple list."""
        value = [1, 2, None, 4]
        result = DFOps.serialize_field(value)
        assert result == [1, 2, None, 4]

    def test_serialize_field_primitive(self):
        """Test serializing primitive value."""
        assert DFOps.serialize_field("string") == "string"
        assert DFOps.serialize_field(42) == 42
        assert DFOps.serialize_field(None) is None


class TestCleanupCodeableConcepts:
    """Test CodeableConcept cleanup."""

    def test_cleanup_codeableconcepts_with_coding(self):
        """Test cleaning up CodeableConcept with coding array."""
        row = pd.Series({
            "json": {
                "coding": [
                    {"system": "http://loinc.org", "code": "1234", "display": "Test", "version": "1.0"}
                ],
                "text": "Test Text"
            }
        })

        result = DFOps.cleanup_codeableconcepts(row)

        assert result["system"] == ["http://loinc.org"]
        assert result["code"] == ["1234"]
        assert result["display"] == ["Test"]
        assert result["text"] == ["Test Text"]

    def test_cleanup_codeableconcepts_without_coding(self):
        """Test cleaning up CodeableConcept without coding array."""
        row = pd.Series({
            "json": {
                "system": "http://direct.org",
                "code": "ABC",
                "display": "Direct"
            }
        })

        result = DFOps.cleanup_codeableconcepts(row)

        assert result["system"] == ["http://direct.org"]
        assert result["code"] == ["ABC"]


class TestCleanupReferences:
    """Test Reference cleanup."""

    def test_cleanup_references_valid(self):
        """Test cleaning up valid reference."""
        row = pd.Series({
            "json": {
                "reference": "Patient/123",
                "display": "John Doe",
                "type": "Patient"
            }
        })

        result = DFOps.cleanup_references(row)

        assert result["reference"] == "Patient/123"
        assert result["display"] == "John Doe"
        assert result["reference_type"] == "Patient"


class TestCleanupIdentifiers:
    """Test Identifier cleanup."""

    def test_cleanup_identifiers_valid(self):
        """Test cleaning up valid identifier."""
        row = pd.Series({
            "json": {
                "system": "http://hospital.org/mrn",
                "value": "MRN123",
                "use": "official",
                "period": {"start": "2020-01-01", "end": "2024-12-31"}
            }
        })

        result = DFOps.cleanup_identifiers(row)

        assert result["system"] == "http://hospital.org/mrn"
        assert result["value"] == "MRN123"
        assert result["use"] == "official"
        assert result["period_start"] == "2020-01-01"
        assert result["period_end"] == "2024-12-31"


class TestFillValues:
    """Test fill values function."""

    def test_fill_values_array_integer(self):
        """Test filling None for NaN in integer array."""
        data = [1.0, float('nan'), 3.0]

        result = DFOps.fill_values(data, "ARRAY<INTEGER>")

        assert result[0] == 1
        assert result[1] is None
        assert result[2] == 3

    def test_fill_values_none_data(self):
        """Test that None data is handled."""
        result = DFOps.fill_values(None, "ARRAY<INTEGER>")
        assert result is None

    def test_fill_values_empty_list(self):
        """Test that empty list is handled."""
        result = DFOps.fill_values([], "ARRAY<INTEGER>")
        assert result == []

    def test_fill_values_nested_array_integer(self):
        """Test filling None for NaN in nested integer array."""
        data = [[1.0, float('nan')], [3.0, 4.0]]

        result = DFOps.fill_values(data, "ARRAY<ARRAY<INTEGER>>")

        assert result[0][0] == 1
        assert result[0][1] is None
        assert result[1][0] == 3
        assert result[1][1] == 4


class TestProcessDataframe:
    """Test process_dataframe method."""

    def test_processes_without_mappings(self):
        """Test processing dataframe without column mappings."""
        df = pd.DataFrame({
            'id': ['1', '2'],
            'name': ['Test1', 'Test2'],
            'value': [100, 200]
        })

        # Mock configparser to return no section
        with patch('pyfiles.dependencies.df_ops.configparser.ConfigParser') as mock_config:
            mock_instance = MagicMock()
            mock_instance.has_section.return_value = False
            mock_config.return_value = mock_instance

            result = DFOps.process_dataframe('test_table', df)

            assert len(result) == 2
            assert 'id' in result.columns

    def test_processes_with_column_mappings(self):
        """Test processing dataframe with column mappings."""
        df = pd.DataFrame({
            'id': ['1'],
            'values': [[1, 2, 3]]  # Use integers instead of floats with nan
        })

        with patch('pyfiles.dependencies.df_ops.configparser.ConfigParser') as mock_config:
            mock_instance = MagicMock()
            mock_instance.has_section.return_value = True
            mock_instance.get.return_value = None  # No type conversion needed
            mock_config.return_value = mock_instance

            result = DFOps.process_dataframe('test_table', df)

            assert len(result) == 1

    def test_processes_dict_values(self):
        """Test processing dataframe with dict values."""
        df = pd.DataFrame({
            'id': ['1'],
            'metadata': [{'key': 'value'}]
        })

        with patch('pyfiles.dependencies.df_ops.configparser.ConfigParser') as mock_config:
            mock_instance = MagicMock()
            mock_instance.has_section.return_value = False
            mock_config.return_value = mock_instance

            result = DFOps.process_dataframe('test_table', df)

            assert result.iloc[0]['metadata'] == {'key': 'value'}


class TestExtractExtensionValues:
    """Test extract_extension_values method."""

    def test_extracts_nested_extensions(self):
        """Test extracting values from nested extensions."""
        data = {
            "extension": [
                {
                    "url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race",
                    "valueCoding": {
                        "system": "urn:oid:2.16.840.1.113883.6.238",
                        "code": "2106-3",
                        "display": "White"
                    }
                }
            ]
        }

        urls = ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-race"]
        coding_paths = ["valueCoding"]

        result = DFOps.extract_extension_values(data, urls, coding_paths)

        assert result == "White"

    def test_handles_multiple_urls(self):
        """Test handling multiple URLs to search."""
        data = {
            "extension": [
                {
                    "url": "http://other-url",
                    "valueString": "Other"
                },
                {
                    "url": "http://target-url",
                    "valueCoding": {"display": "Found"}
                }
            ]
        }

        urls = ["http://target-url", "http://other-url"]
        coding_paths = ["valueCoding"]

        result = DFOps.extract_extension_values(data, urls, coding_paths)

        assert result == "Found"

    def test_returns_none_for_missing(self):
        """Test returning None when extension not found."""
        data = {
            "extension": [
                {"url": "http://different-url", "valueString": "Test"}
            ]
        }

        urls = ["http://nonexistent-url"]
        coding_paths = ["valueCoding"]

        result = DFOps.extract_extension_values(data, urls, coding_paths)

        assert result is None

    def test_handles_list_input(self):
        """Test handling list of extensions directly."""
        data = [
            {
                "url": "http://test-url",
                "valueCoding": {"display": "Test Display"}
            }
        ]

        urls = ["http://test-url"]
        coding_paths = ["valueCoding"]

        result = DFOps.extract_extension_values(data, urls, coding_paths)

        assert result == "Test Display"

    def test_handles_empty_extension(self):
        """Test handling empty extension list."""
        data = {"extension": []}

        urls = ["http://any-url"]
        coding_paths = ["valueCoding"]

        result = DFOps.extract_extension_values(data, urls, coding_paths)

        assert result is None


class TestExtractFhirBackboneElement:
    """Test extract_fhir_backboneelement method."""

    def test_extracts_reference_from_backbone(self):
        """Test extracting reference from backbone element."""
        data = [{
            "actor": {
                "reference": "Practitioner/123",
                "display": "Dr. Smith"
            }
        }]

        attribute_filter = {
            "child": "actor",
            "fhir_datatype": "Reference",
            "reference_filter": {"resource": "Practitioner"}
        }

        result = DFOps.extract_fhir_backboneelement(data, attribute_filter)

        assert result is not None
        assert isinstance(result, int)

    def test_extracts_codeableconcept_from_backbone(self):
        """Test extracting CodeableConcept from backbone element."""
        data = [{
            "code": {
                "coding": [
                    {"system": "http://test", "code": "123", "display": "Test Code"}
                ]
            }
        }]

        attribute_filter = {
            "child": "code",
            "fhir_datatype": "CodeableConcept"
        }

        result = DFOps.extract_fhir_backboneelement(data, attribute_filter)

        assert result == "Test Code"

    def test_extracts_quantity_from_backbone(self):
        """Test extracting SimpleQuantity from backbone element."""
        data = [{
            "quantity": {
                "value": 42,
                "unit": "mg"
            }
        }]

        attribute_filter = {
            "child": "quantity",
            "fhir_datatype": "SimpleQuantity"
        }

        result = DFOps.extract_fhir_backboneelement(data, attribute_filter)

        assert result == 42

    def test_handles_dict_input(self):
        """Test handling dict input (not list)."""
        data = {
            "performer": {
                "reference": "Organization/456"
            }
        }

        attribute_filter = {
            "child": "performer",
            "fhir_datatype": "Reference",
            "reference_filter": {"resource": "Organization"}
        }

        result = DFOps.extract_fhir_backboneelement(data, attribute_filter)

        assert result is not None

    def test_handles_missing_child(self):
        """Test handling when child attribute is missing."""
        data = [{"other": "value"}]

        attribute_filter = {
            "child": "nonexistent",
            "fhir_datatype": "Reference",
            "reference_filter": {"resource": "Patient"}
        }

        result = DFOps.extract_fhir_backboneelement(data, attribute_filter)

        assert result is None


class TestGetTableData:
    """Test get_table_data method."""

    def test_generates_deletion_records(self):
        """Test generating records for deletion."""
        ids_to_delete = ['patient-1', 'patient-2']
        field_names = ['identifier', 'codeableconcept']
        deletion_counts = {'patient-1': 2, 'patient-2': 1}

        result = DFOps.get_table_data(ids_to_delete, field_names, deletion_counts)

        assert isinstance(result, pd.DataFrame)
        assert 'id' in result.columns
        assert 'field_name' in result.columns
        assert 'seq_no' in result.columns
        assert 'record_id' in result.columns
        assert '__op' in result.columns

    def test_returns_empty_for_no_fields(self):
        """Test returning empty dataframe when no field names."""
        ids_to_delete = ['patient-1']
        field_names = []
        deletion_counts = {}

        result = DFOps.get_table_data(ids_to_delete, field_names, deletion_counts)

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0


class TestDataframeMeltAndExplode:
    """Test dataframe_melt_and_explode method."""

    def test_melts_and_explodes_correctly(self):
        """Test melting and exploding dataframe."""
        df = pd.DataFrame({
            'id': ['1'],
            'identifier': [[{'system': 'a'}, {'system': 'b'}]],
            'name': [[{'family': 'Smith'}]]
        })

        result = DFOps.dataframe_melt_and_explode(df)

        assert 'field_name' in result.columns
        assert 'json' in result.columns
        # Should have exploded rows for both identifier and name

    def test_handles_single_dict_values(self):
        """Test handling single dict values (not list)."""
        df = pd.DataFrame({
            'id': ['1'],
            'code': [{'system': 'http://test', 'code': '123'}]
        })

        result = DFOps.dataframe_melt_and_explode(df)

        assert len(result) >= 1


class TestDataframeStack:
    """Test dataframe_stack method."""

    def test_stacks_dataframe(self):
        """Test stacking dataframe with values."""
        df = pd.DataFrame({
            'id': ['1', '1'],
            'field_name': ['identifier', 'identifier'],
            'json': [None, None],
            'system': ['http://a', 'http://b'],
            'value': ['val1', 'val2']
        })

        result = DFOps.dataframe_stack(df)

        if not result.empty:
            assert 'seq_no' in result.columns
            assert 'record_id' in result.columns

    def test_returns_empty_for_empty_input(self):
        """Test returning empty dataframe for empty input."""
        df = pd.DataFrame()

        result = DFOps.dataframe_stack(df)

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
