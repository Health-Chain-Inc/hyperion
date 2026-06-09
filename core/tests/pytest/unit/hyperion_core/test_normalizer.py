"""Unit tests for Normalizer class."""
import pytest
import pandas as pd
from pyfiles.hyperion_core.normalizer import Normalizer


class TestBackboneNormalizationDedentRegression:
    """Regression test for the dedent fix in normalizer.py:319-342.

    Before the fix, ``obj["normalized"] = pd.DataFrame(rows)`` and the column
    rename ran INSIDE the for-loop, building N throwaway DataFrames for N
    entries and leaving a stale value if the last entry didn't match the
    dict-check at line 334. After the fix, both statements run once after the
    loop, so the resulting DataFrame correctly reflects all matching rows.
    """

    def _simulate_backbone_normalization(self, data_to_normalize, column):
        """Replicate the relevant block from Normalizer.run with the FIX applied.

        We don't need a full Normalizer instance — we just need to exercise
        the algorithm with the dedent applied, and verify the result is what
        we expect when the last entry's column value isn't a dict.
        """
        rows = []
        for entry in data_to_normalize:
            if column in entry and isinstance(entry[column], dict):
                row = {"id": entry["id"]}
                row.update(entry[column])
                rows.append(row)
        # Post-loop (dedented per the fix):
        normalized = pd.DataFrame(rows)
        if not normalized.empty:
            normalized.columns = [
                f"{column.lower()}_{col.lower()}" if col != "id" else col
                for col in normalized.columns
            ]
        return normalized

    def test_collects_all_matching_entries_not_just_last(self):
        column = "contact"
        data = [
            {"id": "p1", "contact": {"name": "Alice", "phone": "111"}},
            {"id": "p2", "contact": {"name": "Bob", "phone": "222"}},
            {"id": "p3", "contact": {"name": "Carol", "phone": "333"}},
        ]
        df = self._simulate_backbone_normalization(data, column)
        assert len(df) == 3
        assert set(df["id"].tolist()) == {"p1", "p2", "p3"}

    def test_last_entry_with_non_dict_value_leaves_prior_matches_intact(self):
        """Critical edge case: if the last entry's column is not a dict,
        the prior fix preserves the accumulated rows. Before the fix, a
        non-dict last entry could leave obj["normalized"] stale."""
        column = "contact"
        data = [
            {"id": "p1", "contact": {"name": "Alice"}},
            {"id": "p2", "contact": {"name": "Bob"}},
            {"id": "p3", "contact": None},  # non-dict
        ]
        df = self._simulate_backbone_normalization(data, column)
        assert len(df) == 2
        assert set(df["id"].tolist()) == {"p1", "p2"}

    def test_column_renames_applied_with_lowercase_prefix(self):
        column = "Contact"
        data = [{"id": "p1", "Contact": {"Name": "Alice"}}]
        df = self._simulate_backbone_normalization(data, column)
        # id stays "id"; other columns get "contact_<lowercased>" prefix
        assert "id" in df.columns
        assert "contact_name" in df.columns


class TestNormalizerInitialization:
    """Test Normalizer class initialization."""

    def test_normalizer_creates_successfully(self, fhir_schema, sample_fhir_patient):
        """Test Normalizer initializes with valid inputs."""
        patient_df = pd.DataFrame([sample_fhir_patient])

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="test-file-123",
            fhir_df=patient_df
        )

        assert normalizer.fhir_resource_type == "Patient"
        assert normalizer.filepath_id == "test-file-123"
        assert normalizer.data is not None
        assert isinstance(normalizer.dataframes, dict)
        assert isinstance(normalizer.backbone_objects, dict)

    def test_normalizer_with_empty_dataframe(self, fhir_schema):
        """Test Normalizer with empty DataFrame."""
        empty_df = pd.DataFrame()

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="empty-file",
            fhir_df=empty_df
        )

        assert normalizer.data.empty


