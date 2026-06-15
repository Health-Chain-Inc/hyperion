# Example queries

Once the stack is up (see [Up and running](../README.md#up-and-running) and the engine health check), these show how the FHIR-shaped tables are laid out and how to query them.

Resource tables hold the flattened scalar elements; repeating complex elements (codes, references, identifiers) live in the shared `codeableconcept`, `reference`, and `identifier` tables, keyed by resource `id` + `field_name`. Column names are lowercase.

```sql
USE _hyperion_core_;

-- Sample patient demographics
SELECT id, gender, birthdate, name_family, name_given
FROM patient
LIMIT 5;

-- Sample observations with units (code text via the shared codeableconcept table)
SELECT o.id, c.`text` AS code_text, o.valuequantity_value, o.valuequantity_unit
FROM observation o
JOIN codeableconcept c ON c.id = o.id AND c.field_name = 'code'
WHERE o.valuequantity_value IS NOT NULL
LIMIT 10;

-- Conditions by SNOMED-CT code
SELECT c.code, c.`text`, count(*) AS n
FROM `condition` co
JOIN codeableconcept c ON c.id = co.id AND c.field_name = 'code'
GROUP BY c.code, c.`text`
ORDER BY n DESC
LIMIT 10;

-- Per-patient observation count (subject via the shared reference table)
SELECT r.reference AS patient_ref, count(*) AS observation_count
FROM observation o
JOIN reference r ON r.id = o.id AND r.field_name = 'subject'
GROUP BY r.reference
ORDER BY observation_count DESC
LIMIT 10;
```

By default only `patient`, `observation`, `condition`, and `encounter` are populated. To ingest more resource types, expand `RESOURCE_TYPES`. See [development.md](development.md#common-operations) and [configuration.md](configuration.md).
