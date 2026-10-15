# Quota Persistence for GitHub Actions Workflows

> **Updated (2026-10-15):** written for router v0.2.0. The current, verified
> end-to-end pattern (ledger cache restore/save, SIGTERM flush, concurrency
> serialization) lives in `skills/gemini-router/references/ops-and-ci.md`.

## Why Persist Quota State?

The `gemini-free-router` tracks per-model RPM (requests per minute), RPD (requests per day), and TPM (tokens per minute) using a sliding window. By default, each GitHub Actions workflow runs on a fresh ephemeral runner, so quota state **does not persist** between runs.

For contentfte's SEO blog agent, this means:
- Each workflow starts with full free-tier quota (15 RPM / 500 RPD / 250K TPM per model)
- Blogs generated in previous workflows don't count against the current workflow's quota
- If you generate 1-3 blogs per workflow, this is usually sufficient

However, if you want quota to **accumulate across workflows** (e.g., a daily limit of 20 blogs total regardless of how many workflows run), you need to persist state.

This document covers three practical approaches, with the recommended implementation for contentfte.

---

## Approach 1: GitHub Actions Artifacts (Recommended)

**Best for**: Most contentfte use cases. Zero cost, zero external services, built-in GitHub features.

### How It Works

Each workflow run uploads a `quota-state.json` artifact at the end. The next workflow downloads it at the start, reads the persisted state, and continues from where the previous workflow left off.

### 1. Create the Tracking Script

**`track-quota.ts`**:

```typescript
import { readFileSync, writeFileSync, existsSync } from 'fs';
import { join } from 'path';

// Path for local file (will be artifact in GitHub Actions)
const LOCAL_PATH = './quota-state/quota-state.json';

// Read previous state from artifact (populated by workflow)
let state = {
  lastRun: new Date().toISOString(),
  blogsGenerated: 0,
  rpmUsed: 0,
  rpdUsed: 0,
};

if (existsSync(LOCAL_PATH)) {
  try {
    const prev = JSON.parse(readFileSync(LOCAL_PATH, 'utf8'));
    state = { ...state, ...prev };
    console.log(`Loaded previous state from ${prev.lastRun}`);
  } catch (e) {
    console.warn('Failed to read previous state, starting fresh');
  }
}

// === INCREMENT DURING WORKFLOW ===
// Call these functions at appropriate points in your workflow:

function incrementBlogs() {
  state.blogsGenerated += 1;
}

function incrementRPM() {
  state.rpmUsed += 1;
}

function incrementRPD() {
  state.rpdUsed += 1;
}

// === WRITE STATE ===
function saveState() {
  // Ensure directory exists
  const dir = './quota-state';
  if (!existsSync(dir)) {
    require('fs').mkdirSync(dir, { recursive: true });
  }
  writeFileSync(LOCAL_PATH, JSON.stringify(state, null, 2));
  console.log(`State saved: ${JSON.stringify(state)}`);
}

// === EXPORT FOR USE IN WORKFLOW ===
export { state, incrementBlogs, incrementRPM, incrementRPD, saveState };
```

### **2. GitHub Actions Workflow**

```yaml
name: SEO Blog Generation with Quota Persistence

on:
  workflow_dispatch:
    inputs:
      topic:
        description: 'Blog topic'
        required: true
        default: "AI"

jobs:
  generate-blog:
    runs-on: ubuntu-latest
    concurrency: github.workflow  # CRITICAL: Serialize runs to prevent races
    timeout-minutes: 10
    
    steps:
      - uses: actions/checkout@v4
      
      # --- QUOTA PERSISTENCE START ---
      
      - name: Download previous quota state artifact
        uses: actions/download-artifact@v3
        with:
          name: quota-state
          path: ./quota-state/  # Downloads to this directory
          
      - name: Initialize quota state (if new)
        run: |
          if [ ! -f ./quota-state/quota-state.json ]; then
            echo '{"lastRun":"1970-01-01T00:00:00.000Z","blogsGenerated":0,"rpmUsed":0,"rpdUsed":0}' > ./quota-state/quota-state.json
          fi
          
      - name: Read current quota state
        run: |
          cat ./quota-state/quota-state.json
          
      - name: Run blog generation
        run: |
          # Your blog generation code here
          # Call incrementBlogs(), incrementRPM(), incrementRPD() as needed
          # Example: node -e "const {incrementBlogs} = require('./track-quota'); incrementBlogs(); saveState()"
          
          # Or call your contentfte blog generator
          python contentfte/blog_generator.py --topic "$TOPIC"
          
      - name: Save updated quota state
        run: |
          node -e "
            const {saveState, state} = require('./track-quota');
            saveState();
            console.log('State:', JSON.stringify(state));
          "
          
      # --- QUOTA PERSISTENCE END ---

      - name: Generate blog
        run: |
          # Your existing blog generation step
          # This now has access to persisted quota state
          
      - name: Upload quota state artifact
        uses: actions/upload-artifact@v4
        with:
          name: quota-state
          path: ./quota-state/quota-state.json
          retention-days: 30  # Keep for 30 days (1-90 allowed)
```

