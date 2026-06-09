"""
    class consisting of all insert queries
"""

import logging
import sys


class Queries:
    """
    class to hold all queries and related functions for data insertion
    """

    meta_info_fields = "`id`,`property`,`description`,`status`,`created_date`,`created_by`,`updated_date`"
    schema_history_fields = "`id`,`table_name`,`created_date`,`created_by`,`updated_date`,`version`,`status`,`description`"
    dollar_export_logger_fields = "`id`,`since_date_time`,`till_date_time`,`resource_type`,`status_url`,`dollar_export_status`"
    insert_queries = {
        "schema_history": schema_history_fields,
        "pipeline_meta_info": meta_info_fields,
        "dollar_export_logger":dollar_export_logger_fields
    }


    def __init__(self) -> None:
        pass

    @staticmethod
    def get_insert_query(table_name, is_update):
        """
        function returns insert query for required table
        """
        try:
            query = Queries.insert_queries.get(table_name, None)
            if not is_update:
                query = query.replace("`id`,","")
            columns = query.replace("`", "").split(",")
            values_string = ", ".join(f":{column_name}" for column_name in columns)
            insert_statement = f"INSERT INTO {table_name} ({query}) VALUES ({values_string})"
            return insert_statement
        except Exception:
            logging.exception("Error in get_insert_query")
            sys.exit(1)
