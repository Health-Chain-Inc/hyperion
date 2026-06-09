
import asyncio
import atexit
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from pyfiles.adapters.fhir_clients import AzureFHIRClient, HapiFhirClient
from pyfiles.adapters.queue_clients import AzureQueueClient
from pyfiles.adapters.storage_clients import AzureStorageClient
from pyfiles.dependencies.enum import ApplicationEnums
from pyfiles.dependencies.handlers import Handlers
from pyfiles.dependencies.prerequisites import Prerequisites
from pyfiles.hyperion_core.audit_lineage_manager import AuditLineageManager
from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor
from pyfiles.hyperion_core.fhir_batch_processor import FHIRBatchProcessor
from pyfiles.hyperion_core.fhir_event_processor import FHIREventProcessor
from pyfiles.hyperion_core.fhir_scheduler import FHIRScheduler
from pyfiles.hyperion_core.retry_manager import RetryManager


class Main:
    def __init__(self):
        Handlers.logging_configuration([], os.getenv('LOG_LEVEL'))

    def run(self):
        """
        Function
        """
        logging.info('initializing run')
        (project_configurations,
        core_db_conn_pool,
        audit_db_conn_pool,
        cloud_storage,
        fhir_service,
        servicebus) = Prerequisites.prerequisite_check()

        storage_client = None
        queue_client = None
        fhir_client = None

        def cleanup():
            """Cleanup resources on shutdown."""
            logging.info("Cleaning up resources...")
            if fhir_client and hasattr(fhir_client, 'close'):
                try:
                    fhir_client.close()
                    logging.debug("FHIR client closed")
                except Exception as e:
                    logging.warning("Error closing FHIR client: %s", e)

            if queue_client and hasattr(queue_client, 'close'):
                try:
                    queue_client.close()
                    logging.debug("Queue client closed")
                except Exception as e:
                    logging.warning("Error closing queue client: %s", e)

            if storage_client and hasattr(storage_client, 'close'):
                try:
                    storage_client.close()
                    logging.debug("Storage client closed")
                except Exception as e:
                    logging.warning("Error closing storage client: %s", e)

            if core_db_conn_pool and hasattr(core_db_conn_pool, 'dispose'):
                try:
                    core_db_conn_pool.dispose()
                    logging.debug("Core DB connection pool disposed")
                except Exception as e:
                    logging.warning("Error disposing core DB pool: %s", e)

            if audit_db_conn_pool and hasattr(audit_db_conn_pool, 'dispose'):
                try:
                    audit_db_conn_pool.dispose()
                    logging.debug("Audit DB connection pool disposed")
                except Exception as e:
                    logging.warning("Error disposing audit DB pool: %s", e)

            logging.info("Resource cleanup complete")

        # Register cleanup on exit
        atexit.register(cleanup)

        try:
            if cloud_storage == "azure":
                storage_client = AzureStorageClient(project_configurations)
            # cloud_storage == "local": leave storage_client as None (local mode skips blob staging)

            if servicebus == "azure":
                queue_client = AzureQueueClient(project_configurations)
            # servicebus == "local": leave queue_client as None (local mode skips queue)

            if fhir_service == "azure":
                fhir_client = AzureFHIRClient(project_configurations)
            elif fhir_service == "local":
                fhir_client = HapiFhirClient(project_configurations)
            # else: leave fhir_client as None — caller decides what to do

        except Exception as e:
            logging.exception("Client initialization failed: %s", e)
            cleanup()
            sys.exit(1)

        try:
            if project_configurations:

                if project_configurations['application']['name'] == ApplicationEnums.CORE_DATA_INGESTER.value:
                    core_load = CoreLoadProcessor(queue_client, storage_client, fhir_client, project_configurations, core_db_conn_pool)
                    if queue_client is None and storage_client is None:
                        core_load.local_converter()
                    else:
                        core_load.fhir_converter()

                if project_configurations['application']['name'] == ApplicationEnums.EVENT_LOAD_EXPORTER.value:
                    event_exporter = FHIREventProcessor(project_configurations, storage_client, queue_client, fhir_client)
                    event_exporter.fhir_event_exporter()

                if project_configurations['application']['name'] == ApplicationEnums.BATCH_LOAD_EXPORTER.value:
                    fhir_exporter = FHIRBatchProcessor(project_configurations, storage_client, queue_client, fhir_client)
                    fhir_exporter.fhir_exporter()

                if project_configurations['application']['name'] == ApplicationEnums.AUDIT_LINEAGE_MANAGER.value:
                    audit_lineage_load = AuditLineageManager(project_configurations, queue_client)
                    audit_lineage_load.run()

                if project_configurations['application']['name'] == ApplicationEnums.SCHEDULER.value:
                    scheduler = FHIRScheduler(project_configurations, audit_db_conn_pool, queue_client)
                    asyncio.run(scheduler.main())

                if project_configurations['application']['name'] == ApplicationEnums.RETRY_MANAGER.value:
                    retry_manager = RetryManager(queue_client, storage_client, project_configurations)
                    retry_manager.retry_processor()
        except Exception as e:
            logging.exception("Fatal error in dispatch block: %s", e)
            sys.exit(1)
        finally:
            cleanup()


if __name__ == "__main__":
    main = Main()
    main.run()
