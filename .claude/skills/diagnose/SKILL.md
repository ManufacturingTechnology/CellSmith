---
name: diagnose
description: Systematically diagnose something that isn't working before reporting inability
  — when a command fails, a library appears not to support something, a test or build breaks,
  an import or dependency error occurs, output is wrong or empty, or you are about to say
  something "doesn't work", "isn't possible", "isn't supported", or "can't be done".
  Inventories available diagnostic tools, finds and reads the real documentation, isolates the
  failing layer in a sandbox, classifies the cause, and records versions and repro steps so a
  future attempt can compare rather than restart.
---

# Diagnose before concluding

An error message names **where execution stopped**, not **why**. Reporting the first one as a
conclusion is the most common way to abandon a solvable problem.

This skill is generic — it applies to any project. Examples cite the CellSmith repo where a
concrete case makes a step clearer; they are marked, and nothing here depends on them.

## Do this, in order

1. **Inventory the environment.** What can I actually diagnose *with* here? Installed CLIs
   (run `--help` on anything unfamiliar — learning an unknown CLI that way is explicitly
   effective), a container runtime, a second OS via WSL, an offscreen display, loader and
   dependency tools (`ldd`, `otool`, Dependency Walker), package managers, log locations, and
   **the library's own source in `site-packages`**. Name the tools before guessing at causes.

2. **Find and read the real documentation.** Vendor docs, the installed package's own source
   and schema files, `--help`, release notes, CHANGELOG. Prefer primary sources. Do this
   *before* probing: it retrieves existing evidence instead of generating new evidence, so it
   is cheaper.
   *(CellSmith: reading the mkdocs plugin's source is what explained the `None` nav entries;
   reading the shipped `OFL.txt` files is what verified the font licenses.)*

3. **Isolate the failing layer** with the smallest possible test, and run it in a **sandbox
   by preference** — a scratch script, a throwaway container, a temp dir, a second OS. Three
   reasons: a probe that cannot damage anything needs no caution and can be more aggressive;
   a fresh environment separates "broken here" from "broken everywhere"; and the Red list in
   `CLAUDE.md` legitimately loosens in a sandbox, so more can proceed without asking.
   *(CellSmith: the Mesa-vs-EGL answer came entirely from throwaway containers.)*

4. **Classify the cause.** The four have completely different fixes:

   | Class | Fix | Note |
   |---|---|---|
   | **Missing dependency** | install it | a missing library is **not** a limitation |
   | **Missing/wrong configuration** | a flag, env var, or platform plugin | |
   | **Conflict between existing design decisions** | resolve the conflict | the class most often **misdiagnosed as a technical limit**; check `decisions.md` |
   | **Genuine technical limit** | route around it | only after excluding the three above |

5. **Distinguish the METHOD failing from the GOAL failing.** If the method failed, find
   another route to the same goal. Only a failed goal is a dead end.

6. **Record it systematically** so a future attempt can compare rather than restart. Write to
   the project's decision/status log with **all** of:

   - the **symptom**, verbatim — exact error text and exit code
   - **versions** of every library, tool, and runtime involved
   - **OS + platform**, and the platform plugin or backend in use
   - the **exact repro command**
   - **every configuration tried and what each produced**, including the failures
   - the **root cause**, or the specific remaining unknown
   - the **date**

   Without versions and the tried-configurations list, a revisit repeats the work instead of
   extending it. That list is the artifact.

7. **Stop digging after FOUR consecutive attempts that reveal nothing new.** Not four
   attempts — four that produced no new information. Then report; do not thrash.

## Reporting contract

Whether you solved it or stopped, report: **what was tried and what each attempt revealed ·
the root cause or the specific blocking unknown · two or more options with tradeoffs · a
recommendation with a reason.** Never just "I couldn't."

## Guardrails

- **Do not select an option merely because you found one.** The Red list in `CLAUDE.md`
  decides whether you may act alone.
- **Do not widen a config, suppress an error, or add a workaround to make a symptom
  disappear** without naming the root cause. Address causes, not symptoms.
- **Correct the docs when a probe contradicts them.** A confidently-wrong doc is worse than a
  missing one — it prevents the question instead of prompting it.
  *(CellSmith: a stale claim that headless rendering was impossible suppressed the entire
  visual-testing capability for weeks.)*