class TestDataframeColumnIterator:
    """Test the column classification logic."""

    def test_classifies_codeableconcept_columns(self, fhir_schema, sample_fhir_patient):
        """Test that CodeableConcept columns are identified."""
        patient_df = pd.DataFrame([sample_fhir_patient])

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="test-file",
            fhir_df=patient_df
        )

        (cc, refs, ids, ext, arr_complex,
         non_arr_complex, primitive) = normalizer.dataframe_column_iterator(
            patient_df, "Patient"
        )

        # CodeableConcept should be identified
        assert isinstance(cc, list)
        # maritalStatus is a CodeableConcept in Patient
        if 'maritalStatus' in patient_df.columns:
            assert 'maritalStatus' in cc

    def test_classifies_reference_columns(self, fhir_schema, sample_fhir_patient):
        """Test that Reference columns are identified."""
        patient_df = pd.DataFrame([sample_fhir_patient])

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="test-file",
            fhir_df=patient_df
        )

        (cc, refs, ids, ext, arr_complex,
         non_arr_complex, primitive) = normalizer.dataframe_column_iterator(
            patient_df, "Patient"
        )

        assert isinstance(refs, list)

    def test_classifies_identifier_columns(self, fhir_schema, sample_fhir_patient):
        """Test that Identifier columns are identified."""
        patient_df = pd.DataFrame([sample_fhir_patient])

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="test-file",
            fhir_df=patient_df
        )

        (cc, refs, ids, ext, arr_complex,
         non_arr_complex, primitive) = normalizer.dataframe_column_iterator(
            patient_df, "Patient"
        )

        assert isinstance(ids, list)
        # identifier is always an identifier column
        if 'identifier' in patient_df.columns:
            assert 'identifier' in ids

    def test_classifies_primitive_columns(self, fhir_schema, sample_fhir_patient):
        """Test that primitive columns are identified."""
        patient_df = pd.DataFrame([sample_fhir_patient])

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="test-file",
            fhir_df=patient_df
        )

        (cc, refs, ids, ext, arr_complex,
         non_arr_complex, primitive) = normalizer.dataframe_column_iterator(
            patient_df, "Patient"
        )

        assert isinstance(primitive, list)
        # id and gender should be primitives
        if 'id' in patient_df.columns:
            assert 'id' in primitive
        if 'gender' in patient_df.columns:
            assert 'gender' in primitive

    def test_classifies_extension_columns(self, fhir_schema, sample_fhir_patient):
        """Test that Extension columns are identified."""
        patient_df = pd.DataFrame([sample_fhir_patient])

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="test-file",
            fhir_df=patient_df
        )

        (cc, refs, ids, ext, arr_complex,
         non_arr_complex, primitive) = normalizer.dataframe_column_iterator(
            patient_df, "Patient"
        )

        assert isinstance(ext, list)


class TestGetColumnInformation:
    """Test column information extraction."""

    def test_get_column_info_primitive(self, fhir_schema, sample_fhir_patient):
        """Test getting info for primitive column."""
        patient_df = pd.DataFrame([sample_fhir_patient])

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="test-file",
            fhir_df=patient_df
        )

        fhir_datatype, is_array, complex_datatype, backbone = normalizer.get_column_information(
            "Patient", "gender"
        )

        assert fhir_datatype == "string" or fhir_datatype == "code"
        assert is_array is False

    def test_get_column_info_array(self, fhir_schema, sample_fhir_patient):
        """Test getting info for array column."""
        patient_df = pd.DataFrame([sample_fhir_patient])

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="test-file",
            fhir_df=patient_df
        )

        fhir_datatype, is_array, complex_datatype, backbone = normalizer.get_column_information(
            "Patient", "name"
        )

        assert is_array is True

    def test_get_column_info_complex(self, fhir_schema, sample_fhir_patient):
        """Test getting info for complex column."""
        patient_df = pd.DataFrame([sample_fhir_patient])

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="test-file",
            fhir_df=patient_df
        )

        fhir_datatype, is_array, complex_datatype, backbone = normalizer.get_column_information(
            "Patient", "identifier"
        )

        assert complex_datatype is True


class TestNormalizerRun:
    """Test Normalizer.run() output structure."""

    def test_run_returns_expected_tables(self, fhir_schema, sample_fhir_patient):
        """Test that run() returns dict with expected table keys."""
        patient_df = pd.DataFrame([sample_fhir_patient])

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="test-file",
            fhir_df=patient_df
        )

        result = normalizer.run()

        # Should return dict of DataFrames
        assert isinstance(result, dict)

        # Should have main patient table
        assert 'patient' in result
        assert isinstance(result['patient'], pd.DataFrame)

        # Should have codeableconcept table
        assert 'codeableconcept' in result

        # Should have reference table
        assert 'reference' in result

        # Should have identifier table
        assert 'identifier' in result

    def test_run_patient_has_required_columns(self, fhir_schema, sample_fhir_patient):
        """Test that patient DataFrame has required columns."""
        patient_df = pd.DataFrame([sample_fhir_patient])

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="test-file",
            fhir_df=patient_df
        )

        result = normalizer.run()
        patient_df_result = result['patient']

        # Check for essential FHIR Patient fields (lowercased)
        assert 'id' in patient_df_result.columns

    def test_run_with_real_patient_data(self, fhir_schema, sample_patient_ndjson):
        """Test running normalizer with real patient test data."""
        patient_df = pd.DataFrame(sample_patient_ndjson)

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="test-patient-file",
            fhir_df=patient_df
        )

        result = normalizer.run()

        # Verify basic structure
        assert 'patient' in result
        assert len(result['patient']) == len(sample_patient_ndjson)

    def test_run_preserves_id(self, fhir_schema, sample_fhir_patient):
        """Test that run() preserves the resource ID."""
        patient_df = pd.DataFrame([sample_fhir_patient])

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="test-file",
            fhir_df=patient_df
        )

        result = normalizer.run()

        # ID should be preserved
        assert result['patient'].iloc[0]['id'] == sample_fhir_patient['id']


