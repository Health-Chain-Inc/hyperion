import logging
from datetime import datetime, timedelta, timezone

from dateutil import parser as datetime_parser
from dotenv import load_dotenv

from pyfiles.dependencies.db_ops import DBOps

load_dotenv()


class FHIRScheduler:
    """
    function to invoke functions as required
    """
    def __init__(self, project_configurations, audit_db_conn_pool, queue_client):
        self.project_configurations = project_configurations
        self.audit_db_conn_pool = audit_db_conn_pool
        self.queue_client = queue_client

    async def main(self):
        db_connection = self.audit_db_conn_pool.create_connection()
        try:
            end_date = datetime_parser.parse(
                        self.project_configurations["fhir_exporter"]["end_date"]
                    ).replace(tzinfo=None)
            resource_list = DBOps.fetch_resource_list(db_connection)

            if not resource_list:
                logging.info("Empty resource list, run initial setup before bulk export")
                return

            time_interval = int(self.project_configurations["fhir_exporter"]["time_interval"])
            time_multipler = int(
                self.project_configurations["scheduler_properties"]["time_range_multiplier"]
            )
            last_export_time = DBOps.get_last_export_time(
                db_connection, self.project_configurations
            )
            end_date_flag = True if last_export_time >= end_date else False
            if end_date_flag:
                logging.info("Catch up complete, no messages to be created")
                return

            logging.debug("last_export_time_date_time %s", str(last_export_time))
            current_time_utc = datetime.now(timezone.utc)
            current_time_utc = current_time_utc.replace(tzinfo=None)
            time_difference = current_time_utc - last_export_time
            time_difference = int(time_difference.total_seconds() // 60)
            time_difference = int(time_difference // time_interval) * time_interval
            logging.debug("Time difference %s", time_difference)

            if time_difference < time_interval:
                logging.info("No need to pull data")

            elif time_difference == time_interval and not end_date_flag:
                logging.info("Normal execution data pull in sync")
                next_export_time = last_export_time + timedelta(minutes=time_interval)

                if next_export_time >= end_date:
                    logging.info("Next catch up time greater than end time. Setting the sync time to end date time")
                    next_export_time = end_date

                await message_creator(
                        self.queue_client,
                        last_export_time,
                        next_export_time,
                        db_connection,
                        resource_list,
                )

            else:
                max_cycles = int(
                    self.project_configurations["scheduler_properties"]["max_run_cycles"]
                )
                catchup_cycles = int(time_difference // (time_interval * time_multipler))
                catchup_cycles = max_cycles if catchup_cycles > max_cycles else catchup_cycles
                catchup_cycle = 0
                logging.info("Need to catch up %s times", catchup_cycles)

                while catchup_cycle < catchup_cycles and not end_date_flag:
                    logging.info("Catching up cycle %s/%s", catchup_cycle, catchup_cycles)
                    catchup_cycle = catchup_cycle + 1
                    last_export_time = DBOps.get_last_export_time(
                        db_connection, self.project_configurations
                    )
                    next_export_time = last_export_time + timedelta(
                        minutes=(time_interval * time_multipler)
                    )

                    if next_export_time >= end_date:
                        logging.info("Next catch up time greater than end time. Setting the sync time to end date time")
                        end_date_flag = True
                        next_export_time = end_date

                    await message_creator(
                        self.queue_client,
                        last_export_time,
                        next_export_time,
                        db_connection,
                        resource_list,
                    )
        except Exception:
            logging.exception("Scheduler main() failed")
            raise
        finally:
            if db_connection:
                db_connection.close()


async def message_creator(
    queue_client, last_sync_time, next_sync_time, db_connection, resource_list
):
    """
    function to create and insert messages to service bus
    """
    message_sender = queue_client.get_parameter_queue_sender()
    batch_message_sender = await queue_client.create_message_batch(message_sender)


    for _, resource_name in enumerate(resource_list):
        resource_scheduler_message = queue_client.create_scheduler_message(resource_name,
                                                                        last_sync_time,
                                                                        next_sync_time)

        await queue_client.add_batch_message(batch_message_sender, resource_scheduler_message, _)

    await queue_client.send_batch_messages(message_sender, batch_message_sender)
    DBOps.insert_to_fhir_export_logger(db_connection, last_sync_time, next_sync_time)
    logging.info("Messages and database insertion complete")
