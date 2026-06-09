
import json
import logging
from datetime import datetime

import pandas as pd

from pyfiles.dependencies.data_processing_error import DataProcessingException
from pyfiles.dependencies.df_ops import DFOps
from pyfiles.dependencies.enum import PipelineErrorCode


def _engine_url(configurations, api_path_key=None):
    """Build a URL against the engine's HTTP API using a configurable scheme.

    The scheme defaults to ``http`` for backwards compatibility with the existing
    deployment, but can be flipped via ``[silver_layer] scheme = https`` in
    config.ini (or the ``ENGINE_HTTP_SCHEME`` env var) without source edits.

    Works against a ``configparser.ConfigParser`` (production) or a plain dict
    (unit tests). The previous ``configurations.get("silver_layer", {}).get(...)``
    pattern was broken for ConfigParser because its ``.get(section, option)``
    expects ``option`` as a string, not a fallback dict.
    """
    silver = configurations["silver_layer"] if "silver_layer" in configurations else {}
    scheme = silver.get("scheme", "http") if hasattr(silver, "get") else "http"
    base = f"{scheme}://{configurations['silver_layer']['http_server']}"
    if api_path_key is not None:
        return base + configurations["transaction_api"][api_path_key]
    return base


class TransactionManager:
    def __init__(self):
        pass

    @staticmethod
    def begin_transaction(configurations, table_name, id_to_delete, transaction_label, http_session):
        logging.debug("%s - %s -> Preparing transaction", id_to_delete, table_name)
        # Start the transaction
        begin_url = _engine_url(configurations, "begin_url")
        response = http_session.post(
            begin_url,
            headers={
                "db": configurations["silver_layer"]["core_database"],
                "table": table_name,
                "label": transaction_label,
                "Expect": "100-continue",
            },
            timeout=(10, 30),
        )
        response_data = response.json()

        if response_data["Status"] != "OK":
            raise DataProcessingException(
                f"Beginning transaction failed: {response_data['Message']}",
                response_data["Message"],
                PipelineErrorCode.INSERTION_FAILED.value
            )

        return response_data["TxnId"]

    @staticmethod
    def transaction(
        configurations,
        transaction_flag: str,
        table_name,
        filename: str,
        transaction_id: None,
        data_to_insert,
        transaction_label,
        first_level_complex_datatypes,
        database,
        http_session
    ):

        try:
            if table_name == "audit_table":
                result = data_to_insert
            else:
                id_to_delete = []

                if "_" in filename or "utilitiesdata" in filename:
                    id_to_delete = list(set(data_to_insert["id"]))

                data_to_delete = pd.DataFrame()
                if first_level_complex_datatypes:
                    deletion_counts = {}

                    if (
                        table_name == "identifier"
                        and "identifier_max_array_size_db" in data_to_insert
                    ):
                        deletion_counts_df = data_to_insert[
                            ["id", "identifier_max_array_size_db"]
                        ]
                        deletion_counts = deletion_counts_df.set_index("id")[
                            "identifier_max_array_size_db"
                        ].to_dict()

                    elif (
                        table_name == "reference"
                        and "reference_max_array_size_db" in data_to_insert
                    ):
                        deletion_counts_df = data_to_insert[
                            ["id", "reference_max_array_size_db"]
                        ]
                        deletion_counts = deletion_counts_df.set_index("id")[
                            "reference_max_array_size_db"
                        ].to_dict()

                    elif (
                        table_name == "codeableconcept"
                        and "codeableconcept_max_array_size_db" in data_to_insert
                    ):
                        deletion_counts_df = data_to_insert[
                            ["id", "codeableconcept_max_array_size_db"]
                        ]
                        deletion_counts = deletion_counts_df.set_index("id")[
                            "codeableconcept_max_array_size_db"
                        ].to_dict()

                    data_to_delete = DFOps.get_table_data(
                        id_to_delete,
                        first_level_complex_datatypes.get(table_name, None),
                        deletion_counts,
                    )

                if not data_to_insert.empty:
                    # 0 for upsert
                    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    data_to_insert["updated_date"] = current_date
                    data_to_insert["__op"] = 0

                    result = pd.concat([data_to_delete, data_to_insert], ignore_index=True)
                else:
                    result = data_to_delete

                if result.empty:
                    return True

            json_data = result.to_json(orient="records")

            # Perform load operation
            if transaction_flag == "True":
                load_url = _engine_url(configurations, "load_url")
                headers = {
                    "db": database,
                    "table": table_name,
                    "txn_id": str(transaction_id),
                    "label": f"{transaction_label}",
                    "format": "json",
                    "Expect": "100-continue",
                    "strip_outer_array": "true",
                }

            else:
                load_url = (
                    _engine_url(configurations, "stream_load_url")
                    .replace("table_name", table_name)
                    .replace("silver_layer_database", database)
                )

                headers = {
                    "label": f"{transaction_label}",
                    "format": "json",
                    "Expect": "100-continue",
                    "strip_outer_array": "true",
                }

            # StarRocks FE redirects /_stream_load to a CN/BE on a different port.
            # requests/urllib3 strips Authorization across cross-port redirects
            # (RFC-recommended security behavior), so disable auto-redirect and
            # replay manually through the session — session.auth is reapplied on
            # each request. Equivalent to curl's --location-trusted.
            load_response = http_session.put(
                load_url,
                data=json_data,
                headers=headers,
                timeout=(10, 30),
                allow_redirects=False,
            )
            for _ in range(3):
                if load_response.status_code not in (307, 308):
                    break
                redirect_url = load_response.headers.get("Location")
                if not redirect_url:
                    break
                load_response = http_session.put(
                    redirect_url,
                    data=json_data,
                    headers=headers,
                    timeout=(10, 30),
                    allow_redirects=False,
                )
            response_data = load_response.json()

            if (response_data["Status"] != "OK") and (
                response_data["Status"] != "Success"
            ):
                logging.error("Status check failed: %s", response_data["Status"])
                raise DataProcessingException(
                    f"{response_data['Message']}",
                    response_data,
                    PipelineErrorCode.INSERTION_FAILED.value
                )

            return True

        except DataProcessingException as dpe:
            raise DataProcessingException("Preparing transaction failed", dpe.errors, PipelineErrorCode.INSERTION_FAILED.value) from dpe

        except Exception as e:
            raise DataProcessingException(
                        "Transaction failed",
                        e,
                        PipelineErrorCode.INSERTION_FAILED.value
                    ) from e

    @staticmethod
    def prepare_transaction(
        configurations, table_name, transaction_id, transaction_label, http_session
    ):
        # Prepare the transaction
        prepare_url = _engine_url(configurations, "prepare_url")

        prepare_response = http_session.post(
            prepare_url,
            headers={
                "db": configurations["silver_layer"]["core_database"],
                "table": table_name,
                "txn_id": str(transaction_id),
                "label": transaction_label,
                "Expect": "100-continue",
            },
            timeout=300,
        )
        response_data = prepare_response.json()

        if response_data["Status"] != "OK":
            raise DataProcessingException(
                f"{response_data['Message']}",
                response_data["Message"],
                PipelineErrorCode.INSERTION_FAILED.value
            )
        return True, transaction_label, table_name, "Prepared"

    @staticmethod
    def commit_transaction(configurations, transaction_label, table_name, id_to_delete, filepath_id, http_session):
        # Commit the transaction
        commit_url = _engine_url(configurations, "commit_url")

        commit_response = http_session.post(
            commit_url,
            headers={
                "db": configurations["silver_layer"]["core_database"],
                "table": table_name,
                "label": transaction_label,
                "Expect": "100-continue",
            },
            timeout=300,
        )
        response_data = commit_response.text
        response_data = json.loads(response_data)

        if response_data["Status"] == "FAILED":
            raise DataProcessingException(
                f"Transaction commit failed: {response_data['Message']}",
                response_data["Message"],
                PipelineErrorCode.INSERTION_FAILED.value
            )

        logging.info("%s (file=%s) -> Transaction committed", table_name, id_to_delete)
        return True

    @staticmethod
    def rollback_transaction(
        configurations, transaction_label, table_name, id_to_delete, filepath_id, http_session
    ):
        # Rollback the transaction
        rollback_url = _engine_url(configurations, "rollback_url")

        rollback_response = http_session.post(
            rollback_url,
            headers={
                "db": configurations["silver_layer"]["core_database"],
                "table": table_name,
                "label": transaction_label,
                "Expect": "100-continue",
            },
            timeout=300,
        )

        response_data = rollback_response.json()
        if response_data["Status"] != "OK":
            raise DataProcessingException(
                f"Rollback failed: {response_data['Message']}",
                response_data["Message"],
                PipelineErrorCode.INSERTION_FAILED.value
            )

        logging.info("%s (file=%s) -> Rollback completed", table_name, id_to_delete)
        return True

    @staticmethod
    def transaction_block(
        configurations, table_name, filename, data, complex_datatypes, database, filepath_id, http_session
    ):
        logging.debug(
            "(filepath_id=%s) -> Beginning insert transaction block for table_name=%s", filepath_id, table_name
        )
        timestamp = datetime.now().strftime("%Y%m%dT%H%M%S") + str(
            int(datetime.now().microsecond / 1000)
        ).zfill(3)
        if "-" in filename:
            filename = filename.replace("-", "_")
            filename = filename.replace(".ndjson", "")
        transaction_label = f"{table_name}_{filename}_{timestamp}"

        transaction_id = None
        if configurations["silver_layer"]["is_transaction"] == "True":

            try:
                transaction_id = TransactionManager.begin_transaction(
                    configurations, table_name, filename, transaction_label, http_session
                )

            except DataProcessingException as dpe:
                raise DataProcessingException(str(dpe), dpe.errors, PipelineErrorCode.INSERTION_FAILED.value) from dpe

            except Exception as e:
                raise DataProcessingException(
                    "Beginning Transaction failed", str(e), PipelineErrorCode.INSERTION_FAILED.value
                ) from e

            logging.info(
                "%s - %s -> Beginning insert transaction block successful",
                filename,
                table_name,
            )
            logging.debug(
                "%s - %s -> Getting ready to pre-commit insert records",
                filename,
                table_name,
            )

        try:
            is_insert = TransactionManager.transaction(
                configurations=configurations,
                transaction_flag=configurations["silver_layer"]["is_transaction"],
                table_name=table_name,
                filename=filename,
                transaction_id=transaction_id,
                data_to_insert=data,
                transaction_label=transaction_label,
                first_level_complex_datatypes=complex_datatypes,
                database=database,
                http_session=http_session
            )

            if configurations["silver_layer"]["is_transaction"] != "True":
                if is_insert:
                    logging.info(
                        "(filepath_id=%s) -> Transaction complete for table_name=%s", filepath_id, table_name
                    )
                    return True, None, None

        except DataProcessingException as dpe:
            raise DataProcessingException(str(dpe), dpe.errors, PipelineErrorCode.INSERTION_FAILED.value) from dpe

        except Exception as e:
            raise DataProcessingException(
                "Transaction failed", str(e), PipelineErrorCode.INSERTION_FAILED.value
            ) from e

        try:
            (is_prepared, transaction_label, table_name, prepare_message) = (
                TransactionManager.prepare_transaction(
                    configurations, table_name, transaction_id, transaction_label, http_session
                )
            )

            if not is_prepared:
                logging.info(
                    "(filepath_id=%s) %s -> Failed to prepare transaction block: %s",
                    filepath_id,
                    table_name,
                    prepare_message,
                )
            else:
                logging.info(
                    "(filepath_id=%s) %s -> Preparing transaction block successful",
                    filepath_id,
                    table_name,
                )
            return is_prepared, transaction_label, table_name

        except DataProcessingException as dpe:
            raise DataProcessingException("Preparing transaction failed", dpe.errors, PipelineErrorCode.INSERTION_FAILED.value) from dpe

        except Exception as e:
            raise DataProcessingException(
                "Preparing transaction failed", str(e), PipelineErrorCode.INSERTION_FAILED.value
            ) from e
