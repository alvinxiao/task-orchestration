# Implementation run

Done means the approved SPEC.md is implemented, the installed JSON CLI solves the sample, independent tiny-case enumeration agrees with the optimizer, and validation and edge-case tests pass. Review findings must be resolved or reported with evidence.

## Workflow

1. Locate or install an isolated Python toolchain and verify it runs.
2. Build typed domain requests and results, validation, and a CP-SAT solve operation.
3. Add the JSON CLI, sample, dependency lock, installation guide, and behavioral tests.
4. Independently review the diff and exercise the actual library and CLI.
5. Fix findings, rerun relevant checks, and deliver the verified project.

## Throughput checkpoint

- Blocking first steps. Verify a Python toolchain before implementing solver code.
- Independent workstreams. One implementation owner builds the coupled model, CLI, and tests. The parent reviews the completed artifact.
- Shared mutable state. Only the implementation owner edits application files while running. The parent owns this plan and the decision trail.
- Smallest safe decomposition. One owner prevents schema and solver contracts from diverging in this small greenfield package.

## Design

Use typed records for employees, customers, task types, tasks, solve settings, and results. Normalize IDs at the boundary. Expose solve(request) and keep CP-SAT details private. A JSON CLI uses the same boundary.

The alternative is a dictionary-only solver with validation interleaved into model building. Choose typed records because references and result states need consistent validation across library and CLI entry points.

Hosted arena fan-out is disabled by the local model configuration. No parallel design agents were launched. The approved specification supplies the scheduling and objective decisions.
