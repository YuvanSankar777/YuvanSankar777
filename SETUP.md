# Setup

## 1. Create the profile repo
Create a **public** repo named **exactly your GitHub username** (e.g. `yuvan/yuvan`).
GitHub treats its README as your profile page.

## 2. Add these files
Copy `scripts/`, `.github/`, `requirements.txt`, `README.template.md`, and `README.md`
into that repo. Edit `README.template.md` with your name and links (edit the template,
**never** `README.md` — it gets overwritten).

## 3. Test locally (optional)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export GITHUB_TOKEN=ghp_your_personal_access_token   # classic PAT, `repo` scope
python scripts/update_readme.py
```
Open `README.md` to see the result.

## 4. Run it in GitHub Actions
- Push to `main`. The workflow also runs on push (see `.github/workflows/update.yml`).
- Or go to **Actions → Update README → Run workflow** to trigger manually.
- After the first run, a bot commit `chore: auto-update README [skip ci]` appears,
  and it repeats every 6 hours on the cron schedule.

The built-in `GITHUB_TOKEN` covers all **public** data. Only add a personal
access token secret if you want private-repo stats.

## 5. Enable the blog section (optional)
In `.github/workflows/update.yml`, uncomment `BLOG_RSS_URL` and set it to your feed,
e.g. `https://dev.to/feed/yourusername`.

## How it works
`update_readme.py` fetches your data with one GitHub GraphQL query, renders each
section, and swaps the content between `<!--MARKER-->` / `<!--END_MARKER-->` pairs
in the template. Each section fails independently, so a down API never blanks the page.

## Markers available
| Marker | Content |
| --- | --- |
| `RECENT_REPOS` | 5 most recently pushed repos |
| `STATS` | stars, repos, commits, PRs, followers |
| `TOP_LANGS` | language breakdown bars |
| `BLOG` | latest RSS posts (needs `BLOG_RSS_URL`) |
| `TIMESTAMP` | last-updated time |
