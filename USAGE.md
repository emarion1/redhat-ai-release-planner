# Red Hat AI Products Release Planner - Quick Usage Guide

## For Users (View Only)

**Access the live dashboard:**
```
https://emarion1.github.io/redhat-ai-release-planner/release-manager.html
```

No installation needed - just open in your browser!

### Dashboard Features

#### 📊 Track Current Release Cycles (Default Tab)
- Select a release (3.4, 3.5, etc.) from dropdown
- View all 3 events: EA1, EA2, GA
- See metrics: feature count, story points, capacity status
- Review feature lists with JIRA links

#### 📝 Draft Release Plans
- View AI-recommended 2-year plan (3.5-3.12)
- See release goals for each cycle
- Review capacity-constrained distribution
- View feature names, sizes, and summaries for each event
- All releases respect 80 pt/event limit

#### 🔬 Feature Analysis
- DP/TP/GA phasing analysis
- Feature sizing distribution
- Optimization recommendations for splitting large features
- Optimized draft plans with recommended changes applied

### Capacity Status Colors

- 🟢 **Conservative** (≤30 pts) - Low risk
- 🟡 **Typical** (30-50 pts) - Normal capacity
- 🟠 **Aggressive** (50-80 pts) - High load, needs mitigations
- 🔴 **Over Capacity** (>80 pts) - Extremely risky

---

## For Administrators (Update Data)

### Option 1: Trigger Auto-Update (GitHub Actions)

1. Go to **Actions** tab in GitHub
2. Select "Update Release Plan" workflow
3. Click **Run workflow** → **Run workflow**
4. Wait ~2 minutes
5. Dashboard auto-updates at the same URL

### Option 2: Run Locally

```bash
# Clone repo (first time only)
git clone https://github.com/emarion1/redhat-ai-release-planner.git
cd redhat-ai-release-planner

# Quick start (generates and opens dashboard)
export JIRA_EMAIL='your-email@redhat.com'
export JIRA_TOKEN='your-api-token'
./quickstart.sh

# Or manual steps:
pip install -r requirements.txt
export JIRA_EMAIL='your-email@redhat.com'
export JIRA_TOKEN='your-api-token'
python3 release_manager.py

# View locally
./serve.sh
# Open: http://localhost:8000/release-manager.html
```

### Get JIRA Credentials

1. Visit: https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create API token"
3. Name it (e.g., "Release Planner")
4. Copy the token immediately
5. Set `JIRA_EMAIL` to your Atlassian account email

---

## Update Schedule

**Automatic updates:**
- Every Monday at 8:00 AM UTC
- When code changes are pushed

**Manual updates:**
- Anytime via Actions → Run workflow
- Or run locally with fresh JIRA data

---

## Understanding the Data

### Feature Sizing

Features are auto-sized if missing story points:
- **13 pts (XL):** Infrastructure, migration, architecture
- **8 pts (L):** Implement, develop, create, build
- **5 pts (M):** Update, enhance, improve (default)
- **3 pts (S):** Fix, adjust, minor, docs

### Scheduling Priority

Features are scheduled based on:
1. JIRA Plan ranking (if available)
2. Target end date (earlier dates first)
3. Default priority ranking

### Capacity Planning

- **Target:** 50 pts/event (typical capacity)
- **Hard limit:** 80 pts/event (aggressive max)
- Features that don't fit by RHOAI 3.12 remain unscheduled
- Based on historical data: 27.5 pts/event median

---

## Common Questions

**Q: Why do some features show "NOT IN PLAN"?**
A: They exist in JIRA project RHAISTRAT but aren't in the Advanced Roadmaps plan. They're ranked lower in auto-scheduling.

**Q: Can I edit the plan in the dashboard?**
A: The dashboard is read-only and displays AI-recommended plans based on JIRA data. To modify feature scheduling, update JIRA and regenerate the dashboard.

**Q: How often should I regenerate?**
A: Weekly auto-updates are usually sufficient. Run manually if you've made major JIRA changes and need to see them immediately.

**Q: What's the difference between Fix Version and Target Version?**
A:
- **Fix Version:** Committed and approved for delivery
- **Target Version:** Intended but not yet committed
- Fix Version takes priority in the dashboard

**Q: Why are all releases showing 78-80 pts?**
A: The auto-scheduler respects the 80 pt/event limit. This is by design - features that don't fit remain unscheduled for future planning.

---

## Getting Help

**Dashboard not loading?**
1. Hard refresh: Ctrl+F5 (Windows/Linux) or Cmd+Shift+R (Mac)
2. Check GitHub Actions for errors
3. Verify JIRA_TOKEN is valid

**Need to add features?**
- Add them in JIRA project RHAISTRAT
- Wait for next auto-update or trigger manually

**Want to change release goals?**
- Edit `release_manager.py` line ~1365 (releaseGoals object)
- Commit changes - will auto-deploy

**Questions about data?**
- All data comes from JIRA RHAISTRAT project
- Contact JIRA admin for access issues
- Check DEPLOYMENT.md for infrastructure questions
