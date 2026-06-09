import gc
import json
import logging
import re
from datetime import datetime

import pandas as pd
from dateutil import parser as datetime_parser
from sqlalchemy import bindparam, text

from pyfiles.dependencies.data_processing_error import DataProcessingException
from pyfiles.dependencies.df_ops import DFOps
from pyfiles.dependencies.enum import PipelineErrorCode
from pyfiles.dependencies.handlers import Handlers

# FHIR R4 resource type names are PascalCase identifiers; we lowercase them and
# use the result as a backticked table name in interpolated SQL. Allowlist the
# accepted shape so a malformed resource type (defensive depth — values come
# from an internal enum today, but the validation prevents future foot-guns).
_RESOURCE_TYPE_RE = re.compile(r'^[a-z][a-z0-9_]*$')


class DBOps:
    def __init__(self):
        pass

    @staticmethod
    def filter_data_to_be_processed(db_connection_pool,
                                        fhir_resource_type: str,
                                        fhir_data_df,
                                        application_name,
                                        default_source,
                                        blob_url,
                                        filepath_id=None):
        """
        Function to filter fhir ids and data that need not be processed
        """
        db_connection = None
        intermediate_dfs = []  # Track intermediate DataFrames for cleanup
        logging.debug('(filepath_id=%s) Fetching meta version ids from DB', filepath_id)
        try:
            db_connection = db_connection_pool.create_connection()
            fhir_data_copy = pd.DataFrame()
            intermediate_dfs.append(fhir_data_copy)

            """
            we are looking into to identifier to fetch the source of data
            """
            if 'identifier' not in fhir_data_df.columns:
                fhir_data_copy = fhir_data_df[["id", "meta"]]
                fhir_data_copy = fhir_data_copy.assign(meta_source=default_source)
            else:
                fhir_data_copy = fhir_data_df[["id", "meta", "identifier"]]
                fhir_data_copy["meta_source"] = fhir_data_copy["identifier"].apply(
                        lambda x: DFOps.extract_identifier_source(x, default_source)
                )

            fhir_data_copy["meta_versionid"] = fhir_data_copy["meta"].apply(
                    DFOps.extract_version_id
            )

            fhir_data_copy["meta_lastupdated"] = fhir_data_copy["meta"].apply(
                    DFOps.extract_lastupdated
            )

            if filepath_id:
                fhir_data_copy = fhir_data_copy.assign(filepath_id=filepath_id)
            elif 'event-load' in blob_url:
                fhir_data_copy['filepath_id'] = fhir_data_copy.apply(
                    lambda row: Handlers.generate_event_filepath_id(
                        row['id'], row['meta_versionid']),
                    axis=1
                )
            else:
                fhir_data_copy = fhir_data_copy.assign(
                    filepath_id=Handlers.generate_batch_filepath_id(blob_url)
                )


            fhir_data_copy = fhir_data_copy.assign(resource_type=fhir_resource_type)

            fhir_data_copy = fhir_data_copy.assign(pipeline_type=application_name)

            DFOps.drop_column(fhir_data_copy, ["meta", "identifier"])

            to_be_processed_meta_data = pd.DataFrame()
            audit_data = pd.DataFrame()
            db_data = []

            is_event_load = 'event-load' in blob_url

            # Event load with version 1 → always new, skip DB entirely
            if is_event_load and fhir_data_copy["meta_versionid"].iloc[0] == 1:
                audit_data = fhir_data_copy.assign(operation='new')
                audit_data = audit_data[['id', 'operation', 'meta_versionid', 'meta_lastupdated', 'resource_type', 'filepath_id', 'pipeline_type']]
                DFOps.rename_column(audit_data, 'id', 'resource_id')
                audit_data_json = json.loads(audit_data.to_json(orient="records"))
                audit_data_json = Handlers.convert_empty_strings_to_null(audit_data_json)
                return True, fhir_data_df, to_be_processed_meta_data, audit_data_json

            # All other cases require DB check
            fhir_ids_list = fhir_data_copy["id"].tolist()

            # Allowlist the table-name fragment before interpolating into SQL.
            # ``id`` values are bound via :fhir_ids; resource_type cannot be bound
            # because SQLAlchemy parameters don't substitute for identifiers.
            resource_table = fhir_resource_type.lower()
            if not _RESOURCE_TYPE_RE.match(resource_table):
                raise ValueError(
                    f"Invalid FHIR resource type for SQL table name: {fhir_resource_type!r}"
                )
            meta_version_query = text(
                f"""SELECT id, meta_versionid as meta_versionid_db,
                codeableconcept_max_array_size as codeableconcept_max_array_size_db,
                identifier_max_array_size as identifier_max_array_size_db,
                reference_max_array_size as reference_max_array_size_db
                FROM `{resource_table}` WHERE id IN :fhir_ids"""
            ).bindparams(bindparam('fhir_ids', expanding=True))

            result = db_connection.execute(meta_version_query, {"fhir_ids": fhir_ids_list})
            db_data = result.fetchall()

            if is_event_load:
                # Event load, version > 1 → always update, DB needed for max_array_size columns
                if db_data:
                    db_data_df = pd.DataFrame(db_data)
                    merged_df = pd.merge(fhir_data_copy, db_data_df, on="id", how="left")
                    merged_df["meta_versionid_db"] = merged_df["meta_versionid_db"].fillna(0).astype(int)
                else:
                    # merged_df = fhir_data_copy.copy()
                    # When version id> 1 but is still a fresh load
                    audit_data = fhir_data_copy.assign(operation='new')
                    audit_data = audit_data[['id', 'operation', 'meta_versionid', 'meta_lastupdated', 'resource_type', 'filepath_id', 'pipeline_type']]
                    DFOps.rename_column(audit_data, 'id', 'resource_id')
                    audit_data_json = json.loads(audit_data.to_json(orient="records"))
                    audit_data_json = Handlers.convert_empty_strings_to_null(audit_data_json)
                    return True, fhir_data_df, to_be_processed_meta_data, audit_data_json

                merged_df['operation'] = merged_df.apply(
                    lambda row: 'new' if row['meta_versionid_db'] == 0
                                else ('duplicate' if row['meta_versionid_db'] >= row['meta_versionid']
                                      else 'update'),
                    axis=1
                )

                """This dataframe will be used to get array counts for
                codeableconcept, reference and identifier"""
                to_be_processed_meta_data = merged_df.copy()
                DFOps.drop_column(to_be_processed_meta_data, ["meta_versionid_db", "meta_versionid"])

                audit_data = merged_df[['id', 'operation', 'meta_versionid', 'meta_lastupdated', 'resource_type', 'filepath_id', 'pipeline_type']]
                DFOps.rename_column(audit_data, 'id', 'resource_id')
                audit_data_json = json.loads(audit_data.to_json(orient="records"))
                audit_data_json = Handlers.convert_empty_strings_to_null(audit_data_json)
                return False, fhir_data_df, to_be_processed_meta_data, audit_data_json

            # Batch load → new / update / duplicate
            if db_data:
                db_data_df = pd.DataFrame(db_data)
                merged_df = pd.merge(fhir_data_copy, db_data_df, on="id", how="left")
                merged_df["meta_versionid_db"] = merged_df["meta_versionid_db"].fillna(0).astype(int)
                merged_df['operation'] = merged_df.apply(
                    lambda row: 'new' if row['meta_versionid_db'] == 0
                                else ('duplicate' if row['meta_versionid_db'] >= row['meta_versionid']
                                      else 'update'),
                    axis=1
                )
            else:
                # No records found in DB → all new
                merged_df = fhir_data_copy.copy()
                merged_df['operation'] = 'new'

            """This dataframe will be used to get array counts for
            codeableconcept, reference and identifier"""
            to_be_processed_meta_data = merged_df[merged_df["operation"] == 'update'].copy()
            DFOps.drop_column(to_be_processed_meta_data, ["meta_versionid_db", "meta_versionid"])

            to_be_processed_resources = fhir_data_df[
                fhir_data_df['id'].isin(
                    merged_df.loc[merged_df['operation'] != 'duplicate', 'id']
                )
            ]

            audit_data = merged_df[['id', 'operation', 'meta_versionid', 'meta_lastupdated', 'resource_type', 'filepath_id', 'pipeline_type']]
            DFOps.rename_column(audit_data, 'id', 'resource_id')
            audit_data_json = json.loads(audit_data.to_json(orient="records"))
            audit_data_json = Handlers.convert_empty_strings_to_null(audit_data_json)

            if to_be_processed_resources.empty:
                return False, to_be_processed_resources, to_be_processed_meta_data, audit_data_json

            return True, to_be_processed_resources, to_be_processed_meta_data, audit_data_json

        except Exception as e:
            logging.exception("(filepath_id=%s) Error fetching meta version id", filepath_id)
            raise DataProcessingException(
                f"Error fetching meta_versionid: {e}",
                e,
                PipelineErrorCode.NORMALIZATION_FAILED.value
            ) from e
        finally:
            if db_connection:
                db_connection.close()

            # Cleanup intermediate DataFrames to free memory
            for df in intermediate_dfs:
                try:
                    del df
                except Exception:
                    pass
            intermediate_dfs.clear()
            gc.collect()

    @staticmethod
    def fetch_resource_list(db_connection):
        """
        Function to fetch the resource list from database
        """
        try:
            db_data = DBOps.fetch_data(
                "pipeline_meta_info", "property", "resource_list", db_connection
            )
            resource_list = db_data.get("description", None)
            resource_list = resource_list.split(",") if resource_list else []
            return resource_list
        except Exception:
            logging.exception(
                "Failed to fetch resource list from pipeline_meta_info table"
            )
            raise

    @staticmethod
    def fetch_data(table_name, column_name, search_value, database_connection):
        """
        Function to fetch data based on three parameters
        """
        try:
            schema_history_select = text(
                f"SELECT * FROM `{table_name}` WHERE `{column_name}` = :val"
            )
            result = database_connection.execute(schema_history_select, {"val": search_value})
            db_data = result.mappings().fetchone()
            return db_data if db_data else {}
        except Exception:
            logging.exception("Failed to fetch data from database")
            raise

    @staticmethod
    def get_last_export_time(db_connection, configurations) -> datetime:
        """
        function to fetch last sync date time
        """
        try:
            last_sync_date_sql = "SELECT MAX(till_date_time) FROM fhir_export_logger"
            result = db_connection.execute(text(last_sync_date_sql))
            max_sync_date = result.fetchone()[0]

            if not max_sync_date:
                logging.info("First sync: no previous export time found, using start_date from config")
                max_sync_date = datetime_parser.parse(
                    configurations["fhir_exporter"]["start_date"]
                )
            return max_sync_date
        except Exception:
            logging.exception(
                "Failed to fetch last export time from fhir_export_logger. SQL: %s",
                "SELECT MAX(till_date_time) FROM fhir_export_logger",
            )
            raise

    @staticmethod
    def insert_to_fhir_export_logger(db_connection, last_export_time, next_export_time):
        """
        Function to insert last sync time to database
        """
        try:
            insert_statement = text(
                "INSERT INTO fhir_export_logger (since_date_time, till_date_time) VALUES (:since, :till)"
            )
            db_connection.execute(insert_statement, {"since": str(last_export_time), "till": str(next_export_time)})
            logging.debug("Writing data to fhir_export_logger: since=%s, till=%s", last_export_time, next_export_time)
            db_connection.commit()
        except Exception:
            logging.exception(
                "Failed to insert data into db for data insertion %s, %s",
                next_export_time,
                last_export_time,
            )
            raise
