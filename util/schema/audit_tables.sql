CREATE TABLE IF NOT EXISTS `fhir_lineage` (
  `filepath_id` varchar(36) NOT NULL COMMENT "",
  `resource_type` varchar(30) NOT NULL COMMENT "",
  `fhir_request_url` varchar(500) NULL COMMENT "",
  `record_count` int(11) NULL COMMENT "",
  `pipeline_type` varchar(20) NULL COMMENT "",
  `destination_location` varchar(500) NULL COMMENT "",
  `is_inserted` boolean NULL COMMENT "",
  `retry_count` int NULL COMMENT "",
  `error_code` varchar(3) NULL COMMENT "",
  `reject_location` varchar(500) NULL COMMENT "",
  `inserted_date` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT "",
  `updated_date` datetime NULL COMMENT ""
) ENGINE=OLAP
PRIMARY KEY(`filepath_id`)
COMMENT "OLAP"
DISTRIBUTED BY HASH(`filepath_id`)
PROPERTIES (
"compression" = "LZ4",
"datacache.enable" = "true",
"enable_async_write_back" = "false",
"enable_persistent_index" = "true",
"persistent_index_type" = "CLOUD_NATIVE",
"replication_num" = "env_replication_num"
);


CREATE TABLE IF NOT EXISTS `fhir_audit` (
  `resource_id` varchar(50) NOT NULL COMMENT "",
  `resource_type` varchar(30) NOT NULL COMMENT "",
  `meta_versionid` int(11) NULL COMMENT "",
  `meta_lastupdated` datetime NULL COMMENT "",
  `meta_source` varchar(20) NULL COMMENT "",
  `operation` varchar(20) NULL COMMENT "",
  `pipeline_type` varchar(20) NULL COMMENT "",
  `filepath_id` varchar(36) NULL COMMENT "",
  `inserted_date` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT ""
) ENGINE=OLAP
COMMENT "OLAP"
ORDER BY(resource_id, meta_versionid)
PROPERTIES (
"bloom_filter_columns" = "resource_id",
"compression" = "LZ4",
"datacache.enable" = "true",
"enable_async_write_back" = "false",
"enable_persistent_index" = "true",
"persistent_index_type" = "CLOUD_NATIVE",
"replication_num" = "env_replication_num"
);

CREATE TABLE IF NOT EXISTS  `file_export_logger` (
  `uuid` varchar(36) NOT NULL COMMENT "",
  `source_file_name` varchar(250) NOT NULL COMMENT "",
  `file_move_status` boolean NULL COMMENT ""
) ENGINE=OLAP
PRIMARY KEY(`uuid`)
COMMENT "OLAP"
DISTRIBUTED BY HASH(`uuid`)
PROPERTIES (
"compression" = "LZ4",
"datacache.enable" = "true",
"enable_async_write_back" = "false",
"enable_persistent_index" = "true",
"persistent_index_type" = "CLOUD_NATIVE",
"replication_num" = "env_replication_num"
);

CREATE TABLE IF NOT EXISTS `dollar_export_logger` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT COMMENT "",
  `since_date_time` datetime NOT NULL COMMENT "",
  `till_date_time` datetime NOT NULL COMMENT "",
  `resource_type` varchar(50) NOT NULL COMMENT "",
  `status_url` varchar(500) NULL COMMENT "",
  `dollar_export_status` varchar(20),
  `inserted_date` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT "") ENGINE=OLAP
PRIMARY KEY(`id`)
COMMENT "OLAP"
DISTRIBUTED BY HASH(`id`)
PROPERTIES (
"compression" = "LZ4",
"datacache.enable" = "true",
"enable_async_write_back" = "false",
"enable_persistent_index" = "true",
"persistent_index_type" = "CLOUD_NATIVE",
"replication_num" = "env_replication_num"
);

CREATE TABLE IF NOT EXISTS `fhir_export_logger` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT COMMENT "",
  `since_date_time` datetime NOT NULL COMMENT "",
  `till_date_time` datetime NOT NULL COMMENT "",
  `created_date` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT ""
) ENGINE=OLAP
PRIMARY KEY(`id`)
COMMENT "OLAP"
DISTRIBUTED BY HASH(`id`)
PROPERTIES (
"compression" = "LZ4",
"datacache.enable" = "true",
"enable_async_write_back" = "false",
"enable_persistent_index" = "true",
"persistent_index_type" = "CLOUD_NATIVE",
"replication_num" = "env_replication_num"
);