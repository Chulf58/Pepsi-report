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
