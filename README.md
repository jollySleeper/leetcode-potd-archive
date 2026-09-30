# LeetCode POTD Archive

An archive of LeetCode's Daily Coding Challenge (Problem of the Day) from April 2020, and of the weekly challenge LeetCode returns beside it from August 2020.

- Browse by month on GitHub: [archive/README.md](archive/README.md)
- Search and filter on the site: <https://jollysleeper.github.io/leetcode-potd-archive/>

The site is static. It loads one file, `public/challenges.json`, and filters it in the browser.

## How the data is organized

`archive/YYYY/YYYY-MM.json` is the canonical data: the validated LeetCode response for the month that was queried. A snapshot can contain a weekly challenge dated in the next month; it stays in the file of the month that returned it.

`build` reads every snapshot and generates, grouped by each challenge's own date:

- `archive/YYYY/YYYY-MM.md`, one calendar page per month
- `archive/README.md`, the month index
- `public/challenges.json`, the single file the site fetches

Do not edit the generated files by hand. Change a snapshot (normally by re-fetching it) and run `build`.

## Regenerating locally

Python 3.11 or newer is enough. There are no packages to install.

```text
python3 scripts/update_potd.py backfill                       # every month from 2020-04 through the current UTC month
python3 scripts/update_potd.py previous-month                 # the month before the current UTC month
python3 scripts/update_potd.py fetch --year 2026 --month 9    # re-fetch one month
python3 scripts/update_potd.py build                          # regenerate Markdown and public/challenges.json, no network
```

Every fetch runs `build` afterwards. A month is saved only when LeetCode returns every day of it.

Run the tests (they never touch the network):

```text
python3 -m unittest discover -s scripts -p "test_*.py" -v
```

To preview the site, serve `public/` and open <http://localhost:8000/>:

```text
python3 -m http.server --directory public
```

## Automatic updates

The **Update POTD archive** workflow runs at 01:15 UTC on the 1st of each month, with a retry on the 2nd. It fetches the previous month, commits the changed archive files, and deploys the site. When nothing changed it makes no commit.

To run it by hand, open **Actions → Update POTD archive → Run workflow** and pick a mode:

- `previous-month`: the same as the scheduled run
- `backfill`: re-fetch every month
- `fetch`: repair one month; fill in `year` and `month` (1-12)

Tests and a check that the generated files match the snapshots run on every push and pull request.

No LeetCode login, cookie, or token is used. The archive only calls LeetCode's public GraphQL endpoint.

Not affiliated with LeetCode; problem titles and links belong to LeetCode.
