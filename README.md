# Red Hat AI Products Release Planner

Multi-product release tracking and capacity planning for RHOAI, RHAIIS, and RHELAI.

**[🔗 Live Dashboard](https://emarion1.github.io/redhat-ai-release-planner/release-manager.html)**

## Features

- **Track Current Releases** - Monitor progress across EA1, EA2, and GA events
- **Draft Release Plans** - AI-generated 2-year roadmap based on JIRA data
- **Feature Analysis** - Backlog analysis with sizing recommendations and DP/TP/GA phasing
- **Auto-Scheduling** - Intelligent feature distribution respecting capacity limits
- **Capacity Planning** - Real-time capacity status with historical benchmarks

## Quick Start

### View the Dashboard

No installation needed! Just visit the **[live dashboard](https://emarion1.github.io/redhat-ai-release-planner/release-manager.html)**.

```
https://emarion1.github.io/redhat-ai-release-planner/release-manager.html
```

The dashboard updates automatically every Monday at 8:00 AM UTC.

### Run Locally

```bash
# Clone repository
git clone https://github.com/emarion1/redhat-ai-release-planner.git
cd redhat-ai-release-planner

# Set your JIRA token
export JIRA_TOKEN='your-personal-access-token'

# Quick start (generates and serves dashboard)
./quickstart.sh
```

Open http://localhost:8000/release-manager.html in your browser.

### Get JIRA Token

1. Visit https://issues.redhat.com/secure/ViewProfile.jspa
2. Click "Personal Access Tokens"
3. Create a new token (90-day expiration recommended)
4. Copy the token immediately

## Documentation

- **[USAGE.md](./USAGE.md)** - Complete user guide
- **[DEPLOYMENT.md](./DEPLOYMENT.md)** - Deployment options (GitHub Pages, containers, OpenShift)
- **[DEVELOPMENT.md](./DEVELOPMENT.md)** - Developer guide for customization

## Dashboard Tabs

### 📊 Track Current Release Cycles
- Select any release (3.4, 3.5, etc.)
- View all 3 events: EA1, EA2, GA
- See metrics: feature count, story points, capacity status
- Review complete feature lists with JIRA links

### 📝 Draft Release Plans
- AI-recommended 2-year plan (3.5-3.12)
- Release goals for each cycle
- Capacity-constrained distribution
- Feature names, sizes, and summaries for each event

### 🔬 Feature Analysis
- **Phasing Analysis:** Which features can be split across DP/TP/GA
- **Sizing Distribution:** Breakdown by feature size with recommendations
- **Optimization Recommendations:** Specific suggestions for splitting large features
- **Optimized Draft Plans:** 2-year plan with recommended optimizations applied

## Capacity Guidelines

- 🟢 **Conservative** (≤30 pts) - Low risk
- 🟡 **Typical** (30-50 pts) - Normal capacity
- 🟠 **Aggressive** (50-80 pts) - High load, needs mitigations
- 🔴 **Over Capacity** (>80 pts) - Extremely risky

## Auto-Scheduling Algorithm

The auto-scheduler distributes features across releases based on:

1. **JIRA Plan ranking** (if available)
2. **Target end dates** (earlier dates first)
3. **Story points** for capacity management
4. **Hard capacity limit:** 80 pts/event maximum

Features are automatically sized if story points are missing:
- **XL (13 pts):** Infrastructure, migration, architecture
- **L (8 pts):** Implement, develop, create, build
- **M (5 pts):** Update, enhance, improve (default)
- **S (3 pts):** Fix, adjust, minor, docs

## Automatic Updates

The dashboard updates automatically via GitHub Actions:
- **Weekly:** Every Monday at 8:00 AM UTC
- **On code changes:** When `release_manager.py` or `auto_scheduler.py` are updated

### Manual Update

Trigger a manual update:
1. Go to **Actions** tab in GitHub
2. Select "Update Release Plan" workflow
3. Click **Run workflow** → **Run workflow**
4. Wait ~2 minutes for completion

## Technology

- **Backend:** Python 3.11+
- **Data Source:** JIRA REST API (RHAISTRAT project)
- **Output:** Static HTML with embedded JavaScript
- **Hosting:** GitHub Pages (or any static hosting)
- **Updates:** GitHub Actions

## Requirements

- Python 3.11 or higher
- JIRA Personal Access Token
- Internet connection (for JIRA API)

## Repository Structure

```
/
├── release_manager.py              # Main application
├── auto_scheduler.py               # Auto-scheduling algorithm
├── requirements.txt                # Python dependencies
├── .github/workflows/              # GitHub Actions
│   └── update-release-plan.yml    # Auto-update workflow
├── quickstart.sh                   # Local quickstart script
├── serve.sh                        # Local server script
├── USAGE.md                        # User guide
├── DEPLOYMENT.md                   # Deployment guide
├── DEVELOPMENT.md                  # Developer guide
└── DEPLOYMENT-SUMMARY.md           # Quick deployment reference
```

## Common Questions

**Q: Why do some features show "NOT IN PLAN"?**
A: They exist in JIRA project RHAISTRAT but aren't in the Advanced Roadmaps plan. They're ranked lower in auto-scheduling.

**Q: Can I edit the plan in the dashboard?**
A: The dashboard is read-only. To modify feature scheduling, update JIRA and regenerate the dashboard.

**Q: How often should I regenerate?**
A: Weekly auto-updates are sufficient. Trigger manually if you've made major JIRA changes.

**Q: Why are releases showing 78-80 pts per event?**
A: The auto-scheduler respects the 80 pt/event capacity limit. Features that don't fit remain unscheduled.

## Support

- **Issues:** Report bugs or feature requests in GitHub Issues
- **Documentation:** See USAGE.md, DEPLOYMENT.md, and DEVELOPMENT.md
- **JIRA Access:** Contact your JIRA administrator

## License

Internal Red Hat tool - Not for external distribution

## Maintainers

Red Hat AI Release Engineering Team

---

**Last Updated:** March 2026
**Powered by:** Claude Code (Anthropic)
