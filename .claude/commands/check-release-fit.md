# Check Release Fit

Assess whether current release plans fit within historical capacity using the statistical capacity model.

## Usage

Optionally provide a release version (e.g., 3.4) as the argument: $ARGUMENTS

## Instructions

1. If a specific release version is provided, analyze just that release. Otherwise, analyze all scheduled releases.

2. Run the check script from the submodule:
   ```bash
   cd /Users/emarion/redhat-ai-release-planner
   python3 lib/release_fit_predictor/check_release_fit.py $ARGUMENTS
   ```

3. If the script fails, fall back to the adapter directly:
   ```python
   from fit_predictor_adapter import load_capacity_model, check_release_fit
   model = load_capacity_model()
   result = check_release_fit(total_points, model)
   ```

4. Present the results including:
   - Fit level (EASILY_FITS / FITS_WELL / FITS / TIGHT_FIT / EXCEEDS_CAPACITY)
   - Percentage of median capacity used
   - Remaining capacity to typical maximum
   - Risk assessment and recommendations

5. Reference the capacity model statistics:
   - 41 releases analyzed, 90% confidence interval
   - Median: 27.5 pts, Mean: 38.7 pts
   - CI range: 5 - 140 points
