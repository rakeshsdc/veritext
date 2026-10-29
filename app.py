"""VeriText - Streamlit app. Run with:  streamlit run app.py"""
import pandas as pd
import streamlit as st

from veritext import APP_NAME, APP_TAGLINE
from veritext.extract import extract_text, strip_references
from veritext.names import student_name_from_filename, unique_names
from veritext.report import build_class_report, build_single_report
from veritext.similarity import analyse_class, combine_web, excluded_grams, internal_repetition, level_for, make_doc
from veritext.websearch import check_web

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

st.set_page_config(page_title=APP_NAME, page_icon="📄", layout="wide")
st.title(f"📄 {APP_NAME}")
st.caption(APP_TAGLINE)

# ---------------- sidebar: settings shared by both modules ----------------
with st.sidebar:
    st.header("Report settings")
    institution = st.text_input("Institution / department", "")
    prepared_by = st.text_input("Prepared by (optional)", "")
    subtitle = st.text_input("Report subtitle (optional)", "Prepared with free and open tools.")
    footer = st.text_input("Footer text (optional, page number is always shown)", "")
    st.header("Detection settings")
    n = st.slider("Phrase length (words)", 4, 10, 6, help="Longer = stricter. 6 is a good default.")
    min_run = st.slider("Minimum matching run (words)", 5, 20, 8,
                        help="Ignore matches shorter than this, such as common phrases.")
    high = st.slider("High similarity from (%)", 20, 80, 40)
    moderate = st.slider("Moderate similarity from (%)", 5, 40, 15)
    skip_refs = st.checkbox("Ignore the reference list", True)


def make_meta(title):
    return {"institution": institution, "title": title, "prepared_by": prepared_by, "subtitle": subtitle,
            "footer": footer, "n": n, "min_run": min_run}


def read_files(files):
    out, problems = [], []
    for f in files:
        try:
            text = extract_text(f.name, f.getvalue())
            if skip_refs:
                text = strip_references(text)
            if len(text.split()) < 30:
                problems.append(f"{f.name}: very little readable text (scanned PDF?)")
            out.append((f.name, text))
        except Exception as e:
            problems.append(f"{f.name}: {e}")
    return out, problems


tab1, tab2 = st.tabs(["Module 1: Plagiarism check", "Module 2: Assignment similarity"])

# ---------------- Module 1: one paper against the web ----------------
with tab1:
    st.write("Upload one **.docx** or **.pdf**. Distinctive passages are searched on the web and the matching pages are compared word by word.")
    title1 = st.text_input("Report title", "Independent Similarity Check Report", key="t1")
    up = st.file_uploader("Paper", type=["docx", "pdf"], key="up_single")
    c1, c2 = st.columns(2)
    max_q = c1.slider("Passages to search", 5, 30, 12, help="More passages = better coverage but slower.")
    excl = c2.text_input("Ignore web addresses containing (comma separated)",
                         help="For example the journal page where this paper is already published.")
    if st.button("Run plagiarism check", type="primary", disabled=up is None):
        files, problems = read_files([up])
        for p in problems:
            st.warning(p)
        if files:
            doc = make_doc(files[0][0], files[0][1], n)
            bar = st.progress(0.0, text="Starting")
            web = check_web(doc, n=n, min_run=min_run, max_queries=max_q,
                            exclude_substrings=[x.strip() for x in excl.split(",") if x.strip()],
                            progress=lambda f, m: bar.progress(min(f, 1.0), text=m))
            bar.empty()
            st.session_state["single"] = (doc, web, internal_repetition(doc, n))
    if "single" in st.session_state:
        doc, web, rep = st.session_state["single"]
        lvl = level_for(web["total_pct"], high, moderate)
        m1, m2, m3 = st.columns(3)
        m1.metric("Estimated similarity", f"{web['total_pct']:.1f}%")
        m2.metric("Level", lvl)
        m3.metric("Sources with matches", len(web["sources"]))
        if web["sources"]:
            st.dataframe(pd.DataFrame([{"Match %": round(s["pct"], 1), "Title": s["title"], "Address": s["url"],
                                        "Longest run": s["longest_run"]} for s in web["sources"]]),
                         use_container_width=True, hide_index=True)
        for e in web["errors"][:3]:
            st.caption(f"Note: {e}")
        data = build_single_report(make_meta(title1), doc, web, rep,
                                   f"Phrase length {n} words; minimum run {min_run} words", high, moderate)
        st.download_button("Download report (.docx)", data,
                           file_name=f"Similarity_Report_{doc.name.rsplit('.', 1)[0]}.docx", mime=DOCX)