### **How It Works in Practice**

| Workflow Run | Artifact State | Behavior |
|---|---|---|
| **Run #1** | No artifact exists → state initialized to zeros | Generates blog → state uploaded with `blogsGenerated: 1, rpmUsed: 1` |
| **Run #2** | Downloads artifact → reads `blogsGenerated: 1, rpmUsed: 1` | Generates blog → state uploaded with `blogsGenerated: 2, rpmUsed: 2` |
| **Run #3** | Downloads artifact → reads `blogsGenerated: 2, rpmUsed: 2` | Generates blog → state uploaded with `blogsGenerated: 3, rpmUsed: 3` |

### **Key Configuration**

- **`concurrency: github.workflow`**: Ensures only one workflow runs at a time, preventing lost updates from parallel runs
- **`retention-days: 30`**: Keeps artifacts for 30 days (can be 1-90). After 30 days, the artifact is garbage collected.
- **Path handling**: Artifact downloads to the specified path; we use `./quota-state/` directory.

### **Pros & Cons**

| Pros | Cons |
|---|---|
| ✅ Zero cost (included in GitHub) | ⬜ Artifacts max 90-day retention |
| ✅ Zero external services | ⬜ Lost updates if two runs overlap without concurrency group |
| ✅ Simple to implement | ⬜ Requires `concurrency: github.workflow` for safety |
| ✅ No external credentials | ⬜ Artifacts are immutable (new upload creates new artifact version) |
| ✅ Built-in GitHub features | |

---

## Approach 2: Repository File (Git Commit)

**How It Works**: Each workflow reads/writes `quota-state.json` in the repo and commits changes.

### Implementation Overview

1. **Script reads/writes** `quota-state.json` in repo root
2. **Workflow commits** changes using `actions/checkout` + `git commit`
3. **State persists** in git history

### **GitHub Actions Steps**

```yaml
jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4  # Required for git push
      
      - name: Track quota state
        run: |
          # Read, update, write quota-state.json
          # Git add, commit, push
          git config user.email "actions-bot@github.com"
          git config user.name "GitHub Actions"
          git add quota-state.json
          git commit -m "chore: update quota state [skip ci]"
          git push
      
      - name: Generate blog
        run: python contentfte/blog_generator.py
```

### **Pros & Cons**

| Pros | Cons |
|---|---|
| ✅ State persists permanently in git history | ⬜ Commits on every run → noise in git history |
| ✅ No artifact management | ⬜ Requires `actions/checkout` permission expansion |
| ✅ Full version history of state changes | ⬜ Rate limits: GITHUB_TOKEN limited to 1,000 requests/hour |
| ⬜ No artifact storage costs | ⬜ Not ideal for high-frequency updates |
| ⬜ Can track historical data in git log | ⬜ Sensitive data in repo (avoid secrets) |

---

## Approach 3: Cloud Object Storage (S3/GCS/Azure)

**How It Works**: Store quota state in cloud storage with conditional writes (optimistic locking).

### **S3 Example (TypeScript)**

