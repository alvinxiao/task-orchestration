# Python task assigning with OR-Tools

Status: approved by the user, including the public solve-operation test boundary. Python and OR-Tools are user requirements. The interface and scope choices below were accepted with this specification.

## Problem Statement

Build a Python project that assigns tasks to qualified employees and orders their work, using the Timefold task-assigning quickstart as the behavioral reference. The repository has no application, tests, glossary, or ADRs yet.

## Solution

Provide a Python library and a small JSON command-line interface backed by OR-Tools CP-SAT. Given employees, skills, customers, task types, and tasks, return each employee's ordered schedule, task start and finish times, unassigned tasks, and objective metrics. Include a runnable example and installation instructions.

Preserve the reference's scheduling rules and default objective. A browser interface and hosted service can follow separately.

## User Stories

1. As a planner, I want to define employees, so that I can schedule my team.
2. As a planner, I want to list employee skills, so that only qualified employees receive work.
3. As a planner, I want to define task types with required skills, so that repeated tasks use consistent eligibility rules.
4. As a planner, I want to set base durations, so that the schedule reflects expected effort.
5. As a planner, I want to define customers, so that tasks retain their business context.
6. As a planner, I want to set employee affinity for customers, so that durations reflect familiarity.
7. As a planner, I want missing affinity to use the documented default, so that incomplete preference data has predictable behavior.
8. As a planner, I want to create tasks with stable identifiers, so that I can match results to inputs.
9. As a planner, I want to set earliest start times, so that tasks cannot begin before they are ready.
10. As a planner, I want critical, major, and minor priorities, so that urgent work receives greater emphasis.
11. As a planner, I want each task assigned at most once, so that work is not duplicated.
12. As a planner, I want employee tasks to run without overlap, so that the schedule is executable.
13. As a planner, I want tasks to run to completion, so that the plan does not assume interruptions.
14. As a planner, I want all assignable work scheduled before timing preferences are optimized, so that the optimizer cannot improve its score by dropping work.
15. As a planner, I want tasks lacking a qualified employee reported as unassigned, so that I can address skill gaps.
16. As a planner, I want ordered task lists with start, finish, and duration, so that employees can follow the plan.
17. As a planner, I want overall completion time and the objective components reported separately, so that I understand what was optimized.
18. As a planner, I want a solve time limit, so that planning finishes within my budget.
19. As a planner, I want to distinguish a feasible result from a proven optimum, so that I know the result's certainty.
20. As a planner, I want clear errors for malformed input, so that I can correct my data.
21. As a developer, I want a callable Python solver, so that I can embed planning in another application.
22. As a developer, I want JSON input and output, so that I can run and inspect examples without building a UI.
23. As a developer, I want a complete sample dataset, so that I can run the project immediately after installation.
24. As a developer, I want documented model assumptions, so that I can extend the scheduler safely.
25. As a developer, I want behavioral tests with small known optima, so that changes cannot silently alter scheduling semantics.
26. As a planner, I want empty inputs handled explicitly, so that a day with no work is a valid case.

## Implementation Decisions

