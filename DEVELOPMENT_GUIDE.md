# RHOAI Release Manager - Development Guide

Guide for adding new functionality and customizing the Release Manager.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│ GitHub Actions (Weekly Trigger)                            │
│  - Runs release_manager.py                                 │
│  - Generates release-manager.html                          │
│  - Deploys to GitHub Pages                                 │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ release_manager.py (Python Backend)                        │
│  - Queries JIRA API                                        │
│  - Calls auto_scheduler.py                                 │
│  - Generates HTML with embedded data                       │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ release-manager.html (Static HTML)                         │
│  - Embedded JSON data (features, releases, plan)           │
│  - JavaScript for interactivity                            │
│  - CSS for styling                                         │
│  - No backend required (runs in browser)                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Common Customizations

### 1. Add New JIRA Fields

**Example: Add "Epic Link" field**

1. **Find the field ID in JIRA:**
   ```bash
   # Query JIRA to find field IDs
   curl -X GET "https://issues.redhat.com/rest/api/2/field" \
     -H "Authorization: Bearer $JIRA_TOKEN" | jq '.[].id,.name'
   ```

2. **Update `release_manager.py`:**
   ```python
   # At top with other field definitions (~line 36)
   FIELD_EPIC_LINK = "customfield_12311140"  # Epic Link field ID

   # In get_all_features() function (~line 168)
   params={
       "jql": jql,
       "fields": f"key,summary,status,priority,{FIELD_STORY_POINTS},fixVersions,{FIELD_TARGET_VERSION},{FIELD_TARGET_END_DATE},{FIELD_EPIC_LINK},labels,issuelinks",
       ...
   }

   # In parse_features() function (~line 250)
   # Parse epic link
   epic_link = None
   if fields.get(FIELD_EPIC_LINK):
       epic_link = fields[FIELD_EPIC_LINK]

   # Add to feature dict (~line 290)
   feature = {
       "key": key,
       "summary": fields["summary"],
       ...
       "epic_link": epic_link,  # NEW
       ...
   }
   ```

3. **Display in HTML (~line 1440):**
   ```javascript
   // In renderDraftPlan() or tracking tab display
   html += `<div>Epic: ${feat.epic_link || 'None'}</div>`;
   ```

4. **Test:**
   ```bash
   export JIRA_TOKEN='your-token'
   python3 release_manager.py
   # Open release-manager.html and verify epic link shows
   ```

---

### 2. Modify Auto-Sizing Logic

**Example: Add new size category for "Documentation" features**

Edit `release_manager.py` (~line 205):

```python
def estimate_feature_size(summary, priority):
    """Auto-estimate feature size based on summary and priority"""
    summary_lower = summary.lower()

    # Keywords indicating size
    xl_keywords = ["infrastructure", "migration", "integration", "architecture", "redesign", "framework"]
    l_keywords = ["implement", "develop", "create", "build", "support", "enable"]
    m_keywords = ["update", "enhance", "improve", "add", "extend"]
    s_keywords = ["fix", "adjust", "minor", "small", "ui", "ux", "docs"]
    xs_keywords = ["documentation", "typo", "readme"]  # NEW

    # Check for XS indicators (NEW)
    if any(kw in summary_lower for kw in xs_keywords):
        return FEATURE_SIZING["XS"]  # 1

    # Check for XL indicators
    if any(kw in summary_lower for kw in xl_keywords) or priority == "Blocker":
        return FEATURE_SIZING["XL"]  # 13

    # ... rest of logic
```

**Test:**
```bash
python3 release_manager.py | grep "Auto-sizing distribution"
# Should show 1 pt (XS) category now
```

---

### 3. Change Capacity Limits

**Example: Increase aggressive max from 80 to 100 pts**

Edit `release_manager.py` (~line 42):

```python
CAPACITY = {
    "median": 27.5,
    "mean": 38.7,
    "conservative_max": 30,
    "typical_max": 50,
    "aggressive_max": 100,  # Changed from 80
    "historical_max_release": 140
}
```

Edit `auto_scheduler.py` (~line 96):

```python
# Check if feature fits in current bucket
if bucket['points'] + points <= max_capacity:  # Uses aggressive_max
```

The auto-scheduler will now fill events up to 100 pts before moving to the next event.

