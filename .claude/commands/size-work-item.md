# Size Work Item

Analyze and size a JIRA feature using the Release Fit Predictor's complexity scoring algorithm.

## Usage

Provide a RHAISTRAT key (e.g., RHAISTRAT-1234) as the argument: $ARGUMENTS

## Instructions

1. Run the analysis script from the submodule:
   ```bash
   cd /Users/emarion/redhat-ai-release-planner
   python3 lib/release_fit_predictor/analyze_jira_feature.py $ARGUMENTS
   ```

2. If the script fails (e.g., missing JIRA_TOKEN), fall back to the adapter:
   ```python
   from fit_predictor_adapter import estimate_feature_size_enhanced
   # Use the summary and metadata from the JIRA API directly
   ```

3. Present the results including:
   - Recommended size (S/M/L/XL) with story points
   - Complexity score (0-12 scale)
   - Confidence level and what signals contributed
   - How this compares to the historical distribution

4. If the feature has no JIRA data available, explain that the scoring falls back to keyword heuristics and the result may be less accurate.
