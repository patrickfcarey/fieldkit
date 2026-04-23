# fieldkit

## Overview

**fieldkit** is a collection of small, purpose-built scripts used for real-world operational tasks.

This repository is not a framework, package, or library.
It is a **field-maintainable toolkit**: simple, readable utilities designed to solve specific problems quickly and reliably.

Tools may be written in any language (Python, Bash, PowerShell, etc.) as long as they adhere to the core philosophy:

> **Principles:**
> - **Clarity > Cleverness**
> - **Maintainability > Language Purity**
> - **Readability > Performance (until performance matters)**
---

## Philosophy

This repository exists to support real operational workflows.
Every tool must be understandable, debuggable, and maintainable under pressure.

### Core Principles

1. **Single Purpose**

   * Each script should do one thing well.
   * Avoid combining unrelated responsibilities.

2. **Readable First**

   * Code must be easy to read and reason about later.
   * Avoid dense, clever, or overly abstract implementations.

3. **Heavily Documented**

   * Every non-obvious decision must be explained.
   * Future maintainers must not need to reverse-engineer logic.

4. **Minimal Dependencies**

   * Prefer built-in tools and standard libraries.
   * Add dependencies only when they significantly improve clarity or correctness.

5. **Performance is Secondary**

   * Optimize only when a real bottleneck exists.
   * Do not sacrifice readability for premature optimization.

6. **Language is a Tool, Not an Identity**

   * Use the language that produces the clearest implementation.
   * Mixing Python, Bash, and PowerShell is expected and encouraged.

---

## Repository Structure

The repository is organized by **domain**, not by language.

```text
fieldkit/
  markdown/
  zfs/
  vm/
  windows/
  net/
  tests/
  docs/
  example.env
```

---

## Environment Configuration

This repository uses a `.env` file for configuration.

### Rules

* The application **only reads from `.env`**
* `example.env` is provided as the template
* Users must copy:

```bash
cp example.env .env
```

* `.env` must **never be committed**
* `example.env` must:

  * include all required variables
  * include documentation/comments for each variable
  * provide safe/default values where possible

### Purpose

This ensures:

* consistent configuration
* safe handling of environment-specific values
* predictable behavior across systems

---

## Domain Directories

Each domain groups related tools:

```text
markdown/
  fix_tables.py
  normalize_lists.py
  README.md
  tests/
  docs/
```

Guidelines:

* Keep directory depth shallow
* Group related tools together
* Include a `README.md` per domain describing available tools

---

## Script Structure

Each script must be self-contained and directly executable.

### Required Header Format

Every script must begin with a clear header:

```text
# Name: fix_tables.py
# Description: Fixes malformed Markdown tables by normalizing column alignment.
# Usage: python fix_tables.py <input_file>
# Inputs: Markdown file
# Outputs: Corrected Markdown to stdout or file

# Environment:
#   Tested:
#     - Oracle Linux 9.7 (UEK kernel)
#     - Python 3.11
#   Expected:
#     - Oracle Linux 9.x
#     - RHEL 9 compatible systems
#   Dependencies:
#     - python >= 3.11

# Assumptions:
#   - Input contains pipe-delimited tables
#   - UTF-8 encoding
# Failure Modes:
#   - Invalid table structure
#   - File not found
# Notes:
#   - Designed for quick correction, not full Markdown parsing
```

---

### Environment Documentation Requirements

All scripts must document their runtime environment.

#### Required Fields

* **Tested**

  * Exact platforms and versions the script was validated on
  * Must be real, verified environments

* **Expected**

  * Platforms likely to work based on compatibility
  * Should be reasonable and not overly broad

* **Dependencies**

  * All required binaries, runtimes, or modules
  * Include version constraints where relevant

#### Rules

* At least one **Tested** environment is required
* Do not guess compatibility beyond reasonable assumptions
* Keep entries concise and accurate
* Update when behavior changes due to environment differences

---

## Directory vs Single File Rules

Default:

* Scripts live as single files inside their domain directory

Promote to a subdirectory only when necessary:

```text
markdown/
  fix_tables/
    fix_tables.py
    README.md
    tests/
    docs/
    examples/
```

### Promote when:

* Multiple test fixtures are required
* Script has significant complexity
* Script requires extended documentation
* Script requires examples or assets
* Script is expected to grow

Otherwise, keep it flat.

---

## Testing Strategy

Testing is **layered and flexible**.

### Test Structure

```text
markdown/
  tests/
    test_fix_tables.py
    fixtures/
```

```text
fieldkit/
  tests/
    test_repo_conventions.py
```

---

## Documentation Strategy

Documentation follows the **same structure and philosophy as tests**.

### Docs Structure

```text
markdown/
  docs/
    fix_tables.md
```

```text
fieldkit/
  docs/
    repo_standards.md
```

---

### Documentation Rules

* `docs/` is required at:

  * domain level (when needed)
  * tool level (when complexity justifies it)
  * repository level (for global standards)

* Documentation should include:

  * purpose
  * usage examples
  * edge cases
  * known limitations
  * design decisions (when relevant)

* Prefer:

  * script headers for quick reference
  * `docs/` for deeper explanations

---

## Test Philosophy

* Test **narrow by default**, broad on purpose
* Do not require full-repo tests for small changes
* Ensure tests are easy to run and understand

---

## Naming Conventions

### Scripts

Use:

```text
verb_noun.ext
```

Examples:

* `fix_tables.py`
* `scrub_status.sh`
* `export_ova.ps1`

---

### Directories

Use clear, functional names:

* `markdown`
* `zfs`
* `windows`
* `vm`

Avoid vague or overly clever names.

---

## Docker Policy

fieldkit is **host-first and Docker-supported**.

* Tools should run directly on the host whenever practical

* Docker may be used for:

  * dependency isolation
  * reproducible environments
  * testing and CI

* Docker must **not be required** for tools that depend on:

  * direct OS interaction
  * system-level commands (e.g., ZFS, systemd)
  * host-specific behavior

---

## Contributions (Human and AI)

All contributions must follow this document.

### Hard Requirements

* Must follow structure rules
* Must include documentation
* Must include environment definitions
* Must prioritize readability
* Must not introduce unnecessary complexity

### Rejection Criteria

Changes will be rejected if they:

* Reduce readability
* Introduce unnecessary abstraction
* Add dependencies without justification
* Violate single-purpose design
* Lack documentation
* Lack environment definitions
* Bypass `.env` configuration rules

---

## Design Intent

This repository is designed to be:

* Readable at 2 AM during debugging
* Safe to modify under pressure
* Useful without setup or onboarding
* Stable over long periods of time

---

## Summary

fieldkit is not about writing “good code” in an abstract sense.

It is about writing **clear, practical, maintainable tools** that solve real problems and can be understood instantly when needed.

If a tool is:

* simple
* readable
* well-documented
* and does its job reliably

then it belongs here.
