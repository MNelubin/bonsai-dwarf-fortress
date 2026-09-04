# Jobs Mechanic Overview

## VERIFIED
- Job status IDs 0-3 verified via `fix/corrupt-jobs` docs
- `unit.job` field points to active job (INFERRED)

## INFERRED
- Jobs have structured `unit_count` and `status` fields (from `fix/corrupt-jobs`)
- Status 0 idle, 1 active, 2 finished, 3 blocked pattern

## OPEN
- Full job object schema verification needed
- Mapping between job types and DF UI actions