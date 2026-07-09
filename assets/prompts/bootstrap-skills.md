# Bootstrap Project Skills

Your goal is to build a compact knowledge base that allows future coding agents
to work efficiently without repeatedly exploring the repository.

## Objective

Reduce future reasoning, searching, and token usage.

The documentation should optimize for:

* Fast navigation
* Predictable implementation
* Minimal repository exploration
* Low maintenance cost

Do **not** attempt to fully document the project.

Only document information that future coding agents would otherwise need to
rediscover.

---

## Create a `.skills/` directory

Create the following files if they do not exist.

```
.skills/

README.md
run.md
architecture.md
conventions.md
recipes.md
domain.md
dependencies.md
troubleshooting.md
glossary.md
decision-log.md
```

Only create files that are relevant to the project. Empty files should not
exist.

---

## README.md

Provide a short index explaining:

* purpose of each skill
* when to consult it
* relationships between skills

---

## run.md

Document:

* prerequisites
* install commands
* build commands
* development server
* test commands
* linting
* formatting
* type checking
* migrations
* database setup
* common scripts
* environment variables that developers commonly need

---

## architecture.md

Document:

* repository layout
* architectural layers
* important directories
* dependency direction
* module boundaries
* ownership of responsibilities
* important entry points

Do not describe every folder.

---

## conventions.md

Document project-specific conventions only.

Examples:

* dependency injection
* error handling
* logging
* naming conventions
* testing style
* API conventions
* component structure
* database conventions

Do not repeat language best practices.

---

## recipes.md

Describe common implementation workflows.

Examples:

* adding an endpoint
* adding a database migration
* creating a scheduled job
* adding a UI page
* introducing a new configuration option
* adding permissions
* integrating an external API

These should be concise checklists.

---

## domain.md

Document business concepts.

Include:

* terminology
* invariants
* relationships
* lifecycle rules
* important assumptions

Avoid implementation details.

---

## dependencies.md

Document external systems.

Examples:

* databases
* authentication
* message brokers
* third-party APIs
* storage
* queues
* monitoring

Describe where integrations live.

---

## troubleshooting.md

Document recurring issues.

Include:

* common failures
* debugging tips
* known pitfalls
* recovery commands

---

## glossary.md

Document important domain terminology and abbreviations.

---

## decision-log.md

Record significant architectural decisions.

Each entry should explain:

* decision
* rationale
* alternatives rejected

Do not duplicate ADRs if they already exist.

---

## Writing style

Prefer bullets over paragraphs.

Prefer examples over explanations.

Keep each file under roughly 200 lines.

Avoid duplication.

Cross-reference other skills when appropriate.

The goal is to minimize future repository exploration, not to maximize
documentation.