---

### 4. Add New Tab to Dashboard

**Example: Add "Risk Analysis" tab**

Edit `release_manager.py` in the HTML generation section:

1. **Add tab button (~line 786):**
   ```python
   <div class="tabs">
       <button class="tab-button active" onclick="switchTab('tracking')">📊 Track Current Release Cycles</button>
       <button class="tab-button" onclick="switchTab('planning')">📋 Plan Future Releases</button>
       <button class="tab-button" onclick="switchTab('drafts')">📝 Draft Release Plans</button>
       <button class="tab-button" onclick="switchTab('risks')">⚠️ Risk Analysis</button>  <!-- NEW -->
       <button class="tab-button" onclick="showHelp()" style="margin-left:auto;background:#f8f9fa;color:#333;">❓ Help</button>
   </div>
   ```

2. **Add tab content (~line 945):**
   ```python
   <!-- RISK ANALYSIS TAB -->
   <div id="risks-tab" class="tab-content">
       <div style="max-width: 1400px; margin: 0 auto;">
           <h2>Risk Analysis</h2>
           <div id="risk-display">
               <!-- Populated by JavaScript -->
           </div>
       </div>
   </div>
   ```

3. **Add JavaScript logic (~line 1450):**
   ```javascript
   // Calculate risks
   function calculateRisks() {
       const risks = [];

       for (const [version, releaseData] of Object.entries(allReleases)) {
           for (const [event, features] of Object.entries(releaseData)) {
               const totalPts = features.reduce((sum, f) => sum + f.points, 0);

               if (totalPts > 80) {
                   risks.push({
                       release: version,
                       event: event,
                       points: totalPts,
                       risk: 'HIGH',
                       features: features.length
                   });
               }
           }
       }

       return risks;
   }

   // Render risks
   function renderRisks() {
       const risks = calculateRisks();
       const container = document.getElementById('risk-display');

       let html = '<div class="alert alert-warning">';
       html += `<strong>Found ${risks.length} high-risk events</strong></div>`;

       risks.forEach(risk => {
           html += `<div style="padding:15px; margin:10px 0; border-left:4px solid #ff5630; background:#fff5f5;">`;
           html += `<strong>RHOAI-${risk.release} ${risk.event}</strong><br>`;
           html += `${risk.points} pts (${risk.features} features) - ${risk.risk} RISK`;
           html += `</div>`;
       });

       container.innerHTML = html;
   }

   // Initialize on load
   document.addEventListener('DOMContentLoaded', function() {
       renderDraftPlan();
       renderRisks();  // NEW
   });
   ```

---

### 5. Add New Sorting/Filtering Options

**Example: Sort features by priority in planning tab**

Edit `release_manager.py` (~line 830):

```python
# Add sort dropdown to planning tab
html += """
    <div class="feature-pool">
        <h2>Unscheduled Features ({len(unscheduled)})</h2>
        <div style="margin-bottom:10px;">
            <label>Sort by:</label>
            <select id="sort-features" onchange="sortFeatures(this.value)">
                <option value="rank">Plan Ranking</option>
                <option value="priority">Priority</option>
                <option value="points">Story Points</option>
                <option value="date">Target Date</option>
            </select>
        </div>
        <div id="unscheduled-pool">
"""

# Add JavaScript for sorting (~line 1070)
html += """
    function sortFeatures(sortBy) {
        const pool = document.getElementById('unscheduled-pool');
        const cards = Array.from(pool.querySelectorAll('.feature-card'));

        cards.sort((a, b) => {
            if (sortBy === 'priority') {
                const priorities = {
                    'Blocker': 1, 'Critical': 2, 'Major': 3,
                    'Normal': 4, 'Minor': 5
                };
                const aPri = priorities[a.dataset.priority] || 999;
                const bPri = priorities[b.dataset.priority] || 999;
                return aPri - bPri;
            } else if (sortBy === 'points') {
                return parseInt(b.dataset.points) - parseInt(a.dataset.points);
            }
            // ... other sort options
        });

        cards.forEach(card => pool.appendChild(card));
    }
"""
```

---

### 6. Customize Release Goals

**Example: Update release goals text**

Edit `release_manager.py` (~line 1365):

