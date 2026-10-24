# PepsiReport

A weekly deal finder for plain Pepsi Max and Cult Energy cans in Danish supermarkets. It
reads current offers from Tjek (eTilbudsavis), the REMA 1000 catalogue and nemlig.com,
works out the price per litre without pant, keeps a price history and compares each
offer with it.

## Running

Python 3.12, standard library only.

```
python3 -m dealfinder                          # live run
python3 -m dealfinder --offline tests/fixtures/sample   # saved responses, no network
python3 -m unittest discover -s tests -v       # tests
```

A run appends its offers to `data/history.csv` and writes `out/report.html` (sortable
table) and `out/report.csv`. It prints a summary with offers per product, quarantined and
rejected rows, excluded dealers, request counts and source errors. The exit status is 2
when a source failed; the report then lists the error at the top.

Other options: `--history PATH`, `--out DIR`, `--products PATH`, `--today YYYY-MM-DD`.

## Product ids

`data/products.json` lists confirmed product ids per source (tjek, rema, nemlig) for
Pepsi Max and Cult Energy. A row with a listed id is kept without the text rules below;
the cans and size rules still apply. Other rows go through the text rules, and the report
lists the ones that matched by text so their ids can be checked and added. The nemlig ids
are also the products the nemlig source fetches, one request each. Every history row
stores its source product id: the REMA product id, the nemlig id, or the Tjek offer id
(Tjek returns no EAN or GTIN).

nemlig.com gives a normal price and, during a campaign, a campaign price. Both are
stored. A "2 for 80" offer is recorded as 40.00 per pack, valid for the campaign dates.
Products that are out of stock are skipped and counted in the summary.

## The price list

The report lists every can offer, cheapest kr/L first. Each row shows how far its kr/L is
above or below that product's 12-week average (for example "-12%" or "+5%"), and the
lowest kr/L seen in those 12 weeks.

The average is the mean kr/L of the distinct offers stored in the 12 weeks before the
run. An offer seen in several runs counts once, and the current run is left out. Until
the history covers 4 weeks, the column reads "not enough history yet".

## What is included

- Only cans count, whether single cans, multipacks or cases. Bottles (PET, glass, "fl",
  anything of 1 L or more, or a REMA deposit of 1.50 kr) are neither shown nor stored;
  the summary counts them as "bottles dropped". A size under 1 L with no bottle word
  counts as a can. A row that names both cans and bottles goes to quarantine.
- Plain Pepsi Max only. After "Pepsi Max" the text may only hold sizes, pack and
  container words, or a connector to other products, as in "Pepsi Max eller Faxe Kondi".
  A row that names a flavour (lime, cherry, mango and so on) anywhere is left out, and a
  row with other unexplained words after "Pepsi Max" goes to quarantine. Regular Pepsi
  and SodaStream syrup are left out.
- A row that names Pepsi with several variants but not Max ("Pepsi eller Faxe Kondi,
  flere varianter") is listed with the note "variants, Max likely". It is never written
  to the history, so it does not affect the averages of later runs. It shows no %.
- Every Cult Energy variant. Cult Shaker and words like "Arla Cultura" do not count.
- Shops in Denmark only. Tjek marks German border shops as Danish, so a dealer must also
  be on the list of Danish chains in `dealfinder/match.py`. Other dealers are named in the
  summary as excluded.
- Prices are taken as excluding pant unless the text says "inkl. pant"; then 1 kr per
  can is taken off. Danish shops advertise prices without pant.
- Dates are Danish calendar dates (Europe/Copenhagen).

Offers the program cannot read safely (several pack sizes in one row, a size range,
text and quantity fields that disagree) go to the quarantine section of the report with
a reason. They are not added to the history. A malformed API row (bad date, missing id)
is listed under source errors and sets exit status 2; the rest of the run carries on.

## Weekly run on this PC

A Windows scheduled task runs the finder every Monday at 07:00 (local time), commits
`data/history.csv` to `main`, pushes it, and shows the Windows notification "Pepsi prices
updated". Clicking it opens `out\report.html`. It runs only while the PC is on and you are
logged in; if the PC was off at 07:00, the run starts at the next login or wake. Nothing
is published anywhere else.

The pieces are in `scripts/`:

- `weekly-run.sh` runs in WSL. It checks that no tracked file is modified or staged,
  checks out `main`, fetches, runs `git pull --ff-only`, and requires local `main` to
  equal `origin/main`. A commit left local by an earlier failed push is therefore
  reported, never stacked on; push it or reset it by hand. It then runs
  `python3 -m dealfinder`. The output must hold exactly one valid "Offers kept:" line and
  one "Source errors:" line, otherwise nothing is committed. When the exit status is 0 or
  2 and `data/history.csv` changed, it commits only that file as "Weekly prices
  YYYY-MM-DD" (those two lines go in the body). Before each push it checks that
  `origin/main..HEAD` is exactly that one commit and touches only `data/history.csv`,
  then pushes `origin main`. A rejected push is retried once after `git pull --rebase`.
  If that rebase fails and cannot be aborted, a separate notification says manual
  recovery is needed. It never force-pushes. If the finder crashes, or any other tracked
  file is changed or staged, nothing is committed. The output goes to `out/last-run.log`.
  A failed start-up (bad repository path, log file that cannot be opened) still shows
  the notification, and the reason goes to stderr. The script exits 0 on OK, 2 when the
  finder reported source errors (the history is still committed), and 1 on any failure.
  A crash that leaves `data/history.csv` modified makes the next run refuse until you
  restore it with `git restore data/history.csv`.
- `notify.ps1` shows the notification with built-in Windows PowerShell 5.1 APIs. If the
  toast fails it falls back to a balloon tip, then to `msg.exe`, and logs which one it
  used. Call it with the status text as `-Status` (`-Message` is an alias, and the text
  also works as the first positional argument); `-Title` and `-ReportPath` are optional:
  `powershell.exe -File scripts\notify.ps1 -Status "OK, 8 offers"`. It exits non-zero if
  no notification could be shown.
- `register-weekly-task.ps1` registers the task "PepsiReport weekly prices".

`git push` uses the GitHub CLI as credential helper (`gh auth git-credential`, set in
`~/.gitconfig` in WSL), so `gh auth status` must stay logged in.

Register, from PowerShell on Windows (run it again to replace the task):

```
powershell -ExecutionPolicy Bypass -File C:\Users\chulf\PepsiReport\scripts\register-weekly-task.ps1
powershell -ExecutionPolicy Bypass -File C:\Users\chulf\PepsiReport\scripts\register-weekly-task.ps1 -WhatIf   # preview only
```

Run it by hand, from WSL or by starting the task:

```
bash scripts/weekly-run.sh
powershell.exe -Command "Start-ScheduledTask -TaskName 'PepsiReport weekly prices'"
```

Unregister:

```
powershell -ExecutionPolicy Bypass -File C:\Users\chulf\PepsiReport\scripts\register-weekly-task.ps1 -Unregister
```

The git-safety tests are in `tests/test_weekly_run.py`; they use a temporary repository
and a fake finder, set through `WEEKLY_REPO`, `DEALFINDER_CMD` and `NOTIFY_CMD`.
