# Red Hat AI Products Release Planner - Deployment Guide

This guide shows how to deploy the Release Manager tool for your team.

## Deployment Options

### Option 1: GitHub Actions + GitHub Pages (Recommended)

**Pros:**
- Auto-updates weekly
- No server maintenance
- Free hosting
- Accessible via URL
- Version controlled

**Setup Steps:**

1. **Create GitHub repository**
   ```bash
   # If not already in a repo
   cd /path/to/artifacts
   git init
   git add .
   git commit -m "Initial commit: Red Hat AI Products Release Planner"
   git remote add origin https://github.com/emarion1/redhat-ai-release-planner.git
   git push -u origin main
   ```

2. **Add JIRA Token as Secret**
   - Go to repo **Settings** → **Secrets and variables** → **Actions**
   - Click **New repository secret**
   - Name: `JIRA_TOKEN`
   - Value: Your JIRA Personal Access Token
   - Click **Add secret**

3. **Enable GitHub Pages**
   - Go to **Settings** → **Pages**
   - Source: "Deploy from a branch"
   - Branch: `gh-pages`
   - Folder: `/ (root)`
   - Click **Save**

4. **Trigger first run**
   - Go to **Actions** tab
   - Select "Update Release Plan"
   - Click **Run workflow**
   - Wait ~2 minutes

5. **Access your dashboard**
   ```
   https://emarion1.github.io/redhat-ai-release-planner/release-manager.html
   ```

**Auto-update schedule:**
- Every Monday at 8:00 AM UTC
- On any code changes to `release_manager.py` or `auto_scheduler.py`
- Manual trigger anytime via Actions tab

---

### Option 2: Standalone Static Hosting

**Pros:**
- Simple deployment
- Can use any static host (S3, nginx, Apache, etc.)

**Setup Steps:**

1. **Generate HTML locally**
   ```bash
   export JIRA_TOKEN='your-token'
   python3 release_manager.py
   ```

2. **Deploy to static host**
   ```bash
   # Example: Copy to web server
   scp release-manager.html user@server:/var/www/html/

   # Example: Deploy to S3
   aws s3 cp release-manager.html s3://your-bucket/release-manager.html --acl public-read

   # Example: Serve locally
   python3 -m http.server 8000
   # Access: http://localhost:8000/release-manager.html
   ```

3. **Set up cron for updates** (optional)
   ```bash
   # Add to crontab
   0 8 * * 1 cd /path/to/repo && export JIRA_TOKEN='xxx' && python3 release_manager.py && scp release-manager.html user@server:/var/www/html/
   ```

---

### Option 3: Container Deployment

**Pros:**
- Isolated environment
- Reproducible builds
- Easy to run anywhere

**Setup Steps:**

1. **Create Dockerfile**
   ```dockerfile
   FROM python:3.11-slim

   WORKDIR /app

   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt

   COPY release_manager.py auto_scheduler.py ./

   CMD ["python3", "release_manager.py"]
   ```

2. **Build and run**
   ```bash
   docker build -t redhat-ai-release-planner .
   docker run -e JIRA_TOKEN='your-token' -v $(pwd):/app redhat-ai-release-planner
   ```

3. **Serve with nginx**
   ```bash
   docker run -d -p 8080:80 -v $(pwd)/release-manager.html:/usr/share/nginx/html/index.html:ro nginx
   # Access: http://localhost:8080
   ```

---

### Option 4: OpenShift Deployment

**Pros:**
- Native Red Hat platform
- Enterprise features
- Internal access control

**Setup Steps:**

1. **Create ConfigMap for scripts**
   ```bash
   oc create configmap release-manager-scripts \
     --from-file=release_manager.py \
     --from-file=auto_scheduler.py
   ```

2. **Create Secret for JIRA token**
   ```bash
   oc create secret generic jira-credentials \
     --from-literal=token='your-jira-token'
   ```

