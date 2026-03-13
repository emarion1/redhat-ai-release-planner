"""
Fit Predictor Adapter
Bridge between redhat-ai-release-planner and Release_Fit_Predictor submodule.

Loads scoring models from lib/release_fit_predictor/ and provides
drop-in replacements for the release manager's sizing and capacity functions.
"""

import json
import math
import os
import re

# Path to the submodule data files
_SUBMODULE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib", "release_fit_predictor")

# Size name mapping: release manager uses S/M/L/XL, fit predictor uses full names
_SIZE_TO_ABBREV = {
    "Small": "S",
    "Medium": "M",
    "Large": "L",
    "Extra Large": "XL",
}
_ABBREV_TO_SIZE = {v: k for k, v in _SIZE_TO_ABBREV.items()}

# Points for each size category
_SIZE_POINTS = {
    "Small": 3,
    "Medium": 5,
    "Large": 8,
    "Extra Large": 13,
}

# Default capacity model (used when submodule is unavailable)
_DEFAULT_CAPACITY_MODEL = {
    "confidence_level": "90%",
    "releases_analyzed": 41,
    "releases_in_ci": 38,
    "outliers_removed": 3,
    "min_points": 5.0,
    "max_points": 140.0,
    "mean_points": 38.74,
    "median_points": 27.5,
    "std_dev": 32.07,
    "recommended_range": "5 - 140 points",
}

# Complexity keywords
_HIGH_VALUE_KEYWORDS = [
    "architecture", "platform", "integration", "multi-system",
    "cross-cutting", "infrastructure", "distributed", "scalability",
    "enterprise", "api",
]
_MEDIUM_VALUE_KEYWORDS = [
    "dependencies", "migration", "refactoring", "coordination",
    "phases", "rollout", "compatibility", "observability",
    "multi-phase", "multi-tenant",
]


