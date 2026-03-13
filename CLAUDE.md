# Red Hat AI Products Release Planner

## Overview

This repo generates an interactive HTML dashboard (`release-manager.html`) for Red Hat AI product release planning by querying JIRA. It tracks features for RHOAI, RHAIIS, and RHELAI across release cycles (EA1/EA2/GA), auto-schedules unscheduled features, and provides backlog analysis.

## Architecture

- **`release_manager.py`** - Main script. Queries JIRA, parses features, generates HTML dashboard with 4 tabs: Tracking, Draft Plans, Feature Analysis, Release Fit.
- **`auto_scheduler.py`** - Feature distribution algorithm for 2-year plans.
- **`fit_predictor_adapter.py`** - Bridge to Release Fit Predictor submodule. Provides data-driven complexity scoring (0-12 scale) and statistical capacity model.
- **`lib/release_fit_predictor/`** - Git submodule containing the Release Fit Predictor with scoring algorithm, capacity model, and sizing guide trained on 571 features across 41 releases.

## Feature Sizing

Features are auto-sized when JIRA story points are 0 or missing:

1. **Complexity scoring** (preferred): Uses component count, child issue count, description length, and complexity keywords. Produces a 0-12 score mapped to S(3)/M(5)/L(8)/XL(13).
2. **Keyword heuristic** (fallback): Pattern-matches summary text against size-indicating keywords.

The scoring algorithm spec is in `lib/release_fit_predictor/release-fit-predictor/SKILL.md`.

## Capacity Model

Statistical model from `lib/release_fit_predictor/release_capacity_model.json`:
- 41 releases analyzed, 90% confidence interval
- Median: 27.5 pts, Mean: 38.7 pts, Range: 5-140 pts

## Available Slash Commands

- `/size-work-item RHAISTRAT-XXXX` - Analyze and size a specific JIRA feature
- `/check-release-fit [version]` - Assess release capacity fit

## Running

```bash
export JIRA_TOKEN='your-token'
python3 release_manager.py
# Opens release-manager.html
```

## Submodule Management

```bash
# Initialize after cloning
git submodule update --init --recursive

# Pull latest from Release Fit Predictor
git submodule update --remote
```
