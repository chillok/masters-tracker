// Cloudflare Worker: masters-tracker-sync
//
// Receives a POST from an external pinger (e.g. cron-job.org) and dispatches
// the `Update leaderboard` GitHub Actions workflow so the site is regenerated
// on a reliable schedule. GitHub's own schedule trigger is unreliable for
// short intervals on free public repos, so we drive it externally.
//
// Required Worker environment variables (set in the Cloudflare dashboard):
//   GH_TOKEN      (secret)  fine-scoped PAT with Actions: Read/Write on the repo
//   SYNC_SECRET   (secret)  shared secret the pinger must send in X-Sync-Secret
//   GH_OWNER      (plain)   e.g. "chillok"
//   GH_REPO       (plain)   e.g. "masters-tracker"
//   GH_WORKFLOW   (plain)   filename or id, e.g. "update.yml"
//   GH_REF        (plain)   branch name, e.g. "main"

export default {
  async fetch(req, env) {
    if (req.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    const provided = req.headers.get("X-Sync-Secret");
    if (!env.SYNC_SECRET || provided !== env.SYNC_SECRET) {
      return new Response("Unauthorized", { status: 401 });
    }

    const url = `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}/actions/workflows/${env.GH_WORKFLOW}/dispatches`;

    const ghResp = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "masters-tracker-sync/1.0",
      },
      body: JSON.stringify({ ref: env.GH_REF || "main" }),
    });

    if (!ghResp.ok) {
      const text = await ghResp.text();
      return new Response(`GitHub API error: ${ghResp.status} ${text}`, {
        status: 502,
      });
    }

    return new Response("dispatched\n", { status: 202 });
  },
};