3. **Create CronJob**
   ```yaml
   apiVersion: batch/v1
   kind: CronJob
   metadata:
     name: release-manager-update
   spec:
     schedule: "0 8 * * 1"  # Every Monday 8 AM
     jobTemplate:
       spec:
         template:
           spec:
             containers:
             - name: generator
               image: python:3.11
               command:
               - /bin/sh
               - -c
               - |
                 pip install requests
                 python3 /scripts/release_manager.py
                 cp release-manager.html /output/
               env:
               - name: JIRA_TOKEN
                 valueFrom:
                   secretKeyRef:
                     name: jira-credentials
                     key: token
               volumeMounts:
               - name: scripts
                 mountPath: /scripts
               - name: output
                 mountPath: /output
             volumes:
             - name: scripts
               configMap:
                 name: release-manager-scripts
             - name: output
               persistentVolumeClaim:
                 claimName: release-manager-html
             restartPolicy: OnFailure
   ```

4. **Expose via Route**
   ```bash
   oc create route edge release-manager \
     --service=nginx-service \
     --port=8080
   ```

---

## Security Considerations

### JIRA Token Management

**Best Practices:**
1. Use **GitHub Secrets** (never commit tokens to repo)
2. Rotate tokens every 90 days
3. Use **read-only tokens** (no write permissions needed)
4. Set token expiration in JIRA

**Get JIRA Token:**
1. Go to https://issues.redhat.com/secure/ViewProfile.jspa
2. Click "Personal Access Tokens"
3. Click "Create token"
4. Name: "Red Hat AI Products Release Planner"
5. Expiration: 90 days
6. Copy token immediately

### Access Control

**GitHub Pages:**
- Public repo = public dashboard (anyone can view)
- Private repo = requires GitHub login
- For internal-only: Use private repo or deploy to internal host

**OpenShift:**
- Use Routes with OAuth authentication
- Integrate with Red Hat SSO
- Set RBAC policies

---

## Monitoring

### GitHub Actions

**View workflow runs:**
```
https://github.com/emarion1/YOUR-REPO/actions
```

**Check logs:**
1. Go to Actions tab
2. Click on specific run
3. Click "update-plan" job
4. Expand each step to see logs

**Notifications:**
1. Go to repo **Settings** → **Notifications**
2. Enable "Actions" notifications
3. Get email when workflow fails

### Health Checks

**Verify dashboard is live:**
```bash
curl -I https://emarion1.github.io/YOUR-REPO/release-manager.html
# Should return: HTTP/1.1 200 OK
```

**Check last update:**
```bash
curl -s https://emarion1.github.io/YOUR-REPO/release-manager.html | grep -o 'Generated.*2026'
```

---

## Troubleshooting

### Workflow Fails with "JIRA_TOKEN not set"

**Fix:**
1. Ensure secret is named exactly `JIRA_TOKEN`
2. Check Settings → Secrets → Actions
3. Re-add the secret if needed

### GitHub Pages shows 404

**Fix:**
1. Wait 1-2 minutes after first deployment
2. Check Settings → Pages shows green checkmark
3. Ensure branch is `gh-pages` and folder is `/ (root)`
4. Verify workflow pushed to gh-pages branch

### Dashboard shows old data

**Fix:**
1. Check Actions tab - did workflow run successfully?
2. Hard refresh browser: Ctrl+F5 or Cmd+Shift+R
3. Check workflow logs for errors

### "No draft plan available" message

**Fix:**
1. Check JIRA_TOKEN is valid (test with manual run)
2. Verify JIRA is accessible from GitHub Actions
3. Check workflow logs for JIRA query errors

---

## Maintenance

### Update Schedule

- **Weekly:** Automatic updates via GitHub Actions
- **On-demand:** Manual trigger via Actions tab
- **Code changes:** Auto-deploys when you push changes

### Token Rotation

Every 90 days:
1. Generate new JIRA token
2. Update GitHub secret
3. Test with manual workflow run

### Monitoring Checklist

- [ ] Check Actions tab weekly for failures
- [ ] Verify dashboard loads and shows recent data
- [ ] Review capacity trends monthly
- [ ] Update release goals in code as priorities change

---

## Cost

**GitHub Actions:**
- Free for public repos
- Private repos: 2,000 minutes/month free (this uses ~5 min/week)

**GitHub Pages:**
- Free for public repos
- Free for private repos (requires Pro/Team/Enterprise)

**Storage:**
- Minimal (~1 MB total)

---

## Support

**Issues:**
- File GitHub Issues in this repo
- Tag with "deployment" or "infrastructure"

**JIRA Access:**
- Contact JIRA admin for token issues
- Verify permissions to read RHAISTRAT project

**Questions:**
- Review README.md for usage instructions
- Check existing GitHub Issues
