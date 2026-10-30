"""Free web check: search distinctive sentences, fetch result pages, compare locally."""
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from .similarity import coverage, span_text, make_doc

UA = {"User-Agent": "Mozilla/5.0 (compatible; VeriTextBot/1.0)"}


def pick_queries(doc, k=12, words_per_query=12, skip_grams=frozenset(), n=6, min_words=10):
    """Choose sentences to search. k=None means every usable sentence, otherwise k evenly spaced ones.
    Returns [{'phrase', 'pos', 'start', 'end'}]: pos = position in the text (%), start/end = word range.
    Sentences made mostly of template/question wording are skipped."""
    from bisect import bisect_left
    text = doc.text
    bounds = [0] + [m.end() for m in re.finditer(r"(?<=[.!?])\s+", text)] + [len(text)]
    starts = [t[1] for t in doc.tokens]
    cands = []
    total_chars = max(1, len(text))
    for a, b in zip(bounds, bounds[1:]):
        s = re.sub(r"\s+", " ", text[a:b]).strip()
        if not min_words <= len(s.split()) <= 60 or re.search(r"https?://|doi", s, re.I):
            continue
        w = [m.lower() for m in re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?", s)]
        if skip_grams:
            g = [tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))]
            if g and sum(x in skip_grams for x in g) / len(g) > 0.5:
                continue
        ws, we = bisect_left(starts, a), bisect_left(starts, b)
        cands.append({"phrase": " ".join(s.split()[:words_per_query]), "pos": round(100 * a / total_chars),
                      "start": ws, "end": max(we, ws + 1)})
    if not cands or k is None or k >= len(cands):
        return cands
    step = len(cands) / k
    return [cands[int(i * step)] for i in range(k)]


def ddg_search(query, max_results=5):
    """Search DuckDuckGo (no API key). Tries the exact phrase first, then the same words without quotes.
    Returns [{'href','title'}]; an empty list when nothing is found."""
    try:
        from ddgs import DDGS
    except ImportError:                       # older package name
        from duckduckgo_search import DDGS
    last_error = None
    for q in (f'"{query}"', query):
        try:
            with DDGS() as d:
                res = list(d.text(q, max_results=max_results))
            if res:
                return res
        except Exception as e:
            if "no results" in str(e).lower():
                continue                      # not an error, just nothing found
            last_error = e
            time.sleep(2)                     # possible rate limit; try the other form
    if last_error is not None:
        raise last_error
    return []


