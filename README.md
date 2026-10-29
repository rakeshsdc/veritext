# VeriText

Document similarity and plagiarism screening for teachers and reviewers. Built with Python and Streamlit.

## What it does

**Module 1: Plagiarism check.** Upload a .docx or .pdf. The app searches distinctive phrases on the web (DuckDuckGo, no API key), reads the matching pages and compares them word by word. It produces a .docx report with the passages searched, the sources compared, the matched passages and the similarity percentage.
**Module 2: Assignment similarity.** Upload every student's .docx or .pdf. The student name is read from each file name and can be corrected in a table before the check. Every submission is compared with every other. The report ends with a table of students ranked by similarity, and lists the top pairs with the matching passages.
   - Every submission is also searched on the web, and students whose text matches web pages are flagged as "Matches web source" in the report.
   - An optional question paper or template can be uploaded so that its wording is ignored.

File name examples that work: `Rahul Kumar - Assignment 1.pdf`, `Priya_Nair_Assignment1.docx`, `101_Mohammed_Irfan_final.docx`, `SureshBabu_Assignment_1.pdf`.

## Run on your computer

```
pip install -r requirements.txt
streamlit run app.py
```

## Put it online (free)

1. Create a repository on GitHub and upload all files in this folder (keep the `veritext` folder).
2. Go to share.streamlit.io, sign in with your GitHub account and choose **New app**.
3. Select the repository, the branch (main) and the main file `app.py`, then **Deploy**.

The app address can be shared with colleagues. Uploaded files are processed in memory and are not saved by the app.

## Rename or customise

- Software name: edit `APP_NAME` in `veritext/__init__.py`.
- Institution name, subtitle, prepared-by and footer text are set in the left sidebar. The footer shows the page number only unless you add text. Reports contain no hosting, tool or service names, and the file properties show the institution as author.
- Similarity levels and phrase settings are in the sidebar as well.

## How the similarity is calculated

Each document is split into words. A passage counts as matched when a run of at least 8 words (default) is found, with the same 6-word phrases, in the other text. The percentage is the share of a document's words that fall inside matched runs. For class comparison, the figure for a student is the highest share of that student's text found in any one classmate's work.

## Good to know

- The web check covers pages the search engine returns. DuckDuckGo may refuse searches when many are made quickly or from shared servers; the report notes it when this happens.
- Scanned PDFs without selectable text cannot be read.
- Similarity is not proof of copying. A person must review flagged work.
