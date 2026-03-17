#!/usr/bin/env python3
"""
Red Hat AI Products Release Planner
Multi-product release tracking and capacity planning for RHOAI, RHAIIS, and RHELAI

Usage:
    export JIRA_TOKEN='your-token'
    python3 release_manager.py

Opens release-manager.html in browser
"""

import base64
import json
import os
import re
import sys
import requests
from datetime import datetime
from collections import defaultdict

# Import auto-scheduler
try:
    from auto_scheduler import auto_schedule_features, format_plan_summary
except ImportError:
    # If running standalone, define inline
    def auto_schedule_features(features, capacity, start_version="3.5", num_releases=8):
        """Fallback: returns empty plan"""
        return {}, []
    def format_plan_summary(plan, schedule):
        return "Auto-scheduler not available"

# Import fit predictor adapter (from Release_Fit_Predictor submodule)
try:
    from fit_predictor_adapter import (
        load_capacity_model, capacity_model_to_legacy_format,
        estimate_feature_size_enhanced, check_release_fit,
    )
    FIT_PREDICTOR_AVAILABLE = True
except ImportError:
    FIT_PREDICTOR_AVAILABLE = False

# Configuration
JIRA_BASE_URL = "https://redhat.atlassian.net"
JIRA_TOKEN = os.environ.get("JIRA_TOKEN")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL")
PROJECT = "RHAISTRAT"
PLAN_NAME = "RHOAI Feature Planning and Tracking"
PLAN_VIEW = "Outcomes & Features (Jeff's View)"

# JIRA Custom Fields (Atlassian Cloud IDs)
FIELD_STORY_POINTS = "customfield_10836"
FIELD_TARGET_VERSION = "customfield_10855"
FIELD_TARGET_END_DATE = "customfield_10015"  # Target end date for planning

# Capacity guidelines - loaded from fit predictor model when available,
# otherwise falls back to hardcoded defaults from PREDICTIVE_RELEASE_CAPACITY_REPORT.md
if FIT_PREDICTOR_AVAILABLE:
    _capacity_model = load_capacity_model()
    CAPACITY = capacity_model_to_legacy_format(_capacity_model)
else:
    _capacity_model = None
    CAPACITY = {
        "median": 27.5,
        "mean": 38.7,
        "conservative_max": 30,
        "typical_max": 50,
        "aggressive_max": 80,
        "historical_max_release": 140,
    }

# Feature sizing (from FEATURE_SIZING_QUICK_REFERENCE.md)
FEATURE_SIZING = {
    "XS": 1,
    "S": 3,
    "M": 5,
    "L": 8,
    "XL": 13
}


def get_jira_headers():
    """Get JIRA API headers"""
    if not JIRA_TOKEN or not JIRA_EMAIL:
        print("❌ ERROR: JIRA_TOKEN and/or JIRA_EMAIL environment variable not set")
        print("\nSet your Atlassian Cloud API token and email:")
        print("  export JIRA_EMAIL='your-email@redhat.com'")
        print("  export JIRA_TOKEN='your-api-token'")
        print("\nGet API token from: https://id.atlassian.com/manage-profile/security/api-tokens")
        sys.exit(1)

    credentials = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_TOKEN}".encode()).decode()
    return {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json"
    }


