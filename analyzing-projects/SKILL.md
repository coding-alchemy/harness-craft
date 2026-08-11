---
name: analyzing-projects
description: Use when analyzing an existing codebase to produce source-level project documentation that explains its overall architecture and implementation to developers.
---

# Analyzing Projects

## Overview

Documentation is a lead; source, tests, and real call chains are evidence. When you inherit an unfamiliar repository, its docs tell you what someone once claimed, not what the code does now. Treat every claim as unverified until a specific file, test, or traced call chain confirms it. This skill installs six ordered gates that keep analysis and documentation auditable under deadline and authority pressure.

Use this skill only when both predicates are true: the subject is an existing codebase, and the required deliverable is source-level project documentation explaining overall architecture and implementation to developers. If either predicate is absent, do not use this skill.

## When to Use

- Producing a source-level architecture and implementation introduction for an existing repository.
- Reconstructing an existing project's overall architecture and end-to-end implementation from source and tests for developer documentation.
- Restructuring or refreshing project-introduction docs when the result must still explain the complete source architecture and implementation.
- Auditing architecture docs when the task includes delivering the corrected, complete source-level project introduction.

## When Not to Use

- Repository analysis that does not deliver source-level project-introduction documentation.
- A single bug, function, call chain, code-review question, refactoring proposal, or implementation plan.
- Checking one architecture claim without producing the complete project introduction.
- Installation, usage, deployment, API, contribution, or environment-setup manuals.
- Greenfield conceptual architecture with no existing implementation to verify.

## Required Workflow

Complete each gate in order; do not start a later gate until the earlier one is satisfied.

1. **Freeze the ground truth.** Before reading or editing, record the repository ref and worktree status (branch, commit, uncommitted or untracked changes). All later analysis and validation run against this fixed baseline.

2. **Ground evidence in source.** For each claim, cite every applicable evidence type, tagged SOURCE (the implementing code), TEST (the exercising test), and CALL-CHAIN (the traced request or data flow). If a type does not exist, state that evidence gap; do not invent it. A component or data-store inventory is not evidence without a traced call chain. The README and existing docs are leads only. Mark anything you cannot confirm UNVERIFIED; never promote it to fact.

3. **Set ownership and structure.** Define capability boundaries and assign exactly one canonical owner per topic and per document — no shared writers. Design each document for two audiences: a novice overview and maintainer-level source detail. Before deep dives, define two required project-level views: a project architecture overview and an end-to-end implementation panorama. Add a capability deep dive only when its independent flow, algorithm/state/data contract, risk boundary, or size would overload those views.

4. **Protect edits and parallelism.** Before editing any document, take a pre-edit snapshot and build a protected fact inventory of the accurate statements that edits must not regress. An evidence or claim ledger does not replace either. Give each parallel worker an exclusive set of files; serialize every write to shared indexes (README, overview, navigation) through a single writer. Concurrent append-only writes to a shared index are forbidden — they lose data.

5. **Run fresh mechanical validation.** Against the frozen baseline, run fresh mechanical checks for links, symbols, placeholders, section pairing, and duplication. A cross-document consistency read is not mechanical validation.

6. **Review and gate completion.** Require both a novice reviewer and a maintainer reviewer; do not trust the implementer's self-report, a prior session's success claim, or the fact that links render. Classify every finding; any Critical or Important finding blocks completion until it is fixed and re-reviewed by the original reviewer.

## Output Contract

### 1. Project architecture overview — required

1. **Position and system context:** problem, actors/callers, external systems, runtime entries, primary inputs, outputs/consumers, and system boundary.
2. **Conceptual architecture:** logical components/layers and responsibilities; data plane versus control plane where applicable; explicit labels for conceptual views versus real source boundaries.
3. **Module responsibility map:** major directories/modules, real source symbols, responsibilities, inputs/outputs, and relationships. A directory tree alone does not satisfy this slot.
4. **Capability map:** main-runtime, off-main-runtime, optional, and unwired capabilities, each linked to one canonical owner.
5. **Cross-cutting constraints:** only implementation-defining security, state/consistency, concurrency, portability, determinism, and extension principles that source evidence supports.
6. **Reading and source-navigation route:** 30-second overview, 5-minute mainline, maintainer drill-down, and links among overview, panorama, and deep dives.

### 2. End-to-end implementation panorama — required