def load_capacity_model():
    """Load release_capacity_model.json from the submodule.

    Returns the statistical capacity model dict, or defaults if unavailable.
    """
    model_path = os.path.join(_SUBMODULE_DIR, "release_capacity_model.json")
    try:
        with open(model_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return _DEFAULT_CAPACITY_MODEL.copy()


def load_sizing_guide():
    """Load feature_sizing_guide.json from the submodule.

    Returns the sizing guide dict, or a minimal default if unavailable.
    """
    guide_path = os.path.join(_SUBMODULE_DIR, "feature_sizing_guide.json")
    try:
        with open(guide_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "Feature_Size_Scale": {"Small": 3, "Medium": 5, "Large": 8, "Extra Large": 13},
            "Classification_Signals": [],
        }


def capacity_model_to_legacy_format(model):
    """Convert the fit predictor capacity model to the release manager's CAPACITY dict format.

    The release manager expects keys: median, mean, conservative_max, typical_max,
    aggressive_max, historical_max_release.
    """
    median = model.get("median_points", 27.5)
    mean = model.get("mean_points", 38.74)
    max_pts = model.get("max_points", 140.0)
    std_dev = model.get("std_dev", 32.07)

    return {
        "median": median,
        "mean": round(mean, 1),
        "conservative_max": round(median + 0.1 * std_dev, 0),  # ~30
        "typical_max": round(mean + 0.35 * std_dev, 0),         # ~50
        "aggressive_max": round(mean + 1.3 * std_dev, 0),       # ~80
        "historical_max_release": max_pts,
    }


def calculate_complexity_score(component_count=0, child_issue_count=0,
                               description_length=0, description_text=""):
    """Calculate complexity score on a 0-12 scale.

    Components:
      - Component count score (0-4)
      - Child issue count score (0-4.5)
      - Description length score (0-1.5)
      - Complexity keywords score (0-3)

    Based on the algorithm in SKILL.md, trained on 571 features across 41 releases.
    """
    # 1. Component count score (0-4)
    if component_count == 0:
        comp_score = 0.0
    elif component_count == 1:
        comp_score = 1.0
    else:
        comp_score = 4.0  # 2+ components

    # 2. Child issue count score (0-4.5, logarithmic)
    if child_issue_count == 0:
        child_score = 0.0
    elif child_issue_count == 1:
        child_score = 1.0
    elif child_issue_count == 2:
        child_score = 2.0
    elif child_issue_count == 3:
        child_score = 2.5
    elif child_issue_count == 4:
        child_score = 3.0
    elif child_issue_count <= 6:
        child_score = 3.5
    elif child_issue_count <= 9:
        child_score = 4.0
    else:
        child_score = 4.5  # 10+

    # 3. Description length score (0-1.5)
    if description_length < 500:
        desc_score = 0.5
    elif description_length < 1000:
        desc_score = 0.8
    elif description_length < 2000:
        desc_score = 1.0
    else:
        desc_score = 1.5

    # 4. Complexity keywords score (0-3)
    text_lower = (description_text or "").lower()
    keyword_score = 0.0
    for kw in _HIGH_VALUE_KEYWORDS:
        if kw in text_lower:
            keyword_score += 0.5
    for kw in _MEDIUM_VALUE_KEYWORDS:
        if kw in text_lower:
            keyword_score += 0.3
    keyword_score = min(keyword_score, 3.0)

    total = comp_score + child_score + desc_score + keyword_score
    return min(total, 12.0)


def score_to_size(score, component_count=0):
    """Map a complexity score to a size category.

    Thresholds (boundary scores round UP):
      < 2.0  -> Small (3 pts)
      < 4.5  -> Medium (5 pts)
      < 7.0  -> Large (8 pts)
      >= 7.0 -> Extra Large (13 pts)

    Component override: 2+ components = minimum Large.
    """
    if score < 2.0:
        size = "Small"
    elif score < 4.5:
        size = "Medium"
    elif score < 7.0:
        size = "Large"
    else:
        size = "Extra Large"

    # Component override: 2+ components = minimum Large
    if component_count >= 2 and size in ("Small", "Medium"):
        size = "Large"

    return size


def calculate_confidence(score, component_count=0, child_issue_count=0,
                         description_length=0, status=""):
    """Calculate sizing confidence level.

    Returns a tuple of (numeric_score, label) where label is one of:
    Low, Low-Medium, Medium, Medium-High, High.
    """
    confidence = 5.0  # Base: Medium

    # Data availability adjustments
    if component_count > 0:
        confidence += 1.0
    else:
        confidence -= 1.0

    if child_issue_count > 0:
        confidence += 1.0
    else:
        confidence -= 1.0

    if description_length > 1000:
        confidence += 0.5
    elif description_length < 500:
        confidence -= 0.5

    # Status adjustments
    status_lower = (status or "").lower()
    if status_lower in ("new", "to do"):
        confidence -= 0.5
    elif status_lower == "refined":
        confidence += 0.5

    # Boundary proximity adjustments
    thresholds = [2.0, 4.5, 7.0]
    near_boundary = any(abs(score - t) < 0.5 for t in thresholds)
    far_from_boundary = all(abs(score - t) >= 1.0 for t in thresholds)

    if near_boundary:
        confidence -= 1.0
    elif far_from_boundary:
        confidence += 0.5

    # Signal consistency: check if all signals point to same size
    sizes_from_signals = []
    if component_count >= 2:
        sizes_from_signals.append("Extra Large")
    elif component_count == 1:
        sizes_from_signals.append("Medium")  # typical for M/L
    if child_issue_count >= 4:
        sizes_from_signals.append("Large")
    elif child_issue_count <= 1:
        sizes_from_signals.append("Small")
    if description_length >= 1000:
        sizes_from_signals.append("Large")

    predicted = score_to_size(score, component_count)
    if sizes_from_signals:
        # Check consistency: are signals in the same "tier" as predicted?
        tier_map = {"Small": 0, "Medium": 1, "Large": 2, "Extra Large": 3}
        predicted_tier = tier_map[predicted]
        signal_tiers = [tier_map.get(s, 1) for s in sizes_from_signals]
        if all(t == predicted_tier for t in signal_tiers):
            confidence += 1.0
        elif max(signal_tiers) - min(signal_tiers) >= 2:
            confidence -= 1.0

    # Clamp and map to label
    confidence = max(0.0, min(confidence, 10.0))

    if confidence < 2.0:
        label = "Low"
    elif confidence < 3.5:
        label = "Low-Medium"
    elif confidence < 5.0:
        label = "Medium"
    elif confidence < 6.5:
        label = "Medium-High"
    else:
        label = "High"

    return confidence, label


def estimate_feature_size_enhanced(summary, priority, component_count=0,
                                   child_issue_count=0, description="",
                                   status=""):
    """Drop-in replacement for estimate_feature_size().

    Uses complexity scoring when JIRA metadata is available (component_count,
    child_issue_count, description). Falls back to keyword heuristics when not.

    Returns a dict with:
      - points: int (3, 5, 8, or 13)
      - size: str (S, M, L, XL)
      - method: str ("complexity_scoring" or "keyword_heuristic")
      - complexity_score: float or None
      - confidence: str or None
      - confidence_score: float or None
    """
    description_text = description or ""
    description_length = len(description_text)

    # Use complexity scoring if we have meaningful JIRA data
    has_jira_data = component_count > 0 or child_issue_count > 0 or description_length > 100

    if has_jira_data:
        # Include summary text in keyword analysis
        full_text = summary + " " + description_text
        score = calculate_complexity_score(
            component_count=component_count,
            child_issue_count=child_issue_count,
            description_length=description_length,
            description_text=full_text,
        )
        size_full = score_to_size(score, component_count)
        points = _SIZE_POINTS[size_full]
        size_abbrev = _SIZE_TO_ABBREV[size_full]

        conf_score, conf_label = calculate_confidence(
            score, component_count, child_issue_count, description_length, status
        )

        return {
            "points": points,
            "size": size_abbrev,
            "method": "complexity_scoring",
            "complexity_score": round(score, 1),
            "confidence": conf_label,
            "confidence_score": round(conf_score, 1),
        }
    else:
        # Keyword heuristic fallback (matches original estimate_feature_size logic)
        summary_lower = summary.lower()
        xl_keywords = ["infrastructure", "migration", "integration", "architecture", "redesign", "framework"]
        l_keywords = ["implement", "develop", "create", "build", "support", "enable"]
        s_keywords = ["fix", "adjust", "minor", "small", "ui", "ux", "docs"]

        if any(kw in summary_lower for kw in xl_keywords) or priority == "Blocker":
            points, size = 13, "XL"
        elif any(kw in summary_lower for kw in l_keywords) or priority == "Critical":
            points, size = 8, "L"
        elif any(kw in summary_lower for kw in s_keywords):
            points, size = 3, "S"
        else:
            points, size = 5, "M"

        return {
            "points": points,
            "size": size,
            "method": "keyword_heuristic",
            "complexity_score": None,
            "confidence": None,
            "confidence_score": None,
        }


def check_release_fit(total_points, capacity_model=None):
    """Check if a release's total points fit within historical capacity.

    Returns a dict with:
      - level: str (EASILY_FITS, FITS_WELL, FITS, TIGHT_FIT, EXCEEDS_CAPACITY)
      - color: str (CSS color for display)
      - pct_of_median: float
      - remaining_to_typical: float
      - message: str
    """
    if capacity_model is None:
        capacity_model = load_capacity_model()

    median = capacity_model.get("median_points", 27.5)
    mean = capacity_model.get("mean_points", 38.74)
    max_pts = capacity_model.get("max_points", 140.0)

    pct_of_median = (total_points / median * 100) if median > 0 else 0

    if total_points <= median * 0.4:
        level = "EASILY_FITS"
        color = "#28a745"
        message = f"Well within capacity ({pct_of_median:.0f}% of median)"
    elif total_points <= median * 0.8:
        level = "FITS_WELL"
        color = "#28a745"
        message = f"Comfortable fit ({pct_of_median:.0f}% of median)"
    elif total_points <= median * 1.5:
        level = "FITS"
        color = "#ffc107"
        message = f"Fits within normal range ({pct_of_median:.0f}% of median)"
    elif total_points <= max_pts:
        level = "TIGHT_FIT"
        color = "#fd7e14"
        message = f"Tight fit - near upper limit ({pct_of_median:.0f}% of median)"
    else:
        level = "EXCEEDS_CAPACITY"
        color = "#dc3545"
        message = f"Exceeds historical maximum ({pct_of_median:.0f}% of median)"

    # Calculate remaining capacity to typical max (mean + ~0.35*std_dev ~ 50)
    typical_max = mean + 0.35 * capacity_model.get("std_dev", 32.07)
    remaining = typical_max - total_points

    return {
        "level": level,
        "color": color,
        "pct_of_median": round(pct_of_median, 1),
        "remaining_to_typical": round(remaining, 1),
        "message": message,
    }
