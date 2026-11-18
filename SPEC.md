# Python task assigning with OR-Tools

Status: approved by the user, including the public solve-operation test boundary. Python and OR-Tools are user requirements. The interface and scope choices below were accepted with this specification.

## Problem Statement

Build a Python project that assigns tasks to qualified employees and orders their work, using the Timefold task-assigning quickstart as the behavioral reference. The repository has no application, tests, glossary, or ADRs yet.

## Solution

Provide a Python library and a small JSON command-line interface backed by OR-Tools CP-SAT. Given employees, skills, customers, task types, and tasks, return each employee's ordered schedule, task start and finish times, unassigned tasks, and objective metrics. Include a runnable example and installation instructions.

Preserve the reference's scheduling rules. The objective is the user-requested strict lexicographic priority policy with squared-load fairness, replacing the reference's mixed weighted cost. A browser interface and hosted service can follow separately.

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
10. As a planner, I want CRITICAL, HIGH, MEDIUM, and LOW priorities, so that urgent work receives greater emphasis; legacy MAJOR and MINOR inputs are accepted as HIGH and LOW.
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
- This initial model has no deadline, capacity horizon, or employee calendar. Therefore every task with an eligible employee can be assigned, and the model forces all of them present without a separate feasibility phase. Revisit this decision if constraints later make eligible tasks mutually infeasible.
- Derive a safe horizon from the maximum earliest start plus the sum of maximum eligible task durations. Check bounds, including squared load terms and per-priority completion totals, against CP-SAT integer limits. Do not use an arbitrary short horizon that silently discards work.
- Schedule by strict lexicographic priority over CRITICAL, HIGH, MEDIUM, LOW. Each stage minimizes that priority's total completion time (the sum of assigned tasks' finish times) and runs to proven OPTIMAL before an equality locks its exact integer value. Empty stages are trivially proven zero. A FEASIBLE stage stops the sequence as provisional without advancing; an UNKNOWN or expired stage keeps the last incumbent and stops as provisional. A final fairness stage minimizes the sum of squared per-employee assigned work minutes among schedules that keep every locked total. Employee capacity is treated as equal; normalizing loads by actual capacity is deferred until shifts exist.
- Preserve the solver's chosen starts when returning a schedule instead of compacting them, so no post-processing can change a locked priority total. Recompute all reported metrics from the returned schedule.
- Return assignments, unassigned IDs and reasons, makespan, per-priority completion totals, per-employee work minutes, the squared load cost, one stage record per objective (name, status, proven flag, optional value and bound), a proven priority prefix, a provisional flag, and elapsed solve time. Preserve OPTIMAL, FEASIBLE, INFEASIBLE, MODEL_INVALID, and UNKNOWN distinctions. Return no invented schedule when the solver has no incumbent. An UNKNOWN result is not proof of infeasibility, and a provisional result is not a strict lexicographic optimum.
- Use a single total time budget. Document reproducibility settings for development, without promising identical tied schedules across solver versions.
- Include a sample exercising multiple skills, affinities, priorities, release times, and an unassignable task. Document installation, library use, CLI use, and result interpretation.

## Testing Decisions

