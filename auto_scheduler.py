#!/usr/bin/env python3
"""
Auto-scheduler for Red Hat AI Products Release Planning
Distributes features across release events based on priority and capacity.
Product-aware: RHOAI, RHAIIS, and RHELAI features are scheduled into
their own product release buckets.
"""

KNOWN_PRODUCTS = ["RHOAI", "RHAIIS", "RHELAI"]


def generate_release_schedule(start_version="3.5", num_releases=8):
    """
    Generate release schedule for next 2 years

    Args:
        start_version: Starting version (e.g., "3.5")
        num_releases: Number of releases to plan (8 = 2 years at quarterly cadence)

    Returns:
        List of release versions with event types
    """
    major, minor = map(int, start_version.split("."))

    schedule = []
    for i in range(num_releases):
        version = f"{major}.{minor + i}"
        schedule.append({
            "version": version,
            "events": ["EA1", "EA2", "GA"]
        })

    return schedule


def auto_schedule_features(features, capacity_guidelines, start_version="3.5", num_releases=8):
    """
    Auto-schedule features into release events based on priority.

    Product-aware: features are routed to their product's release buckets.
    RHOAI features → "3.5-EA1", RHAIIS features → "RHAIIS:3.5-EA1", etc.
    The returned plan uses a unified key format so all products coexist.

    Algorithm:
    1. Sort features by priority (rank from JIRA plan)
    2. Group by product, then fill each product's release events in order
    3. Respect capacity guidelines (target: typical_max, hard limit: aggressive_max)

    Args:
        features: List of feature dicts with 'rank', 'points', 'key', 'product', etc.
        capacity_guidelines: Dict with 'typical_max', 'aggressive_max', etc.
        start_version: Starting version
        num_releases: Number of releases to plan

    Returns:
        Tuple of (plan dict, schedule list)
    """
    schedule = generate_release_schedule(start_version, num_releases)

    # Sort features globally
    def sort_key(f):
        in_plan = f.get('in_plan', False)
        target_date = f.get('target_end_date', None)
        rank = f.get('rank', 9999)
        if target_date:
            date_sort = target_date
        else:
            date_sort = "9999-12-31"
        return (not in_plan, date_sort, rank)

    sorted_features = sorted(features, key=sort_key)

    # Capacity targets
    target_capacity = capacity_guidelines.get('typical_max', 50)
    max_capacity = capacity_guidelines.get('aggressive_max', 80)

    # Group features by product
    features_by_product = {}
    for f in sorted_features:
        product = f.get('product', 'RHOAI')
        if product not in features_by_product:
            features_by_product[product] = []
        features_by_product[product].append(f)

    # Determine which products have features to schedule
    products_with_features = set(features_by_product.keys())

    # Initialize buckets for each product
    plan = {}

    # For RHOAI (the default/primary product), use plain version keys: "3.5-EA1"
    # For other products, prefix the key: "RHAIIS:3.5-EA1"
    def make_bucket_key(product, version, event):
        if product == "RHOAI":
            return f"{version}-{event}"
        return f"{product}:{version}-{event}"

    # Build per-product bucket key lists
    product_bucket_keys = {}
    for product in products_with_features:
        keys = []
        for release in schedule:
            version = release["version"]
            for event in release["events"]:
                bk = make_bucket_key(product, version, event)
                keys.append(bk)
                plan[bk] = {
                    "features": [],
                    "points": 0,
                    "capacity_status": "conservative"
                }
        product_bucket_keys[product] = keys

    # Schedule each product's features into that product's buckets
    for product, prod_features in features_by_product.items():
        bucket_keys = product_bucket_keys[product]
        current_bucket_idx = 0

        for feature in prod_features:
            points = feature.get('points', 0)
            if points == 0:
                continue

            placed = False
            attempts = 0
            max_attempts = len(bucket_keys)

            while not placed and attempts < max_attempts:
                bucket_key = bucket_keys[current_bucket_idx % len(bucket_keys)]
                bucket = plan[bucket_key]

                if bucket['points'] + points <= max_capacity:
                    bucket['features'].append(feature)
                    bucket['points'] += points

                    if bucket['points'] <= capacity_guidelines.get('conservative_max', 30):
                        bucket['capacity_status'] = 'conservative'
                    elif bucket['points'] <= target_capacity:
                        bucket['capacity_status'] = 'typical'
                    elif bucket['points'] <= max_capacity:
                        bucket['capacity_status'] = 'aggressive'
                    else:
                        bucket['capacity_status'] = 'over_capacity'

                    placed = True

                    if bucket['points'] >= target_capacity:
                        current_bucket_idx += 1
                else:
                    current_bucket_idx += 1
                    attempts += 1

    # Remove empty product buckets (products with few features won't fill all slots)
    plan = {k: v for k, v in plan.items() if v['features']}

    return plan, schedule


def format_plan_summary(plan, schedule):
    """Format auto-schedule plan for display"""
    summary = []

    # Collect all products present in the plan
    products_in_plan = set()
    for bk in plan:
        if ":" in bk:
            products_in_plan.add(bk.split(":")[0])
        else:
            products_in_plan.add("RHOAI")

    for product in sorted(products_in_plan):
        for release in schedule:
            version = release["version"]
            release_total = 0
            release_features = 0

            header_printed = False

            for event in release["events"]:
                if product == "RHOAI":
                    bucket_key = f"{version}-{event}"
                else:
                    bucket_key = f"{product}:{version}-{event}"

                if bucket_key not in plan:
                    continue

                if not header_printed:
                    summary.append(f"\n{'='*60}")
                    summary.append(f"{product}-{version}")
                    summary.append(f"{'='*60}")
                    header_printed = True

                bucket = plan[bucket_key]
                feature_count = len(bucket['features'])
                points = bucket['points']
                status = bucket['capacity_status']

                release_total += points
                release_features += feature_count

                status_icon = {
                    'conservative': '🟢',
                    'typical': '🟡',
                    'aggressive': '🟠',
                    'over_capacity': '🔴'
                }.get(status, '⚪')

                summary.append(f"\n  {event}: {feature_count} features, {points} pts {status_icon} ({status})")

                if feature_count > 0:
                    for i, feat in enumerate(bucket['features'][:3]):
                        rank_str = f"#{feat['rank']}" if feat.get('in_plan') else "—"
                        summary.append(f"    {rank_str} {feat['key']} - {feat['summary'][:50]}... ({feat['points']} pts)")

                    if feature_count > 3:
                        summary.append(f"    ... and {feature_count - 3} more features")

            if header_printed:
                summary.append(f"\n  TOTAL: {release_features} features, {release_total} pts")

    return "\n".join(summary)


if __name__ == "__main__":
    # Test with sample data
    sample_features = [
        {"key": "TEST-1", "summary": "High priority feature", "rank": 1, "points": 8, "in_plan": True, "product": "RHOAI"},
        {"key": "TEST-2", "summary": "Medium priority", "rank": 2, "points": 5, "in_plan": True, "product": "RHAIIS"},
        {"key": "TEST-3", "summary": "Low priority", "rank": 3, "points": 13, "in_plan": True, "product": "RHOAI"},
    ]

    capacity = {
        "conservative_max": 30,
        "typical_max": 50,
        "aggressive_max": 80
    }

    plan, schedule = auto_schedule_features(sample_features, capacity, start_version="3.5", num_releases=2)
    print(format_plan_summary(plan, schedule))