- Use Python and OR-Tools CP-SAT. Select and lock compatible dependency versions during implementation.
- Keep domain validation, optimization, and result serialization behind one public solve operation. A thin CLI reads JSON and writes a structured result. Do not add a database or web server for the initial project.
- Model employees with IDs, names, skill sets, and customer affinities; customers with IDs and names; task types with IDs, positive integer base durations, and required skills; tasks with IDs, task-type and customer references, nonnegative earliest start minutes, and priority.
- Validate unique IDs, references, enums, integer ranges, and positive solve limits at the input boundary. Reject invalid data with field-specific errors before invoking CP-SAT.
- Use integer minutes relative to a shared planning origin. Match the reference affinity multipliers: NONE=4, LOW=3, MEDIUM=2, HIGH=1. Missing employee/customer affinity means NONE. Duration equals base duration multiplied by affinity.
- Create optional intervals only for qualified task/employee pairs. Exactly one eligible interval is present for each assignable task. Tasks with no eligible employees remain explicitly unassigned. Enforce employee no-overlap and task earliest starts.
- This initial model has no deadline, capacity horizon, or employee calendar. Therefore every task with an eligible employee can be assigned. Fixing these assignments' presence preserves the reference's medium-level objective without a separate optimization phase. Revisit this decision if constraints later make eligible tasks mutually infeasible.
- Derive a safe horizon from the maximum earliest start plus the sum of maximum eligible task durations. Check bounds, including squared objective terms, against CP-SAT integer limits. Do not use an arbitrary short horizon that silently discards work.
- Preserve the reference default soft cost: sum of squared employee finish times plus the sum of assigned task finish times weighted 4 for CRITICAL, 2 for MAJOR, and 1 for MINOR. Empty employees finish at zero. Model squares with bounded integer multiplication constraints.
- Report actual makespan as the maximum employee finish separately. The reference's constraint named "Minimize makespan" uses a squared-finish sum, not this maximum. Do not silently replace its objective with pure makespan minimization.
- Return tasks sorted by start for each employee. Compact each sequence to earliest feasible starts before returning it, matching the reference sequence semantics; recompute all reported metrics from the returned schedule.
- Return assignments, unassigned IDs and reasons, makespan, objective components, elapsed solve time, solver status, and optimality information. Preserve OPTIMAL, FEASIBLE, INFEASIBLE, MODEL_INVALID, and UNKNOWN distinctions. Return no invented schedule when the solver has no incumbent. An UNKNOWN result is not proof of infeasibility.
- Use a single total time budget. Document reproducibility settings for development, without promising identical tied schedules across solver versions.
- Include a sample exercising multiple skills, affinities, priorities, release times, and an unassignable task. Document installation, library use, CLI use, and result interpretation.

## Testing Decisions

- Approved primary test boundary: the public solve operation, from validated planning request to observable schedule/result.
- Test external behavior, not variable names, internal model construction, or a particular tied solution. Run the real CP-SAT solver for scheduling acceptance tests.
- Verify every returned assignment has all required skills, appears once, starts after release, has the correct affinity-dependent duration, and does not overlap another task for that employee.
- Use tiny exhaustive assignment/order enumeration as an independent oracle for the objective. Check squared employee finish costs and priority-weighted completion costs, including a case that distinguishes this objective from pure makespan.
- Cover missing affinity, all affinity levels, employee idle time, unassignable tasks, no employees, no tasks, and multiple optimal schedules.
- Check malformed references, duplicate identifiers, invalid durations/priorities, and unsafe numeric bounds through the same public boundary.
- Verify result status handling without timing-sensitive expectations. Exercise status translation with controlled outcomes where actual solver timeouts would be flaky. Never require a machine to reach a particular status in a few milliseconds.
- Add one CLI smoke test that reads the example and checks parseable output. Keep domain assertions at the solve boundary.
- There is no local test prior art. The reference repository separates constraint-provider tests, validation tests, and integration tests; use its behavioral cases as guidance without copying Java-specific test structure.

## Out of Scope

Browser UI, REST service, asynchronous jobs, persistence, authentication, deployment, task execution, agent orchestration, employee calendars, breaks, shifts, deadlines, task dependencies, preemption, pinned assignments, live replanning, configurable constraint weights, and full Timefold API compatibility.

These scope boundaries were accepted with the specification for the first runnable Python project.

## Further Notes

The configured issue tracker is alvinxiao/task-orchestration on GitHub. Publish this approved specification with the ready-for-agent label.

Research inspected the stable branch on 2026-11-17; that branch can change. Record the source commit when implementing compatibility fixtures. Retain required notices if adapting upstream code or data.

Sources:

- [Timefold task-assigning overview](https://github.com/TimefoldAI/timefold-quickstarts/blob/stable/use-cases/task-assigning/README.md)
- [Actual reference objective](https://github.com/TimefoldAI/timefold-quickstarts/blob/stable/use-cases/task-assigning/src/main/java/org/acme/taskassigning/solver/TaskAssigningConstraintProvider.java)
- [Task timing and duration](https://github.com/TimefoldAI/timefold-quickstarts/blob/stable/use-cases/task-assigning/src/main/java/org/acme/taskassigning/domain/Task.java)
- [Affinity multipliers](https://github.com/TimefoldAI/timefold-quickstarts/blob/stable/use-cases/task-assigning/src/main/java/org/acme/taskassigning/domain/Affinity.java)
- [OR-Tools CP-SAT integer modeling and statuses](https://developers.google.com/optimization/cp/cp_solver)
- [OR-Tools scheduling intervals and no-overlap](https://developers.google.com/optimization/scheduling/job_shop)