```python
const releaseGoals = {
    "3.5": "Your custom goal for 3.5 here",
    "3.6": "Your custom goal for 3.6 here",
    // ... etc
};
```

Or make them dynamic from JIRA:

```python
# In get_all_features(), query for release-level epics
# Store goals in database or config file
# Load and inject into HTML
```

---

### 7. Add Export Functionality

**Example: Export plan to JSON**

Add to HTML (~line 862):

```python
<button onclick="exportPlan()" style="padding:10px 20px;background:#0052cc;color:white;border:none;border-radius:6px;cursor:pointer;">
    📥 Export Plan
</button>
```

Add JavaScript (~line 1050):

```javascript
function exportPlan() {
    const plan = {};

    document.querySelectorAll('.event-bucket').forEach(bucket => {
        const release = bucket.dataset.release;
        const event = bucket.dataset.event;
        const features = [];

        bucket.querySelectorAll('.feature-card').forEach(card => {
            features.push({
                key: card.dataset.key,
                points: parseInt(card.dataset.points)
            });
        });

        const key = `${release}-${event}`;
        plan[key] = features;
    });

    const json = JSON.stringify(plan, null, 2);
    const blob = new Blob([json], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `release-plan-${new Date().toISOString().split('T')[0]}.json`;
    a.click();
}
```

---

## Development Workflow

### Local Development Loop

```bash
# 1. Make your changes to release_manager.py or auto_scheduler.py

# 2. Test locally
export JIRA_TOKEN='your-token'
python3 release_manager.py

# 3. View in browser
./serve.sh 8000
# Open: http://localhost:8000/release-manager.html

# 4. Iterate until satisfied

# 5. Commit and push
git add release_manager.py
git commit -m "Add: Your feature description"
git push origin main

# 6. GitHub Actions auto-deploys to live site
```

### Debugging Tips

**1. Check Python errors:**
```bash
python3 release_manager.py 2>&1 | tee output.log
```

**2. Validate HTML:**
- Open release-manager.html in browser
- Press F12 for Developer Console
- Check Console tab for JavaScript errors

**3. Inspect embedded data:**
```bash
# Extract embedded JSON from HTML
grep -A 100 "const allReleases" release-manager.html | head -50
grep -A 100 "const recommendedPlan" release-manager.html | head -50
```

**4. Test JIRA queries independently:**
```python
import os
import requests

JIRA_TOKEN = os.environ.get("JIRA_TOKEN")
headers = {
    "Authorization": f"Bearer {JIRA_TOKEN}",
    "Content-Type": "application/json"
}

# Test query
response = requests.get(
    "https://issues.redhat.com/rest/api/2/search",
    headers=headers,
    params={
        "jql": "project = RHAISTRAT AND key = RHAISTRAT-1287",
        "fields": "key,summary,customfield_12310243"
    }
)

print(response.json())
```

---

## Code Organization

### File Structure
```
/workspace/artifacts/
├── release_manager.py       # Main script - your entry point
├── auto_scheduler.py         # Scheduling algorithm
├── requirements.txt          # Dependencies
├── .github/
│   └── workflows/
│       └── update-release-plan.yml  # Auto-deployment
├── quickstart.sh             # Local quick start
├── serve.sh                  # Local server
└── release-manager.html      # Generated output
```

### Key Functions in release_manager.py

| Function | Line | Purpose |
|----------|------|---------|
| `get_jira_headers()` | ~62 | JIRA authentication |
| `get_all_features()` | ~152 | Query JIRA for features |
| `estimate_feature_size()` | ~197 | Auto-sizing logic |
| `parse_features()` | ~224 | Parse JIRA response |
| `group_features_by_release()` | ~305 | Group by release/event |
| `generate_html()` | ~333 | Generate HTML output |
| `main()` | ~1576 | Main execution flow |

### Key Functions in auto_scheduler.py

| Function | Line | Purpose |
|----------|------|---------|
| `generate_release_schedule()` | ~7 | Generate release list |
| `auto_schedule_features()` | ~31 | Scheduling algorithm |
| `format_plan_summary()` | ~142 | Format console output |

---

## Testing

### Unit Tests (Recommended)

Create `test_release_manager.py`:

