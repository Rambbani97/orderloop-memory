# Importing Products via CSV (UTF-8 Encoding)

**Applies to:** All plans · **Last updated:** November 2026

## The encoding problem

CSV files saved from Microsoft Excel are often stored in **ANSI**
(Windows-1250 / Windows-1252) encoding instead of UTF-8. Characters outside
plain ASCII — Polish ł, ę, ś; Spanish ñ; French é, è; German ü — get mangled,
and OrderLoop's importer rejects the file with "Invalid file format" before
processing any row.

You can spot it by opening the CSV in a plain text editor (e.g. Notepad): if
accented characters show as strange symbols, the file is not UTF-8.

## How to save a CSV as UTF-8 in Excel

1. Open the file in Excel.
2. **File > Save As** and choose **"CSV UTF-8 (Comma delimited) (*.csv)"** —
   not plain "CSV (Comma delimited)".
3. Make sure there are no duplicate BOM markers or empty trailing rows.
4. Upload again via **Products > Import**.
5. Before confirming the full import, check the first 5–10 rows in the
   preview: accented characters must display correctly.

## Alternative: Google Sheets

Open the file in Google Sheets, then **File > Download > Comma-separated
values (.csv)**. Google Sheets always exports UTF-8.

## Tips

- Always start from the template downloaded from OrderLoop
  (**Products > Import > Download template**) and only fill in the rows.
- The error appears immediately after upload, before any row is processed —
  that is the importer rejecting the file encoding, not a problem with your
  product data.
- If the preview shows correct characters but the import still fails, check
  for a stray empty row at the end of the file or a duplicate header row.
