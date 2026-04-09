# sync-worker

Tiny Cloudflare Worker that dispatches the `Update leaderboard` GitHub
Actions workflow on demand. Wired up to an external pinger (e.g.
cron-job.org) so the site is rebuilt on a reliable 10-minute schedule
instead of depending on GitHub's unreliable `schedule` trigger.

## Architecture

```
cron-job.org  ──POST + X-Sync-Secret─▶  Cloudflare Worker
                                              │
                                              │  POST /workflows/update.yml/dispatches
                                              ▼
                                        GitHub API
                                              │
                                              ▼
                                     GitHub Actions runs
                                              │
                                              ▼
                                     Deploy to GitHub Pages
```

## One-time setup

### 1. Generate a GitHub fine-scoped PAT

1. Go to <https://github.com/settings/personal-access-tokens/new>
2. **Token name**: `masters-tracker-sync`
3. **Expiration**: 90 days (or your preference)
4. **Resource owner**: your user
5. **Repository access**: *Only select repositories* → `masters-tracker`
6. **Repository permissions** → **Actions**: `Read and write`
7. Click **Generate token** and copy the value (`github_pat_…`)

### 2. Create the Cloudflare Worker

1. Sign up at <https://dash.cloudflare.com/sign-up> (free, no card)
2. Dashboard → **Workers & Pages** → **Create** → **Create Worker**
3. Name: `masters-tracker-sync`
4. Click **Deploy** (deploys the placeholder)
5. **Edit code** → paste the contents of `worker.js` → **Deploy**

### 3. Set Worker environment variables

Worker page → **Settings** → **Variables and Secrets**:

| Name          | Type     | Value                          |
| ------------- | -------- | ------------------------------ |
| `GH_TOKEN`    | Secret   | the PAT from step 1            |
| `SYNC_SECRET` | Secret   | long random string (see below) |
| `GH_OWNER`    | Plain    | `chillok`                      |
| `GH_REPO`     | Plain    | `masters-tracker`              |
| `GH_WORKFLOW` | Plain    | `update.yml`                   |
| `GH_REF`      | Plain    | `main`                         |

Generate a random shared secret locally:

```bash
openssl rand -hex 32
```

### 4. Test the Worker

```bash
curl -i -X POST \
  -H "X-Sync-Secret: <the secret>" \
  https://masters-tracker-sync.<your-subdomain>.workers.dev
```

Expected: `HTTP/2 202` and `dispatched`. Then check the repo Actions
tab — a `workflow_dispatch` run should appear within a second or two.

### 5. Set up cron-job.org

1. Sign up at <https://cron-job.org>
2. **Create cronjob**
3. **URL**: the Worker URL from step 4
4. **Schedule**: Every 10 minutes (`*/10 * * * *`)
5. **Advanced** → Request method: `POST`
6. **Advanced** → Request headers:
   - `X-Sync-Secret: <the same secret>`
7. Save and enable

cron-job.org's free tier has no rate issues at 10-min intervals.

## Updating the Worker code

The Worker source lives in `worker.js` in this repo for version
control. To redeploy after edits: paste the updated `worker.js`
contents into the Cloudflare dashboard editor and click **Deploy**.

(If you want CLI-based deploys, install `wrangler`; not required for
this tiny Worker.)
