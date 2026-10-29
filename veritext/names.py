"""Guess a student's name from an uploaded file name."""
import os
import re

STOP = {
    "assignment", "assign", "submission", "submitted", "final", "copy", "draft", "homework", "hw",
    "report", "unit", "module", "task", "file", "doc", "docx", "pdf", "answer", "answers", "paper",
    "question", "questions", "work", "project", "lab", "exp", "experiment", "of", "by", "sem",
    "semester", "class", "new", "version", "revised", "updated", "online", "history", "essay",
    "ass", "asg", "sub", "rollno", "roll", "no", "name",
}


def student_name_from_filename(filename: str) -> str:
    stem = os.path.splitext(os.path.basename(filename))[0]
    stem = re.sub(r"\(\d+\)\s*$", "", stem)             # "(1)" suffix from downloads
    stem = re.sub(r"([a-z])([A-Z])", r"\1 \2", stem)    # RahulKumar -> Rahul Kumar
    tokens = re.split(r"[\s_\-\.,+]+", stem)
    keep = [t for t in tokens
            if t and re.search(r"[A-Za-z]", t) and not re.search(r"\d", t) and t.lower() not in STOP]
    name = " ".join(keep).strip().title()
    return name or stem or filename


def unique_names(names):
    """Make duplicate names unique by appending (2), (3)..."""
    seen, out = {}, []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else f"{n} ({seen[n]})")
    return out
