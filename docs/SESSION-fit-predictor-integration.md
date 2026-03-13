# Session: Release Fit Predictor Integration

**Date**: 2026-03-12
**Goal**: Integrate the Release Fit Predictor's data-driven scoring into the Red Hat AI Products Release Planner

## What Was Analyzed

- **Release Manager** (`release_manager.py`, 2576 lines): Existing auto-sizing used keyword heuristics; capacity thresholds were hardcoded.
- **Release Fit Predictor** (submodule): Complexity scoring algorithm (0-12 scale) trained on 571 historical RHAISTRAT features across 41 releases. Statistical capacity model with 90% confidence intervals.
- **SKILL.md**: Authoritative specification for the scoring algorithm including component scoring, child issue scoring, description length scoring, keyword scoring, confidence calculation, and size thresholds.

## Decisions Made

1. **Git submodule** at `lib/release_fit_predictor/` keeps both repos independent and updatable.
2. **Adapter pattern** (`fit_predictor_adapter.py`) bridges naming conventions (S/M/L/XL vs Small/Medium/Large/Extra Large) and handles path resolution.
3. **Graceful degradation**: All adapter functions use try/except with fallback defaults. The release manager works identically if the submodule is missing.
4. **Drop-in replacement**: `estimate_feature_size()` signature was extended with optional parameters for backward compatibility. When the adapter is available, it delegates to complexity scoring; otherwise, the original keyword heuristic runs.
5. **New dashboard tab**: "Release Fit" tab shows capacity model summary, per-release fit assessments, and sizing method distribution.

## Files Created

| File | Purpose |
|------|---------|
| `fit_predictor_adapter.py` | Integration adapter with scoring, sizing, confidence, and capacity functions |
| `.claude/commands/size-work-item.md` | Slash command to size individual JIRA features |
| `.claude/commands/check-release-fit.md` | Slash command to check release capacity fit |
| `CLAUDE.md` | Project context for Claude Code |
| `docs/SESSION-fit-predictor-integration.md` | This file |

## Files Modified

| File | Changes |
|------|---------|
| `release_manager.py` | Added adapter import, dynamic CAPACITY loading, enriched JIRA query (components, description), enhanced `estimate_feature_size()` with optional params, enriched `parse_features()` with component/description extraction and sizing metadata, added Release Fit tab (HTML + JS) |
| `.github/workflows/update-release-plan.yml` | Added `submodules: recursive` to checkout, added submodule update step, added `fit_predictor_adapter.py` and `lib/release_fit_predictor/**` to paths trigger |

## Files Created by Git

| File | Purpose |
|------|---------|
| `.gitmodules` | Submodule configuration (auto-created by `git submodule add`) |
| `lib/release_fit_predictor/` | Submodule directory |

## How to Update the Submodule

```bash
# Pull latest changes from the Release Fit Predictor
cd /Users/emarion/redhat-ai-release-planner
git submodule update --remote

# Commit the updated submodule reference
git add lib/release_fit_predictor
git commit -m "Update Release Fit Predictor submodule"
```

## Verification Steps

1. **Submodule**: `git submodule status` should show the pinned commit
2. **Adapter load**: `python3 -c "from fit_predictor_adapter import load_capacity_model; print(load_capacity_model())"`
3. **Complexity scoring**: `python3 -c "from fit_predictor_adapter import estimate_feature_size_enhanced; print(estimate_feature_size_enhanced('Build infrastructure platform', 'Critical', component_count=3, child_issue_count=7))"`
4. **Keyword fallback**: `python3 -c "from fit_predictor_adapter import estimate_feature_size_enhanced; print(estimate_feature_size_enhanced('Fix minor UI bug', 'Normal'))"`
5. **Dashboard**: Run `python3 release_manager.py` (with JIRA_TOKEN) and check for 4 tabs including Release Fit
6. **Slash commands**: `/size-work-item RHAISTRAT-1234` and `/check-release-fit`

## Scoring Algorithm Summary

The complexity score (0-12) is computed from four weighted components:

- **Component count** (0-4 pts): 0 comps=0, 1 comp=1, 2+ comps=4
- **Child issue count** (0-4.5 pts): Logarithmic scale from 0 to 10+
- **Description length** (0-1.5 pts): From <500 chars to 2000+ chars
- **Complexity keywords** (0-3 pts): High-value (+0.5) and medium-value (+0.3) keywords

Size thresholds (boundary scores round UP):
- Score < 2.0 = Small (3 pts)
- Score < 4.5 = Medium (5 pts)
- Score < 7.0 = Large (8 pts)
- Score >= 7.0 = Extra Large (13 pts)

Component override: 2+ components = minimum Large.

---

## Follow-up: Product-Aware Grouping, Per-Event Fit, and Deploy Key

**Date**: 2026-03-13

### Issues Fixed

1. **Multi-product mixing**: `group_features_by_release()` previously stripped only the `rhoai-` prefix and used bare version numbers (e.g., "3.4") as keys. This combined RHOAI, RHAIIS, and RHELAI features into a single bucket. Fixed by extracting product from `scheduled_to` and using composite keys like `RHOAI-3.4`, `RHAIIS-3.4`.

2. **Per-release vs per-event mismatch**: The capacity model's 27.5 median is per-event (EA1/EA2/GA), but the Release Fit tab summed all events together before comparing, making every release appear to exceed capacity. Fixed by computing fit per-event.

3. **Deploy key for private submodule**: GitHub Actions couldn't check out the private `Release_Fit_Predictor` submodule. Added `webfactory/ssh-agent` step with `SUBMODULE_DEPLOY_KEY` secret and changed `.gitmodules` URL from HTTPS to SSH.

### Changes Made

| File | Changes |
|------|---------|
| `release_manager.py` | Added `re` import (top-level), `KNOWN_PRODUCTS` constant, `_extract_product()` helper; modified `group_features_by_release()` to use composite keys; added product filter buttons (CSS + HTML) to Tracking tab; added `filterProduct()` JS; updated `loadRelease()` for composite keys; changed release fit data to per-event; rewrote `renderReleaseFitAssessments()` JS |
| `.github/workflows/update-release-plan.yml` | Added `webfactory/ssh-agent@v0.9.0` step before submodule checkout; split checkout from submodule init |
| `.gitmodules` | Changed URL from HTTPS to SSH (`git@github.com:ahinek/Release_Fit_Predictor.git`) |

### Deploy Key Setup

1. Generate SSH key pair: `ssh-keygen -t ed25519 -C "deploy-key" -f deploy_key -N ""`
2. Add `deploy_key.pub` as a read-only deploy key on `ahinek/Release_Fit_Predictor` (Settings > Deploy keys)
3. Add `deploy_key` contents as secret `SUBMODULE_DEPLOY_KEY` on `emarion1/redhat-ai-release-planner` (Settings > Secrets)
