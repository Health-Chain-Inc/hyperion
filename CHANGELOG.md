# Changelog

All notable changes to Hyperion are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-06-09

Initial public release.

### Added
- **hyperion-core**: FHIR R4 → Hyperion Engine ingestion pipeline:
  batch load (scheduled time-window pulls) and event load (Azure
  Service Bus-driven, Azure mode only), shared normalization path,
  audit/lineage tracking, retry handling, and engine-cluster sidecars
  (root-password manager, metadata exporter/restorer, grant manager).
- **hyperion-util**: one-shot engine bootstrap: storage volume,
  `_hyperion_core_` / `_hyperion_audit_` databases, one table per FHIR R4
  resource type generated from the HL7 FHIR JSON Schema, service account.
- **Local demo**: single-command Docker Compose stack: HAPI FHIR seeded
  with Synthea synthetic patients, StarRocks 3.4 shared-data engine over
  MinIO, end-to-end pipeline run.
- **Azure deployment**: hybrid compose against Azure Health Data
  Services FHIR, Service Bus, and Blob Storage/ADLS Gen2.
- Cloud adapter layer (`core/pyfiles/adapters/`): abstract base classes
  for FHIR / storage / queue clients; implement these to add providers.
- 950+ unit tests (743 core, 215 util) plus integration and e2e tiers.
