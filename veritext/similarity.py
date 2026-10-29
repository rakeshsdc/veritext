"""Word n-gram overlap engine. Pure Python, no heavy dependencies."""
import re
from dataclasses import dataclass, field
from itertools import combinations

TOKEN = re.compile(r"[A-Za-z0-9À-ɏऀ-ॿഀ-ൿ]+(?:['’][A-Za-z]+)?")

LEVELS = ((40.0, "High"), (15.0, "Moderate"), (0.0, "Low"))


def level_for(pct: float, high=40.0, moderate=15.0) -> str:
    if pct >= high:
        return "High"
    if pct >= moderate:
        return "Moderate"
    return "Low"


@dataclass
class Doc:
    name: str
    text: str
    tokens: list = field(default_factory=list)   # (lower_word, start, end)
    words: list = field(default_factory=list)
    n: int = 6
    grams: list = field(default_factory=list)
    gramset: set = field(default_factory=set)

    @property
    def length(self):
        return len(self.words)


def make_doc(name: str, text: str, n: int = 6) -> Doc:
    toks = [(m.group().lower(), m.start(), m.end()) for m in TOKEN.finditer(text)]
    words = [t[0] for t in toks]
    grams = [tuple(words[i:i + n]) for i in range(max(0, len(words) - n + 1))]
    return Doc(name=name, text=text, tokens=toks, words=words, n=n, grams=grams, gramset=set(grams))


def excluded_grams(template_text: str, n: int) -> set:
    """Shingles from a question paper / template that should be ignored in comparisons."""
    if not template_text:
        return set()
    return make_doc("template", template_text, n).gramset


def _mask(doc: Doc, other: set, excluded: set, min_run: int) -> bytearray:
    n = doc.n
    marks = bytearray(len(doc.words))
    for i, g in enumerate(doc.grams):
        if g in other and g not in excluded:
            marks[i:i + n] = b"\x01" * n
    # drop runs shorter than min_run
    i, L = 0, len(marks)
    while i < L:
        if marks[i]:
            j = i
            while j < L and marks[j]:
                j += 1
            if j - i < min_run:
                marks[i:j] = b"\x00" * (j - i)
            i = j
        else:
            i += 1
    return marks


def _spans(marks: bytearray):
    spans, i, L = [], 0, len(marks)
    while i < L:
        if marks[i]:
            j = i
            while j < L and marks[j]:
                j += 1
            spans.append((i, j))
            i = j
        else:
            i += 1
    return spans


def span_text(doc: Doc, span) -> str:
    s, e = span
    return doc.text[doc.tokens[s][1]: doc.tokens[e - 1][2]].replace("\n", " ")


def coverage(doc: Doc, other_gramset: set, excluded=frozenset(), min_run: int = 8):
    """Return (percent of doc words inside matched runs, matched spans, mask)."""
    if doc.length == 0:
        return 0.0, [], bytearray()
    marks = _mask(doc, other_gramset, excluded, min_run)
    pct = 100.0 * sum(marks) / doc.length
    return pct, _spans(marks), marks


@dataclass
class PairResult:
    a: str
    b: str
    cov_a: float
    cov_b: float
    spans_a: list
    spans_b: list
    excerpts: list          # longest matched passages, as text from doc a

    @property
    def score(self) -> float:
        return max(self.cov_a, self.cov_b)

    @property
    def longest_run(self) -> int:
        return max([e - s for s, e in self.spans_a] or [0])


def compare_pair(a: Doc, b: Doc, excluded=frozenset(), min_run: int = 8, top_excerpts: int = 5) -> PairResult:
    ca, sa, _ = coverage(a, b.gramset, excluded, min_run)
    cb, sb, _ = coverage(b, a.gramset, excluded, min_run)
    longest = sorted(sa, key=lambda s: s[1] - s[0], reverse=True)[:top_excerpts]
    return PairResult(a.name, b.name, ca, cb, sa, sb, [span_text(a, s) for s in longest])


def analyse_class(docs, excluded=frozenset(), min_run: int = 8, high=40.0, moderate=15.0):
    """Compare every pair. Returns (pairs sorted by score, per-student summary rows)."""
    pairs = [compare_pair(a, b, excluded, min_run) for a, b in combinations(docs, 2)]
    pairs.sort(key=lambda p: p.score, reverse=True)
    best = {d.name: {"student": d.name, "words": d.length, "max": 0.0, "partner": "-", "n_over": 0} for d in docs}
    for p in pairs:
        for me, other, own_cov in ((p.a, p.b, p.cov_a), (p.b, p.a, p.cov_b)):
            row = best[me]
            # similarity of *this* student's text found in the other student's work
            if own_cov > row["max"]:
                row["max"], row["partner"] = own_cov, other
            if own_cov >= moderate:
                row["n_over"] += 1
    rows = sorted(best.values(), key=lambda r: r["max"], reverse=True)
    for r in rows:
        r["level"] = level_for(r["max"], high, moderate)
    return pairs, rows


def internal_repetition(doc: Doc, n: int = 6, examples: int = 5):
    """Repeated n-word phrases inside one document."""
    from collections import Counter
    c = Counter(doc.grams)
    rep = {g: k for g, k in c.items() if k > 1}
    covered = bytearray(len(doc.words))
    for i, g in enumerate(doc.grams):
        if g in rep:
            covered[i:i + n] = b"\x01" * n
    pct = 100.0 * sum(covered) / doc.length if doc.length else 0.0
    # collapse overlapping grams: show the most repeated distinct phrases
    top = sorted(rep.items(), key=lambda kv: (-kv[1], kv[0]))
    shown, seen_words = [], set()
    for g, k in top:
        if len(seen_words & set(g)) >= n - 1 and shown:
            continue
        shown.append((" ".join(g), k))
        seen_words |= set(g)
        if len(shown) >= examples:
            break
    return {"count": len(rep), "pct": pct, "examples": shown}


def combine_web(rows, web_by_name, high=40.0, moderate=15.0):
    """Add web-match results to the per-student rows and set the flag and overall level."""
    for r in rows:
        w = web_by_name.get(r["student"])
        r["web_pct"] = w["total_pct"] if w else None
        r["web_sources"] = w["sources"] if w else []
        r["web_top"] = w["sources"][0]["url"] if w and w["sources"] else "-"
        flags = []
        if r["max"] >= moderate:
            flags.append("Matches classmate")
        if r["web_pct"] is not None and r["web_pct"] >= moderate:
            flags.append("Matches web source")
        r["flag"] = " + ".join(flags) if flags else "-"
        overall = max(r["max"], r["web_pct"] or 0.0)
        r["overall"] = overall
        r["level"] = level_for(overall, high, moderate)
    rows.sort(key=lambda r: r["overall"], reverse=True)
    return rows