```typescript
import { S3Client, GetObjectCommand, PutObjectCommand } from '@aws-sdk/client-s3';

const s3 = new S3Client({ region: 'us-east-1' });
const BUCKET = 'my-quota-bucket';
const KEY = 'quota-state.json';

async function getQuotaState() {
  try {
    const { Body } = await s3.send(new GetObjectCommand({ Bucket: BUCKET, Key: KEY }));
    return JSON.parse(Body.toString());
  } catch {
    return { lastRun: '', blogsGenerated: 0, rpmUsed: 0, rpdUsed: 0 };
  }
}

async function updateQuotaState(update: any) {
  const { Body: data } = await s3.send(new GetObjectCommand({ Bucket: BUCKET, Key: KEY }));
  const current = JSON.parse(data.toString());
  const newState = { ...current, ...update, lastRun: new Date().toISOString() };
  
  // Optimistic locking: PUT with If-Match using ETag
  await s3.send(new PutObjectCommand({
    Bucket: BUCKET,
    Key: KEY,
    Body: JSON.stringify(newState),
    // If-Match: current.ETag  // This prevents lost updates
  }));
  
  return newState;
}
```

### **GitHub Actions with OIDC**

```yaml
- name: Configure AWS credentials
  uses: aws-actions/configure-aws-credentials@v4
  with:
    role-to-assume-arn: arn:aws:iam::123456789012:role/GitHubActionsS3
    aws-region: us-east-1

- name: Get quota state
  run: npx ts-node s3-quota.ts --get

- name: Generate blog
  run: python contentfte/blog_generator.py

- name: Update quota state
  run: npx ts-node s3-quota.ts --update --blogs 1
```

### **Pros & Cons**

| Pros | Cons |
|---|---|
| ✅ High durability and concurrency | ⬜ Requires cloud account (AWS/GCP/Azure) |
| ✅ Strong consistency with conditional writes | ⬜ IAM setup and permissions management |
| ✅ Works across independent workflows | ⬜ Cloud storage costs ($$$) |
| ✅ Excellent for high-frequency updates | ⬜ Overkill for simple quota tracking |
| ✅ Lifecycle policies can auto-cleanup | ⬜ More complex than artifacts |

---

## Decision Matrix

| Choose This Approach If... | Avoid If... |
|---|---|
| **Low-frequency, low-concurrency** (1-5 blogs/workflow) | You need indefinite retention >90 days |
| **Zero cost is a priority** | You need millisecond-level consistency |
| **Simple setup preferred** | You're already using AWS/Azure/GCP and have IAM setup |
| **GitHub native features suffice** | Your workflows run highly concurrently without serialization |
| **Contentfte typical use** (1-3 blogs/workflow) | You're tracking 100+ blogs/day |

---

## Implementation Walkthrough for contentfte

### **Step 1: Add Artifact Persistence to Your Workflow**

Add this to your existing `.github/workflows/blog-generation.yml`:

```yaml
name: Generate SEO Blog

on:
  workflow_dispatch:
    inputs:
      topic:
        description: 'Blog topic'
        required: true
        default: "AI"

jobs:
  generate:
    runs-on: ubuntu-latest
    concurrency: github.workflow  # CRITICAL: Serialize runs!
    timeout-minutes: 10
    
    steps:
      - uses: actions/checkout@v4
      
      # ---- QUOTA PERSISTENCE START ----
      
      - name: Download previous quota state
        uses: actions/download-artifact@v3
        with:
          name: quota-state
          path: ./quota-state/
          
      - name: Initialize quota state (if new)
        run: |
          if [ ! -f ./quota-state/quota-state.json ]; then
            mkdir -p quota-state
            echo '{"lastRun":"1970-01-01T00:00:00.000Z","blogsGenerated":0,"rpmUsed":0,"rpdUsed":0}' > ./quota-state/quota-state.json
          fi
          
      - name: Read current state
        run: |
          cat ./quota-state/quota-state.json
          
      - name: Run blog generation
        run: |
          # Your existing blog generation code
          # During generation, increment counters:
          #   npm run increment-blogs     # or equivalent
          #   npm run increment-rpm       # or equivalent
          #   npm run increment-rpd       # or equivalent
          
      - name: Save updated quota state
        run: |
          # Read current, increment, write back
          STATE=$(cat ./quota-state/quota-state.json)
          BLOGS=$(( $(echo "$STATE" | jq '.blogsGenerated') + 1 ))
          RPM=$(( $(echo "$STATE" | jq '.rpmUsed') + 1 ))
          RPD=$(( $(echo "$STATE" | jq '.rpdUsed') + 1 ))
          DATE=$(date -u +%Y-%m-%dT%H:%M:%S.000Z)
          echo "{\"lastRun\":\"$DATE\",\"blogsGenerated\":$BLOGS,\"rpmUsed\":$RPM,\"rpdUsed\":$RPD}" > ./quota-state/quota-state.json
          
      - name: Upload quota state artifact
        uses: actions/upload-artifact@v4
        with:
          name: quota-state
          path: ./quota-state/quota-state.json
          retention-days: 30
      # ---- QUOTA PERSISTENCE END ----
      
      - name: Generate blog
        run: |
          python contentfte/blog_generator.py \
            --topic "${{ github.event.inputs.topic }}"
```

