
import ast
import configparser
import gc
import hashlib
import json
import logging
import math
import re
from datetime import date, datetime
from functools import lru_cache
from io import StringIO
from zoneinfo import ZoneInfo

import pandas as pd
from dateutil import parser as datetime_parser
from dateutil.parser import ParserError

from pyfiles.dependencies.data_processing_error import DataProcessingException
from pyfiles.dependencies.enum import PipelineErrorCode


class DFOps:
    def __init__(self):
        pass

    @staticmethod
    def dataframe_melt_and_explode(dataframe):
        """Function to melt and explode to have single JSON"""
        dataframe = (dataframe
                     .melt(
                            id_vars=["id"],
                            var_name="field_name",
                            value_name="json"
                        )
        )

        dataframe = (
            dataframe
            .dropna(subset=["json"])
            .reset_index(drop=True)
        )

        dataframe["field_name"] = dataframe["field_name"].apply(lambda x: x.lower() if isinstance(x, str) else x)

        dataframe["json"] = dataframe["json"].apply(lambda x:[x] if isinstance(x, dict) else x)
        dataframe = (
            dataframe
            .set_index(["id", "field_name"])
            .apply(lambda x: x.apply(pd.Series).stack())
            .reset_index()
        )

        DFOps.drop_column(dataframe, ["level_2"])
        return dataframe

    @staticmethod
    def dataframe_stack(dataframe):
        """Function to handle all arrays from parsed columns"""
        if not dataframe.empty:
            dataframe["index"] = range(len(dataframe))
            DFOps.drop_column(dataframe, ["json"])

            if ('assigner' in dataframe.columns) or ('type' in dataframe.columns):
                if 'assigner' in dataframe.columns:
                    dataframe['assigner'] = dataframe['assigner'].astype(str)
                else:
                    dataframe['assigner'] = "{}"
                if 'type' in dataframe.columns:
                    dataframe['type'] = dataframe['type'].astype(str)
                else:
                    dataframe['type'] = "{}"

                dataframe = (
                    dataframe
                    .set_index(["index", "id", "field_name", "assigner", "type"])
                    .apply(lambda x: x.apply(pd.Series).stack())
                    .reset_index()
                )

                dataframe['assigner'] = dataframe['assigner'].apply(lambda x: x.replace("{}", "None"))
                dataframe['type'] = dataframe['type'].apply(lambda x: x.replace("{}", "None"))

                dataframe['assigner'] = dataframe['assigner'].apply(lambda x: ast.literal_eval(x) if isinstance(x, str) and x != 'None' else x)
                dataframe['type'] = dataframe['type'].apply(lambda x: ast.literal_eval(x) if isinstance(x, str) and x != 'None' else x)

            elif 'identifier' in dataframe.columns:
                dataframe['identifier'] = dataframe['identifier'].astype(str)
                dataframe = (
                    dataframe
                    .set_index(["index", "id", "field_name", "identifier"])
                    .apply(lambda x: x.apply(pd.Series).stack())
                    .reset_index()
                )

                dataframe['identifier'] = dataframe['identifier'].apply(lambda x: x.replace("{}", "None"))
                dataframe['identifier'] = dataframe['identifier'].apply(lambda x: ast.literal_eval(x) if isinstance(x, str) and x != 'None' else x)
                # Handlers.rename_column(dataframe, "level_4", "seq_no")

            else:
                dataframe = (
                    dataframe
                    .set_index(["index", "id", "field_name"])
                    .apply(lambda x: x.apply(pd.Series).stack())
                    .reset_index()
                )

                # Handlers.rename_column(dataframe, "level_3", "seq_no")

            dataframe['seq_no'] = dataframe.groupby(['id', 'field_name']).cumcount()
            dataframe = dataframe.dropna(axis=1, how='all')
            dataframe = dataframe.where(pd.notnull(dataframe), None)
            dataframe = dataframe.where(pd.notna(dataframe), None)
            dataframe['record_id'] = (dataframe['id'] + '_' +
                            dataframe['field_name'] + '_' +
                            dataframe['seq_no'].astype(str))

            dataframe = dataframe.replace('None', None)
            return dataframe

        return pd.DataFrame()

    @staticmethod
    def handle_codeableconcept_extensions(extension_value, coding_extension):
        """Function to handle codeableconcept extensions - extensions are array of arrays"""
        if extension_value and coding_extension:
            return [sublist + [value] for sublist, value in zip(coding_extension, extension_value, strict=False)]
        if extension_value:
            return [extension_value]
        if coding_extension:
            return coding_extension
        return None

    @staticmethod
    def cleanup_codeableconcepts(row:pd.Series):
        """
        Handle codeableconcept datatype
        """
        system = []
        code = []
        version = []
        display = []
        userselected = []
        text = []
        extension = []
        if isinstance(row["json"], dict) and pd.notnull(row["json"]):
            total_records_count = len(row["json"].get("coding", []))
            if "coding" in row["json"]:
                for dictionary in row["json"]["coding"]:
                    system.append(dictionary.get("system", None))
                    code.append(dictionary.get("code", None))
                    display.append(dictionary.get("display", None))
                    userselected.append(dictionary.get("userSelected", None))
                    version.append(dictionary.get("version", None))
                    # array of arrays
                    extension.append(dictionary.get("extension", None))
                # array
                extension_value = row["json"].get("extension",None)
                coding_extension = None if all(x is None for x in extension) else extension
                extension = DFOps.handle_codeableconcept_extensions(extension_value, coding_extension)
            else:
                total_records_count = 1
                system.append(row["json"].get("system", None))
                code.append(row["json"].get("code", None))
                display.append(row["json"].get("display", None))
                userselected.append(row["json"].get("userSelected", None))
                version.append(row["json"].get("version", None))
                extension.append(row["json"].get("extension", None))
            text_value = row["json"].get("text", None)
            if text_value is not None:
                if isinstance(total_records_count, int):
                    text = [text_value] * total_records_count
                else:
                    text = [text_value]

        row["system"] = system
        row["code"] = code
        row["version"] = version
        row["display"] = display
        row["text"] = text
        row["userselected"] = userselected
        row["extension"] = extension
        return row


    @staticmethod
    def cleanup_references(row: pd.Series) -> pd.Series:
        """
        function to clean reference datatype
        """
        if isinstance(row["json"], dict) and pd.notnull(row["json"]):
            row["reference"] = row["json"].get("reference", None)
            row["display"] = row["json"].get("display", None)
            row["reference_type"] = row["json"].get("type", None)
            row["identifier"] = row["json"].get("identifier", None)
            row["extension"] = row["json"].get("extension", None)

        return row

    @staticmethod
    def cleanup_identifiers(row: pd.Series) -> pd.Series:
        """
        Handle identifier datatype
        """

        if isinstance(row["json"], dict) and pd.notnull(row["json"]):
            row["system"] = row["json"].get("system", None)
            row["value"] = row["json"].get("value", None)
            row["use"] = row["json"].get("use", None)
            row["type"] = row["json"].get("type", None)
            row["assigner"] = row["json"].get("assigner", None)
            row["period_start"] = row["json"].get("period", {}).get("start", None)
            row["period_end"] = row["json"].get("period", {}).get("end", None)
            row["extension"] = row["json"].get("extension",None)

        return row

    @staticmethod
    def process_codeableconcepts(dataframe: pd.DataFrame, fhir_resource, filepath_id):
        """
        codeableconcepts data processing function
        """
        logging.debug("(filepath_id=%s) -> Working on codeableconcepts fhir_resource=%s", filepath_id, fhir_resource)
        try:
            if dataframe.empty:
                logging.debug("(filepath_id=%s) -> Codeableconcept data not available for fhir_resource=%s", filepath_id, fhir_resource)
                return pd.DataFrame()

            dataframe = DFOps.dataframe_melt_and_explode(dataframe)

            dataframe = dataframe.apply(
                DFOps.cleanup_codeableconcepts, axis=1
            )

            dataframe = DFOps.dataframe_stack(dataframe)

            DFOps.drop_column(dataframe, ["level_3","index"])

            max_cc_dataframe = dataframe.groupby('id')['seq_no'].max().reset_index()

            max_cc_dataframe = max_cc_dataframe.rename(columns={'seq_no': 'codeableconcept_max_array_size'})

            logging.debug("(filepath_id=%s) -> Codeableconcepts processing complete for fhir_resource=%s", filepath_id, fhir_resource)
            return dataframe, max_cc_dataframe

        except Exception as ex:
            error_message = f"{fhir_resource} - {filepath_id} -> Codeableconcepts processing failed"
            raise DataProcessingException(error_message, str(ex), PipelineErrorCode.NORMALIZATION_FAILED.value) from ex

    @staticmethod
    def process_references(dataframe: pd.DataFrame, fhir_resource, filepath_id):
        """
        references data processing function
        """
        logging.debug("(filepath_id=%s) -> Working on references for fhir_resource=%s", filepath_id, fhir_resource)
        try:
            if dataframe.empty:
                logging.debug("(filepath_id=%s) -> References data not available for fhir_resource=%s", filepath_id, fhir_resource)
                return pd.DataFrame()

            dataframe = DFOps.dataframe_melt_and_explode(dataframe)

            dataframe = dataframe.apply(
                DFOps.cleanup_references, axis=1
            )

            dataframe = DFOps.dataframe_stack(dataframe)

            DFOps.rename_column(dataframe, 'reference_type', 'type')

            max_reference_dataframe = dataframe.groupby('id')['seq_no'].max().reset_index()

            max_reference_dataframe = max_reference_dataframe.rename(columns={'seq_no': 'reference_max_array_size'})

            logging.debug("(filepath_id=%s) -> References processing complete for fhir_resource=%s", filepath_id, fhir_resource)
            return dataframe, max_reference_dataframe

        except Exception as ex:
            error_message = f"{fhir_resource} - {filepath_id} -> References processing failed: {str(ex)}"
            raise DataProcessingException(error_message, str(ex), PipelineErrorCode.NORMALIZATION_FAILED.value) from ex

    @staticmethod
    def process_identifiers(dataframe: pd.DataFrame, fhir_resource, filepath_id):
        """
        identifiers data processing function
        """
        logging.debug("(filepath_id=%s) -> Working on identifiers for fhir_resource=%s", filepath_id, fhir_resource)
        try:
            if dataframe.empty:
                logging.debug("(filepath_id=%s) -> Identifiers data not available for fhir_resource=%s", filepath_id, fhir_resource)
                return pd.DataFrame()

            dataframe = DFOps.dataframe_melt_and_explode(dataframe)

            dataframe = dataframe.apply(
                DFOps.cleanup_identifiers, axis=1
            )

            dataframe = DFOps.dataframe_stack(dataframe)

            DFOps.drop_column(dataframe, ['level_5', 'index'])

            max_identifier_dataframe = dataframe.groupby('id')['seq_no'].max().reset_index()

            max_identifier_dataframe = max_identifier_dataframe.rename(columns={'seq_no': 'identifier_max_array_size'})

            logging.debug("(filepath_id=%s) -> Identifiers processing complete for fhir_resource=%s", filepath_id, fhir_resource)
            return dataframe, max_identifier_dataframe

        except Exception as ex:
            error_message = f"{fhir_resource} - {filepath_id} -> Identifiers processing failed: {str(ex)}"
            raise DataProcessingException(error_message, str(ex), PipelineErrorCode.NORMALIZATION_FAILED.value) from ex

    @staticmethod
    @lru_cache(maxsize=100)
    def _create_pandas_dataframe_cached(fhir_json_str: str):
        """
        Create dataframe from JSON string (hashable for cache).

        Args:
            fhir_json_str: FHIR resource JSON as string
        """
        fhir_json = json.loads(fhir_json_str)
        if isinstance(fhir_json, list):
            return pd.DataFrame(fhir_json)
        return pd.read_json(StringIO(fhir_json_str), lines=True)

    @staticmethod
    def create_pandas_dataframe(fhir_json):
        """
        Create dataframe from JSON.

        Args:
            fhir_json: FHIR resource JSON (dict, list, or string)
        """
        try:
            # Convert to string for caching if not already a string
            if isinstance(fhir_json, str):
                fhir_json_str = fhir_json
            else:
                fhir_json_str = json.dumps(fhir_json, sort_keys=True)

            return DFOps._create_pandas_dataframe_cached(fhir_json_str)
        except Exception as e:
            logging.exception("NDJSON to DataFrame conversion failed: %s", e)
            raise DataProcessingException("Ndjson to dataframe conversion failed", str(e), PipelineErrorCode.NORMALIZATION_FAILED.value) from e


    @staticmethod
    def hash_row(value):
        """
        Hash value on row

        Args:
            value: column value
        """
        # # Serialize row to JSON format to handle different data types consistently
        row_string = json.dumps(value, sort_keys=True)
        # Generate SHA-256 hash
        return hashlib.sha256(row_string.encode()).hexdigest()

    @staticmethod
    def rename_column(dataframe: pd.DataFrame, old_column_name, new_column_name):
        """Rename column if available"""
        if old_column_name in dataframe.columns:
            dataframe.rename(columns={old_column_name: new_column_name}, inplace=True)

    @staticmethod
    def drop_column(dataframe, column_list):
        """Drop column if available"""
        for column in column_list:
            if column in dataframe.columns:
                dataframe.drop(columns={column}, inplace=True)

    @staticmethod
    def concatenate_dataframes(parent_dataframe, dataframe_list):
        """Concatenate dataframes with parent dataframe if exist"""
        if dataframe_list is not None:
            existing_dataframes = [
                df for df in dataframe_list if isinstance(df, pd.DataFrame)
            ]
            if existing_dataframes:
                if parent_dataframe is None:
                    result = pd.concat(existing_dataframes, ignore_index=True)
                else:
                    result = pd.concat(
                        [parent_dataframe] + existing_dataframes, ignore_index=True
                    )
                # Clear the list after concatenation to free memory
                dataframe_list.clear()
                gc.collect()
                return result
        return parent_dataframe

    @staticmethod
    def process_dataframe(key, normalized_dataframe):
        config = configparser.ConfigParser()
        resource_config = f"../configurations/{key.lower()}.ini"
        config.read(resource_config)

        if not config.has_section("column_mappings"):
            records = [
                {
                    column_name: DFOps.serialize_field(value)
                    for column_name, value in row.items()
                }
                for _, row in normalized_dataframe.iterrows()
            ]
        else:
            records = [
                {
                    column_name: DFOps.serialize_field(
                        DFOps.fill_values(
                            value,
                            config.get("column_mappings", column_name, fallback=None),
                        )
                    )
                    for column_name, value in row.items()
                }
                for _, row in normalized_dataframe.iterrows()
            ]
        return pd.DataFrame.from_records(records)

    @staticmethod
    def serialize_field(value):
        # Check if value is a dictionary or a list of dictionaries
        if isinstance(value, dict) or (
            isinstance(value, list) and all(isinstance(item, dict) for item in value)
        ):
            return value  # Serialize dictionaries or list of dictionaries to JSON

        if isinstance(value, list):
            # Ensure that the list contains either sublists or None values
            if all(isinstance(sublist, list) or sublist is None for sublist in value):
                # Now ensure that each sublist contains dictionaries or None values
                if all(
                    sublist is None or all(isinstance(item, dict) for item in sublist)
                    for sublist in value
                    if sublist is not None
                ):
                    # Serialize list of lists of dictionaries or None
                    return [
                        (
                            [None if v is None else v for v in sublist]
                            if sublist is not None
                            else None
                        )
                        for sublist in value
                    ]

        # If it's a list but not a list of dictionaries (e.g., simple list), handle it as a JSON array
        if isinstance(value, list):
            # If the list contains None values, we can replace them with null
            return [None if v is None else v for v in value]
        return value

    @staticmethod
    def fill_values(data, data_type):
        """
        Function checks the data type and fills default values if needed
        """
        if data:
            if data_type == "ARRAY<INTEGER>":
                for _, array_value in enumerate(data):
                    data[_] = None if math.isnan(array_value) else int(array_value)
            elif data_type == "ARRAY<ARRAY<INTEGER>>":
                for outer, arrays in enumerate(data):
                    for inner, array_value in enumerate(arrays):
                        data[outer][inner] = (
                            None if math.isnan(array_value) else int(array_value)
                        )

        return data

    @staticmethod
    def extract_version_id(meta_str):
        try:
            meta_dict = ast.literal_eval(f"{meta_str}")
            if not isinstance(meta_dict, dict):
                return 0
            return int(meta_dict.get("versionId", 0))
        except (ValueError, SyntaxError, AttributeError, TypeError):
            return 0

    @staticmethod
    def extract_lastupdated(meta_str):
        try:
            meta_dict = ast.literal_eval(f"{meta_str}")
            if not isinstance(meta_dict, dict):
                return None
            return meta_dict.get("lastUpdated", None)
        except (ValueError, SyntaxError, AttributeError, TypeError):
            return None

    @staticmethod
    def extract_identifier_source(identifier_str, default_source):
        try:
            identifier_dict = ast.literal_eval(f"{identifier_str}")
            source = None

            if isinstance(identifier_dict, list):
                for element in identifier_dict:
                    if 'source' in element.get("system", '').lower():
                        source = element.get("value", None)
                        break

            if isinstance(identifier_dict, dict):
                if 'source' in identifier_dict.get("system", '').lower():
                    source = identifier_dict.get("value", None)

            if source:
                return source
            return default_source
        except (ValueError, SyntaxError):
            return None


    @staticmethod
    def get_table_data(ids_to_delete: list, field_names: list, deletion_counts):
        if field_names:
            data = [
                (id_to_delete, field, element)
                for id_to_delete in ids_to_delete
                for field in field_names
                for element in range(0, deletion_counts.get(id_to_delete, 0) + 1)
            ]
            data = pd.DataFrame(data, columns=["id", "field_name", "seq_no"])
            data["record_id"] = (
                data["id"] + "_" + data["field_name"] + "_" + data["seq_no"].astype(str)
            )
            data["__op"] = 1
            return data
        return pd.DataFrame()

    @staticmethod
    def string_to_bigint(text):

        """Generates an MD5 hash of a given string."""
        # create md5 hash for the input string/uuid (non-cryptographic: dedup ID only)
        md5_hash = hashlib.md5(usedforsecurity=False)
        md5_hash.update(text.encode('utf-8'))

        # converting all characters into big int
        hash_id = int(md5_hash.hexdigest()[:16], 16)
        return hash_id

    @staticmethod
    def parse_fhir_datetime_component(date_value, component: str):
        """
        Parse FHIR date/datetime values and return a specific component
        ('year', 'month', 'day', 'date', 'datetime', 'time').

        Args:
            date_value (Any): FHIR date value (string, datetime, date, NaT, etc.)
            component (str): Which part to extract ('year', 'month', 'day', 'date', 'datetime', 'time').

        Returns:
            int | str | date | datetime | None:
                - int if 'year', 'month', 'day'
                - date if 'date'
                - str if 'time' (HH:MM:SS)
                - datetime if 'datetime'
                - None if invalid or missing
        """

        # --- Validate component ---
        component = component.lower()
        valid_components = {"year", "month", "day", "date", "datetime", "time"}
        if component not in valid_components:
            raise ValueError(f"component must be one of: {valid_components}")

        # --- Handle missing or NaN values ---
        if pd.isna(date_value):
            return None

        # --- Handle datetime or date objects directly ---
        if isinstance(date_value, datetime):
            dt = date_value
        elif isinstance(date_value, date):
            dt = datetime(date_value.year, date_value.month, date_value.day)

        # --- Parse string inputs ---
        else:
            date_str = str(date_value).strip()

            # Skip placeholder date
            if "0001-01-01" in date_str:
                return None

            try:
                # Year only (e.g., "2021")
                if re.fullmatch(r"\d{4}", date_str):
                    dt = datetime(int(date_str), 1, 1)

                # Year-month or month-year
                elif re.fullmatch(r"\d{4}[-/]\d{1,2}", date_str) or re.fullmatch(r"\d{1,2}[-/]\d{4}", date_str):
                    parts = re.split(r"[-/]", date_str)
                    if len(parts[0]) == 4:  # YYYY-MM
                        year, month = int(parts[0]), int(parts[1])
                    else:  # MM-YYYY
                        month, year = int(parts[0]), int(parts[1])
                    dt = datetime(year, month, 1)

                # Full date (YYYY-MM-DD or YYYY/MM/DD)
                elif re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", date_str):
                    year, month, day = map(int, re.split(r"[-/]", date_str))
                    dt = datetime(year, month, day)

                # ISO datetime (e.g., "2021-06-10T12:34:56Z")
                elif re.match(r"\d{4}-\d{2}-\d{2}T", date_str):
                    try:
                        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        if dt.tzinfo is not None:
                            dt = dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
                    except (ValueError, TypeError, OverflowError):
                        dt = datetime_parser.parse(date_str)

                # Fallback: dateutil.parser
                else:
                    dt = datetime_parser.parse(date_str)

            except (ValueError, TypeError, OverflowError, ParserError):
                return None

        # --- Return requested component ---
        if component == "datetime":
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        elif component == "date":
            return dt.date().isoformat()
        elif component == "time":
            return dt.strftime('%H:%M:%S')
        elif component == "year":
            return dt.year
        elif component == "month":
            return dt.month
        elif component == "day":
            return dt.day

    @staticmethod
    def extract_extension_values(data, urls, coding_paths):
        """
        Recursively extracts values from FHIR extensions matching given URLs and paths.

        Accepts either:
        • a FHIR resource dict with an "extension" field, or
        • a list of extension dicts directly.

        Args:
            data (dict | list): FHIR resource or list of extensions.
            urls (list[str]): Extension URLs to match.
            coding_paths (list[str]): Dot-separated paths to extract values from (e.g. 'valueCoding').

        Returns:
            list[dict]: List of {"url": <matched_url>, "value": <extracted_value>} dictionaries.
        """

        # results = []

        def traverse_path(obj, path):
            keys = path.split(".")
            for key in keys:
                if isinstance(obj, list):
                    temp = []
                    for item in obj:
                        if isinstance(item, dict) and key in item:
                            temp.append(item[key])
                    obj = temp
                    if not obj:
                        return None
                    if len(obj) == 1:
                        obj = obj[0]
                elif isinstance(obj, dict):
                    obj = obj.get(key)
                    if obj is None:
                        return None
                else:
                    return None
            return obj

        def recurse(ext_list):
            for ext in ext_list:
                ext_url = ext.get("url")
                # Only proceed if url exists
                if not ext_url:
                    continue

                # If url matches, check value paths
                if ext_url in urls:
                    for path in coding_paths:
                        val = traverse_path(ext, path)
                        if val is not None:
                            return {"url": ext_url, "value": val}

        # Start recursion
        if isinstance(data, dict):
            result = recurse(data.get("extension", []))
        elif isinstance(data, list):
            result = recurse(data)
        else:
            result = {}

        display_value = None
        if result:
            if isinstance(result.get('value'), list):
                display_value = result.get('value', [])[0].get('display', None)
            else:
                display_value = result.get('value', {}).get('display', None)

        return display_value

    @staticmethod
    def extract_fhir_references(ref_data, resource_type):
        """
        Extracts references of a specific FHIR resource type from a list or single reference.

        Args:
            ref_data (dict or list): Single reference dict or list of reference dicts.
            resource_type (str): FHIR resource type to filter (e.g., 'Patient', 'Practitioner').

        Returns:
            list: List of reference IDs matching the resource type.
        """
        if not ref_data:
            return None

        # Ensure we have a list to iterate over
        if isinstance(ref_data, dict):
            ref_list = [ref_data]
        elif isinstance(ref_data, list):
            ref_list = ref_data
        else:
            # Unknown type
            return []

        results = []
        for ref in ref_list:
            ref_str = ref.get("reference")
            if ref_str and f'{resource_type}' in ref_str:
                # Extract just the ID part
                ref_id = ref_str.split("/")[1]
                results.append(ref_id)

        if results:
            return DFOps.string_to_bigint(results[0])
        return None

    @staticmethod
    def extract_fhir_addresses(addr_data):
        """
        Extracts key components from a FHIR Address resource.
        If input is a list, only the first element is considered.
        'line' array is mapped to address_1 and address_2.
        """
        if not addr_data:
            return {}

        # Take the first element if it's a list
        if isinstance(addr_data, list):
            address = addr_data[0] if addr_data else {}
        elif isinstance(addr_data, dict):
            address = addr_data
        else:
            return {}

        lines = address.get("line", [])
        # Note: each ternary expression is parenthesized explicitly so that ``+`` binds
        # to the ternary results rather than to the ``else`` branches. The unparenthesized
        # form (``a if x else "" + b if y else "" + c``) parses as a chained ternary and
        # silently drops line[1] / postalCode from the hash key.
        location_key = (
            (lines[0] if len(lines) > 0 else "")
            + (lines[1] if len(lines) > 1 else "")
            + address.get("postalCode", "")
        )
        return {
            "location_id": DFOps.string_to_bigint(location_key),
            "use": address.get("use", ""),
            "type": address.get("type", ""),
            "text": address.get("text", ""),
            "address_1": lines[0] if len(lines) > 0 else "",
            "address_2": lines[1] if len(lines) > 1 else "",
            "city": address.get("city", ""),
            "district": address.get("district", ""),
            "state": address.get("state", ""),
            "postalcode": address.get("postalCode", ""),
            "country": address.get("country", "")
        }

    @staticmethod
    def extract_fhir_backboneelement(data, attribute_filter):
        """
        Extracts and transforms data from a FHIR BackboneElement structure based on a provided filter.

        This function is designed to handle nested FHIR elements (BackboneElements),
        such as components, performers, or sub-elements within a resource. It retrieves
        a child attribute, optionally processes it depending on its FHIR data type
        (e.g., Reference, CodeableConcept), and returns the extracted value.

        Parameters
        ----------
        data : dict or list
            The FHIR BackboneElement data (can be a dictionary or a list of dictionaries).
            If it is a list, only the first element is used (assumed to be the latest or most relevant).
        attribute_filter : dict
            A dictionary describing which child attribute to extract and how to interpret it.
            Expected keys include:
                - "child": str
                    The key of the child attribute to extract.
                - "fhir_datatype": str
                    The datatype of the child (e.g., "Reference", "CodeableConcept").
                - "reference_filter": dict, optional
                    If the datatype is "Reference", provides the resource type filter.

        Returns
        -------
        Any
            The extracted value based on the specified filter. This may be:
            - A reference ID (if "Reference" type)
            - A display string (if "CodeableConcept" type)
            - `None` if the expected value cannot be extracted.
        """
        fhir_child_attribute = attribute_filter.get("child")
        if isinstance(data, list):
            data = data[0]
        data = data.get(fhir_child_attribute, {})

        if attribute_filter.get("fhir_datatype") == 'Reference':
            resource_type = attribute_filter.get("reference_filter", {}).get("resource")
            return DFOps.extract_fhir_references(data, resource_type)

        if attribute_filter.get("fhir_datatype") == 'CodeableConcept':
            return DFOps.extract_fhir_codeableconcepts(data)

        if attribute_filter.get("fhir_datatype") == "SimpleQuantity":
            return DFOps.extract_fhir_valuequantity(data)

    @staticmethod
    def extract_fhir_annotations(ref_data):
        """
        Extracts the 'text' (and optionally metadata) from FHIR Annotation resources.

        Args:
            ref_data (dict | list): FHIR Annotation or list of Annotations.

        Returns:
            str | None:
                - The first annotation's text (FHIR Annotation.text)
                - None if no valid annotation found
        """

        if not ref_data:
            return None

        ref_list = [ref_data] if isinstance(ref_data, dict) else ref_data if isinstance(ref_data, list) else []

        if not ref_list:
            return None

        for ref in ref_list:
            if not isinstance(ref, dict):
                continue

            text = ref.get("text")
            if text:
                return text

        return None

    @staticmethod
    def extract_fhir_humannames(humanname_data):
        """
        Extract key components from a FHIR HumanName resource.
        If input is a list, only the first element is considered.

        Adds a 'full_name' field constructed from prefix, given, family, and suffix.
        """

        name = humanname_data[0] if isinstance(humanname_data, list) else humanname_data

        use = name.get("use", "")
        text = name.get("text", "")
        family = name.get("family", "")
        given_list = name.get("given", [])
        prefix_list = name.get("prefix", [])
        suffix_list = name.get("suffix", [])
        period = name.get("period", "")

        given = given_list[0] if given_list else ""
        prefix = prefix_list[0] if prefix_list else ""
        suffix = suffix_list[0] if suffix_list else ""

        full_name_parts = [prefix, *given_list, family, suffix]
        full_name = " ".join([p for p in full_name_parts if p]).strip()

        return {
            "use": use,
            "text": text,
            "family": family,
            "given": given,
            "prefix": prefix,
            "suffix": suffix,
            "period": period,
            "full_name": full_name
        }

    @staticmethod
    def extract_fhir_identifiers(identifiers, system):
        """
        Extract the value of a FHIR Identifier matching the given system URL.

        Args:
            identifiers (dict | list): FHIR Identifier(s)
            system (str): The system URL to match

        Returns:
            str | None: The value of the first matching identifier, or None if not found
        """

        if isinstance(identifiers, dict):
            identifiers = [identifiers]
        elif not isinstance(identifiers, list):
            return None

        for ident in identifiers:
            if not isinstance(ident, dict):
                continue
            if ident.get("system") == system:
                return ident.get("value")

        return None

    @staticmethod
    def extract_fhir_coding(data):
        """
        Extracts the 'display' value from a FHIR Coding element.

        This method handles cases where the input `data` may be a list of codings by
        taking the first element as the primary coding. If 'display' is missing, it returns None.

        Parameters
        ----------
        data : dict or list of dict
            A FHIR Coding element or a list of Coding elements.

        Returns
        -------
        str or None
            The 'display' value of the coding, or None if not present.
        """
        if isinstance(data, list):
            data = data[0]

        return data.get('display', None)

    @staticmethod
    def extract_fhir_codeableconcepts(data):
        """
        Extracts the display value from the first coding in a FHIR CodeableConcept element.

        A CodeableConcept may contain multiple codings. This method selects the first coding
        and retrieves its 'display' value using `extract_fhir_coding`.

        Parameters
        ----------
        data : dict or list of dict
            A FHIR CodeableConcept element or a list containing one.

        Returns
        -------
        str or None
            The display value of the first coding, or None if no codings are present.
        """
        if isinstance(data, list):
            data = data[0]

        codings = data.get('coding', [])
        if codings:
            return DFOps.extract_fhir_coding(codings)

    @staticmethod
    def extract_fhir_valuequantity(data):

        if isinstance(data, list):
            data = data[0]

        if data:
            return data.get('value')