def get_jira_plan_id():
    """Get plan ID for 'RHOAI Feature Planning and Tracking'"""
    print(f"🔍 Searching for JIRA Plan: '{PLAN_NAME}'...")

    # Try Advanced Roadmaps API endpoints
    endpoints = [
        "/rest/jpo/1.0/plan",
        "/rest/portfolio/1.0/plan",
        "/rest/teams/1.0/plan/search"
    ]

    for endpoint in endpoints:
        try:
            response = requests.get(
                f"{JIRA_BASE_URL}{endpoint}",
                headers=get_jira_headers(),
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                print(f"✅ Found plans via {endpoint}")

                # Search for matching plan name
                plans = data if isinstance(data, list) else data.get("values", [])
                for plan in plans:
                    if PLAN_NAME.lower() in plan.get("title", "").lower():
                        plan_id = plan.get("id")
                        print(f"✅ Found plan ID: {plan_id}")
                        return plan_id

        except Exception as e:
            print(f"  ⚠️ {endpoint} not accessible: {e}")
            continue

    print(f"⚠️  Could not find plan via API")
    return None


def get_plan_feature_ranking(plan_id):
    """Get feature ranking from JIRA Plan"""
    if not plan_id:
        return {}

    print(f"📊 Fetching feature ranking from plan {plan_id}...")

    try:
        # Try to get issues from plan in ranked order
        response = requests.get(
            f"{JIRA_BASE_URL}/rest/jpo/1.0/plan/{plan_id}/issue",
            headers=get_jira_headers(),
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            issues = data if isinstance(data, list) else data.get("issues", [])

            # Create ranking dict: {issue_key: rank_number}
            ranking = {}
            for idx, issue in enumerate(issues, start=1):
                key = issue.get("key") or issue.get("issueKey")
                if key:
                    ranking[key] = idx

            print(f"✅ Retrieved ranking for {len(ranking)} features")
            return ranking

    except Exception as e:
        print(f"⚠️  Could not get plan ranking: {e}")

    return {}


def get_all_features():
    """Get all RHAISTRAT features with status, points, versions"""
    print(f"📥 Querying all {PROJECT} features...")

    jql = f"project = {PROJECT} AND type IN (Feature, Initiative, Epic, Story)"

    all_issues = []
    max_results = 100
    next_page_token = None

    while True:
        params = {
            "jql": jql,
            "fields": f"key,summary,status,priority,issuetype,{FIELD_STORY_POINTS},fixVersions,{FIELD_TARGET_VERSION},{FIELD_TARGET_END_DATE},labels,issuelinks,components,description",
            "maxResults": max_results
        }
        if next_page_token:
            params["nextPageToken"] = next_page_token

        response = requests.get(
            f"{JIRA_BASE_URL}/rest/api/3/search/jql",
            headers=get_jira_headers(),
            params=params,
            timeout=30
        )

        if response.status_code != 200:
            print(f"❌ JIRA query failed: {response.status_code}")
            return []

        data = response.json()
        issues = data.get("issues", [])
        all_issues.extend(issues)

        print(f"  Retrieved {len(all_issues)} features so far...")

        # Token-based pagination: stop when isLast or no nextPageToken
        if data.get("isLast", True) or "nextPageToken" not in data:
            break
        next_page_token = data["nextPageToken"]

    print(f"✅ Retrieved {len(all_issues)} total features")
    return all_issues


def estimate_feature_size(summary, priority, component_count=0, child_issue_count=0,
                          description="", status=""):
    """
    Auto-estimate feature size based on summary and priority.
    When the fit predictor adapter is available, uses data-driven complexity scoring
    (0-12 scale trained on 571 features). Falls back to keyword heuristics otherwise.

    Returns story points (3, 5, 8, or 13) for backward compatibility.
    When fit predictor is available, also sets module-level _last_sizing_result
    with detailed scoring metadata.
    """
    global _last_sizing_result

    if FIT_PREDICTOR_AVAILABLE:
        result = estimate_feature_size_enhanced(
            summary, priority,
            component_count=component_count,
            child_issue_count=child_issue_count,
            description=description,
            status=status,
        )
        _last_sizing_result = result
        return result["points"]

    # Keyword heuristic fallback
    _last_sizing_result = None
    summary_lower = summary.lower()

    xl_keywords = ["infrastructure", "migration", "integration", "architecture", "redesign", "framework"]
    l_keywords = ["implement", "develop", "create", "build", "support", "enable"]
    s_keywords = ["fix", "adjust", "minor", "small", "ui", "ux", "docs"]

    if any(kw in summary_lower for kw in xl_keywords) or priority == "Blocker":
        return FEATURE_SIZING["XL"]  # 13

    if any(kw in summary_lower for kw in l_keywords) or priority == "Critical":
        return FEATURE_SIZING["L"]  # 8

    if any(kw in summary_lower for kw in s_keywords):
        return FEATURE_SIZING["S"]  # 3

    return FEATURE_SIZING["M"]  # 5


# Module-level variable to hold detailed sizing result from last estimate_feature_size call
_last_sizing_result = None


def parse_features(issues, ranking):
    """Parse JIRA issues into feature objects"""
    features = []
    auto_sized_count = 0

    for issue in issues:
        key = issue["key"]
        fields = issue["fields"]

        # Parse fix versions (committed releases)
        fix_versions = []
        for fv in fields.get("fixVersions", []):
            fix_versions.append(fv["name"])

        # Parse target version (planned release)
        target_version = None
        if fields.get(FIELD_TARGET_VERSION):
            tv_field = fields[FIELD_TARGET_VERSION]
            # Handle both dict and list formats
            if isinstance(tv_field, dict):
                target_version = tv_field.get("name")
            elif isinstance(tv_field, list) and len(tv_field) > 0:
                target_version = tv_field[0].get("name") if isinstance(tv_field[0], dict) else str(tv_field[0])
            else:
                target_version = str(tv_field) if tv_field else None

        # Parse target end date
        target_end_date = None
        if fields.get(FIELD_TARGET_END_DATE):
            target_end_date = fields[FIELD_TARGET_END_DATE]  # Format: "YYYY-MM-DD"

        # Determine scheduling status
        if fix_versions:
            scheduled_to = fix_versions[0]
            status_category = "committed"
        elif target_version:
            scheduled_to = target_version
            status_category = "planned"
        else:
            scheduled_to = None
            status_category = "unscheduled"

        # Get labels
        labels = fields.get("labels", [])

        # Extract component count and description for complexity scoring
        components = fields.get("components", [])
        component_count = len(components) if isinstance(components, list) else 0
        description = fields.get("description") or ""
        feature_status = fields["status"]["name"]

        # Count child issues from issuelinks
        child_issue_count = 0
        for link in fields.get("issuelinks", []):
            if link.get("type", {}).get("inward", "").lower() in ("is parent of", "is epic of"):
                if "outwardIssue" in link:
                    child_issue_count += 1
            elif link.get("type", {}).get("outward", "").lower() in ("is parent of", "is epic of"):
                if "outwardIssue" in link:
                    child_issue_count += 1

        # Get story points - AUTO-SIZE if 0 or missing
        points = fields.get(FIELD_STORY_POINTS) or 0
        original_points = points

        sizing_method = "jira_provided"
        complexity_score = None
        sizing_confidence = None

        if points == 0:
            priority = fields["priority"]["name"] if fields.get("priority") else "Normal"
            points = estimate_feature_size(
                fields["summary"], priority,
                component_count=component_count,
                child_issue_count=child_issue_count,
                description=description,
                status=feature_status,
            )
            auto_sized_count += 1

            # Capture detailed sizing metadata from adapter
            if _last_sizing_result:
                sizing_method = _last_sizing_result.get("method", "keyword_heuristic")
                complexity_score = _last_sizing_result.get("complexity_score")
                sizing_confidence = _last_sizing_result.get("confidence")

        # Check if feature is in the plan
        in_plan = key in ranking
        rank = ranking.get(key, 9999)  # Use plan ranking or default to end

        # Get issue type
        issue_type = fields.get("issuetype", {}).get("name", "Feature")

        feature = {
            "key": key,
            "summary": fields["summary"],
            "status": feature_status,
            "priority": fields["priority"]["name"] if fields.get("priority") else "Normal",
            "issue_type": issue_type,
            "points": points,
            "original_points": original_points,
            "auto_sized": points != original_points,
            "fix_versions": fix_versions,
            "target_version": target_version,
            "target_end_date": target_end_date,
            "scheduled_to": scheduled_to,
            "status_category": status_category,
            "labels": labels,
            "rank": rank,
            "in_plan": in_plan,
            "component_count": component_count,
            "sizing_method": sizing_method,
            "complexity_score": complexity_score,
            "sizing_confidence": sizing_confidence,
        }

        features.append(feature)

    # Sort by: in_plan first (True before False), then by rank
    features.sort(key=lambda f: (not f["in_plan"], f["rank"]))

    print(f"  🤖 Auto-sized {auto_sized_count} features with missing story points")

    return features


KNOWN_PRODUCTS = ["RHOAI", "RHAIIS", "RHELAI"]


def _extract_product(scheduled_to):
    """Extract product name from scheduled_to string."""
    upper = scheduled_to.upper()
    for product in KNOWN_PRODUCTS:
        if upper.startswith(product):
            return product
    return "RHOAI"  # default


def group_features_by_release(features):
    """Group features by scheduled release"""
    releases = defaultdict(lambda: {
        "EA1": [],
        "EA2": [],
        "GA": [],
    })

    unscheduled = []

    for feature in features:
        scheduled_to = feature["scheduled_to"]

        if not scheduled_to:
            feature["product"] = "RHOAI"
            unscheduled.append(feature)
            continue

        # Extract product and annotate feature
        product = _extract_product(scheduled_to)
        feature["product"] = product

        # Strip all known product prefixes for event parsing
        scheduled_lower = scheduled_to.lower().replace("_", " ")
        for prefix in KNOWN_PRODUCTS:
            scheduled_lower = scheduled_lower.replace(prefix.lower() + "-", "").replace(prefix.lower(), "")

        # Parse release version (e.g., "rhoai-3.4.EA1" -> release="3.4", event="EA1")
        # Handle formats like: "3.4", "3.4.EA1", "3.4-EA1", "3.4 EA1", "rhaiis-3.4 ea-1"

        # Extract version number (e.g., "3.4" or "2.20")
        version_match = re.search(r'(\d+)\.(\d+)', scheduled_to)

        if version_match:
            major = version_match.group(1)
            minor = version_match.group(2)
            release_num = f"{major}.{minor}"
            release_key = f"{product}-{release_num}"

            # Determine event type
            if "ea1" in scheduled_lower or "ea-1" in scheduled_lower:
                event = "EA1"
            elif "ea2" in scheduled_lower or "ea-2" in scheduled_lower:
                event = "EA2"
            elif "ga" in scheduled_lower:
                event = "GA"
            else:
                # No event specified - default to GA
                event = "GA"

            releases[release_key][event].append(feature)
        else:
            # Couldn't parse version - add to unscheduled
            unscheduled.append(feature)

    return dict(releases), unscheduled


def calculate_release_metrics(release_data):
    """Calculate metrics for each release event"""
    metrics = {}

    for event, features in release_data.items():
        total_points = sum(f["points"] for f in features)
        total_features = len(features)

        # Capacity status
        if total_points <= CAPACITY["conservative_max"]:
            capacity_status = "conservative"
            color = "#28a745"  # green
        elif total_points <= CAPACITY["typical_max"]:
            capacity_status = "typical"
            color = "#90ee90"  # light green
        elif total_points <= CAPACITY["aggressive_max"]:
            capacity_status = "aggressive"
            color = "#ffc107"  # yellow
        else:
            capacity_status = "over_capacity"
            color = "#dc3545"  # red

        vs_median = round((total_points / CAPACITY["median"] - 1) * 100) if total_points > 0 else 0

        metrics[event] = {
            "features": total_features,
            "points": total_points,
            "capacity_status": capacity_status,
            "color": color,
            "vs_median_pct": vs_median
        }

    return metrics


def analyze_feature_phasing(feature):
    """
    Analyze if a feature can be phased across DP/TP/GA
    Returns: {
        "phaseable": bool,
        "recommendation": str,
        "complexity": str
    }
    """
    summary = feature["summary"].lower()
    points = feature["points"]

    # Indicators that feature is large/complex enough to phase
    phase_indicators = [
        "infrastructure", "architecture", "framework", "integration",
        "migration", "platform", "ecosystem", "redesign"
    ]

    # Indicators that feature is atomic (shouldn't be phased)
    atomic_indicators = [
        "fix", "bug", "typo", "documentation", "docs",
        "minor", "small", "adjust", "update config"
    ]

    has_phase_indicator = any(ind in summary for ind in phase_indicators)
    has_atomic_indicator = any(ind in summary for ind in atomic_indicators)

    # Determine if phaseable
    if points >= 8 and has_phase_indicator:
        return {
            "phaseable": True,
            "recommendation": f"Split into phases: DP (basic functionality) → TP (extended features) → GA (production hardening)",
            "complexity": "High"
        }
    elif points >= 8 and not has_atomic_indicator:
        return {
            "phaseable": True,
            "recommendation": f"Consider phasing: DP (core feature) → TP (refinement) → GA (optimization)",
            "complexity": "Medium"
        }
    elif points >= 5 and has_phase_indicator:
        return {
            "phaseable": True,
            "recommendation": f"Potential for DP/TP split, GA for full release",
            "complexity": "Medium"
        }
    elif has_atomic_indicator or points <= 3:
        return {
            "phaseable": False,
            "recommendation": "Deliver as single feature (not complex enough to phase)",
            "complexity": "Low"
        }
    else:
        return {
            "phaseable": False,
            "recommendation": "Deliver in single release event (GA preferred)",
            "complexity": "Low"
        }


def generate_split_recommendation(feature):
    """
    Generate specific splitting recommendations for oversized features
    Returns detailed split strategy or None if feature shouldn't be split
    """
    summary = feature["summary"]
    summary_lower = summary.lower()
    points = feature["points"]

    # Check if feature contains multiple concerns
    has_multiple = any(word in summary_lower for word in ["and", "multiple", "several", "various", "&"])

    if not has_multiple and points < 13:
        return None

    # Analyze what type of split would work best
    split_details = []

    # Infrastructure/Integration features
    if any(word in summary_lower for word in ["infrastructure", "integration", "platform"]):
        split_details = [
            {"name": f"Part 1: Core Infrastructure", "points": 8, "phase": "DP"},
            {"name": f"Part 2: Integration & Testing", "points": 5, "phase": "TP/GA"}
        ]
        reason = "Complex infrastructure work - split into core setup and integration phases"
        suggested_split = "8 pts (core) + 5 pts (integration)"

    # Architecture/Redesign features
    elif any(word in summary_lower for word in ["architecture", "redesign", "refactor"]):
        split_details = [
            {"name": f"Part 1: Design & Foundation", "points": 5, "phase": "DP"},
            {"name": f"Part 2: Implementation", "points": 8, "phase": "TP/GA"}
        ]
        reason = "Architectural work - separate design phase from implementation"
        suggested_split = "5 pts (design) + 8 pts (implementation)"

    # Migration features
    elif "migration" in summary_lower:
        split_details = [
            {"name": f"Part 1: Migration Framework", "points": 5, "phase": "DP"},
            {"name": f"Part 2: Data Migration", "points": 5, "phase": "TP"},
            {"name": f"Part 3: Validation & Cleanup", "points": 3, "phase": "GA"}
        ]
        reason = "Migration complexity - split into framework, execution, and validation"
        suggested_split = "5 pts + 5 pts + 3 pts"

    # Features with "and" - likely multiple concerns
    elif " and " in summary_lower or " & " in summary_lower:
        # Try to identify the two parts
        parts = summary.replace(" and ", "|").replace(" & ", "|").split("|")
        if len(parts) >= 2:
            split_details = [
                {"name": f"Part 1: {parts[0].strip()[:50]}", "points": 8, "phase": "DP/TP"},
                {"name": f"Part 2: {parts[1].strip()[:50]}", "points": 5, "phase": "TP/GA"}
            ]
            reason = "Feature contains multiple concerns - split into separate deliverables"
            suggested_split = "8 pts (first part) + 5 pts (second part)"
        else:
            split_details = [
                {"name": f"Part 1: Core Functionality", "points": 8, "phase": "DP/TP"},
                {"name": f"Part 2: Extended Features", "points": 5, "phase": "GA"}
            ]
            reason = "Large scope - split into core and extended functionality"
            suggested_split = "8 pts (core) + 5 pts (extended)"

    # Default split for other large features
    else:
        split_details = [
            {"name": f"Part 1: Core Functionality", "points": 8, "phase": "DP/TP"},
            {"name": f"Part 2: Refinement & Optimization", "points": 5, "phase": "GA"}
        ]
        reason = "Large feature - split into MVP and refinement phases"
        suggested_split = "8 pts (MVP) + 5 pts (refinement)"

    return {
        "reason": reason,
        "suggested_split": suggested_split,
        "split_details": split_details
    }


def analyze_feature_sizing(features):
    """
    Analyze feature sizing distribution and provide recommendations
    Returns: {
        "distribution": {...},
        "recommendations": [...],
        "oversized": [...],
        "undersized": [...]
    }
    """
    distribution = {
        "XL": {"count": 0, "features": [], "total_points": 0},
        "L": {"count": 0, "features": [], "total_points": 0},
        "M": {"count": 0, "features": [], "total_points": 0},
        "S": {"count": 0, "features": [], "total_points": 0},
        "XS": {"count": 0, "features": [], "total_points": 0}
    }

    total_features = len(features)
    total_points = 0
    oversized = []  # Features that should be split
    undersized = []  # Features that might be combined

    for feature in features:
        points = feature["points"]
        total_points += points

        # Categorize by size
        if points >= 13:
            size = "XL"
        elif points >= 8:
            size = "L"
        elif points >= 5:
            size = "M"
        elif points >= 3:
            size = "S"
        else:
            size = "XS"

        distribution[size]["count"] += 1
        distribution[size]["features"].append(feature)
        distribution[size]["total_points"] += points

        # Identify oversized features (XL that could be split)
        if points >= 13:
            summary_lower = feature["summary"].lower()
            split_recommendation = generate_split_recommendation(feature)

            if split_recommendation:
                oversized.append({
                    "feature": feature,
                    "reason": split_recommendation["reason"],
                    "suggested_split": split_recommendation["suggested_split"],
                    "split_details": split_recommendation["split_details"]
                })

    # Calculate percentages
    for size in distribution:
        distribution[size]["percentage"] = round((distribution[size]["count"] / total_features * 100), 1) if total_features > 0 else 0

    # Generate recommendations
    recommendations = []

    # Check for too many XL features
    xl_pct = distribution["XL"]["percentage"]
    if xl_pct > 15:
        recommendations.append({
            "type": "warning",
            "message": f"{xl_pct}% of features are XL (13 pts). Ideal is <10%. Consider splitting large features into smaller, deliverable increments.",
            "impact": "high"
        })

    # Check for too many M features
    m_pct = distribution["M"]["percentage"]
    if m_pct > 50:
        recommendations.append({
            "type": "info",
            "message": f"{m_pct}% of features are M (5 pts). This is acceptable but consider if some could be S (3 pts) for faster delivery.",
            "impact": "low"
        })

    # Check for good L distribution
    l_pct = distribution["L"]["percentage"]
    if l_pct > 60:
        recommendations.append({
            "type": "warning",
            "message": f"{l_pct}% of features are L (8 pts). High proportion of large features. Consider breaking down into M or S.",
            "impact": "medium"
        })

    # Ideal distribution recommendation
    recommendations.append({
        "type": "success",
        "message": f"Ideal distribution: S(35%), M(40%), L(20%), XL(<5%). Current: S({distribution['S']['percentage']}%), M({distribution['M']['percentage']}%), L({distribution['L']['percentage']}%), XL({distribution['XL']['percentage']}%)",
        "impact": "info"
    })

    return {
        "distribution": distribution,
        "total_features": total_features,
        "total_points": total_points,
        "recommendations": recommendations,
        "oversized": oversized,
        "average_size": round(total_points / total_features, 1) if total_features > 0 else 0
    }


def generate_optimized_plan(features, capacity, sizing_analysis):
    """
    Generate optimized release plan based on sizing recommendations
    Applies feature splitting recommendations and re-schedules
    """
    from copy import deepcopy

    # Create optimized feature list
    optimized_features = []

    for feature in features:
        # Check if feature should be split
        should_split = any(
            rec["feature"]["key"] == feature["key"]
            for rec in sizing_analysis["oversized"]
        )

        if should_split and feature["points"] >= 13:
            # Split XL feature into 2 L features
            base_key = feature["key"]

            # Part 1: Core functionality
            part1 = deepcopy(feature)
            part1["key"] = f"{base_key}-P1"
            part1["summary"] = f"{feature['summary'][:60]}... (Part 1: Core)"
            part1["points"] = 8
            part1["auto_sized"] = False
            part1["optimized"] = True
            optimized_features.append(part1)

            # Part 2: Extended functionality
            part2 = deepcopy(feature)
            part2["key"] = f"{base_key}-P2"
            part2["summary"] = f"{feature['summary'][:60]}... (Part 2: Extended)"
            part2["points"] = 5
            part2["auto_sized"] = False
            part2["optimized"] = True
            optimized_features.append(part2)
        else:
            # Keep feature as-is
            optimized_features.append(feature)

    # Re-run auto-scheduler on optimized features
    from auto_scheduler import auto_schedule_features

    optimized_plan, schedule = auto_schedule_features(
        optimized_features,
        capacity,
        start_version="3.5",
        num_releases=8
    )

    return {
        "plan": optimized_plan,
        "schedule": schedule,
        "features": optimized_features,
        "split_count": len(optimized_features) - len(features)
    }


def analyze_backlog(features):
    """
    Comprehensive backlog analysis
    Returns complete analysis for HTML display
    """
    # 1. Phasing analysis
    phasing_results = []
    phaseable_count = 0

    for feature in features:
        result = analyze_feature_phasing(feature)
        if result["phaseable"]:
            phaseable_count += 1
        phasing_results.append({
            "feature": feature,
            "analysis": result
        })

    # 2. Sizing analysis
    sizing_analysis = analyze_feature_sizing(features)

    # 3. Optimization insights
    insights = {
        "phasing": {
            "total": len(features),
            "phaseable": phaseable_count,
            "percentage": round((phaseable_count / len(features) * 100), 1) if features else 0
        },
        "sizing": sizing_analysis,
        "efficiency_score": calculate_efficiency_score(sizing_analysis)
    }

    return {
        "phasing_results": phasing_results,
        "sizing_analysis": sizing_analysis,
        "insights": insights
    }


def calculate_efficiency_score(sizing_analysis):
    """Calculate delivery efficiency score based on sizing distribution"""
    dist = sizing_analysis["distribution"]

    # Ideal distribution weights
    # Higher score for more S and M features (faster delivery)
    score = 0
    score += dist["S"]["percentage"] * 1.5  # S features get 1.5x weight
    score += dist["M"]["percentage"] * 1.2  # M features get 1.2x weight
    score += dist["L"]["percentage"] * 0.8  # L features get 0.8x weight
    score += dist["XL"]["percentage"] * 0.5  # XL features get 0.5x weight (should be rare)

    # Cap at 100
    return min(100, round(score))


def generate_html(features, releases, unscheduled, capacity, recommended_plan=None, backlog_analysis=None, optimized_plan=None):
    """Generate interactive HTML release manager"""

    # Count features in vs not in plan (before using in HTML)
    in_plan_count = sum(1 for f in unscheduled if f['in_plan'])
    not_in_plan_count = len(unscheduled) - in_plan_count

    # Calculate metrics for all releases
    release_metrics = {}
    for release_num, release_data in releases.items():
        release_metrics[release_num] = calculate_release_metrics(release_data)

    # Prepare recommended plan for embedding
    if recommended_plan:
        # Convert to simpler format for JavaScript
        recommended_plan_js = {}
        for bucket_key, bucket_data in recommended_plan.items():
            recommended_plan_js[bucket_key] = {
                "features": [f["key"] for f in bucket_data["features"]],
                "points": bucket_data["points"],
                "capacity_status": bucket_data["capacity_status"]
            }
    else:
        recommended_plan_js = {}

    # Compute release fit data per-event for the Release Fit tab
    release_fit_data = {}
    if FIT_PREDICTOR_AVAILABLE:
        cap_model = load_capacity_model()
        for release_key, release_data in releases.items():
            release_fit_data[release_key] = {}
            for event_name, event_features in release_data.items():
                event_pts = sum(f["points"] for f in event_features)
                if event_pts > 0:
                    fit = check_release_fit(event_pts, cap_model)
                    release_fit_data[release_key][event_name] = {
                        "total_points": event_pts,
                        "feature_count": len(event_features),
                        **fit,
                    }

    # Sizing method distribution
    sizing_stats = {"complexity_scoring": 0, "keyword_heuristic": 0, "jira_provided": 0, "total": len(features)}
    for f in features:
        method = f.get("sizing_method", "jira_provided")
        if method in sizing_stats:
            sizing_stats[method] += 1

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Red Hat AI Products Release Planner</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #f5f7fa;
            color: #333;
        }}

        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}

        .header h1 {{
            font-size: 24px;
            margin-bottom: 5px;
        }}

        .header p {{
            opacity: 0.9;
            font-size: 14px;
        }}

        .tabs {{
            background: white;
            border-bottom: 2px solid #e1e8ed;
            padding: 0 30px;
        }}

        .tab-button {{
            display: inline-block;
            padding: 15px 25px;
            cursor: pointer;
            border: none;
            background: none;
            font-size: 15px;
            font-weight: 500;
            color: #666;
            border-bottom: 3px solid transparent;
            transition: all 0.3s;
        }}

        .tab-button:hover {{
            color: #667eea;
        }}

        .tab-button.active {{
            color: #667eea;
            border-bottom-color: #667eea;
        }}

        .tab-content {{
            display: none;
            padding: 30px;
        }}

        .tab-content.active {{
            display: block;
        }}

        .planning-layout {{
            display: grid;
            grid-template-columns: 300px 1fr;
            gap: 20px;
            height: calc(100vh - 200px);
        }}

        .feature-pool {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            overflow-y: auto;
        }}

        .feature-pool h2 {{
            font-size: 16px;
            margin-bottom: 15px;
            color: #333;
        }}

        .feature-card {{
            background: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            padding: 12px;
            margin-bottom: 10px;
            cursor: move;
            transition: all 0.2s;
        }}

        .feature-card:hover {{
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            transform: translateY(-2px);
        }}

        .feature-card.dragging {{
            opacity: 0.5;
        }}

        .feature-key {{
            font-weight: 600;
            color: #0052cc;
            font-size: 13px;
            margin-bottom: 4px;
        }}

        .feature-summary {{
            font-size: 13px;
            color: #333;
            margin-bottom: 8px;
            line-height: 1.4;
        }}

        .feature-meta {{
            display: flex;
            gap: 10px;
            font-size: 11px;
            color: #666;
        }}

        .feature-points {{
            background: #e3f2fd;
            padding: 2px 6px;
            border-radius: 3px;
            font-weight: 500;
        }}

        .feature-rank {{
            background: #fff3cd;
            padding: 2px 6px;
            border-radius: 3px;
        }}

        .releases-area {{
            overflow-y: auto;
        }}

        .release-section {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}

        .release-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }}

        .release-title {{
            font-size: 18px;
            font-weight: 600;
        }}

        .release-events {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
        }}

        .event-bucket {{
            background: #f8f9fa;
            border: 2px dashed #dee2e6;
            border-radius: 6px;
            padding: 15px;
            min-height: 200px;
        }}

        .event-bucket.drag-over {{
            background: #e7f3ff;
            border-color: #667eea;
        }}

        .event-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 2px solid #dee2e6;
        }}

        .event-name {{
            font-weight: 600;
            font-size: 14px;
        }}

        .capacity-meter {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 12px;
        }}

        .capacity-bar {{
            width: 60px;
            height: 8px;
            background: #e9ecef;
            border-radius: 4px;
            overflow: hidden;
        }}

        .capacity-fill {{
            height: 100%;
            transition: all 0.3s;
        }}

        .tracking-layout {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        .release-selector {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}

        .release-selector select {{
            padding: 10px 15px;
            font-size: 15px;
            border: 2px solid #dee2e6;
            border-radius: 6px;
            cursor: pointer;
        }}

        .product-filters {{
            display: flex;
            gap: 8px;
            margin-bottom: 12px;
        }}

        .product-btn {{
            padding: 6px 16px;
            border: 2px solid #dee2e6;
            border-radius: 20px;
            background: white;
            cursor: pointer;
            font-size: 13px;
            font-weight: 600;
            transition: all 0.2s;
        }}

        .product-btn:hover {{
            border-color: #0052cc;
            color: #0052cc;
        }}

        .product-btn.active {{
            background: #0052cc;
            color: white;
            border-color: #0052cc;
        }}

        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}

        .metric-card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}

        .metric-label {{
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }}

        .metric-value {{
            font-size: 28px;
            font-weight: 600;
            color: #333;
        }}

        .metric-subtitle {{
            font-size: 12px;
            color: #999;
            margin-top: 4px;
        }}

        .alert {{
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 20px;
        }}

        .alert-info {{
            background: #d1ecf1;
            border-left: 4px solid #0c5460;
            color: #0c5460;
        }}

        .alert-warning {{
            background: #fff3cd;
            border-left: 4px solid #856404;
            color: #856404;
        }}

        .alert-danger {{
            background: #f8d7da;
            border-left: 4px solid #721c24;
            color: #721c24;
        }}

        .feature-table {{
            width: 100%;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}

        .feature-table th {{
            background: #f8f9fa;
            padding: 12px;
            text-align: left;
            font-size: 12px;
            text-transform: uppercase;
            color: #666;
            border-bottom: 2px solid #dee2e6;
        }}

        .feature-table td {{
            padding: 12px;
            border-bottom: 1px solid #dee2e6;
            font-size: 13px;
        }}

        .feature-table tr:hover {{
            background: #f8f9fa;
        }}

        .status-badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 500;
        }}

        .status-new {{ background: #e7e7e7; color: #333; }}
        .status-progress {{ background: #0052cc; color: white; }}
        .status-review {{ background: #ff991f; color: white; }}
        .status-pending {{ background: #00875a; color: white; }}
        .status-closed {{ background: #36b37e; color: white; }}

        .priority-blocker {{ color: #de350b; font-weight: 600; }}
        .priority-critical {{ color: #ff5630; font-weight: 600; }}
        .priority-major {{ color: #ff8b00; }}
        .priority-normal {{ color: #666; }}

        .info-icon {{
            display: inline-block;
            width: 18px;
            height: 18px;
            background: #0052cc;
            color: white;
            border-radius: 50%;
            text-align: center;
            line-height: 18px;
            font-size: 12px;
            cursor: pointer;
            margin-left: 5px;
        }}

        .info-icon:hover {{
            background: #0065ff;
        }}

        .modal {{
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.5);
        }}

        .modal-content {{
            background: white;
            margin: 5% auto;
            padding: 30px;
            border-radius: 10px;
            width: 80%;
            max-width: 700px;
            max-height: 80vh;
            overflow-y: auto;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        }}

        .modal-close {{
            color: #aaa;
            float: right;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
        }}

        .modal-close:hover {{
            color: #000;
        }}

        .info-card {{
            background: #e7f3ff;
            border-left: 4px solid #0052cc;
            padding: 15px;
            margin: 15px 0;
            border-radius: 4px;
        }}

        .info-card h4 {{
            margin: 0 0 8px 0;
            color: #0052cc;
        }}

        .info-card p {{
            margin: 5px 0;
            font-size: 14px;
            line-height: 1.5;
        }}

        .analysis-nav-btn {{
            padding: 10px 20px;
            margin: 0 10px 0 0;
            border: none;
            background: #f5f5f5;
            color: #666;
            cursor: pointer;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.3s;
        }}

        .analysis-nav-btn:hover {{
            background: #e0e0e0;
        }}

        .analysis-nav-btn.active {{
            background: #667eea;
            color: white;
        }}

        .analysis-section {{
            background: white;
            padding: 25px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}

        .metric-box {{
            display: inline-block;
            padding: 15px 20px;
            margin: 10px;
            border-radius: 8px;
            text-align: center;
            min-width: 150px;
        }}

        .metric-box-value {{
            font-size: 32px;
            font-weight: 700;
            margin-bottom: 5px;
        }}

        .metric-box-label {{
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
        }}

        .recommendation-box {{
            padding: 15px;
            margin: 10px 0;
            border-left: 4px solid;
            border-radius: 4px;
        }}

        .recommendation-high {{
            background: #fff5f5;
            border-color: #dc3545;
        }}

        .recommendation-medium {{
            background: #fff8e6;
            border-color: #ffc107;
        }}

        .recommendation-low {{
            background: #f0f7ff;
            border-color: #0052cc;
        }}

        .recommendation-success {{
            background: #f0fff4;
            border-color: #28a745;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Red Hat AI Products Release Planner</h1>
        <p>Multi-product release tracking and capacity planning | Data from JIRA Plan: {PLAN_NAME}</p>
    </div>

    <div class="tabs">
        <button class="tab-button active" onclick="switchTab('tracking', this)">📊 Track Current Release Cycles</button>
        <button class="tab-button" onclick="switchTab('drafts', this)">📝 Draft Release Plans</button>
        <button class="tab-button" onclick="switchTab('analysis', this)">🔬 Feature Analysis</button>
        <button class="tab-button" onclick="switchTab('releasefit', this)">🎯 Release Fit</button>
        <button class="tab-button" onclick="showHelp()" style="margin-left:auto;background:#f8f9fa;color:#333;">❓ Help</button>
    </div>

    <!-- TRACKING TAB (DEFAULT) -->
    <div id="tracking-tab" class="tab-content active">
        <div class="tracking-layout">
            <div class="release-selector">
                <label for="release-select"><strong>Select Release Cycle to Track:</strong>
                    <span class="info-icon" onclick="showInfo('release-cycle')">ℹ️</span>
                </label>
                <div class="product-filters">
"""

    # Build product filter buttons dynamically
    products_in_data = sorted(set(k.split("-")[0] for k in releases.keys()))
    html += '                    <button class="product-btn active" onclick="filterProduct(\'ALL\', this)">ALL</button>\n'
    for prod in products_in_data:
        html += f'                    <button class="product-btn" onclick="filterProduct(\'{prod}\', this)">{prod}</button>\n'

    html += """                </div>
                <select id="release-select" onchange="loadRelease(this.value)">
                    <option value="">-- Select Release Cycle --</option>
"""

    # Add existing releases to dropdown using composite keys
    for release_key in sorted(releases.keys(), reverse=True):
        html += f'                    <option value="{release_key}" data-product="{release_key.split("-")[0]}">{release_key}</option>\n'

    html += """
                </select>
                <p style="font-size:12px;color:#666;margin-top:8px;">
                    Each release cycle includes 3 events: EA1, EA2, and GA
                </p>
            </div>

            <div id="release-details">
                <div class="alert alert-info">
                    <strong>👆 Select a release cycle above</strong> to view tracking details for all 3 events (EA1, EA2, GA)
                </div>
            </div>
        </div>
    </div>

    <!-- DRAFT PLANS TAB -->
    <div id="drafts-tab" class="tab-content">
        <div style="max-width: 1400px; margin: 0 auto;">
            <div class="product-filters" id="drafts-product-filters">
"""

    html += '                <button class="product-btn active" onclick="filterDraftsProduct(\'ALL\', this)">ALL</button>\n'
    for prod in products_in_data:
        html += f'                <button class="product-btn" onclick="filterDraftsProduct(\'{prod}\', this)">{prod}</button>\n'

    html += """            </div>
            <div class="alert alert-info">
                <strong>📝 AI-Recommended 2-Year Release Plan</strong>
                <span class="info-icon" onclick="showInfo('draft-plan')">ℹ️</span>
                <p style="margin-top: 10px; font-size: 14px;">
                    This plan was generated by the auto-scheduler based on:
                    <br>• Priority ranking from JIRA Plan
                    <br>• Feature story points
                    <br>• Capacity guidelines (target 50 pts/event, max 80 pts/event)
                </p>
            </div>

            <div id="draft-plan-display">
                <!-- Populated by JavaScript -->
            </div>
        </div>
    </div>

    <!-- FEATURE ANALYSIS TAB -->
    <div id="analysis-tab" class="tab-content">
        <div style="max-width: 1400px; margin: 0 auto;">
            <div class="product-filters" id="analysis-product-filters">
"""

    html += '                <button class="product-btn active" onclick="filterAnalysisProduct(\'ALL\', this)">ALL</button>\n'
    for prod in products_in_data:
        html += f'                <button class="product-btn" onclick="filterAnalysisProduct(\'{prod}\', this)">{prod}</button>\n'

    html += """            </div>
            <div class="alert alert-info">
                <strong>🔬 Feature Backlog Analysis & Optimization</strong>
                <span class="info-icon" onclick="showInfo('analysis')">ℹ️</span>
                <p style="margin-top: 10px; font-size: 14px;">
                    Comprehensive analysis of your feature backlog for optimal delivery:
                    <br>• DP/TP/GA phasing recommendations
                    <br>• Feature sizing distribution and optimization
                    <br>• Delivery efficiency scoring
                    <br>• Optimized release plan based on best practices
                </p>
            </div>

            <!-- Navigation within Analysis tab -->
            <div style="background: white; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                <button onclick="showAnalysisSection('phasing')" class="analysis-nav-btn active" id="btn-phasing">
                    📋 Phasing Analysis
                </button>
                <button onclick="showAnalysisSection('sizing')" class="analysis-nav-btn" id="btn-sizing">
                    📏 Sizing Analysis
                </button>
                <button onclick="showAnalysisSection('recommendations')" class="analysis-nav-btn" id="btn-recommendations">
                    💡 Recommendations
                </button>
                <button onclick="showAnalysisSection('optimized')" class="analysis-nav-btn" id="btn-optimized">
                    🎯 Optimized Draft Plans
                </button>
            </div>

            <!-- Section 1: Phasing Analysis -->
            <div id="analysis-phasing" class="analysis-section">
                <!-- Populated by JavaScript -->
            </div>

            <!-- Section 2: Sizing Analysis -->
            <div id="analysis-sizing" class="analysis-section" style="display:none;">
                <!-- Populated by JavaScript -->
            </div>

            <!-- Section 3: Recommendations -->
            <div id="analysis-recommendations" class="analysis-section" style="display:none;">
                <!-- Populated by JavaScript -->
            </div>

            <!-- Section 4: Optimized Plan -->
            <div id="analysis-optimized" class="analysis-section" style="display:none;">
                <!-- Populated by JavaScript -->
            </div>
        </div>
    </div>

    <!-- RELEASE FIT TAB -->
    <div id="releasefit-tab" class="tab-content">
        <div style="max-width: 1400px; margin: 0 auto;">
            <div class="product-filters" id="fit-product-filters">
"""

    html += '                <button class="product-btn active" onclick="filterFitProduct(\'ALL\', this)">ALL</button>\n'
    for prod in products_in_data:
        html += f'                <button class="product-btn" onclick="filterFitProduct(\'{prod}\', this)">{prod}</button>\n'

    html += """            </div>
            <div class="alert alert-info">
                <strong>🎯 Release Fit Predictor</strong>
                <p style="margin-top: 10px; font-size: 14px;">
                    Data-driven release capacity analysis using a statistical model trained on
                    571 features across 41 releases. Complexity scoring (0-12 scale) replaces
                    simple keyword heuristics for more accurate auto-sizing.
                </p>
            </div>

            <div id="releasefit-content">
                <!-- Populated by JavaScript -->
            </div>
        </div>
    </div>

    <script>
        // Store all data
        const jiraBaseUrl = """ + json.dumps(JIRA_BASE_URL) + """;
        const allReleases = """ + json.dumps(releases, indent=2) + """;
        const releaseMetrics = """ + json.dumps(release_metrics, indent=2) + """;
        const capacity = """ + json.dumps(capacity, indent=2) + """;
        const allProducts = """ + json.dumps(products_in_data, indent=2) + """;
        const recommendedPlan = """ + json.dumps(recommended_plan_js, indent=2) + """;

        // Backlog analysis data
        const backlogAnalysis = """ + json.dumps(backlog_analysis if backlog_analysis else {}, indent=2) + """;

        // Full feature lookup for getting names and details
        const allFeatures = """ + json.dumps({f["key"]: {"summary": f["summary"], "points": f["points"], "product": f.get("product", "RHOAI"), "issue_type": f.get("issue_type", "Feature")} for f in features}, indent=2) + """;

        // Optimized plan data with full feature info
        const optimizedPlanData = """ + json.dumps(
            {
                "plan": {k: {
                    "features": [{"key": f["key"], "summary": f["summary"], "points": f["points"]} for f in v["features"]],
                    "points": v["points"],
                    "capacity_status": v["capacity_status"]
                } for k, v in optimized_plan["plan"].items()} if optimized_plan else {},
                "split_count": optimized_plan["split_count"] if optimized_plan else 0
            }, indent=2) + """;

        // Release Fit Predictor data
        const capacityModel = """ + json.dumps(_capacity_model if _capacity_model else {}, indent=2) + """;
        const releaseFitData = """ + json.dumps(release_fit_data, indent=2) + """;
        const sizingStats = """ + json.dumps(sizing_stats, indent=2) + """;
        const fitPredictorAvailable = """ + json.dumps(FIT_PREDICTOR_AVAILABLE) + """;

        // Product filter state
        let currentDraftsProduct = 'ALL';
        let currentAnalysisProduct = 'ALL';
        let currentFitProduct = 'ALL';

        // Feature lookup for quick access
        const featureElements = {};

        document.addEventListener('DOMContentLoaded', function() {
            // Build feature element lookup
            document.querySelectorAll('.feature-card').forEach(card => {
                featureElements[card.dataset.key] = card;
            });
            // Render release fit tab content
            if (fitPredictorAvailable) {
                renderReleaseFitTab();
            }
        });

        // Tab switching
        function switchTab(tab, btn) {
            document.querySelectorAll('.tab-button').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

            btn.classList.add('active');
            document.getElementById(tab + '-tab').classList.add('active');
        }

        // Product filtering for tracking tab
        function filterProduct(product, btn) {
            // Toggle active button
            document.querySelectorAll('.product-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            // Show/hide dropdown options
            const select = document.getElementById('release-select');
            const options = select.querySelectorAll('option[data-product]');
            options.forEach(opt => {
                if (product === 'ALL' || opt.dataset.product === product) {
                    opt.style.display = '';
                } else {
                    opt.style.display = 'none';
                }
            });

            // Reset selection and detail view
            select.value = '';
            document.getElementById('release-details').innerHTML = `
                <div class="alert alert-info">
                    <strong>👆 Select a release cycle above</strong> to view tracking details for all 3 events (EA1, EA2, GA)
                </div>
            `;
        }

        // Product filtering for drafts tab
        function filterDraftsProduct(product, btn) {
            document.querySelectorAll('#drafts-product-filters .product-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentDraftsProduct = product;
            renderDraftPlan();
        }

        // Product filtering for analysis tab
        function filterAnalysisProduct(product, btn) {
            document.querySelectorAll('#analysis-product-filters .product-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentAnalysisProduct = product;
            renderAnalysis();
        }

        // Product filtering for release fit tab
        function filterFitProduct(product, btn) {
            document.querySelectorAll('#fit-product-filters .product-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentFitProduct = product;
            renderReleaseFitTab();
        }

        // Load release tracking details
        function loadRelease(releaseKey) {
            if (!releaseKey) {
                document.getElementById('release-details').innerHTML = `
                    <div class="alert alert-info">Select a release above to view tracking details</div>
                `;
                return;
            }

            const releaseData = allReleases[releaseKey];
            const metrics = releaseMetrics[releaseKey];

            if (!releaseData) {
                document.getElementById('release-details').innerHTML = `
                    <div class="alert alert-warning">No data found for ${releaseKey}</div>
                `;
                return;
            }

            // Calculate totals
            let totalFeatures = 0;
            let totalPoints = 0;
            for (const ev in metrics) {
                totalFeatures += metrics[ev].features;
                totalPoints += metrics[ev].points;
            }

            const vsHistorical = (totalPoints / capacity.historical_max_release * 100).toFixed(0);

            let html = `
                <div class="metrics-grid">
                    <div class="metric-card">
                        <div class="metric-label">Total Features</div>
                        <div class="metric-value">${totalFeatures}</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">Total Points</div>
                        <div class="metric-value">${totalPoints}</div>
                        <div class="metric-subtitle">${vsHistorical}% of historical max</div>
                    </div>
            `;

            // Add per-event metric cards dynamically
            for (const ev of ['EA1', 'EA2', 'GA']) {
                if (metrics[ev] && metrics[ev].features > 0) {
                    const pct = metrics[ev].vs_median_pct;
                    html += `
                    <div class="metric-card">
                        <div class="metric-label">${ev}</div>
                        <div class="metric-value">${metrics[ev].points}</div>
                        <div class="metric-subtitle">${metrics[ev].features} features (${pct > 0 ? '+' : ''}${pct}%)</div>
                    </div>
                    `;
                }
            }

            html += '</div>';

            // Add capacity warnings
            if (totalPoints > capacity.aggressive_max) {
                html += `
                    <div class="alert alert-danger">
                        <strong>⚠️ Over Capacity:</strong> ${totalPoints} points exceeds aggressive threshold (${capacity.aggressive_max} pts).
                        This release is ${vsHistorical}% of historical maximum. Consider descoping.
                    </div>
                `;
            } else if (totalPoints > capacity.typical_max) {
                html += `
                    <div class="alert alert-warning">
                        <strong>⚠️ Aggressive Scope:</strong> ${totalPoints} points is above typical capacity (${capacity.typical_max} pts).
                        Requires strong execution and may need mitigations.
                    </div>
                `;
            }

            for (const event of ['EA1', 'EA2', 'GA']) {
                const features = releaseData[event];
                if (features && features.length > 0) {
                    html += `
                        <div class="metric-card" style="grid-column: 1 / -1; margin-top: 10px;">
                            <h3 style="margin-bottom: 15px;">${event} Features (${features.length})</h3>
                            <table class="feature-table">
                                <thead>
                                    <tr>
                                        <th>Key</th>
                                        <th>Summary</th>
                                        <th>Status</th>
                                        <th>Priority</th>
                                        <th>Points</th>
                                    </tr>
                                </thead>
                                <tbody>
                    `;

                    features.forEach(f => {
                        const statusClass = 'status-' + f.status.toLowerCase().replace(/[^a-z]/g, '');
                        const priorityClass = 'priority-' + f.priority.toLowerCase();
                        const typeBadge = f.issue_type === 'Initiative'
                            ? '<span style="display:inline-block;font-size:11px;padding:1px 6px;border-radius:3px;background:#e3fcef;color:#006644;margin-left:6px;">Initiative</span>'
                            : '<span style="display:inline-block;font-size:11px;padding:1px 6px;border-radius:3px;background:#deebff;color:#0747a6;margin-left:6px;">Feature</span>';
                        html += `
                                    <tr>
                                        <td><a href="${jiraBaseUrl}/browse/${f.key}" target="_blank">${f.key}</a>${typeBadge}</td>
                                        <td>${f.summary}</td>
                                        <td><span class="status-badge ${statusClass}">${f.status}</span></td>
                                        <td class="${priorityClass}">${f.priority}</td>
                                        <td><strong>${f.points}</strong></td>
                                    </tr>
                        `;
                    });

                    html += `
                                </tbody>
                            </table>
                        </div>
                    `;
                }
            }

            document.getElementById('release-details').innerHTML = html;
        }

        // Release Fit tab rendering
        function renderReleaseFitTab() {
            const container = document.getElementById('releasefit-content');
            if (!container) return;

            let html = '';

            // Capacity Model Summary
            html += renderCapacityModelSummary();

            // Sizing Method Distribution
            html += renderSizingMethodDistribution();

            // Per-release fit assessments
            html += renderReleaseFitAssessments();

            container.innerHTML = html;
        }

        function renderCapacityModelSummary() {
            if (!capacityModel || !capacityModel.releases_analyzed) {
                return '<div class="alert alert-warning">Capacity model not available. Ensure the Release Fit Predictor submodule is initialized.</div>';
            }
            const m = capacityModel;
            return `
                <div class="analysis-section" style="margin-bottom:20px;">
                    <h3 style="margin-bottom:15px;">📊 Capacity Model Summary</h3>
                    <p style="color:#666;margin-bottom:15px;">Statistical model based on ${m.releases_analyzed} historical releases (${m.releases_in_ci} within ${m.confidence_level} confidence interval, ${m.outliers_removed} outliers removed)</p>
                    <div style="display:flex;flex-wrap:wrap;gap:15px;">
                        <div class="metric-box" style="background:#e8f5e9;flex:1;min-width:140px;">
                            <div class="metric-box-value" style="color:#2e7d32;">${m.median_points}</div>
                            <div>Median pts/release</div>
                        </div>
                        <div class="metric-box" style="background:#e3f2fd;flex:1;min-width:140px;">
                            <div class="metric-box-value" style="color:#1565c0;">${m.mean_points.toFixed(1)}</div>
                            <div>Mean pts/release</div>
                        </div>
                        <div class="metric-box" style="background:#fff3e0;flex:1;min-width:140px;">
                            <div class="metric-box-value" style="color:#e65100;">${m.std_dev.toFixed(1)}</div>
                            <div>Std Deviation</div>
                        </div>
                        <div class="metric-box" style="background:#fce4ec;flex:1;min-width:140px;">
                            <div class="metric-box-value" style="color:#c62828;">${m.min_points} - ${m.max_points}</div>
                            <div>${m.confidence_level} CI Range</div>
                        </div>
                    </div>
                </div>
            `;
        }

        function renderSizingMethodDistribution() {
            const s = sizingStats;
            if (!s || s.total === 0) return '';
            const pctComplexity = (s.complexity_scoring / s.total * 100).toFixed(1);
            const pctKeyword = (s.keyword_heuristic / s.total * 100).toFixed(1);
            const pctJira = (s.jira_provided / s.total * 100).toFixed(1);
            return `
                <div class="analysis-section" style="margin-bottom:20px;">
                    <h3 style="margin-bottom:15px;">📏 Sizing Method Distribution</h3>
                    <p style="color:#666;margin-bottom:15px;">How features were sized across ${s.total} total features</p>
                    <table style="width:100%;border-collapse:collapse;">
                        <thead>
                            <tr style="border-bottom:2px solid #ddd;text-align:left;">
                                <th style="padding:8px;">Method</th>
                                <th style="padding:8px;">Count</th>
                                <th style="padding:8px;">Percentage</th>
                                <th style="padding:8px;width:50%;">Distribution</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr style="border-bottom:1px solid #eee;">
                                <td style="padding:8px;">🎯 JIRA-Provided</td>
                                <td style="padding:8px;">${s.jira_provided}</td>
                                <td style="padding:8px;">${pctJira}%</td>
                                <td style="padding:8px;"><div style="background:#28a745;height:20px;border-radius:4px;width:${pctJira}%;min-width:2px;"></div></td>
                            </tr>
                            <tr style="border-bottom:1px solid #eee;">
                                <td style="padding:8px;">🧠 Complexity Scoring</td>
                                <td style="padding:8px;">${s.complexity_scoring}</td>
                                <td style="padding:8px;">${pctComplexity}%</td>
                                <td style="padding:8px;"><div style="background:#0052cc;height:20px;border-radius:4px;width:${pctComplexity}%;min-width:2px;"></div></td>
                            </tr>
                            <tr style="border-bottom:1px solid #eee;">
                                <td style="padding:8px;">🔤 Keyword Heuristic</td>
                                <td style="padding:8px;">${s.keyword_heuristic}</td>
                                <td style="padding:8px;">${pctKeyword}%</td>
                                <td style="padding:8px;"><div style="background:#fd7e14;height:20px;border-radius:4px;width:${pctKeyword}%;min-width:2px;"></div></td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            `;
        }

        function renderReleaseFitAssessments() {
            const releaseKeys = Object.keys(releaseFitData).sort();
            if (releaseKeys.length === 0) return '<div class="alert alert-warning">No release fit data available.</div>';

            // Group release keys by product
            const byProduct = {};
            for (const rk of releaseKeys) {
                const product = rk.split('-')[0];
                if (!byProduct[product]) byProduct[product] = [];
                byProduct[product].push(rk);
            }

            const levelLabels = {
                'EASILY_FITS': 'Easily Fits',
                'FITS_WELL': 'Fits Well',
                'FITS': 'Fits',
                'TIGHT_FIT': 'Tight Fit',
                'EXCEEDS_CAPACITY': 'Exceeds Capacity'
            };

            let html = '<div class="analysis-section"><h3 style="margin-bottom:15px;">🎯 Per-Event Fit Assessment</h3>';
            html += '<p style="color:#666;margin-bottom:15px;">Each event (EA1, EA2, GA) is assessed independently against the per-event capacity median.</p>';

            for (const product of Object.keys(byProduct).sort()) {
                if (currentFitProduct !== 'ALL' && product !== currentFitProduct) continue;
                html += '<h4 style="margin:20px 0 12px;border-bottom:2px solid #dee2e6;padding-bottom:6px;">' + product + '</h4>';

                for (const rk of byProduct[product]) {
                    const events = releaseFitData[rk];
                    const eventNames = Object.keys(events).sort((a,b) => {
                        const order = {EA1:0, EA2:1, GA:2};
                        return (order[a] ?? 4) - (order[b] ?? 4);
                    });
                    if (eventNames.length === 0) continue;

                    html += '<h5 style="margin:12px 0 8px;color:#555;">' + rk + '</h5>';
                    html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;margin-bottom:16px;">';

                    for (const ev of eventNames) {
                        const d = events[ev];
                        const label = levelLabels[d.level] || d.level;
                        const barPct = Math.min(d.pct_of_median, 200) / 2;

                        html += `
                            <div style="background:white;border:2px solid ${d.color};border-radius:8px;padding:14px;">
                                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                                    <h4 style="margin:0;font-size:15px;">${ev}</h4>
                                    <span style="background:${d.color};color:white;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;">${label}</span>
                                </div>
                                <div style="margin-bottom:6px;">
                                    <span style="font-size:22px;font-weight:700;">${d.total_points}</span>
                                    <span style="color:#666;font-size:13px;"> pts across ${d.feature_count} features</span>
                                </div>
                                <div style="background:#eee;border-radius:4px;height:10px;margin-bottom:6px;">
                                    <div style="background:${d.color};height:10px;border-radius:4px;width:${barPct}%;"></div>
                                </div>
                                <div style="font-size:11px;color:#666;">
                                    ${d.pct_of_median}% of median |
                                    ${d.remaining_to_typical > 0 ? d.remaining_to_typical + ' pts remaining' : Math.abs(d.remaining_to_typical) + ' pts over typical max'}
                                </div>
                            </div>
                        `;
                    }
                    html += '</div>';
                }
            }
            html += '</div>';
            return html;
        }

        // Help and info functions
        function showHelp() {
            document.getElementById('help-modal').style.display = 'block';
        }

        function showInfo(topic) {
            const infoContent = {
                'release-cycle': `
                    <h3>About Release Cycles</h3>
                    <div class="info-card">
                        <h4>What is a Release Cycle?</h4>
                        <p>Each RHOAI release (e.g., 3.4, 3.5) is a quarterly release cycle with 3 distinct events:</p>
                        <ul>
                            <li><strong>EA1 (Early Access 1):</strong> First preview release</li>
                            <li><strong>EA2 (Early Access 2):</strong> Second preview release</li>
                            <li><strong>GA (General Availability):</strong> Production-ready release</li>
                        </ul>
                    </div>
                    <div class="info-card">
                        <h4>Fix Version vs Target Version</h4>
                        <p><strong>Fix Version:</strong> Feature is <em>committed</em> and approved for this release event</p>
                        <p><strong>Target Version:</strong> Feature is <em>intended</em> for this release event but not yet committed</p>
                    </div>
                    <div class="info-card">
                        <h4>Default to GA</h4>
                        <p>Features with only a version number (e.g., "3.5") but no specific event (EA1/EA2) default to the GA release event.</p>
                    </div>
                `,
                'capacity': `
                    <h3>Capacity Guidelines</h3>
                    <div class="info-card">
                        <h4>Story Points per Event</h4>
                        <ul>
                            <li>🟢 <strong>Conservative:</strong> ≤30 pts - Low risk</li>
                            <li>🟡 <strong>Typical:</strong> 30-50 pts - Normal capacity</li>
                            <li>🟠 <strong>Aggressive:</strong> 50-80 pts - High load, needs mitigations</li>
                            <li>🔴 <strong>Over Capacity:</strong> >80 pts - Extremely risky</li>
                        </ul>
                        <p><strong>Historical baseline:</strong> Median 27.5 pts/event, Max 140 pts per entire release</p>
                    </div>
                `,
                'draft-plan': `
                    <h3>About Draft Release Plans</h3>
                    <div class="info-card">
                        <h4>How the AI Scheduler Works</h4>
                        <p>The auto-scheduler distributes unscheduled features across future releases using:</p>
                        <ul>
                            <li><strong>Priority First:</strong> Features ranked in JIRA Plan are scheduled before others</li>
                            <li><strong>Capacity Aware:</strong> Targets ~50 pts per event (typical capacity)</li>
                            <li><strong>Hard Limits:</strong> Will not exceed 80 pts per event (aggressive max)</li>
                            <li><strong>Sequential Fill:</strong> Fills 3.5 EA1 → EA2 → GA → 3.6 EA1 → etc.</li>
                        </ul>
                    </div>
                `,
                'analysis': `
                    <h3>About Feature Analysis</h3>
                    <div class="info-card">
                        <h4>Phasing Analysis (DP/TP/GA)</h4>
                        <p>Evaluates which features are large or complex enough to benefit from phased delivery:</p>
                        <ul>
                            <li><strong>Dev Preview (DP):</strong> Early release for initial customer feedback</li>
                            <li><strong>Tech Preview (TP):</strong> Refinement based on feedback</li>
                            <li><strong>General Availability (GA):</strong> Production-ready release</li>
                        </ul>
                        <p>Features with 8+ story points and appropriate complexity are candidates for phasing.</p>
                    </div>
                    <div class="info-card">
                        <h4>Sizing Distribution Analysis</h4>
                        <p>Shows breakdown of features by size (XS/S/M/L/XL) and compares to ideal distribution:</p>
                        <ul>
                            <li>S (3 pts): 35% - Fast delivery</li>
                            <li>M (5 pts): 40% - Balanced value</li>
                            <li>L (8 pts): 20% - Acceptable if necessary</li>
                            <li>XL (13 pts): &lt;5% - Should be rare, consider splitting</li>
                        </ul>
                        <p><strong>Efficiency Score:</strong> Weighted score based on distribution (target: 80+)</p>
                    </div>
                    <div class="info-card">
                        <h4>Recommendations</h4>
                        <p>Specific suggestions for improving delivery efficiency:</p>
                        <ul>
                            <li>Which XL features should be split into smaller deliverables</li>
                            <li>How current distribution compares to ideal targets</li>
                            <li>Expected benefits of optimization (faster delivery, better planning)</li>
                        </ul>
                    </div>
                    <div class="info-card">
                        <h4>Optimized Plan</h4>
                        <p>Shows 2-year plan with recommended optimizations applied:</p>
                        <ul>
                            <li>Large features automatically split into smaller parts</li>
                            <li>Capacity limits strictly enforced</li>
                            <li>Compare to original plan to see potential improvements</li>
                        </ul>
                    </div>
                `
            };

            if (infoContent[topic]) {
                document.getElementById('info-modal-content').innerHTML = infoContent[topic];
                document.getElementById('info-modal').style.display = 'block';
            }
        }

        // Render draft plan
        function renderDraftPlan() {
            const container = document.getElementById('draft-plan-display');

            if (!recommendedPlan || Object.keys(recommendedPlan).length === 0) {
                container.innerHTML = `
                    <div class="alert alert-warning">
                        <strong>⚠️ No draft plan available</strong>
                        <p>The auto-scheduler was unable to generate a recommended plan. This may be because:</p>
                        <ul>
                            <li>No unscheduled features with story points were found</li>
                            <li>The auto-scheduler module is not available</li>
                        </ul>
                    </div>
                `;
                return;
            }

            // Group by release version
            const quarters = {
                "3.5": "Q2 2026", "3.6": "Q3 2026", "3.7": "Q4 2026", "3.8": "Q1 2027",
                "3.9": "Q2 2027", "3.10": "Q3 2027", "3.11": "Q4 2027", "3.12": "Q1 2028"
            };

            // Release goals based on key themes
            const releaseGoals = {
                "3.5": "Focus on distributed inference improvements, model serving enhancements, and evaluation capabilities.",
                "3.6": "Advance observability and showback features, API parity improvements, and agent metadata support.",
                "3.7": "Enhance AI safety tools, Kubeflow migration support, and model catalog customization.",
                "3.8": "Strengthen agentic framework support, Ray training improvements, and MLflow integration.",
                "3.9": "Expand RBAC capabilities, AutoML integration, and vLLM CPU support for broader deployment.",
                "3.10": "Deepen multilingual support, MCP server integration, and OIDC authentication across components.",
                "3.11": "Advance FIPS compliance, data science pipeline UX, and inference graph capabilities.",
                "3.12": "Refine IDE integration, Feature Store RBAC, and lifecycle documentation for enterprise readiness."
            };

            const releases = {};
            for (const bucketKey in recommendedPlan) {
                const [version, event] = bucketKey.split('-');
                if (!releases[version]) {
                    releases[version] = { EA1: null, EA2: null, GA: null };
                }
                releases[version][event] = recommendedPlan[bucketKey];
            }

            // Apply product filter
            if (currentDraftsProduct !== 'ALL') {
                for (const version in releases) {
                    for (const event in releases[version]) {
                        if (releases[version][event]) {
                            const orig = releases[version][event];
                            const filtered = orig.features.filter(key => {
                                const f = allFeatures[key];
                                return f && f.product === currentDraftsProduct;
                            });
                            const pts = filtered.reduce((s, key) => s + (allFeatures[key] ? allFeatures[key].points : 0), 0);
                            releases[version][event] = {
                                features: filtered,
                                points: pts,
                                capacity_status: pts <= 30 ? 'conservative' : pts <= 50 ? 'typical' : pts <= 80 ? 'aggressive' : 'over_capacity'
                            };
                        }
                    }
                }
            }

            let html = '';

            // Render each release (only 3.4 and after)
            const sortedVersions = Object.keys(releases)
                .filter(v => parseFloat(v) >= 3.4)
                .sort((a, b) => {
                    const aNum = parseFloat(a);
                    const bNum = parseFloat(b);
                    return aNum - bNum;
                });

            for (const version of sortedVersions) {
                const releaseData = releases[version];
                const quarter = quarters[version] || '';

                // Calculate release totals
                let releaseTotalFeatures = 0;
                let releaseTotalPoints = 0;
                for (const event in releaseData) {
                    if (releaseData[event]) {
                        releaseTotalFeatures += releaseData[event].features.length;
                        releaseTotalPoints += releaseData[event].points;
                    }
                }

                const goals = releaseGoals[version] || 'Planned feature delivery for this release cycle.';

                html += `
                    <div style="background: white; border-radius: 8px; padding: 25px; margin-bottom: 25px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                        <h2 style="margin: 0 0 10px 0; color: #333; border-bottom: 2px solid #667eea; padding-bottom: 10px;">
                            RHOAI-${version}
                            <span style="font-size: 16px; color: #666; font-weight: normal;">(${quarter})</span>
                            <span style="float: right; font-size: 16px; font-weight: normal; color: #666;">
                                ${releaseTotalFeatures} features, ${releaseTotalPoints} pts total
                            </span>
                        </h2>
                        <div style="background: #f0f7ff; border-left: 4px solid #667eea; padding: 12px 15px; margin: 0 0 20px 0; border-radius: 4px;">
                            <strong style="color: #667eea; font-size: 14px;">Release Goals:</strong>
                            <p style="margin: 5px 0 0 0; color: #555; font-size: 14px; line-height: 1.5;">${goals}</p>
                        </div>
                        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px;">
                `;

                // Render each event
                for (const event of ['EA1', 'EA2', 'GA']) {
                    const eventData = releaseData[event];

                    if (eventData && eventData.features.length > 0) {
                        const statusIcon = {
                            'conservative': '🟢',
                            'typical': '🟡',
                            'aggressive': '🟠',
                            'over_capacity': '🔴'
                        }[eventData.capacity_status] || '⚪';

                        const statusColor = {
                            'conservative': '#28a745',
                            'typical': '#90ee90',
                            'aggressive': '#ffc107',
                            'over_capacity': '#dc3545'
                        }[eventData.capacity_status] || '#ccc';

                        html += `
                            <div style="background: #f8f9fa; border-radius: 6px; padding: 15px; border-left: 4px solid ${statusColor};">
                                <h3 style="margin: 0 0 10px 0; font-size: 16px; color: #333;">
                                    ${event} ${statusIcon}
                                </h3>
                                <p style="margin: 0 0 10px 0; font-size: 14px; color: #666;">
                                    <strong>${eventData.features.length} features, ${eventData.points} pts</strong>
                                    <br>
                                    <em style="font-size: 12px;">${eventData.capacity_status.replace('_', ' ')}</em>
                                </p>
                        `;

                        // Calculate size distribution for this event
                        const sizeDistribution = { XL: 0, L: 0, M: 0, S: 0, XS: 0 };
                        eventData.features.forEach(key => {
                            const feature = allFeatures[key];
                            if (feature) {
                                const pts = feature.points;
                                if (pts >= 13) sizeDistribution.XL++;
                                else if (pts >= 8) sizeDistribution.L++;
                                else if (pts >= 5) sizeDistribution.M++;
                                else if (pts >= 3) sizeDistribution.S++;
                                else sizeDistribution.XS++;
                            }
                        });

                        // Show size summary
                        html += `
                                <div style="background: white; padding: 8px; border-radius: 4px; margin-bottom: 10px; font-size: 11px;">
                                    <strong>Sizes:</strong>
                        `;
                        ['XL', 'L', 'M', 'S', 'XS'].forEach(size => {
                            if (sizeDistribution[size] > 0) {
                                html += ` <span style="background: #e0e0e0; padding: 2px 5px; border-radius: 2px; margin: 0 2px;">${size}:${sizeDistribution[size]}</span>`;
                            }
                        });
                        html += `</div>`;

                        // Show feature list with names and sizes
                        html += `<div style="max-height: 200px; overflow-y: auto;">`;
                        eventData.features.forEach(key => {
                            const feature = allFeatures[key];
                            if (feature) {
                                const pts = feature.points;
                                const size = pts >= 13 ? 'XL' : pts >= 8 ? 'L' : pts >= 5 ? 'M' : pts >= 3 ? 'S' : 'XS';
                                html += `
                                    <div style="padding: 6px 0; border-bottom: 1px solid #eee; font-size: 11px;">
                                        <div style="font-weight: 600; color: #0052cc; margin-bottom: 2px;">
                                            ${key}
                                            <span style="background: #667eea; color: white; padding: 1px 4px; border-radius: 2px; font-size: 10px; margin-left: 4px;">${pts}pts ${size}</span>
                                        </div>
                                        <div style="color: #666; font-size: 10px;">${feature.summary.substring(0, 80)}${feature.summary.length > 80 ? '...' : ''}</div>
                                    </div>
                                `;
                            } else {
                                html += `<div style="padding: 3px 0; color: #0052cc;">• ${key}</div>`;
                            }
                        });
                        html += `</div>`;

                        html += `
                            </div>
                        `;
                    } else {
                        // Empty event
                        html += `
                            <div style="background: #f8f9fa; border-radius: 6px; padding: 15px; border-left: 4px solid #ccc;">
                                <h3 style="margin: 0 0 10px 0; font-size: 16px; color: #999;">
                                    ${event}
                                </h3>
                                <p style="margin: 0; font-size: 14px; color: #999;">
                                    <em>No features scheduled</em>
                                </p>
                            </div>
                        `;
                    }
                }

                html += `
                        </div>
                    </div>
                `;
            }

            container.innerHTML = html;
        }

        // Initialize draft plan on load
        document.addEventListener('DOMContentLoaded', function() {
            renderDraftPlan();
            renderAnalysis();
        });

        // Analysis tab navigation
        function showAnalysisSection(section) {
            // Hide all sections
            document.querySelectorAll('.analysis-section').forEach(s => s.style.display = 'none');
            document.querySelectorAll('.analysis-nav-btn').forEach(btn => btn.classList.remove('active'));

            // Show selected section
            document.getElementById(`analysis-${section}`).style.display = 'block';
            document.getElementById(`btn-${section}`).classList.add('active');
        }

        // Render all analysis sections
        function renderAnalysis() {
            if (!backlogAnalysis || !backlogAnalysis.insights) {
                document.getElementById('analysis-phasing').innerHTML = '<p>No analysis data available</p>';
                return;
            }

            renderPhasingAnalysis();
            renderSizingAnalysis();
            renderRecommendations();
            renderOptimizedPlan();
        }

        // Render Phasing Analysis section
        function renderPhasingAnalysis() {
            const container = document.getElementById('analysis-phasing');

            // Filter phasing results by product
            let results = backlogAnalysis.phasing_results || [];
            if (currentAnalysisProduct !== 'ALL') {
                results = results.filter(r => {
                    const f = allFeatures[r.feature.key];
                    return f && f.product === currentAnalysisProduct;
                });
            }
            const total = results.length;
            const phaseableCount = results.filter(r => r.analysis.phaseable).length;
            const percentage = total > 0 ? Math.round(phaseableCount / total * 100) : 0;

            let html = `
                <h2 style="margin: 0 0 20px 0; color: #333;">DP/TP/GA Phasing Analysis</h2>

                <div style="margin: 20px 0;">
                    <div class="metric-box" style="background: #e7f3ff;">
                        <div class="metric-box-value" style="color: #0052cc;">${total}</div>
                        <div class="metric-box-label">Total Features</div>
                    </div>
                    <div class="metric-box" style="background: #f0fff4;">
                        <div class="metric-box-value" style="color: #28a745;">${phaseableCount}</div>
                        <div class="metric-box-label">Phaseable Features</div>
                    </div>
                    <div class="metric-box" style="background: #fff8e6;">
                        <div class="metric-box-value" style="color: #ff8b00;">${percentage}%</div>
                        <div class="metric-box-label">Phasing Potential</div>
                    </div>
                </div>

                <div style="background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="margin: 0 0 15px 0; color: #555; font-size: 16px;">What This Means</h3>
                    <p style="margin: 0; line-height: 1.6; color: #666;">
                        <strong>${phaseableCount}</strong> features (${percentage}%) are large or complex enough to benefit from phased delivery across DP → TP → GA.
                        This allows for:
                        <br>• Earlier customer feedback with Dev Preview (DP)
                        <br>• Iterative refinement in Tech Preview (TP)
                        <br>• Production-ready release in General Availability (GA)
                    </p>
                </div>

                <h3 style="margin: 20px 0 15px 0; color: #333;">Feature-Level Phasing Recommendations</h3>
                <div style="max-height: 400px; overflow-y: auto;">
            `;

            // Show sample of phaseable features
            const phaseableFeatures = results
                .filter(r => r.analysis.phaseable)
                .slice(0, 20);  // Show first 20

            phaseableFeatures.forEach(result => {
                const f = result.feature;
                const analysis = result.analysis;

                html += `
                    <div style="padding: 15px; margin: 10px 0; border-left: 4px solid #667eea; background: #f9f9f9; border-radius: 4px;">
                        <div style="font-weight: 600; color: #333; margin-bottom: 5px;">
                            ${f.key} <span style="background: #667eea; color: white; padding: 2px 8px; border-radius: 3px; font-size: 11px; margin-left: 5px;">${f.points} pts</span>
                        </div>
                        <div style="font-size: 13px; color: #666; margin-bottom: 8px;">${f.summary}</div>
                        <div style="font-size: 12px; color: #555; background: white; padding: 8px; border-radius: 3px;">
                            <strong>💡 Recommendation:</strong> ${analysis.recommendation}
                        </div>
                    </div>
                `;
            });

            if (phaseableFeatures.length < phaseableCount) {
                const remaining = phaseableCount - phaseableFeatures.length;
                html += `<p style="margin: 15px 0; color: #666; font-style: italic;">...and ${remaining} more phaseable features</p>`;
            }

            html += `</div>`;

            container.innerHTML = html;
        }

        // Render Sizing Analysis section
        function renderSizingAnalysis() {
            const container = document.getElementById('analysis-sizing');

            // Compute sizing from filtered features
            let featureKeys = Object.keys(allFeatures);
            if (currentAnalysisProduct !== 'ALL') {
                featureKeys = featureKeys.filter(k => allFeatures[k].product === currentAnalysisProduct);
            }
            const totalFeatures = featureKeys.length;
            const totalPts = featureKeys.reduce((s, k) => s + allFeatures[k].points, 0);
            const avgSize = totalFeatures > 0 ? (totalPts / totalFeatures).toFixed(1) : 0;

            const dist = { XL: {count:0, total_points:0, percentage:0}, L: {count:0, total_points:0, percentage:0}, M: {count:0, total_points:0, percentage:0}, S: {count:0, total_points:0, percentage:0}, XS: {count:0, total_points:0, percentage:0} };
            featureKeys.forEach(k => {
                const pts = allFeatures[k].points;
                const size = pts >= 13 ? 'XL' : pts >= 8 ? 'L' : pts >= 5 ? 'M' : pts >= 3 ? 'S' : 'XS';
                dist[size].count++;
                dist[size].total_points += pts;
            });
            for (const size in dist) {
                dist[size].percentage = totalFeatures > 0 ? Math.round(dist[size].count / totalFeatures * 100) : 0;
            }

            // Compute efficiency score
            const weights = { XS: 60, S: 100, M: 90, L: 70, XL: 40 };
            let effScore = 0;
            for (const size in dist) {
                effScore += (dist[size].percentage / 100) * weights[size];
            }
            effScore = Math.round(effScore);

            let html = `
                <h2 style="margin: 0 0 20px 0; color: #333;">Feature Sizing Distribution</h2>

                <div style="margin: 20px 0;">
                    <div class="metric-box" style="background: #e7f3ff;">
                        <div class="metric-box-value" style="color: #0052cc;">${totalFeatures}</div>
                        <div class="metric-box-label">Total Features</div>
                    </div>
                    <div class="metric-box" style="background: #fff8e6;">
                        <div class="metric-box-value" style="color: #ff8b00;">${avgSize}</div>
                        <div class="metric-box-label">Average Size (pts)</div>
                    </div>
                    <div class="metric-box" style="background: #f0fff4;">
                        <div class="metric-box-value" style="color: #28a745;">${effScore}</div>
                        <div class="metric-box-label">Efficiency Score</div>
                    </div>
                </div>

                <h3 style="margin: 20px 0 15px 0; color: #333;">Distribution by Size</h3>
                <table class="feature-table">
                    <thead>
                        <tr>
                            <th>Size</th>
                            <th>Points</th>
                            <th>Count</th>
                            <th>Percentage</th>
                            <th>Total Points</th>
                            <th>Ideal Target</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            const idealTargets = {
                "XL": "< 5%",
                "L": "20%",
                "M": "40%",
                "S": "35%",
                "XS": "< 5%"
            };

            const sizeOrder = ["XL", "L", "M", "S", "XS"];
            sizeOrder.forEach(size => {
                const sizeData = dist[size];
                const ptsLabel = size === "XL" ? "13" : size === "L" ? "8" : size === "M" ? "5" : size === "S" ? "3" : "1";

                // Color code based on percentage
                let rowStyle = "";
                if (size === "XL" && sizeData.percentage > 10) {
                    rowStyle = "background: #fff5f5;";
                } else if (size === "L" && sizeData.percentage > 50) {
                    rowStyle = "background: #fff8e6;";
                }

                html += `
                    <tr style="${rowStyle}">
                        <td><strong>${size}</strong></td>
                        <td>${ptsLabel}</td>
                        <td>${sizeData.count}</td>
                        <td>
                            <div style="display: flex; align-items: center;">
                                <div style="width: 100px; background: #e0e0e0; height: 20px; border-radius: 10px; margin-right: 10px;">
                                    <div style="width: ${sizeData.percentage}%; background: #667eea; height: 100%; border-radius: 10px;"></div>
                                </div>
                                <strong>${sizeData.percentage}%</strong>
                            </div>
                        </td>
                        <td>${sizeData.total_points}</td>
                        <td><span style="color: #666; font-size: 12px;">${idealTargets[size]}</span></td>
                    </tr>
                `;
            });

            html += `
                    </tbody>
                </table>

                <div style="background: #f0f7ff; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #0052cc;">
                    <h4 style="margin: 0 0 10px 0; color: #0052cc;">Sizing Best Practices</h4>
                    <ul style="margin: 0; padding-left: 20px; line-height: 1.8; color: #555;">
                        <li><strong>S (3 pts)</strong> features deliver fastest - aim for 35% of backlog</li>
                        <li><strong>M (5 pts)</strong> features balance speed and value - target 40%</li>
                        <li><strong>L (8 pts)</strong> features acceptable but consider splitting - max 20%</li>
                        <li><strong>XL (13 pts)</strong> features should be rare - keep under 5%</li>
                    </ul>
                </div>
            `;

            container.innerHTML = html;
        }

        // Render Recommendations section
        function renderRecommendations() {
            const container = document.getElementById('analysis-recommendations');
            const sizing = backlogAnalysis.sizing_analysis;

            let html = `
                <h2 style="margin: 0 0 20px 0; color: #333;">Optimization Recommendations</h2>
            `;

            // Show sizing recommendations (general messages, always shown)
            sizing.recommendations.forEach(rec => {
                const className = rec.impact === 'high' ? 'recommendation-high' :
                                rec.impact === 'medium' ? 'recommendation-medium' :
                                rec.impact === 'low' ? 'recommendation-low' : 'recommendation-success';

                const icon = rec.type === 'warning' ? '⚠️' :
                            rec.type === 'info' ? 'ℹ️' : '✅';

                html += `
                    <div class="recommendation-box ${className}">
                        <div style="font-weight: 600; margin-bottom: 8px;">
                            ${icon} ${rec.message}
                        </div>
                    </div>
                `;
            });

            // Show oversized features that should be split (filtered by product)
            let oversizedItems = sizing.oversized || [];
            if (currentAnalysisProduct !== 'ALL') {
                oversizedItems = oversizedItems.filter(item => {
                    const f = allFeatures[item.feature.key];
                    return f && f.product === currentAnalysisProduct;
                });
            }
            if (oversizedItems.length > 0) {
                html += `
                    <h3 style="margin: 30px 0 15px 0; color: #333;">Features Recommended for Splitting</h3>
                    <p style="color: #666; margin-bottom: 15px;">
                        The following ${oversizedItems.length} features are large (XL) and contain multiple concerns.
                        Consider splitting them into smaller, more focused features for faster delivery.
                    </p>
                `;

                oversizedItems.forEach(item => {
                    const f = item.feature;
                    html += `
                        <div style="padding: 15px; margin: 10px 0; background: #fff8e6; border-left: 4px solid #ff8b00; border-radius: 4px;">
                            <div style="font-weight: 600; color: #333; margin-bottom: 5px;">
                                ${f.key} <span style="background: #ff8b00; color: white; padding: 2px 8px; border-radius: 3px; font-size: 11px; margin-left: 5px;">${f.points} pts</span>
                            </div>
                            <div style="font-size: 13px; color: #666; margin-bottom: 8px;">${f.summary}</div>
                            <div style="font-size: 12px; color: #555; margin-bottom: 10px;">
                                <strong>Why split:</strong> ${item.reason}
                                <br>
                                <strong>Recommended split:</strong> ${item.suggested_split}
                            </div>
                    `;

                    // Show detailed split recommendations
                    if (item.split_details && item.split_details.length > 0) {
                        html += `
                            <div style="background: white; padding: 12px; border-radius: 4px; margin-top: 10px;">
                                <div style="font-weight: 600; font-size: 11px; color: #ff8b00; margin-bottom: 8px; text-transform: uppercase;">Suggested Feature Breakdown:</div>
                        `;

                        item.split_details.forEach((part, idx) => {
                            html += `
                                <div style="padding: 8px; margin: 5px 0; background: #f9f9f9; border-left: 3px solid #667eea; font-size: 12px;">
                                    <div style="font-weight: 600; color: #333;">
                                        ${f.key}-P${idx + 1}: ${part.name}
                                        <span style="background: #667eea; color: white; padding: 1px 6px; border-radius: 2px; font-size: 10px; margin-left: 5px;">${part.points} pts</span>
                                        <span style="background: #f0f7ff; color: #0052cc; padding: 1px 6px; border-radius: 2px; font-size: 10px; margin-left: 5px;">${part.phase}</span>
                                    </div>
                                </div>
                            `;
                        });

                        html += `
                            </div>
                        `;
                    }

                    html += `
                        </div>
                    `;
                });
            }

            html += `
                <div style="background: #f0fff4; padding: 20px; border-radius: 8px; margin: 30px 0; border-left: 4px solid #28a745;">
                    <h4 style="margin: 0 0 10px 0; color: #28a745;">Expected Benefits</h4>
                    <ul style="margin: 0; padding-left: 20px; line-height: 1.8; color: #555;">
                        <li>Faster feature delivery (smaller features complete quicker)</li>
                        <li>Better capacity planning (more predictable velocity)</li>
                        <li>Improved DP/TP/GA phasing opportunities</li>
                        <li>Reduced risk (smaller changes are less risky)</li>
                        <li>More frequent customer feedback</li>
                    </ul>
                </div>
            `;

            container.innerHTML = html;
        }

        // Render Optimized Plan section
        function renderOptimizedPlan() {
            const container = document.getElementById('analysis-optimized');

            let html = `
                <h2 style="margin: 0 0 20px 0; color: #333;">Optimized Draft Release Plans</h2>

                <div class="alert alert-info" style="margin-bottom: 20px;">
                    <strong>🎯 Optimization Applied</strong>
                    <p style="margin: 10px 0 0 0;">
                        This plan applies the sizing recommendations above:
                        <br>• Large features (XL) split into smaller deliverables
                        <br>• ${optimizedPlanData.split_count} features optimized for faster delivery
                        <br>• Capacity limits strictly enforced (80 pts/event max)
                        <br>• Features prioritized by target end date
                    </p>
                </div>
            `;

            if (!optimizedPlanData.plan || Object.keys(optimizedPlanData.plan).length === 0) {
                html += '<p>No optimized plan available</p>';
                container.innerHTML = html;
                return;
            }

            // Group by release
            const quarters = {
                "3.5": "Q2 2026", "3.6": "Q3 2026", "3.7": "Q4 2026", "3.8": "Q1 2027",
                "3.9": "Q2 2027", "3.10": "Q3 2027", "3.11": "Q4 2027", "3.12": "Q1 2028"
            };

            const releases = {};
            for (const bucketKey in optimizedPlanData.plan) {
                const [version, event] = bucketKey.split('-');
                if (!releases[version]) {
                    releases[version] = { EA1: null, EA2: null, GA: null };
                }
                releases[version][event] = optimizedPlanData.plan[bucketKey];
            }

            // Apply product filter
            if (currentAnalysisProduct !== 'ALL') {
                for (const version in releases) {
                    for (const event in releases[version]) {
                        if (releases[version][event]) {
                            const orig = releases[version][event];
                            const filtered = orig.features.filter(feature => {
                                const f = allFeatures[feature.key];
                                return f && f.product === currentAnalysisProduct;
                            });
                            const pts = filtered.reduce((s, feature) => s + feature.points, 0);
                            releases[version][event] = {
                                features: filtered,
                                points: pts,
                                capacity_status: pts <= 30 ? 'conservative' : pts <= 50 ? 'typical' : pts <= 80 ? 'aggressive' : 'over_capacity'
                            };
                        }
                    }
                }
            }

            const sortedVersions = Object.keys(releases)
                .filter(v => parseFloat(v) >= 3.4)
                .sort((a, b) => parseFloat(a) - parseFloat(b));

            for (const version of sortedVersions) {
                const releaseData = releases[version];
                const quarter = quarters[version] || '';

                let releaseTotalFeatures = 0;
                let releaseTotalPoints = 0;
                for (const event in releaseData) {
                    if (releaseData[event]) {
                        releaseTotalFeatures += releaseData[event].features.length;
                        releaseTotalPoints += releaseData[event].points;
                    }
                }

                html += `
                    <div style="background: white; border-radius: 8px; padding: 25px; margin-bottom: 25px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                        <h3 style="margin: 0 0 15px 0; color: #333; border-bottom: 2px solid #28a745; padding-bottom: 10px;">
                            RHOAI-${version}
                            <span style="font-size: 14px; color: #666; font-weight: normal;">(${quarter})</span>
                            <span style="float: right; font-size: 14px; font-weight: normal; color: #666;">
                                ${releaseTotalFeatures} features, ${releaseTotalPoints} pts
                            </span>
                        </h3>
                        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px;">
                `;

                for (const event of ['EA1', 'EA2', 'GA']) {
                    const eventData = releaseData[event];

                    if (eventData && eventData.features.length > 0) {
                        const statusColor = {
                            'conservative': '#28a745',
                            'typical': '#90ee90',
                            'aggressive': '#ffc107',
                            'over_capacity': '#dc3545'
                        }[eventData.capacity_status] || '#ccc';

                        const statusIcon = {
                            'conservative': '🟢',
                            'typical': '🟡',
                            'aggressive': '🟠',
                            'over_capacity': '🔴'
                        }[eventData.capacity_status] || '';

                        html += `
                            <div style="background: #f8f9fa; border-radius: 6px; padding: 15px; border-left: 4px solid ${statusColor};">
                                <h4 style="margin: 0 0 10px 0; font-size: 16px; color: #333;">
                                    ${event} ${statusIcon}
                                </h4>
                                <p style="margin: 0 0 10px 0; font-size: 14px; color: #666;">
                                    <strong>${eventData.features.length} features, ${eventData.points} pts</strong>
                                    <br>
                                    <em style="font-size: 12px;">${eventData.capacity_status.replace('_', ' ')}</em>
                                </p>
                        `;

                        // Calculate size distribution for this event
                        const sizeDistribution = { XL: 0, L: 0, M: 0, S: 0, XS: 0 };
                        eventData.features.forEach(feature => {
                            const pts = feature.points;
                            if (pts >= 13) sizeDistribution.XL++;
                            else if (pts >= 8) sizeDistribution.L++;
                            else if (pts >= 5) sizeDistribution.M++;
                            else if (pts >= 3) sizeDistribution.S++;
                            else sizeDistribution.XS++;
                        });

                        // Show size summary
                        html += `
                            <div style="background: white; padding: 8px; border-radius: 4px; margin-bottom: 10px; font-size: 11px;">
                                <strong>Sizes:</strong>
                        `;
                        ['XL', 'L', 'M', 'S', 'XS'].forEach(size => {
                            if (sizeDistribution[size] > 0) {
                                html += ` <span style="background: #e0e0e0; padding: 2px 5px; border-radius: 2px; margin: 0 2px;">${size}:${sizeDistribution[size]}</span>`;
                            }
                        });
                        html += `</div>`;

                        // Show feature list with names and sizes
                        html += `<div style="max-height: 200px; overflow-y: auto;">`;
                        eventData.features.forEach(feature => {
                            const pts = feature.points;
                            const size = pts >= 13 ? 'XL' : pts >= 8 ? 'L' : pts >= 5 ? 'M' : pts >= 3 ? 'S' : 'XS';
                            html += `
                                <div style="padding: 6px 0; border-bottom: 1px solid #eee; font-size: 11px;">
                                    <div style="font-weight: 600; color: #0052cc; margin-bottom: 2px;">
                                        ${feature.key}
                                        <span style="background: #667eea; color: white; padding: 1px 4px; border-radius: 2px; font-size: 10px; margin-left: 4px;">${pts}pts ${size}</span>
                                    </div>
                                    <div style="color: #666; font-size: 10px;">${feature.summary.substring(0, 80)}${feature.summary.length > 80 ? '...' : ''}</div>
                                </div>
                            `;
                        });
                        html += `</div>`;

                        html += `</div>`;
                    } else {
                        html += `
                            <div style="background: #f8f9fa; border-radius: 6px; padding: 15px; border-left: 4px solid #ccc;">
                                <h4 style="margin: 0 0 10px 0; font-size: 16px; color: #999;">
                                    ${event}
                                </h4>
                                <p style="margin: 0; font-size: 14px; color: #999;">
                                    <em>No features scheduled</em>
                                </p>
                            </div>
                        `;
                    }
                }

                html += `</div></div>`;
            }

            html += `
                <div style="background: #f0fff4; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #28a745;">
                    <h4 style="margin: 0 0 10px 0; color: #28a745;">Comparison: Original vs Optimized</h4>
                    <p style="margin: 0; color: #555; line-height: 1.6;">
                        <strong>Original Plan:</strong> May have had over-capacity events or large features blocking delivery
                        <br>
                        <strong>Optimized Plan:</strong> All events within capacity, features right-sized for efficient delivery
                        <br><br>
                        <em>Note: The optimized plan is a recommendation. Review and adjust based on business priorities and dependencies.</em>
                    </p>
                </div>
            `;

            container.innerHTML = html;
        }

        function closeModal(modalId) {
            document.getElementById(modalId).style.display = 'none';
        }

        // Close modal when clicking outside
        window.onclick = function(event) {
            if (event.target.className === 'modal') {
                event.target.style.display = 'none';
            }
        }
    </script>

    <!-- Help Modal -->
    <div id="help-modal" class="modal">
        <div class="modal-content">
            <span class="modal-close" onclick="closeModal('help-modal')">&times;</span>
            <h2>Red Hat AI Products Release Planner - Help Guide</h2>

            <div class="info-card">
                <h4>📊 Track Current Release Cycles</h4>
                <p>Monitor progress on scheduled releases (3.4, 3.5, etc.)</p>
                <ul>
                    <li>Select a release cycle from the dropdown</li>
                    <li>View all 3 events: EA1, EA2, GA</li>
                    <li>See metrics: feature count, story points, capacity status</li>
                    <li>Review feature lists with status and priority</li>
                </ul>
            </div>

            <div class="info-card">
                <h4>📝 Draft Release Plans</h4>
                <p>View AI-recommended 2-year release plan (3.5-3.12)</p>
                <ul>
                    <li><strong>Auto-Generated:</strong> Features distributed by priority & target dates</li>
                    <li><strong>Capacity-Aware:</strong> Respects 80 pts/event maximum</li>
                    <li><strong>Release Goals:</strong> Each release shows strategic objectives</li>
                    <li><strong>Detailed View:</strong> Shows feature names, sizes, and summaries for each event</li>
                </ul>
            </div>

            <div class="info-card">
                <h4>🔬 Feature Analysis</h4>
                <p>Comprehensive backlog analysis and optimization</p>
                <ul>
                    <li><strong>Phasing Analysis:</strong> Which features can be split across DP/TP/GA</li>
                    <li><strong>Sizing Distribution:</strong> Breakdown of feature sizes with recommendations</li>
                    <li><strong>Recommendations:</strong> Specific suggestions for splitting oversized features</li>
                    <li><strong>Optimized Plan:</strong> 2-year plan with recommended optimizations applied</li>
                    <li><strong>Efficiency Score:</strong> Measure of delivery efficiency (target: 80+)</li>
                </ul>
            </div>

            <div class="info-card">
                <h4>🔄 Release Cycle Structure</h4>
                <p>Each RHOAI release has 3 events delivered quarterly:</p>
                <ul>
                    <li><strong>EA1:</strong> Early Access 1 (DP/TP features only)</li>
                    <li><strong>EA2:</strong> Early Access 2 (DP/TP features only)</li>
                    <li><strong>GA:</strong> General Availability (DP/TP/GA features)</li>
                </ul>
                <p><strong>Maturity Levels:</strong> DP (Dev Preview) → TP (Tech Preview) → GA (General Availability)</p>
            </div>

            <div class="info-card">
                <h4>📏 Capacity Guidelines</h4>
                <ul>
                    <li>🟢 Conservative: ≤30 pts</li>
                    <li>🟡 Typical: 30-50 pts</li>
                    <li>🟠 Aggressive: 50-80 pts</li>
                    <li>🔴 Over Capacity: >80 pts</li>
                </ul>
                <p><strong>Historical baseline:</strong> 27.5 pts/event median</p>
            </div>

            <div class="info-card">
                <h4>🏷️ Feature Status</h4>
                <ul>
                    <li><strong>Fix Version:</strong> Committed and approved</li>
                    <li><strong>Target Version:</strong> Intended but not committed</li>
                    <li><strong>In Plan:</strong> Ranked in JIRA Advanced Roadmaps Plan</li>
                    <li><strong>Not in Plan:</strong> In RHAISTRAT project but not in plan</li>
                </ul>
            </div>

            <div class="info-card">
                <h4>💡 Tips</h4>
                <ul>
                    <li>Click ℹ️ icons throughout the interface for contextual help</li>
                    <li>Features show story points - auto-sized if not set in JIRA</li>
                    <li>Drag features between events to rebalance capacity</li>
                    <li>Watch capacity meters - stay under 80 pts per event</li>
                </ul>
            </div>
        </div>
    </div>

    <!-- Info Modal -->
    <div id="info-modal" class="modal">
        <div class="modal-content">
            <span class="modal-close" onclick="closeModal('info-modal')">&times;</span>
            <div id="info-modal-content"></div>
        </div>
    </div>
</body>
</html>
"""

    return html


def main():
    """Main execution"""
    print("=" * 70)
    print("Red Hat AI Products Release Planner")
    print("=" * 70)
    print()

    # Get JIRA Plan ranking
    plan_id = get_jira_plan_id()
    ranking = get_plan_feature_ranking(plan_id)

    if not ranking:
        print("⚠️  Warning: Could not retrieve plan ranking from JIRA")
        print("   Features will be ordered by default JIRA ranking")
        print()

    # Get all features
    issues = get_all_features()
    features = parse_features(issues, ranking)

    # Group by release
    releases, unscheduled = group_features_by_release(features)

    # Count features in/not in plan
    total_in_plan = sum(1 for f in features if f['in_plan'])
    total_not_in_plan = len(features) - total_in_plan
    unscheduled_in_plan = sum(1 for f in unscheduled if f['in_plan'])
    unscheduled_not_in_plan = len(unscheduled) - unscheduled_in_plan

    print()
    print(f"📊 Summary:")
    print(f"   Total features: {len(features)}")
    print(f"     In JIRA Plan: {total_in_plan}")
    print(f"     Not in JIRA Plan: {total_not_in_plan}")
    print(f"   Unscheduled: {len(unscheduled)}")
    print(f"     In plan: {unscheduled_in_plan}")
    print(f"     Not in plan: {unscheduled_not_in_plan}")
    print(f"   Scheduled releases: {len(releases)}")
    for rel_key in sorted(releases.keys()):
        rel_data = releases[rel_key]
        total = sum(len(rel_data[e]) for e in rel_data)
        print(f"     {rel_key}: {total} features")

    # Show auto-sizing summary
    auto_sized = [f for f in features if f.get('auto_sized', False)]
    if auto_sized:
        print()
        print(f"📏 Auto-Sizing Summary:")
        print(f"   Total features: {len(features)}")
        print(f"   With story points: {len(features) - len(auto_sized)}")
        print(f"   Auto-sized (0 → estimated): {len(auto_sized)}")

        # Count by size
        size_counts = {}
        for f in auto_sized:
            pts = f['points']
            size_counts[pts] = size_counts.get(pts, 0) + 1

        print(f"   Auto-sizing distribution:")
        for pts in sorted(size_counts.keys(), reverse=True):
            size_name = {13: "XL", 8: "L", 5: "M", 3: "S", 1: "XS"}.get(pts, "?")
            print(f"     {pts} pts ({size_name}): {size_counts[pts]} features")

    # Generate auto-schedule recommendation
    print()
    print("🤖 Generating recommended release plan for next 2 years...")
    recommended_plan, schedule = auto_schedule_features(
        unscheduled,
        CAPACITY,
        start_version="3.5",
        num_releases=8  # 2 years at quarterly cadence
    )

    if recommended_plan:
        print(format_plan_summary(recommended_plan, schedule))

        # Count scheduled vs unscheduled
        scheduled_features = set()
        total_scheduled_points = 0
        for bucket_key, bucket_data in recommended_plan.items():
            for feat in bucket_data['features']:
                scheduled_features.add(feat['key'])
                total_scheduled_points += feat['points']

        unscheduled_remaining = len(unscheduled) - len(scheduled_features)
        unscheduled_remaining_points = sum(f['points'] for f in unscheduled if f['key'] not in scheduled_features)

        print()
        print("=" * 60)
        print("📊 Capacity Planning Summary:")
        print(f"   Total unscheduled features: {len(unscheduled)}")
        print(f"   Scheduled in plan (3.5-3.12): {len(scheduled_features)} features, {total_scheduled_points} pts")
        print(f"   Remaining unscheduled: {unscheduled_remaining} features, {unscheduled_remaining_points} pts")
        print(f"   (Features with target dates prioritized)")
        print("=" * 60)

    # Perform backlog analysis
    print()
    print("🔬 Analyzing feature backlog...")
    backlog_analysis = analyze_backlog(features)

    print(f"   Features analyzed: {len(features)}")
    print(f"   Phaseable features (DP/TP/GA): {backlog_analysis['insights']['phasing']['phaseable']} ({backlog_analysis['insights']['phasing']['percentage']}%)")
    print(f"   Delivery efficiency score: {backlog_analysis['insights']['efficiency_score']}/100")

    # Generate optimized plan
    print()
    print("🤖 Generating optimized release plan...")
    optimized_plan_result = generate_optimized_plan(unscheduled, CAPACITY, backlog_analysis['sizing_analysis'])

    if optimized_plan_result['split_count'] > 0:
        print(f"   Split {optimized_plan_result['split_count']} large features into smaller deliverables")

    # Generate HTML
    print()
    print("🎨 Generating HTML interface...")
    html_content = generate_html(
        features,
        releases,
        unscheduled,
        CAPACITY,
        recommended_plan=recommended_plan,
        backlog_analysis=backlog_analysis,
        optimized_plan=optimized_plan_result
    )

    output_file = "release-manager.html"
    with open(output_file, 'w') as f:
        f.write(html_content)

    print(f"✅ Created: {output_file}")
    print()
    print("=" * 70)
    print("Next steps:")
    print("  1. Open release-manager.html in your browser")
    print("  2. Use 'Draft Release Plans' tab to view AI-recommended roadmaps")
    print("  3. Use 'Track Current Releases' tab to monitor progress")
    print("=" * 70)


if __name__ == "__main__":
    main()