- Approved primary test boundary: the public solve operation, from validated planning request to observable schedule/result.
- Test external behavior, not variable names, internal model construction, or a particular tied solution. Run the real CP-SAT solver for scheduling acceptance tests.
- Verify every returned assignment has all required skills, appears once, starts after release, has the correct affinity-dependent duration, and does not overlap another task for that employee.
- Use tiny exhaustive assignment/order enumeration as an independent oracle for the lexicographic objective: the tuple of per-priority completion totals in strict CRITICAL, HIGH, MEDIUM, LOW order followed by the squared load cost, with test-local literals rather than production constants. Include a case that proves a lower priority cannot worsen a higher priority's aggregate, and one that proves permutations are allowed when totals are fixed.
- Prove stage behavior with controlled solver outcomes: a FEASIBLE first stage stops provisional, a later UNKNOWN stage retains the prior incumbent, one shared budget covers setup and all stages, empty and no-eligible cases are trivially proven, affinity changes assigned work minutes, and fairness only applies after every priority total is locked.
- Cover missing affinity, all affinity levels, employee idle time, unassignable tasks, no employees, no tasks, and multiple optimal schedules.
- Check malformed references, duplicate identifiers, invalid durations/priorities, legacy priority aliases, and unsafe numeric bounds through the same public boundary.
- Verify result status handling without timing-sensitive expectations. Exercise status translation with controlled outcomes where actual solver timeouts would be flaky. Never require a machine to reach a particular status in a few milliseconds.
- Add one CLI smoke test that reads the example and checks parseable output. Keep domain assertions at the solve boundary.
- There is no local test prior art. The reference repository separates constraint-provider tests, validation tests, and integration tests; use its behavioral cases as guidance without copying Java-specific test structure.

## Out of Scope

Browser UI, REST service, asynchronous jobs, persistence, authentication, deployment, task execution, agent orchestration, employee calendars, breaks, shifts, deadlines, task dependencies, preemption, pinned assignments, live replanning, configurable constraint weights, and full Timefold API compatibility.

These scope boundaries were accepted with the specification for the first runnable Python project.

## Replanning Amendment

Added after the strict-priority milestone: operational replanning when jobs arrive while others run, preserving the strict priority policy and the single public solve operation. The original scope deferred "live replanning"; this amendment accepts it.

- `PlanningRequest.replanning` is an optional typed `ReplanningContext` defaulting to `current_time=0` with empty records, so old requests validate and solve unchanged, including the stage list.
- Named data shape: `ReplanningContext` with `current_time`, `completed_task_ids`, `in_progress` (`task_id`, `employee_id`, `actual_start`, `remaining_minutes`), `committed` (`task_id`, `employee_id`, `start`), and `previous_assignments` (`task_id`, `employee_id`, `start`). All minute fields are strict integers with nonnegative bounds; `remaining_minutes` is positive.
- Completed IDs must refer to tasks retained in the request; completed tasks are excluded from assignments, unassigned entries, and every objective. Completed work contributes nothing to priority totals or fairness.
- In-progress tasks keep their employee and actual start in the output, finish at `current_time + remaining_minutes`, and are distinguished from remaining work in the output (`duration` is the remaining minutes). The employee reserves `[current_time, current_time + remaining_minutes]`, not the original duration. Priority completion sums include the fixed finish; fairness counts only remaining minutes for in-progress work and full duration for pending and committed work, never elapsed minutes. Skills may be grandfathered for running work since it started under the old policy, but the employee must exist, and an employee has at most one in-progress task.
- Committed tasks fix employee and future start (at or after `current_time`); duration is the affinity-based duration and the fixed employee must still be eligible. Pending tasks start at or after `max(current_time, earliest_start)`. Fixed intervals (in-progress and committed) may not overlap on one employee. Duplicate IDs in records, tasks in more than one execution state, unknown task or employee references, and invalid starts are rejected at the input boundary.
- The horizon derives from `current_time`, fixed finishes, and pending releases plus durations, with the existing CP-SAT integer-limit guards, including the stability stage's bounded domain.
- With `previous_assignments`, one final STABILITY stage runs after all four priority stages and the fairness stage are proven and locked, minimizing the count of previous pending tasks whose employee or start changed, one change per task, not duration weighted. With no previous assignments the stage is skipped or proven zero. Changes and explicit metrics (`changed_tasks`, `unchanged_tasks`, the change list) are reported on the result. Previously completed, in-progress, and committed tasks are not stability-tracked.
- Stage locking now covers fairness as well as the four priorities, so no later stage can trade away a locked fairness optimum. The provisional and last-incumbent semantics and the single shared time budget are unchanged.

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