# ---------------- Module 2: class assignments ----------------
with tab2:
    st.write("Upload every student's submission (**.docx** or **.pdf**). Name each file with the student's name, "
             "for example `Rahul Kumar - Assignment 1.pdf`. Names are read from the file names and can be corrected below. "
             "Submissions are compared with each other, and can also be checked for text copied from the web.")
    title2 = st.text_input("Report title", "Assignment Similarity Report", key="t2")
    files = st.file_uploader("Submissions", type=["docx", "pdf"], accept_multiple_files=True, key="up_class")
    tmpl = st.file_uploader("Optional: question paper or template to ignore", type=["docx", "pdf"], key="up_tmpl")
    w1, w2 = st.columns(2)
    do_web = w1.checkbox("Also check every submission against the web", True)
    web_q = w2.slider("Passages searched per submission", 3, 15, 6,
                      help="Each submission takes about 10 to 30 seconds. Fewer passages is faster.", disabled=not do_web)
    if files:
        if len(files) < 2:
            st.info("Upload at least two submissions to compare.")
        names = unique_names([student_name_from_filename(f.name) for f in files])
        edited = st.data_editor(pd.DataFrame({"File": [f.name for f in files], "Student name": names}),
                                disabled=["File"], hide_index=True, use_container_width=True, key="names")
        if st.button("Check submissions", type="primary", disabled=len(files) < 2):
            read, problems = read_files(files)
            for p in problems:
                st.warning(p)
            lookup = dict(zip(edited["File"], edited["Student name"]))
            docs = [make_doc(lookup.get(fn, fn), text, n) for fn, text in read]
            ex = set()
            if tmpl is not None:
                tr, _ = read_files([tmpl])
                ex = excluded_grams(tr[0][1], n) if tr else set()
            with st.spinner("Comparing every pair..."):
                pairs, rows = analyse_class(docs, ex, min_run, high, moderate)
            web_by_name = {}
            if do_web:
                bar = st.progress(0.0, text="Checking the web")
                for i, d in enumerate(docs):
                    web_by_name[d.name] = check_web(
                        d, n=n, min_run=min_run, max_queries=web_q, excluded_grams=ex, max_pages=10, delay=0.7,
                        progress=lambda f, m, i=i, d=d: bar.progress(min((i + f) / len(docs), 1.0), text=f"{d.name}: {m}"))
                bar.empty()
                rows = combine_web(rows, web_by_name, high, moderate)
            st.session_state["class"] = (pairs, rows, len(docs), do_web, bool(tmpl))
    if "class" in st.session_state:
        pairs, rows, ndocs, web_run, used_tmpl = st.session_state["class"]
        st.subheader("Students ranked by similarity")
        table = []
        for i, r in enumerate(rows):
            row = {"Rank": i + 1, "Student": r["student"], "Highest similarity %": round(r.get("overall", r["max"]), 1),
                   "Closest classmate": f"{r['partner']} ({r['max']:.1f}%)" if r["max"] > 0 else "-"}
            if web_run:
                row["Web match %"] = round(r["web_pct"], 1) if r.get("web_pct") is not None else None
                row["Flag"] = r["flag"]
            row["Level"] = r["level"]
            table.append(row)
        df = pd.DataFrame(table)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.subheader("Top classmate pairs")
        st.dataframe(pd.DataFrame([{"Student A": p.a, "Student B": p.b, "A in B %": round(p.cov_a, 1),
                                    "B in A %": round(p.cov_b, 1), "Longest run (words)": p.longest_run}
                                   for p in pairs[:20]]), use_container_width=True, hide_index=True)
        note = f"Phrase length {n} words; minimum run {min_run} words" + ("; question text ignored" if used_tmpl else "")
        data = build_class_report(make_meta(title2), rows, pairs, note, ndocs, web_run=web_run,
                                  high=high, moderate=moderate)
        st.download_button("Download class report (.docx)", data, file_name="Assignment_Similarity_Report.docx", mime=DOCX)
        st.download_button("Download ranking (.csv)", df.to_csv(index=False).encode("utf-8"),
                           file_name="similarity_ranking.csv", mime="text/csv")

st.divider()
st.caption("Similarity is not proof of plagiarism. Review every flagged match before drawing conclusions.")
