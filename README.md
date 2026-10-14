# Sri Lankan Tamil Inscriptions Bibliography

A categorised bibliography of publications on **Sri Lankan Tamil inscriptions, archaeology, hero stones and rock art**, covering 1996–2026 plus key earlier reference works.

**Keywords:** கல்வெட்டு · கல்வெட்டுகள் · தமிழ் · தொல்லியல் · நடுகல் · பாறை ஓவியம் · inscription · epigraphy · Tamil Brahmi · archaeology · hero stone · rock art · coins

## Download

| File | What it is |
|---|---|
| [`output/SriLanka_Tamil_Inscriptions_Bibliography.xlsx`](output/SriLanka_Tamil_Inscriptions_Bibliography.xlsx) | Excel workbook: Summary, Books, Research Papers, Newspaper Articles, Magazines & Journals, All Records, Sources & Method |
| [`output/bibliography.csv`](output/bibliography.csv) | The same records as one CSV (UTF-8, opens in Excel) |

Each record has: ID, year, date, title, author/editor, publisher/source, type, language, themes, keywords, whether it falls within 1996–2026, notes, and a clickable URL.

## How it is organised

```
data/raw/batchNN.tsv     hand-collected records (researched and checked)
data/raw/auto_*.tsv      records added automatically by the weekly scraper (marked "review" in Notes)
data/last_run.json       what the last scraper run found
scraper/config.json      search keywords and place names (edit this to change what is collected)
scraper/collect.py       the scraper
scripts/build_excel.py   rebuilds the Excel and CSV from data/raw/*.tsv
.github/workflows/       weekly GitHub Actions schedule
```

## Automatic weekly updates

Every Monday, GitHub Actions runs `scraper/collect.py`, which searches:

- **Google News** (Tamil and English): newspaper reports, filed under *Newspaper Articles*
- **Ezhuna (எழுநா)**: online magazine articles, filed under *Magazines & Journals*
- **Noolaham (நூலகம்)**: digitised books, magazines and newspapers
- **OpenAlex** and **Crossref**: scholarly articles and books, filed under *Research Papers* / *Books*

New, relevant items that aren't already in the data are appended, the Excel is rebuilt, and the change is committed.

To run it by hand, open **Actions → Weekly bibliography update → Run workflow**.

Auto-collected rows are marked `Auto-collected <date> (<source>); review.` in Notes. Check them before citing. When you have checked a row, you can move it into a `batchNN.tsv` file.

## Adding records by hand

Add a row to any `data/raw/*.tsv` file, with tab-separated columns:

`category  type  year  date  title  author  publisher_source  language  keywords  url  notes`

`category` must be one of: `Books`, `Research Papers`, `Newspaper Articles`, `Magazines/Journals`.

Then rebuild:

```bash
pip install -r requirements.txt
python scripts/build_excel.py
```

## Coverage notes

- Rows whose Notes say **"to verify"** are missing a year, author or exact title.
- Older works (before 1996) are included only where they are foundational for Tamil epigraphy in Sri Lanka. They are flagged `No (earlier reference)` in the *Within 1996-2026* column.
- Newspaper coverage is strongest for TamilNet, Tamil Guardian, Virakesari, Thinakkural, Tamil Mirror and the English weeklies. Many older Tamil newspaper issues are only available as page scans on Noolaham, which the scraper indexes by issue rather than by article.
