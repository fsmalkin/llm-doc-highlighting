# Eval Findings and Observations

This document tracks evaluation findings so we can prioritize fixes without losing context.

How to add a finding
- Include doc id + example id.
- Note which method failed and how.
- Add any context that would change the next run (prompt, rails, scoring).

## Findings log

### 2026-02-02 - FUNSD test run

- doc=83823750, ex=83823750_q24
  - Indexed returned a single-character span (tight highlight) that appears correct.
  - Raw + Fuzzy selected the wrong token.
  - Action: investigate raw + fuzzy prompt or matching for single-character answers.