1. **Real orchestration entries:** how user/API/CLI/event entries reach the actual orchestrator, dispatcher, or main call chain.
2. **Normal end-to-end flow:** actual calls and data flow from input to final output/consumer, with stage handoffs.
3. **Stage contract matrix:** each major stage's real entry symbol, input, output, state/side effect, next consumer, and canonical owner.
4. **Data-shape evolution:** cross-stage types, schemas/key fields, persistence forms, and transformation boundaries.
5. **Control-flow variants:** actual optional stages, branches, short circuits, fallback, cache hits, incremental, retry, concurrency, and async paths that apply.
6. **Cross-stage failure and effects:** propagation/isolation, degradation, partial success, transaction/atomicity, external writes, and recovery that apply.
7. **Conceptual-to-source mapping:** where conceptual stages or existing document terms match—or do not match—real functions, commands, and runtime paths.

### 3. Capability deep dives — conditional

Create a separate deep dive or equivalently clear boundary when a capability has an independent entry/flow, important algorithm/state/data contract, distinct security/failure/performance/dependency boundary, or would overload the project-level narrative. For each selected capability or pipeline stage, use all nine explicit slots below; otherwise do not create a token deep dive merely to satisfy a file count.

Use explicit headings or table fields for all nine slots below; none may be implicit or replaced by a general “implementation details” section.

1. **Purpose and boundary:** responsibility, exclusions, and relationship to the wider system or pipeline.
2. **Entries and call chain:** CLI/API/event/hook or other runtime entries, callers, and the actual internal call chain.
3. **Inputs and preconditions:** types, schemas or key fields, configuration, validation, and prerequisites.
4. **Processing and decisions:** ordered steps, key algorithms, branches, short circuits, fallback selection, and concurrency where relevant.
5. **Outputs and consumers:** return types, schemas or key fields, emitted artifacts/events, and downstream consumers.
6. **State and side effects:** cache, persistence, files, queues, mutations, idempotency, and cleanup.
7. **Dependencies and integrations:** internal collaborators plus required, external, and optional dependencies.
8. **Failure and limits:** errors, retries, degradation, security boundaries, performance/scale constraints, and unsupported cases.
9. **Evidence:** source files and symbols, tests plus the behavior each test proves, traced `CALL-CHAIN`, and explicit `UNVERIFIED` gaps.

For a staged pipeline, repeat the nine slots for every stage and add cross-stage data contracts, transformations, optional paths, cache hits, incremental behavior, and differences between the simplified model and real control flow.

### Completion evidence

- Every factual claim carries a `SOURCE`, `TEST`, or `CALL-CHAIN` citation, or is labelled `UNVERIFIED`; use all applicable evidence types rather than forcing all three where one does not exist.
- A baseline record, per-document pre-edit snapshots, and a protected fact inventory exist.
- Each topic has one canonical owner; shared indexes were written serially.
- Fresh mechanical checks passed against the baseline.
- Novice and maintainer reviews are recorded; no Critical or Important finding is open.

## Quick Reference

| Gate | Requirement |
|------|-------------|
| 1 Baseline | Record ref plus worktree status before touching anything |
| 2 Evidence | SOURCE, TEST, CALL-CHAIN, or UNVERIFIED; state what each citation proves |
| 3 Ownership | One canonical owner per topic; novice plus maintainer views |
| 4 Protect | Pre-edit snapshots plus protected fact inventory; exclusive files; serialized shared indexes |
| 5 Validate | Fresh links, symbols, placeholders, pairing, duplication checks |
| 6 Review | Novice plus maintainer review; Critical or Important blocks plus re-review |
| Deliverable | Required architecture overview + required implementation panorama + conditional nine-slot deep dives |

## Red Flags

Stop if you catch yourself thinking:

- "I am analyzing a repository, so this skill automatically applies." Not unless the deliverable is source-level project architecture and implementation documentation.
- "The README is probably accurate, so I can trust it." It is a lead; confirm with every applicable SOURCE, TEST, or CALL-CHAIN type and mark gaps UNVERIFIED.
- "An inventory of components and data stores is enough evidence." Not without a traced call chain.
- "My evidence ledger counts as a pre-edit snapshot and protected fact inventory." Snapshot each document and inventory its protected facts first.
- "Append-only writes to the shared index are safe under concurrency." Serialize them through one writer.
- "A consistency cross-read is my validation." Run fresh mechanical checks instead.
- "I verified my own work, so it is done." Require a novice reviewer and a maintainer reviewer.
- "Links render and a prior session reported success, so ship it." A Critical or Important concern blocks completion until fixed and re-reviewed.
