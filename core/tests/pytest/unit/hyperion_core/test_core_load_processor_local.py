"""Unit tests for CoreLoadProcessor.local_converter (local-mode pipeline).

After the local-mode refactor, ``local_converter`` runs the same downstream
pipeline as Azure mode: ``get_processed_data`` -> ``normalizer`` ->
``streamloader`` -> ``TransactionManager.transaction``. These tests verify the
local-mode-specific wiring (FHIR pull, per-resource iteration, skip-empty)
while mocking the shared downstream path.
"""
import pandas as pd
from unittest.mock import MagicMock, patch


def make_config(resource_types=None):
    return {
        "application": {"name": "core-data-ingester"},
        "schema": {"hl7_file_name": "schema/fhir.schema.json"},
        "FHIR": {"ndjson_file_size": "1000"},
        "local.fhir": {"server_url": "http://hapi-fhir:8080/fhir"},
        "default_value": {
            "resource_types": ",".join(resource_types or ["Patient"]),
            "lookback_days": "30",
        },
        "silver_layer": {
            "http_server": "starrocks-fe:8030",
            "username": "root",
            "password": "",
            "core_database": "_hyperion_core_",
        },
        "processing": {"local_batch_size": "100"},
    }


class TestCoreLoadProcessorLocalConverter:
    def test_pulls_resources_from_each_configured_type(self):
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        fhir_client = MagicMock()
        fhir_client.iter_resources.side_effect = [iter([]), iter([])]
        db_pool = MagicMock()

        with patch.object(CoreLoadProcessor, "get_fhir_structure", return_value={}):
            proc = CoreLoadProcessor(
                queue_client=None,
                storage_client=None,
                fhir_client=fhir_client,
                project_configurations=make_config(["Patient", "Observation"]),
                db_connection_pool=db_pool,
            )
            proc.local_converter()

        types_pulled = [call.args[0] for call in fhir_client.iter_resources.call_args_list]
        assert types_pulled == ["Patient", "Observation"]

    def test_normalizes_per_resource_not_bundle_wrapper(self):
        """Resources are passed to the pipeline individually, never wrapped in a Bundle."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        fhir_client = MagicMock()
        fhir_client.iter_resources.return_value = iter([
            {"resourceType": "Patient", "id": "p1"},
            {"resourceType": "Patient", "id": "p2"},
        ])
        db_pool = MagicMock()

        # get_processed_data is the first downstream call; capture what it sees.
        captured_fhir_data = {}
        def fake_get_processed_data(self, fhir_data, fhir_resource_type, blob_url, filepath_id=None):
            captured_fhir_data["data"] = fhir_data
            return (True, pd.DataFrame(fhir_data), pd.DataFrame(), None)

        with patch.object(CoreLoadProcessor, "get_fhir_structure", return_value={}), \
             patch.object(CoreLoadProcessor, "get_processed_data", fake_get_processed_data), \
             patch.object(CoreLoadProcessor, "normalizer", return_value={}), \
             patch.object(CoreLoadProcessor, "streamloader"):
            proc = CoreLoadProcessor(
                queue_client=None,
                storage_client=None,
                fhir_client=fhir_client,
                project_configurations=make_config(["Patient"]),
                db_connection_pool=db_pool,
            )
            proc.local_converter()

        # local_converter feeds get_processed_data a list of resource dicts —
        # individual Patients, not a single Bundle. Each row has its own id.
        passed = captured_fhir_data["data"]
        assert isinstance(passed, list)
        assert {r["id"] for r in passed} == {"p1", "p2"}
        # No row should itself be a Bundle wrapper.
        for r in passed:
            assert r.get("resourceType") != "Bundle"

    def test_streamloader_invoked_with_normalized_dictionary(self):
        """Each resource type's normalized tables are passed to streamloader as one batch."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        fhir_client = MagicMock()
        fhir_client.iter_resources.return_value = iter([
            {"resourceType": "Patient", "id": "p1"},
        ])
        db_pool = MagicMock()

        normalized = {
            "Patient": pd.DataFrame([{"id": "p1", "name": "Alice"}]),
            "codeableconcept": pd.DataFrame([{"id": "p1", "field_name": "x", "seq_no": 0}]),
        }

        with patch.object(CoreLoadProcessor, "get_fhir_structure", return_value={}), \
             patch.object(
                 CoreLoadProcessor, "get_processed_data",
                 return_value=(True, pd.DataFrame([{"id": "p1"}]), pd.DataFrame(), None),
             ), \
             patch.object(CoreLoadProcessor, "normalizer", return_value=normalized), \
             patch.object(CoreLoadProcessor, "get_deletion_attributes",
                          return_value={"Patient": {"patient": []}}), \
             patch.object(CoreLoadProcessor, "streamloader") as mock_streamloader:
            proc = CoreLoadProcessor(
                queue_client=None,
                storage_client=None,
                fhir_client=fhir_client,
                project_configurations=make_config(["Patient"]),
                db_connection_pool=db_pool,
            )
            proc.local_converter()

        # streamloader is invoked once per resource type, with the full normalized dict.
        assert mock_streamloader.call_count == 1
        call_args = mock_streamloader.call_args
        # streamloader signature: (filename, filepath_id, resource_data_dictionary, complex_dtypes, array_counts_df)
        passed_dict = call_args.args[2]
        assert "Patient" in passed_dict
        assert "codeableconcept" in passed_dict

    def test_skips_empty_resource_pulls(self):
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        fhir_client = MagicMock()
        fhir_client.iter_resources.return_value = iter([])  # zero resources
        db_pool = MagicMock()

        with patch.object(CoreLoadProcessor, "get_fhir_structure", return_value={}), \
             patch.object(CoreLoadProcessor, "get_processed_data") as mock_gpd, \
             patch.object(CoreLoadProcessor, "normalizer") as mock_norm, \
             patch.object(CoreLoadProcessor, "streamloader") as mock_streamloader:
            proc = CoreLoadProcessor(
                queue_client=None,
                storage_client=None,
                fhir_client=fhir_client,
                project_configurations=make_config(["Patient"]),
                db_connection_pool=db_pool,
            )
            proc.local_converter()

        # Empty pull: nothing downstream should run.
        mock_gpd.assert_not_called()
        mock_norm.assert_not_called()
        mock_streamloader.assert_not_called()

    def test_skips_when_all_rows_are_duplicates(self):
        """When get_processed_data reports process_data=False (all dedup hits), skip normalize+load."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        fhir_client = MagicMock()
        fhir_client.iter_resources.return_value = iter([
            {"resourceType": "Patient", "id": "p1"},
        ])
        db_pool = MagicMock()

        with patch.object(CoreLoadProcessor, "get_fhir_structure", return_value={}), \
             patch.object(
                 CoreLoadProcessor, "get_processed_data",
                 return_value=(False, pd.DataFrame(), pd.DataFrame(), None),
             ), \
             patch.object(CoreLoadProcessor, "normalizer") as mock_norm, \
             patch.object(CoreLoadProcessor, "streamloader") as mock_streamloader:
            proc = CoreLoadProcessor(
                queue_client=None,
                storage_client=None,
                fhir_client=fhir_client,
                project_configurations=make_config(["Patient"]),
                db_connection_pool=db_pool,
            )
            proc.local_converter()

        mock_norm.assert_not_called()
        mock_streamloader.assert_not_called()


class TestCoreLoadProcessorAzurePathRegression:
    def test_azure_path_processor_initializes_with_clients(self):
        """Regression guard: Azure-path init still works with non-None clients."""
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

        with patch.object(CoreLoadProcessor, "get_fhir_structure", return_value={}):
            proc = CoreLoadProcessor(
                queue_client=MagicMock(),
                storage_client=MagicMock(),
                fhir_client=MagicMock(),
                project_configurations=make_config(),
                db_connection_pool=MagicMock(),
            )
        assert proc.queue_client is not None
        assert proc.storage_client is not None
