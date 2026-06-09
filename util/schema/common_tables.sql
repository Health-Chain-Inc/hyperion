CREATE TABLE IF NOT EXISTS `schema_history` (
    `id` BIGINT AUTO_INCREMENT,
    `table_name` VARCHAR(255) NOT NULL,
    `created_date` datetime NOT NULL,
    `created_by` VARCHAR(100) NOT NULL,
    `updated_date` datetime,
    `version` INT NOT NULL,
    `status` VARCHAR(50) NOT NULL,
    `description` TEXT
) PRIMARY KEY (`id`) PROPERTIES (
    "compression" = "LZ4",
    "datacache.enable" = "true",
    "enable_async_write_back" = "false",
    "enable_persistent_index" = "true",
    "persistent_index_type" = "CLOUD_NATIVE",
    "replication_num" = "env_replication_num"
);

CREATE TABLE IF NOT EXISTS `pipeline_meta_info` (
    `id` BIGINT AUTO_INCREMENT,
    `property` VARCHAR(255) NOT NULL,
    `description` TEXT,
    `status` VARCHAR(50) NOT NULL,
    `created_date` datetime NOT NULL,
    `created_by` VARCHAR(100) NOT NULL,
    `updated_date` datetime
) PRIMARY KEY (`id`) PROPERTIES (
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

CREATE TABLE IF NOT EXISTS `codeableconcept` (
    `id` varchar(100) NOT NULL COMMENT "",
    `field_name` varchar(255) NOT NULL COMMENT "",
    `seq_no` bigint(20) NOT NULL COMMENT "",
    `system` varchar(255) NULL COMMENT "",
    `version` varchar(255) NULL COMMENT "",
    `code` varchar(255) NULL COMMENT "",
    `display` varchar(255) NULL COMMENT "",
    `userselected` boolean COMMENT "",
    `text` varchar(1048576) NULL COMMENT "",
    `extension` array<json> NULL COMMENT "",
    `updated_date` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT "",
    INDEX codeableconcept_fieldname_index (`field_name`) USING BITMAP COMMENT '',
    INDEX codeableconcept_code_index (`code`) USING BITMAP COMMENT ''
) ENGINE = OLAP PRIMARY KEY (`id`, `field_name`, `seq_no`) COMMENT "OLAP" DISTRIBUTED BY HASH (`id`) BUCKETS 16 PROPERTIES (
    "bloom_filter_columns" = "id, system",
    "compression" = "LZ4",
    "datacache.enable" = "true",
    "enable_async_write_back" = "false",
    "enable_persistent_index" = "true",
    "persistent_index_type" = "CLOUD_NATIVE",
    "replication_num" = "env_replication_num",
    "colocate_with" = "core_group"
);

CREATE TABLE IF NOT EXISTS `reference` (
    `id` varchar(100) NOT NULL COMMENT "",
    `field_name` varchar(255) NOT NULL COMMENT "",
    `seq_no` bigint(20) NOT NULL COMMENT "",
    `reference` varchar(255) NULL COMMENT "",
    `type` varchar(255) NULL COMMENT "",
    `identifier` json NULL COMMENT "",
    `display` varchar(255) NULL COMMENT "",
    `extension` array<json> NULL COMMENT "",
    `updated_date` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT "",
    INDEX reference_fieldname_index (`field_name`) USING BITMAP COMMENT ''
) ENGINE = OLAP PRIMARY KEY (`id`, `field_name`, `seq_no`) COMMENT "OLAP" DISTRIBUTED BY HASH (`id`) BUCKETS 16 PROPERTIES (
    "bloom_filter_columns" = "id, reference",
    "compression" = "LZ4",
    "datacache.enable" = "true",
    "enable_async_write_back" = "false",
    "enable_persistent_index" = "true",
    "persistent_index_type" = "CLOUD_NATIVE",
    "replication_num" = "env_replication_num",
    "colocate_with" = "core_group"
);

CREATE TABLE IF NOT EXISTS `identifier` (
    `id` varchar(100) NOT NULL COMMENT "",
    `field_name` varchar(255) NOT NULL COMMENT "",
    `seq_no` bigint(20) NOT NULL COMMENT "",
    `use` varchar(255) NULL COMMENT "",
    `type` json NULL COMMENT "",
    `system` varchar(255) NULL COMMENT "",
    `value` varchar(255) NULL COMMENT "",
    `period_start` datetime NULL COMMENT "",
    `period_end` datetime NULL COMMENT "",
    `assigner` json NULL COMMENT "",
    `extension` array<json> NULL COMMENT "",
    `updated_date` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT "",
    INDEX identifier_fieldname_index (`field_name`) USING BITMAP COMMENT ''
) ENGINE = OLAP PRIMARY KEY (`id`, `field_name`, `seq_no`) COMMENT "OLAP" DISTRIBUTED BY HASH (`id`) BUCKETS 16 PROPERTIES (
    "bloom_filter_columns" = "id, system",
    "compression" = "LZ4",
    "datacache.enable" = "true",
    "enable_async_write_back" = "false",
    "enable_persistent_index" = "true",
    "persistent_index_type" = "CLOUD_NATIVE",
    "replication_num" = "env_replication_num",
    "colocate_with" = "core_group"
);

CREATE TABLE IF NOT EXISTS `fhir_lineage` (
  `filepath_id` varchar(36) NOT NULL COMMENT "",
  `resource_type` varchar(30) NOT NULL COMMENT "",
  `fhir_request_url` varchar(500) NULL COMMENT "",
  `record_count` int(11) NULL COMMENT "",
  `pipeline_type` varchar(20) NULL COMMENT "",
  `destination_location` varchar(500) NULL COMMENT "",
  `is_inserted` boolean NULL COMMENT "",
  `retry_count` int(11) NULL COMMENT "",
  `error_code` varchar(3) NULL COMMENT "",
  `reject_location` varchar(500) NULL COMMENT "",
  `created_date` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT "",
  `updated_date` datetime NULL COMMENT ""
) ENGINE=OLAP
PRIMARY KEY(`filepath_id`)
COMMENT "OLAP"
DISTRIBUTED BY HASH(`filepath_id`) BUCKETS 8
PROPERTIES (
"compression" = "LZ4",
"datacache.enable" = "true",
"enable_async_write_back" = "false",
"enable_persistent_index" = "true",
"persistent_index_type" = "CLOUD_NATIVE",
"replication_num" = "env_replication_num",
"colocate_with" = "audit_group"
);


CREATE TABLE IF NOT EXISTS `fhir_audit` (
  `resource_id` varchar(100) NOT NULL COMMENT "",
  `resource_type` varchar(30) NOT NULL COMMENT "",
  `meta_versionid` int(11) NULL COMMENT "",
  `meta_lastupdated` datetime NOT NULL COMMENT "",
  `meta_source` varchar(20) NULL COMMENT "",
  `operation` varchar(20) NULL COMMENT "",
  `pipeline_type` varchar(20) NULL COMMENT "",
  `filepath_id` varchar(36) NULL COMMENT "",
  `created_date` datetime NULL DEFAULT CURRENT_TIMESTAMP COMMENT ""
) ENGINE=OLAP
DUPLICATE KEY(`resource_id`)
COMMENT "OLAP"
PARTITION BY date_trunc('day', meta_lastupdated)
DISTRIBUTED BY HASH(`filepath_id`) BUCKETS 8
ORDER BY(resource_id, meta_versionid)
PROPERTIES (
"bloom_filter_columns" = "resource_id, filepath_id",
"compression" = "LZ4",
"datacache.enable" = "true",
"enable_async_write_back" = "false",
"replication_num" = "env_replication_num",
"partition_live_number" = "365",
"colocate_with" = "audit_group"
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

 CREATE TABLE IF NOT EXISTS `metadata_backup_log` (
    `backup_id` VARCHAR(36) NOT NULL,
    `hostname` VARCHAR(256) NOT NULL,
    `backup_timestamp` DATETIME NOT NULL,
    `status` VARCHAR(20) NOT NULL,
    `folder_name` VARCHAR(256) NULL,
    `total_files` INT NULL,
    `total_size_bytes` BIGINT,
    `verified_files` INT NULL,
    `attempts` INT NULL,
    `error_message` VARCHAR(2048) NULL,
    `duration_seconds` DOUBLE NULL
  ) ENGINE = OLAP
PRIMARY KEY(`backup_id`)
COMMENT "OLAP"
DISTRIBUTED BY HASH(`backup_id`) BUCKETS 1
PROPERTIES (
"compression" = "LZ4",
"datacache.enable" = "true",
"enable_async_write_back" = "false",
"enable_persistent_index" = "true",
"persistent_index_type" = "CLOUD_NATIVE",
"replication_num" = "env_replication_num"
);
