# Music Mile community calendar

A beginner-friendly scraper that combines publicly listed events from Music Mile venues into one calendar webpage. GitHub Actions refreshes it every Monday and GitHub Pages hosts it free.

## Set it up (no coding experience required)

1. Create a free account at https://github.com and sign in.
2. Click **New repository**. Name it `music-mile-calendar`, choose **Public**, and click **Create repository**.
3. Download and unzip this project. On your repository page choose **Add file → Upload files**. Drag in the *contents* of the unzipped `music-mile-calendar` folder, including `.github`, `config`, and `docs`, then commit the files. If Windows hides `.github`, turn on **View → Show → Hidden items** in File Explorer first.
4. Open the repository's **Settings → Pages**. Under “Build and deployment,” choose **Deploy from a branch**. Select `main`, choose `/docs`, and click **Save**.
5. Open the **Actions** tab, select **Update calendar**, and click **Run workflow** for the first update.
6. After a minute or two, Settings → Pages displays your public URL: `https://YOUR-USERNAME.github.io/music-mile-calendar/`.

The workflow runs every Monday. GitHub may disable scheduled workflows after 60 days with no repository activity; if that happens, open **Actions** and re-enable it.

The most active sources have dedicated adapters: King Eddy and Studio Bell use their event-card markup; Ironwood and Gravity use their public Stagehand listings; The Attic generates the recurring series explicitly described on its events page; and the Calgary Folk Fest listing is filtered to cards whose venue field is exactly `Festival Hall`. Dates that cannot be parsed, dates more than two years away, and events that have ended are not published.

## Change or add a venue

Open `config/venues.yml` on GitHub, click the pencil icon, edit a name or URL, and commit. The next run will use it. The webpage's **Source status** section shows failures and zero-result sources because venue websites sometimes change.

## Test on your computer (optional)

Install Python 3.12, open a terminal in this folder, then run:

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scrape.py
python -m http.server 8000 --directory docs
```

Open http://localhost:8000. Press `Ctrl+C` to stop the local server.

## Important limitation

This reads public venue webpages. Venues that publish only to Instagram/Facebook, show only recurring prose, block automated access, or do not include machine-readable dates may show zero events. The status panel makes that visible. Review the calendar periodically and respect each site's terms and robots policy.
