# MAA bond data feed (free)

A GitHub Action runs `fetch_data.py` every weekday and commits `data.json`.
The MAA Bond Worksheet reads that file.

Sources: FINRA TRACE end-of-day last-sale price and yield, pulled through the
open-source OpenBB FINRA provider. U.S. Treasury par yield curve, with FRED as
the fallback. No keys or paid services.

## One-time setup (about 10 minutes)

1. Create a free GitHub account, then a new **public** repository named `maa-bond-data`.
   It has to be public: the worksheet reads the raw file with no login.
   The data is public market data.
2. Upload `fetch_data.py` and `README.md` to the repo root. Upload `update-data.yml` to
   `.github/workflows/update-data.yml`. The folder path matters; GitHub ignores the file anywhere else.
3. Go to **Settings → Actions → General → Workflow permissions** and choose **Read and write permissions**.
4. Go to **Actions → Update MAA bond data → Run workflow**. After 2–4 minutes, `data.json` appears in the repo.
   If the run fails, open it and read the log. Errors also land in `data.json` under `"errors"`.
5. Open `data.json` in GitHub, click **Raw**, and copy the URL. It looks like
   `https://raw.githubusercontent.com/<you>/maa-bond-data/main/data.json`.
6. Open the worksheet, click **Data source**, and paste the URL. It's saved in that browser.
   To bake it into the file instead, set `DEFAULT_DATA_URL`.

## Schedule

Weekdays at 22:30 and 11:30 UTC. GitHub can start scheduled runs late, sometimes
by up to an hour. GitHub disables scheduled workflows in a repo with no activity
for 60 days. If the badges go stale, check the Actions tab and re-enable the workflow.
