# engine.py

Sequential paper commits, finite pending passes and resume orchestration.

Inputs/outputs, algorithm and states, units, settings, audit/retries, resume, commands, validation, tests and limitations are specified in the shared [stabilization contract](stabilization.README.md) and [pending revalidation contract](revalidator.README.md).


## Screening data columns

The evidence-backed [data observation contract](data_observations.README.md) defines response fields, extraction/validation, JSON persistence, J?M mapping, unknown/excluded states, audit, resume, tests and limitations. Verdict-independent observations never register confirmed datasets.