def fetch_text(url, timeout=10, max_bytes=1_500_000, max_pdf_bytes=8_000_000, max_pdf_pages=80):
    """Read a web page, an XML article or a PDF and return plain text ('' if unreadable)."""
    import requests
    from bs4 import BeautifulSoup
    r = requests.get(url, headers=UA, timeout=timeout, stream=True)
    ctype = r.headers.get("content-type", "").lower()
    if "pdf" in ctype or urlparse(url).path.lower().endswith(".pdf"):
        try:
            if int(r.headers.get("content-length", 0)) > max_pdf_bytes:
                return ""
        except ValueError:
            pass
        from .extract import _pdf_text
        raw = r.raw.read(max_pdf_bytes, decode_content=True)
        return _pdf_text(raw, max_pages=max_pdf_pages)
    if not any(x in ctype for x in ("html", "text", "xml")):
        return ""
    raw = r.raw.read(max_bytes, decode_content=True)
    soup = BeautifulSoup(raw, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        t.decompose()
    return soup.get_text(" ")


# ---------------- open scholarly databases (free, no key) ----------------
def europepmc_search(phrase, max_results=3, timeout=10):
    """Exact-phrase search of open-access full texts in Europe PMC."""
    import requests
    r = requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", timeout=timeout, headers=UA,
                     params={"query": f'"{phrase}" AND OPEN_ACCESS:y', "format": "json",
                             "resultType": "lite", "pageSize": max_results})
    out = []
    for x in (r.json().get("resultList", {}) or {}).get("result", []) or []:
        pmc = x.get("pmcid")
        if pmc:
            out.append({"href": f"https://europepmc.org/article/PMC/{pmc}", "title": x.get("title", pmc),
                        "fetch": f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmc}/fullTextXML"})
    return out


def openalex_search(phrase, max_results=3, timeout=10):
    """Exact-phrase search in OpenAlex; returns the open-access copy (PDF or landing page) of each hit."""
    import os
    import requests
    params = {"search": f'"{phrase}"', "per-page": max_results, "filter": "open_access.is_oa:true",
              "select": "id,title,doi,open_access,best_oa_location"}
    if os.environ.get("VERITEXT_EMAIL"):
        params["mailto"] = os.environ["VERITEXT_EMAIL"]
    r = requests.get("https://api.openalex.org/works", params=params, timeout=timeout, headers=UA)
    out = []
    for w in r.json().get("results", []) or []:
        loc = w.get("best_oa_location") or {}
        href = loc.get("pdf_url") or loc.get("landing_page_url") or (w.get("open_access") or {}).get("oa_url")
        if href:
            out.append({"href": href, "title": w.get("title") or href})
    return out


def make_search(scholarly=True):
    """Return a search function: web search, plus open-access databases when scholarly=True.
    A failure in one source never stops the others."""
    def search(phrase):
        jobs = [ddg_search] + ([europepmc_search, openalex_search] if scholarly else [])

        def run(fn, quiet):
            try:
                return fn(phrase)
            except Exception as e:
                if quiet:
                    return []
                raise e
        with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
            futs = [ex.submit(run, fn, fn is not ddg_search) for fn in jobs]
            results, first_err = [], None
            for f in futs:
                try:
                    results.extend(f.result())
                except Exception as e:
                    first_err = e
        if not results and first_err is not None:
            raise first_err
        seen, merged = set(), []
        for res in results:
            u = res.get("href")
            if u and u not in seen:
                seen.add(u)
                merged.append(res)
        return merged
    return search


def _domain(u):
    return urlparse(u).netloc.replace("www.", "") or u


def check_web(doc, n=6, min_run=8, max_queries=12, max_pages=20, exclude_substrings=(),
              excluded_grams=frozenset(), progress=None, search_fn=ddg_search, fetch_fn=fetch_text,
              delay=1.0, adaptive=True):
    """Search sentences, read the result pages, compare each page with the whole document.
    max_queries=None searches every sentence. With adaptive=True a sentence that is already inside a
    matched run is not searched again. Returns dict(total_pct, sources, per_query, ...)."""
    queries = pick_queries(doc, k=max_queries, skip_grams=excluded_grams, n=n)
    union = bytearray(doc.length)
    page_info, pct_by_url, titles, fetch_map = {}, {}, {}, {}
    errors, per_query = [], []
    run = skipped = pages = fails_in_row = 0
    stopped_early = cap_reached = False
    for qi, q in enumerate(queries):
        if progress:
            progress(qi / max(1, len(queries)), f"Passage {qi + 1} of {len(queries)}  |  {pages} pages compared")
        span = union[q["start"]:q["end"]]
        if adaptive and len(span) and sum(span) / len(span) >= 0.8:
            skipped += 1
            per_query.append({**q, "n_results": -1, "best_pct": 0.0, "best_domain": ""})
            continue
        found = []
        try:
            for res in search_fn(q["phrase"]):
                u = res.get("href") or res.get("url") or ""
                if not u or any(x.lower() in u.lower() for x in exclude_substrings if x.strip()):
                    continue
                found.append(u)
                titles.setdefault(u, res.get("title", u))
                if res.get("fetch"):
                    fetch_map[u] = res["fetch"]
            fails_in_row = 0
        except Exception as e:                 # rate limit / network
            if "no results" not in str(e).lower():
                errors.append(f"Search failed: {str(e)[:120]}")
                fails_in_row += 1
                time.sleep(min(10, 2 * fails_in_row))
                if fails_in_row >= 6:
                    stopped_early = True
                    per_query.append({**q, "n_results": 0, "best_pct": 0.0, "best_domain": ""})
                    break
        run += 1
        for u in found:
            if u in page_info:
                continue
            if pages >= max_pages:
                cap_reached = True
                continue
            pages += 1
            try:
                page_text = fetch_fn(fetch_map.get(u, u))
            except Exception as e:
                errors.append(f"Could not read {u[:60]}: {str(e)[:60]}")
                page_info[u] = None
                continue
            if not page_text or len(page_text.split()) < 40:
                page_info[u] = None
                continue
            page = make_doc(u, page_text, n)
            pct, spans, marks = coverage(doc, page.gramset, excluded_grams, min_run)
            pct_by_url[u] = pct
            page_info[u] = None
            if pct > 0:
                for i, m in enumerate(marks):
                    if m:
                        union[i] = 1
                longest = sorted(spans, key=lambda sp: sp[1] - sp[0], reverse=True)[:3]
                page_info[u] = {"url": u, "title": titles.get(u, u), "pct": pct,
                                "longest_run": max(e - s for s, e in spans),
                                "excerpts": [span_text(doc, sp) for sp in longest]}
        best_u = max(found, key=lambda u: pct_by_url.get(u, 0.0), default=None)
        best = pct_by_url.get(best_u, 0.0) if best_u else 0.0
        per_query.append({**q, "n_results": len(found), "best_pct": best,
                          "best_domain": _domain(best_u) if best_u and best > 0 else ""})
        time.sleep(delay)
    sources = sorted((v for v in page_info.values() if v), key=lambda x: x["pct"], reverse=True)
    total = 100.0 * sum(union) / doc.length if doc.length else 0.0
    return {"total_pct": total, "sources": sources, "per_query": per_query, "queries_total": len(queries),
            "queries_run": run, "queries_skipped": skipped, "pages_checked": pages,
            "stopped_early": stopped_early, "page_cap_reached": cap_reached, "errors": errors}