### **Step 2: Add TypeScript Tracking Script (Optional)**

If you want TypeScript-typed state management, add `track-quota.ts` to your repo and compile/run via `npx ts-node`:

```typescript
// track-quota.ts - as shown above
// Then in workflow:
- run: npx ts-node track-quota.ts
```

### **Step 3: Update Your Blog Generation Code**

Modify your blog generator to read from and write to the quota state:

```typescript
// In your blog generator TypeScript/Python:
// Read state at start:
const state = JSON.parse(readFileSync('./quota-state/quota-state.json', 'utf8'));

// During generation:
state.blogsGenerated += 1;
state.rpmUsed += 1;  // or however you track

// Write state at end:
writeFileSync('./quota-state/quota-state.json', JSON.stringify(state, null, 2));
```

---

## Verification Steps

### **Test: Two Consecutive Workflow Runs**

1. **Trigger Workflow #1** with topic "AI"
   - Check artifact: should show `blogsGenerated: 1`
   
2. **Trigger Workflow #2** with topic "SEO"
   - Check artifact: should show `blogsGenerated: 2`
   - Verify the state carried over correctly

### **Test: Concurrency Safety**

Ensure `concurrency: github.workflow` is set in your workflow YAML. This guarantees only one workflow runs at a time, preventing race conditions on the artifact.

### **Step 4: Monitor**

- Go to GitHub → Actions → Your workflow → Artifacts tab
- Verify artifacts are being downloaded/uploaded correctly
- Check that `quota-state.json` values increment as expected

---

## Checklist for Implementation

- [ ] Add `concurrency: github.workflow` to your blog generation job
- [ ] Add artifact download step at workflow start
- [ ] Add artifact upload step at workflow end
- [ ] Create `quota-state/quota-state.json` initialization logic
- [ ] Add quota increment logic during blog generation
- [ ] Test with two consecutive workflow runs
- [ ] Set `retention-days` appropriate for your needs (default 30)
- [ ] Document the process for your team

---

## Migration from No Persistence

If you're currently **not** persisting quota:

1. **First workflow run**: State initialized to zeros → generates blogs → state uploaded
2. **Second workflow run**: Downloads previous → increments → generates blogs → state uploaded
3. **Subsequent runs**: Always starts from where previous left off

The transition is backward-compatible—existing workflows without persistence will simply start fresh each time, and new workflows with artifact persistence will begin tracking from zero on their first run.

---

## Frequently Asked Questions

**Q:** *What if two workflows run simultaneously?*  
**A:** Add `concurrency: github.workflow` to your job. This ensures only one workflow runs at a time, preventing lost updates on the artifact.

**Q:** *Can I persist other state beyond blogs/RPM?*  
**A:** Yes—the `quota-state.json` can hold any JSON. Just ensure both workflows agree on the schema.

**Q:** *What if the artifact upload fails?*  
**A:** The workflow will fail, and the artifact won't be updated. The next workflow will download the previous successful artifact. Retry the workflow.

**Q:** *Can I keep state forever?*  
**A:** Artifacts have max 90-day retention. For permanent storage, consider Approach 2 (git commit) or Approach 3 (cloud storage).

**Q:** *Do I need this if I only generate 1 blog per workflow?*  
**A:** If 1 blog per workflow is within your free-tier quota, you don't strictly need persistence. However, it provides valuable tracking and is low-friction to implement.

---

## Final Recommendation

For contentfte's SEO Blog Agent, **Approach 1 (GitHub Artifacts)** provides the best balance of:

- ✅ Zero cost
- ✅ Zero external services
- ✅ Sufficient for typical use (1-3 blogs/workflow)
- ✅ Built-in GitHub features (no infrastructure to manage)
- ✅ Easy to implement and understand

Add the artifact persistence steps to your existing workflow, and you'll have persistent quota tracking with minimal effort.

---
*Guide last updated: October 2026. Compatible with gemini-free-router v0.2.0.*