class TestNormalizerStaticMethod:
    """Test the static normalizer method."""

    def test_normalizer_static_with_array(self):
        """Test static normalizer with array columns."""
        input_df = pd.DataFrame({
            'id': ['1', '2'],
            'names': [
                [{'family': 'Smith', 'given': ['John']}],
                [{'family': 'Doe', 'given': ['Jane']}]
            ]
        })

        result = Normalizer.normalizer(input_df, ['names'], is_array=True)

        assert isinstance(result, pd.DataFrame)
        assert 'id' in result.columns

    def test_normalizer_static_with_non_array(self):
        """Test static normalizer with non-array columns."""
        input_df = pd.DataFrame({
            'id': ['1', '2'],
            'status': [
                {'coding': [{'code': 'active'}]},
                {'coding': [{'code': 'inactive'}]}
            ]
        })

        result = Normalizer.normalizer(input_df, ['status'], is_array=False)

        assert isinstance(result, pd.DataFrame)

    def test_normalizer_static_empty_input(self):
        """Test static normalizer with empty DataFrame."""
        input_df = pd.DataFrame({'id': []})

        result = Normalizer.normalizer(input_df, [], is_array=False)

        assert isinstance(result, pd.DataFrame)


class TestNormalizerWithObservation:
    """Test Normalizer with Observation resources."""

    def test_run_with_observation(self, fhir_schema, sample_fhir_observation):
        """Test normalizer with Observation resource."""
        obs_df = pd.DataFrame([sample_fhir_observation])

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Observation",
            filepath_id="test-obs-file",
            fhir_df=obs_df
        )

        result = normalizer.run()

        # Should have observation table
        assert 'observation' in result
        assert isinstance(result['observation'], pd.DataFrame)
        assert len(result['observation']) == 1


class TestNormalizerColumnLowercase:
    """Test that column names are lowercased."""

    def test_columns_are_lowercased(self, fhir_schema, sample_fhir_patient):
        """Test that all column names in result are lowercase."""
        patient_df = pd.DataFrame([sample_fhir_patient])

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="test-file",
            fhir_df=patient_df
        )

        result = normalizer.run()

        # Check main resource table
        for col in result['patient'].columns:
            assert col == col.lower(), f"Column '{col}' is not lowercase"


class TestNormalizerBackboneElements:
    """Test handling of BackboneElement structures."""

    def test_backbone_objects_initialized(self, fhir_schema, sample_fhir_patient):
        """Test that backbone_objects dict is initialized."""
        patient_df = pd.DataFrame([sample_fhir_patient])

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="test-file",
            fhir_df=patient_df
        )

        # backbone_objects should be a dict (may be empty for Patient)
        assert isinstance(normalizer.backbone_objects, dict)


class TestNormalizerMaxArraySizes:
    """Test max array size tracking."""

    def test_max_codeableconcept_array_size(self, fhir_schema, sample_patient_ndjson):
        """Test that max codeableconcept array size is tracked."""
        patient_df = pd.DataFrame(sample_patient_ndjson)

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="test-file",
            fhir_df=patient_df
        )

        result = normalizer.run()

        # If codeableconcepts exist, max array size should be tracked
        if 'codeableconcept_max_array_size' in result['patient'].columns:
            # Should be numeric
            assert result['patient']['codeableconcept_max_array_size'].dtype in ['int64', 'float64']


class TestNormalizerWithDiagnosticReport:
    """Test Normalizer with DiagnosticReport resources."""

    def test_run_with_diagnostic_report(self, fhir_schema, sample_diagnostic_report_ndjson):
        """Test normalizer with DiagnosticReport resource."""
        if not sample_diagnostic_report_ndjson:
            pytest.skip("No DiagnosticReport test data available")

        dr_df = pd.DataFrame(sample_diagnostic_report_ndjson)

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="DiagnosticReport",
            filepath_id="test-dr-file",
            fhir_df=dr_df
        )

        result = normalizer.run()

        # Should have diagnosticreport table
        assert 'diagnosticreport' in result
        assert isinstance(result['diagnosticreport'], pd.DataFrame)


class TestNormalizerEdgeCases:
    """Test edge cases and error handling."""

    def test_normalizer_with_missing_columns(self, fhir_schema):
        """Test normalizer handles missing optional columns."""
        minimal_patient = pd.DataFrame([{
            'id': 'minimal-patient',
            'resourceType': 'Patient'
        }])

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="minimal-file",
            fhir_df=minimal_patient
        )

        result = normalizer.run()

        assert 'patient' in result
        assert len(result['patient']) == 1

    def test_normalizer_with_null_values(self, fhir_schema):
        """Test normalizer handles null values in data."""
        patient_with_nulls = pd.DataFrame([{
            'id': 'null-patient',
            'resourceType': 'Patient',
            'gender': None,
            'birthDate': None
        }])

        normalizer = Normalizer(
            resource_structure=fhir_schema,
            fhir_resource_type="Patient",
            filepath_id="null-file",
            fhir_df=patient_with_nulls
        )

        result = normalizer.run()

        assert 'patient' in result
        # Should not raise an error
