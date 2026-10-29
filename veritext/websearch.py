"""Free web check: search distinctive sentences, fetch result pages, compare locally."""
import re
import time
from urllib.parse import urlparse

from .similarity import coverage, span_text, make_doc

UA = {"User-Agent": "Mozilla/5.0 (compatible; VeriTextBot/1.0)"}


def pick_queries(doc, k=12, words_per_query=12, skip_grams=frozenset(), n=6):
    """Choose k evenly spaced sentences; use their first words as the search phrase.
    Returns [{'phrase', 'pos'}] where pos is the approximate position in the text (%).
    Sentences made mostly of template/question wording are skipped."""
    flat = re.sub(r"\s+", " ", doc.text)
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", flat)]
    cands = []
    total = max(1, len(sents))
    for idx, s in enumerate(sents):
        if not 14 <= len(s.split()) <= 45 or re.search(r"https?://|doi", s, re.I):
            continue
        if skip_grams:
            w = [m.lower() for m in re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?", s)]
            g = [tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))]
            if g and sum(x in skip_grams for x in g) / len(g) > 0.5:
                continue
        cands.append((s, round(100 * idx / total)))
    if not cands:
        return []
    k = min(k, len(cands))
    step = len(cands) / k
    out = []
    for i in range(k):
        s, pos = cands[int(i * step)]
        out.append({"phrase": " ".join(s.split()[:words_per_query]), "pos": pos})
    return out


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


def fetch_text(url, timeout=8, max_bytes=1_500_000):
    import requests
    from bs4 import BeautifulSoup
    r = requests.get(url, headers=UA, timeout=timeout, stream=True)
    ctype = r.headers.get("content-type", "")
    if "html" not in ctype and "text" not in ctype:
        return ""
    raw = r.raw.read(max_bytes, decode_content=True)
    soup = BeautifulSoup(raw, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        t.decompose()
    return soup.get_text(" ")


def _domain(u):
    return urlparse(u).netloc.replace("www.", "") or u


def check_web(doc, n=6, min_run=8, max_queries=12, max_pages=20, exclude_substrings=(),
              excluded_grams=frozenset(), progress=None, search_fn=ddg_search, fetch_fn=fetch_text,
              delay=1.0):
    """Returns dict(total_pct, sources, per_query, queries_run, pages_checked, errors)."""
    queries = pick_queries(doc, k=max_queries, skip_grams=excluded_grams, n=n)
    urls, titles, errors, q_urls = [], {}, [], []
    for qi, q in enumerate(queries):
        if progress:
            progress(qi / max(1, len(queries)) * 0.5, f"Searching phrase {qi + 1} of {len(queries)}")
        found = []
        try:
            for res in search_fn(q["phrase"]):
                u = res.get("href") or res.get("url") or ""
                if not u or any(x.lower() in u.lower() for x in exclude_substrings if x.strip()):
                    continue
                found.append(u)
                if u not in titles:
                    urls.append(u)
                    titles[u] = res.get("title", u)
        except Exception as e:                 # rate limit / network
            if "no results" not in str(e).lower():
                errors.append(f"Search failed: {str(e)[:120]}")
                if len(errors) >= 5:
                    q_urls.append(found)
                    break
        q_urls.append(found)
        time.sleep(delay)
    urls = urls[:max_pages]

    union = bytearray(doc.length)
    sources, pct_by_url = [], {}
    for ui, u in enumerate(urls):
        if progress:
            progress(0.5 + ui / max(1, len(urls)) * 0.5, f"Reading page {ui + 1} of {len(urls)}")
        try:
            page_text = fetch_fn(u)
        except Exception as e:
            errors.append(f"Could not read {u[:60]}: {str(e)[:60]}")
            continue
        if not page_text or len(page_text.split()) < 40:
            continue
        page = make_doc(u, page_text, n)
        pct, spans, marks = coverage(doc, page.gramset, excluded_grams, min_run)
        pct_by_url[u] = pct
        if pct <= 0:
            continue
        for i, m in enumerate(marks):
            if m:
                union[i] = 1
        longest = sorted(spans, key=lambda s: s[1] - s[0], reverse=True)[:3]
        sources.append({"url": u, "title": titles.get(u, u), "pct": pct,
                        "longest_run": max(e - s for s, e in spans),
                        "excerpts": [span_text(doc, s) for s in longest]})
    sources.sort(key=lambda s: s["pct"], reverse=True)

    per_query = []
    for q, found in zip(queries, q_urls):
        best_u = max(found, key=lambda u: pct_by_url.get(u, 0.0), default=None)
        best = pct_by_url.get(best_u, 0.0) if best_u else 0.0
        per_query.append({"phrase": q["phrase"], "pos": q["pos"], "n_results": len(found),
                          "best_pct": best, "best_domain": _domain(best_u) if best_u and best > 0 else ""})
    total = 100.0 * sum(union) / doc.length if doc.length else 0.0
    return {"total_pct": total, "sources": sources, "per_query": per_query,
            "queries_run": len(queries), "pages_checked": len(urls), "errors": errors}