```python
import unittest
from release_manager import estimate_feature_size

class TestAutoSizing(unittest.TestCase):
    def test_xl_keywords(self):
        size = estimate_feature_size("Infrastructure migration", "Normal")
        self.assertEqual(size, 13)

    def test_blocker_priority(self):
        size = estimate_feature_size("Simple fix", "Blocker")
        self.assertEqual(size, 13)

    def test_default_medium(self):
        size = estimate_feature_size("Random feature", "Normal")
        self.assertEqual(size, 5)

if __name__ == '__main__':
    unittest.main()
```

Run tests:
```bash
python3 -m pytest test_release_manager.py
```

### Integration Tests

```bash
# Test full pipeline
export JIRA_TOKEN='your-token'
python3 release_manager.py

# Verify output
test -f release-manager.html || echo "FAIL: HTML not generated"
grep -q "RHOAI Release Manager" release-manager.html || echo "FAIL: Missing title"
grep -q "Draft Release Plans" release-manager.html || echo "FAIL: Missing tab"
```

---

## Deployment Pipeline

### How Changes Get Deployed

```
1. Developer makes changes locally
   ↓
2. Commits to main branch
   ↓
3. GitHub Actions detects push
   ↓
4. Runs release_manager.py with JIRA_TOKEN secret
   ↓
5. Generates fresh release-manager.html
   ↓
6. Deploys to gh-pages branch
   ↓
7. GitHub Pages serves updated HTML
   ↓
8. Users see changes (may need hard refresh)
```

### Manual Deployment

```bash
# Generate locally
export JIRA_TOKEN='your-token'
python3 release_manager.py

# Deploy manually
git checkout gh-pages
cp release-manager.html .
git add release-manager.html
git commit -m "Manual update"
git push origin gh-pages
```

---

## Advanced Customizations

### 1. Add Database Backend

Replace static HTML with Flask/FastAPI:

```python
from flask import Flask, render_template
import json

app = Flask(__name__)

@app.route('/')
def index():
    # Query JIRA in real-time
    features = get_all_features()
    return render_template('release_manager.html', features=features)

if __name__ == '__main__':
    app.run()
```

### 2. Add Authentication

For internal-only access:

```python
from flask_login import LoginManager, login_required

@app.route('/')
@login_required
def index():
    ...
```

### 3. Add Write-Back to JIRA

Update target versions based on planning:

```python
def update_jira_target_version(issue_key, target_version):
    url = f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}"
    data = {
        "fields": {
            FIELD_TARGET_VERSION: {"name": target_version}
        }
    }
    response = requests.put(url, headers=get_jira_headers(), json=data)
    return response.status_code == 204
```

---

## Performance Optimization

### Caching JIRA Data

```python
import pickle
from datetime import datetime, timedelta

CACHE_FILE = "jira_cache.pkl"
CACHE_TTL = timedelta(hours=1)

def get_cached_features():
    if os.path.exists(CACHE_FILE):
        mtime = datetime.fromtimestamp(os.path.getmtime(CACHE_FILE))
        if datetime.now() - mtime < CACHE_TTL:
            with open(CACHE_FILE, 'rb') as f:
                return pickle.load(f)

    # Cache miss - query JIRA
    features = get_all_features()
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(features, f)

    return features
```

---

## Getting Help

**For development questions:**
- Check this DEVELOPMENT.md guide
- Review inline comments in release_manager.py
- Test changes locally before deploying

**For JIRA API questions:**
- JIRA REST API docs: https://docs.atlassian.com/jira/REST/
- Field IDs: `curl https://issues.redhat.com/rest/api/2/field`
- JQL reference: https://support.atlassian.com/jira-software-cloud/docs/use-advanced-search-with-jira-query-language-jql/

**For GitHub Actions questions:**
- Workflow syntax: https://docs.github.com/en/actions/reference/workflow-syntax-for-github-actions
- Secrets: https://docs.github.com/en/actions/security-guides/encrypted-secrets
- Debugging: Check Actions tab logs

---

## Examples Repository

Common customization examples:

```bash
# Clone examples (if available)
git clone https://github.com/example/rhoai-release-manager-examples.git

# Or create your own branch for experiments
git checkout -b feature/my-new-feature
```

---

**Happy developing!** 🚀

For questions or contributions, open an issue or PR in the GitHub repo.
