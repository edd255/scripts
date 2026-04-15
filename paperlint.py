#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from enum import IntFlag
from pathlib import Path
from typing import Callable, Iterable, Sequence


YELLOW = "\033[33m"
BLUE = "\033[94m"
GRAY = "\033[90m"
RESET = "\033[0m"

ENV_TOKEN_RE = re.compile(r"\\(?P<kind>begin|end)\{(?P<name>[^}]+)\}")
TEXT_STYLE_RE = re.compile(r"\\text([^{]+)\{([^}]+)\}")


class Category(IntFlag):
    GENERAL = 1
    TYPOGRAPHY = 2
    VISUAL = 4
    STYLE = 8
    REFERENCE = 16


@dataclass(frozen=True)
class WarningRecord:
    line: int
    message: str
    span: tuple[int, int] | None = None
    category: str = ""


@dataclass(frozen=True)
class EnvRange:
    start: int
    end: int  # exclusive


@dataclass(frozen=True)
class Rule:
    func: Callable[["Document"], list[WarningRecord]]
    category: Category
    name: str


@dataclass(frozen=True)
class CliConfig:
    tex_files: list[Path]
    enabled_rules: set[str]
    error_exit: bool


class Document:
    def __init__(self, path: Path, text: str) -> None:
        self.path = path
        self.text = text
        self.lines = text.splitlines()
        self.clean_lines = [strip_comment(line) for line in self.lines]
        (
            self.env_ranges_raw,
            self.env_ranges_base,
            self.active_raw,
            self.active_base,
        ) = build_environment_index(self.lines)

    @classmethod
    def from_path(cls, path: Path) -> "Document":
        with path.open("r", encoding="utf-8", errors="surrogateescape") as handle:
            return cls(path=path, text=handle.read())

    def is_in_env(self, env_name: str, line: int) -> bool:
        return self.active_base.get(env_name, [False] * len(self.lines))[line]

    def is_in_any_env(self, line: int) -> bool:
        return any(mask[line] for mask in self.active_base.values())

    def is_in_any_float(self, line: int) -> bool:
        return any(
            self.is_in_env(name, line) for name in ("figure", "listing", "table")
        )

    def is_in_code(self, line: int) -> bool:
        return self.is_in_env("lstlisting", line)

    def is_in_equation(self, line: int) -> bool:
        return any(
            self.is_in_env(name, line)
            for name in (
                "equation",
                "align",
                "eqnarray",
                "theorem",
                "proof",
                "proposition",
            )
        )

    def ranges_for(self, env_name: str) -> list[EnvRange]:
        return list(self.env_ranges_base.get(env_name, ()))


def strip_comment(line: str) -> str:
    for index, char in enumerate(line):
        if char != "%":
            continue
        backslashes = 0
        probe = index - 1
        while probe >= 0 and line[probe] == "\\":
            backslashes += 1
            probe -= 1
        if backslashes % 2 == 0:
            return line[:index].rstrip()
    return line


def build_environment_index(
    lines: Sequence[str],
) -> tuple[
    dict[str, list[EnvRange]],
    dict[str, list[EnvRange]],
    dict[str, list[bool]],
    dict[str, list[bool]],
]:
    raw_starts: dict[str, list[int]] = defaultdict(list)
    raw_ranges: dict[str, list[EnvRange]] = defaultdict(list)

    for line_number, line in enumerate(lines):
        for token in ENV_TOKEN_RE.finditer(line):
            raw_name = token.group("name")
            kind = token.group("kind")
            if kind == "begin":
                raw_starts[raw_name].append(line_number)
            else:
                if raw_starts[raw_name]:
                    start = raw_starts[raw_name].pop()
                    raw_ranges[raw_name].append(EnvRange(start=start, end=line_number))

    last_line = len(lines)
    for raw_name, starts in raw_starts.items():
        while starts:
            raw_ranges[raw_name].append(EnvRange(start=starts.pop(), end=last_line))

    raw_ranges = {
        name: sorted(ranges, key=lambda item: (item.start, item.end))
        for name, ranges in raw_ranges.items()
    }

    base_ranges: dict[str, list[EnvRange]] = defaultdict(list)
    for raw_name, ranges in raw_ranges.items():
        base_ranges[raw_name.removesuffix("*")].extend(ranges)

    for name, ranges in base_ranges.items():
        ranges.sort(key=lambda item: (item.start, item.end))

    raw_active = {
        name: ranges_to_mask(ranges, len(lines)) for name, ranges in raw_ranges.items()
    }
    base_active = {
        name: ranges_to_mask(ranges, len(lines)) for name, ranges in base_ranges.items()
    }
    return raw_ranges, dict(base_ranges), raw_active, base_active


def ranges_to_mask(ranges: Sequence[EnvRange], line_count: int) -> list[bool]:
    mask = [False] * line_count
    for env_range in ranges:
        end = min(env_range.end, line_count)
        for line_number in range(env_range.start, end):
            mask[line_number] = True
    return mask


def collect_tex_files(path: Path) -> list[Path]:
    if path.is_file():
        if path.suffix != ".tex":
            raise SystemExit(f"Expected a .tex file or a directory, got: {path}")
        return [path]

    if path.is_dir():
        return sorted(file for file in path.rglob("*.tex") if file.is_file())

    raise SystemExit(f"Path does not exist: {path}")


def parse_cli(argv: Sequence[str]) -> CliConfig:
    parser = argparse.ArgumentParser(
        description="Lint LaTeX papers.",
        usage="%(prog)s <file.tex/path> [-x <excluded-switch>] [-i <included-switch>] [--error]",
    )
    parser.add_argument("path", type=Path)
    parser.add_argument("--error", action="store_true", dest="error_exit")
    known, remaining = parser.parse_known_args(argv)

    enabled_rules = resolve_enabled_rules(remaining)
    tex_files = collect_tex_files(known.path)
    return CliConfig(
        tex_files=tex_files, enabled_rules=enabled_rules, error_exit=known.error_exit
    )


def resolve_enabled_rules(tokens: Sequence[str]) -> set[str]:
    enabled = {rule.name for rule in RULES}
    switch_map = build_switch_map()

    index = 0
    while index < len(tokens):
        flag = tokens[index]
        if flag not in {"-i", "-x"}:
            raise SystemExit(f"Unknown argument: {flag}")
        if index + 1 >= len(tokens):
            raise SystemExit(f"Missing switch after {flag}")

        switch = tokens[index + 1]
        if switch not in switch_map:
            raise SystemExit(f"Unknown switch '{switch}'")

        names = switch_map[switch]
        if flag == "-i":
            enabled.update(names)
        else:
            enabled.difference_update(names)
        index += 2

    return enabled


def build_switch_map() -> dict[str, set[str]]:
    mapping = {
        name: {rule.name for rule in RULES if rule.category & category}
        for name, category in CATEGORY_SWITCHES.items()
    }
    mapping.update({rule.name: {rule.name} for rule in RULES})
    return mapping


def make_warning(
    line: int,
    message: str,
    span: tuple[int, int] | None = None,
    *,
    category: str = "",
) -> WarningRecord:
    return WarningRecord(line=line, message=message, span=span, category=category)


def add_category(
    warnings: Iterable[WarningRecord], category: str
) -> list[WarningRecord]:
    return [
        WarningRecord(line=w.line, message=w.message, span=w.span, category=category)
        for w in warnings
    ]


def warn_from_match(
    line: int,
    message: str,
    match: re.Match[str],
    *,
    category: str = "",
) -> WarningRecord:
    return make_warning(line, message, match.span(), category=category)


def check_space_before_cite(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        match = re.search(r"[^ ~]\\cite", line)
        if match and r"\etal\cite" not in line:
            warnings.append(warn_from_match(i, r"No space before \cite", match))
    return warnings


def check_float_alignment(doc: Document, env: str) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        match = re.search(rf"\\begin\{{{re.escape(env)}\}}", line)
        if match and not re.search(
            rf"\\begin\{{{re.escape(env)}\}}\[[^\]]*[htbH][^\]]*\]",
            line,
        ):
            warnings.append(
                make_warning(
                    i,
                    f"{env} without alignment: {line.strip()}",
                    match.span(),
                )
            )
    return warnings


def check_figure_alignment(doc: Document) -> list[WarningRecord]:
    return check_float_alignment(doc, "figure")


def check_table_alignment(doc: Document) -> list[WarningRecord]:
    return check_float_alignment(doc, "table")


def check_listing_alignment(doc: Document) -> list[WarningRecord]:
    return check_float_alignment(doc, "listing")


def check_float_has_label(doc: Document, env: str) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for env_range in doc.ranges_for(env):
        has_label = any(
            re.search(r"\\label\{", doc.lines[i])
            for i in range(env_range.start, env_range.end)
        )
        if not has_label:
            warnings.append(make_warning(env_range.start, f"{env} without a label"))
    return warnings


def check_float_has_caption(doc: Document, env: str) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for env_range in doc.ranges_for(env):
        has_caption = any(
            re.search(r"\\caption\{", doc.lines[i])
            for i in range(env_range.start, env_range.end)
        )
        if not has_caption:
            warnings.append(make_warning(env_range.start, f"{env} without a caption"))
    return warnings


def check_float_caption_label_order(doc: Document, env: str) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for env_range in doc.ranges_for(env):
        label_line = -1
        caption_line = -1
        for i in range(env_range.start, env_range.end):
            if re.search(r"\\caption\{", doc.lines[i]):
                caption_line = i
            if re.search(r"\\label\{", doc.lines[i]):
                label_line = i
        if label_line > -1 and caption_line > -1 and label_line < caption_line:
            warnings.append(
                make_warning(
                    env_range.start,
                    f"label before caption in {env}, swap for correct references",
                )
            )
    return warnings


def check_no_resizebox_for_tables(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for table_range in doc.ranges_for("table"):
        for i in range(table_range.start, table_range.end):
            match = re.search(r"\\resizebox\{", doc.lines[i])
            if match:
                warnings.append(
                    make_warning(
                        table_range.start,
                        "table with resizebox -> use adjustbox instead",
                        match.span(),
                    )
                )
                break
    return warnings


def check_weird_units(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        for blocked in (r"\textwidth", r"\linewidth"):
            if blocked in line:
                start = line.index(blocked)
                warnings.append(
                    make_warning(
                        i,
                        f"use \\hsize instead of {blocked}",
                        (start, start + len(blocked)),
                    )
                )
    return warnings


def check_figure_has_label(doc: Document) -> list[WarningRecord]:
    return check_float_has_label(doc, "figure")


def check_table_has_label(doc: Document) -> list[WarningRecord]:
    return check_float_has_label(doc, "table")


def check_listing_has_label(doc: Document) -> list[WarningRecord]:
    return check_float_has_label(doc, "listing")


def check_figure_has_caption(doc: Document) -> list[WarningRecord]:
    return check_float_has_caption(doc, "figure")


def check_table_has_caption(doc: Document) -> list[WarningRecord]:
    return check_float_has_caption(doc, "table")


def check_listing_has_caption(doc: Document) -> list[WarningRecord]:
    return check_float_has_caption(doc, "listing")


def check_figure_caption_label_order(doc: Document) -> list[WarningRecord]:
    return check_float_caption_label_order(doc, "figure")


def check_table_caption_label_order(doc: Document) -> list[WarningRecord]:
    return check_float_caption_label_order(doc, "table")


def check_listing_caption_label_order(doc: Document) -> list[WarningRecord]:
    return check_float_caption_label_order(doc, "listing")


def check_todos(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.clean_lines):
        for match in re.finditer(r"TODO", line):
            warnings.append(warn_from_match(i, "TODO found", match))
    return warnings


def check_notes(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.clean_lines):
        for token in (r"\note", r"\todo"):
            start = line.find(token)
            if start != -1:
                warnings.append(
                    make_warning(i, f"{token} found", (start, start + len(token)))
                )
    return warnings


def check_math_numbers(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        match = re.search(r"\$\d+\$", line)
        if match and not doc.is_in_any_float(i):
            warnings.append(
                warn_from_match(
                    i, "Number in math mode, consider using siunit instead", match
                )
            )
    return warnings


def check_large_numbers_without_si(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        match = re.search(r"[\s(]\d{5,}[\s),.]", line)
        if match and not doc.is_in_any_float(i):
            warnings.append(
                warn_from_match(
                    i,
                    "Large number without formating, consider using siunit",
                    match,
                )
            )
    return warnings


def check_env_not_in_float(
    doc: Document, env: str, float_env: str
) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for env_range in doc.ranges_for(env):
        if not doc.is_in_env(float_env, env_range.start):
            warnings.append(
                make_warning(
                    env_range.start,
                    f"{env} not within {float_env} environment",
                )
            )
    return warnings


def check_listing_in_correct_float(doc: Document) -> list[WarningRecord]:
    return check_env_not_in_float(doc, "lstlisting", "listing")


def check_tabular_in_correct_float(doc: Document) -> list[WarningRecord]:
    return check_env_not_in_float(doc, "tabular", "table")


def check_tikz_in_correct_float(doc: Document) -> list[WarningRecord]:
    return check_env_not_in_float(doc, "tikzpicture", "figure")


def check_comment_has_space(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        stripped = line.strip()
        if not stripped or "%" not in stripped or stripped.startswith("%"):
            continue
        match = re.search(r"[^\s\\}{%]+%", line)
        if match and not doc.is_in_code(i):
            warnings.append(
                warn_from_match(i, "Comment without a whitespace before", match)
            )
    return warnings


def check_percent_without_siunitx(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        match = re.search(r"\d+\s*\\%", line)
        if match:
            warnings.append(
                warn_from_match(i, "Number with percent without siunit", match)
            )
    return warnings


def check_short_form(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.clean_lines):
        match = re.search(r"[^`%]\w+'[a-rt-z]", line)
        if match:
            warnings.append(warn_from_match(i, "Contracted form used", match))
    return warnings


def check_labels_referenced(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    labels: list[tuple[str, int, tuple[int, int]]] = []
    for i, line in enumerate(doc.clean_lines):
        for match in re.finditer(r"\\label\{([^}]+)\}", line):
            labels.append((match.group(1), i, match.span()))
    for label, line_number, span in labels:
        referenced = any(f"ref{{{label}}}" in line for line in doc.lines)
        if not referenced and not (
            label.startswith("sec") or label.startswith("subsec")
        ):
            warnings.append(
                make_warning(line_number, f"Label {label} is not referenced", span)
            )
    return warnings


def check_section_capitalization(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        match = re.search(r"(section|paragraph)\{([^}]+)\}", line)
        if not match:
            continue
        title = match.group(2)
        search_start = match.start(2)
        for word in title.split():
            if len(word) > 4 and word[0].islower():
                offset = line.find(word, search_start, match.end(2))
                span = (offset, offset + 1) if offset != -1 else match.span(2)
                warnings.append(make_warning(i, "Wrong capitalization of header", span))
                break
    return warnings


def check_quotation(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.clean_lines):
        start_match = re.search(r'[^\\]"\w+', line)
        end_match = re.search(r'\w+"', line)
        if (start_match or end_match) and not doc.is_in_code(i):
            match = start_match if start_match else end_match
            warnings.append(
                warn_from_match(
                    i,
                    "Wrong quotation, use `` and '' instead of \"",
                    match,
                )
            )
    return warnings


def check_hline_in_table(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        match = re.search(r"\\hline", line)
        if match and doc.is_in_env("tabular", i):
            warnings.append(
                warn_from_match(
                    i,
                    r"\hline in table, consider using \toprule, \midrule, \bottomrule.",
                    match,
                )
            )
    return warnings


def check_space_before_punctuation(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        match = re.search(r"\s+[,.!?:;]", line)
        if match and not doc.is_in_any_env(i):
            warnings.append(warn_from_match(i, "Spacing before punctuation", match))
    return warnings


def check_headers_without_text(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    header_re = re.compile(r"(section|paragraph)\{([^}]+)\}")
    for i, line in enumerate(doc.lines):
        match = header_re.search(line)
        if not match:
            continue
        next_index = i
        while next_index + 1 < len(doc.lines):
            next_index += 1
            stripped = doc.lines[next_index].strip()
            if not stripped or stripped.startswith("%"):
                continue
            if header_re.search(doc.lines[next_index]):
                warnings.append(
                    make_warning(
                        i,
                        "Section header without text before next header",
                        match.span(),
                    )
                )
            break
    return warnings


def check_one_sentence_paragraphs(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        if not (0 < i < len(doc.lines) - 1):
            continue
        if (
            not doc.lines[i - 1].strip()
            and doc.lines[i].strip()
            and not doc.lines[i + 1].strip()
        ):
            if doc.lines[i].strip().startswith("\\"):
                continue
            if ". " in doc.lines[i]:
                continue
            warnings.append(
                make_warning(i, "One-sentence paragraph", (0, len(doc.lines[i])))
            )
    return warnings


def check_multiple_sentences_per_line(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.clean_lines):
        match = re.search(r"[.!?]\s+\w+", line.rstrip())
        if match and "vs." not in line.rstrip():
            warnings.append(warn_from_match(i, "Multiple sentences in one line", match))
    return warnings


def check_unbalanced_brackets(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        if line.count("(") == line.count(")") or doc.is_in_code(i):
            continue
        first = min(
            line.index("(") if "(" in line else len(line),
            line.index(")") if ")" in line else len(line),
        )
        last = max(
            line.rindex("(") if "(" in line else len(line),
            line.rindex(")") if ")" in line else len(line),
        )
        warnings.append(
            make_warning(
                i,
                "Mismatch of opening and closing parenthesis",
                (first, last),
            )
        )
    return warnings


def check_and_or(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        match = re.search(r"and/or", line)
        if match:
            warnings.append(
                warn_from_match(i, "And/or discouraged in academic writing", match)
            )
    return warnings


def check_ellipsis(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        match = re.search(r"\w+\.\.\.", line)
        if match:
            warnings.append(
                warn_from_match(
                    i, 'Ellipsis "..." discouraged in academic writing', match
                )
            )
    return warnings


def check_etc(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        match = re.search(r"\s+etc[.\w]", line)
        if match:
            warnings.append(
                warn_from_match(
                    i, 'Unspecific "etc" discouraged in academic writing', match
                )
            )
    return warnings


def check_footnote(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        match = re.search(r"\s*\\footnote\{[^}]+\}\.", line)
        if match:
            warnings.append(
                warn_from_match(i, "Footnote must be after the full stop", match)
            )
    return warnings


def check_table_top_caption(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for table_range in doc.ranges_for("table"):
        caption_line = -1
        tabular_line = -1
        for i in range(table_range.start, table_range.end):
            if re.search(r"\\caption\{", doc.lines[i]):
                caption_line = i
            if re.search(r"\\begin\{tabular", doc.lines[i]):
                tabular_line = i
        if tabular_line != -1 and caption_line != -1 and tabular_line < caption_line:
            warnings.append(
                make_warning(table_range.start, "Table caption must be above table")
            )
    return warnings


def check_punctuation_end_of_line(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.clean_lines):
        stripped = line.strip()
        if len(stripped) < 10:
            continue
        if len(stripped.split()) < 8:
            continue
        if doc.is_in_any_float(i) or doc.is_in_code(i):
            continue
        if stripped.startswith("\\") or stripped.startswith("%"):
            continue
        if stripped.endswith("\\\\") or stripped.endswith("}"):
            continue
        if stripped.endswith((".", "!", "?", ":", ";")):
            continue
        match = re.search(r"\s*[\w})$]+[.!?}{:;\\]\s*$", line.rstrip())
        if not match:
            end = len(line)
            warnings.append(
                make_warning(
                    i,
                    "Line ends without punctuation",
                    (max(0, end - 2), end),
                )
            )
    return warnings


def check_table_vertical_lines(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        match = re.search(r"\\begin\{tabular\}\{([^}]+)\}", line)
        if match and "|" in match.group(1):
            warnings.append(
                warn_from_match(i, "Vertical lines in tables are discouraged", match)
            )
    return warnings


def check_will(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        match = re.search(r"\s+will\s+", line)
        if match:
            warnings.append(
                warn_from_match(i, 'Usage of "will" is discouraged.', match)
            )
    return warnings


def check_subsection_count(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    last_section_line = -1
    last_section_span: tuple[int, int] | None = None
    subsection_count = 0

    for i, line in enumerate(doc.lines):
        section_match = re.search(r"\\section\{", line)
        if section_match:
            if last_section_line != -1 and subsection_count == 1:
                warnings.append(
                    make_warning(
                        last_section_line,
                        "Section only has one subsection",
                        last_section_span,
                    )
                )
            last_section_line = i
            last_section_span = section_match.span()
            subsection_count = 0

        if re.search(r"\\subsection\{", line):
            subsection_count += 1

    if last_section_line != -1 and subsection_count == 1:
        warnings.append(
            make_warning(
                last_section_line,
                "Section only has one subsection",
                last_section_span,
            )
        )

    return warnings


def check_mixed_compact_and_item(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    if r"\begin{compactenum}" in doc.text:
        for i, line in enumerate(doc.lines):
            match = re.search(r"\\begin\{enumerate\}", line)
            if match:
                warnings.append(
                    warn_from_match(i, "compactenum mixed with enumerate", match)
                )
    if r"\begin{compactitem}" in doc.text:
        for i, line in enumerate(doc.lines):
            match = re.search(r"\\begin\{itemize\}", line)
            if match:
                warnings.append(
                    warn_from_match(i, "compactitem mixed with itemize", match)
                )
    return warnings


def check_center_in_float(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for env_range in doc.ranges_for("center"):
        if doc.is_in_any_float(env_range.start):
            match = re.search(r"\\begin\{center\}", doc.lines[env_range.start])
            if match:
                warnings.append(
                    warn_from_match(
                        env_range.start,
                        r"Use \centering instead of \begin{center} inside floats",
                        match,
                    )
                )
    return warnings


def check_appendix(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        match = re.search(r"\\begin\{appendix\}", line)
        if match:
            warnings.append(
                warn_from_match(i, r"Use \appendix instead of \begin{appendix}", match)
            )
    return warnings


def check_eqnarray(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        match = re.search(r"\\begin\{eqnarray\}", line)
        if match:
            warnings.append(
                warn_from_match(
                    i, r"Use \begin{align} instead of \begin{eqnarray}", match
                )
            )
    return warnings


def check_acm_pc(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    replacements = [
        (r"\bsupremacy\b", "advantage"),
        (r"\bmaster\b", "main/primary/leader/parent/host"),
        (r"\bslave\b", "secondary/replica/follower/child/worker/client"),
        (r"\bhe\b", "they"),
        (r"\bshe\b", "they"),
        (r"\bhis\b", "their"),
        (r"\bhers?\b", "their/them"),
        (r"\bhim\b", "them"),
        (r"\bmale\s+connector\b", "plug"),
        (r"\bfemale\s+connector\b", "socket"),
        (r"\bblind\b", "anonymous"),
        (r"\bblack\-?\s?list\b", "blocklist/unapprovedlist"),
        (r"\bwhite\-?\s?list\b", "allowlist/approvedlist"),
        (r"\bblack\-?\s?hat\b", "unethical attacker/hostile force"),
        (r"\bwhite\-?\s?hat\b", "ethical attacker/friendly force"),
        (r"\bblack\-?\s?box\b", "opaque box"),
        (r"\bwhite\-?\s?box\b", "clear box"),
        (r"\baverage\s?user\b", "common/standard/typical user"),
        (r"\babort\s?child\b", "cancel/force quit/stop/end/finalize"),
        (r"\bterminate\s?child\b", "cancel/force quit/stop/end/finalize"),
        (r"\bdark\-?\s?pattern\b", "deceptive design"),
        (r"\bdummy\-?\s?head\b", "temporary head"),
        (r"\bgender\-?\s?bender\b", "plug-socket adapter"),
        (r"\borphaned\-?\s?object\b", "unreferenced/unlinked object"),
        (r"\bsanity\-?\s?check\b", "coherence/quick/well-formedness check"),
    ]
    for i, line in enumerate(doc.lines):
        for pattern, replacement in replacements:
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if match:
                warnings.append(
                    make_warning(
                        i,
                        f'Discouraged term "{match.group()}", consider replacing with "{replacement}"',
                        match.span(),
                    )
                )
    return warnings


def check_cite_noun(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.lines):
        match = re.search(r"\b(in|from|by|and|or)[\s~]\\cite", line.lower())
        if match:
            warnings.append(warn_from_match(i, "Citation is used as noun", match))
        match = re.search(r"^\s*\\cite", line)
        if match:
            warnings.append(
                warn_from_match(
                    i,
                    "Citation at the beginning of a sentence (probably as noun)",
                    match,
                )
            )
    return warnings


def check_cite_duplicate(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    cite_re = re.compile(r"\\(?:no)?citeA?\{([^}]+)\}")
    for i, line in enumerate(doc.lines):
        for match in cite_re.finditer(line):
            keys = [key.strip() for key in match.group(1).split(",") if key.strip()]
            seen: set[str] = set()
            duplicates: list[str] = []
            for key in keys:
                if key in seen and key not in duplicates:
                    duplicates.append(key)
                seen.add(key)
            if duplicates:
                first_duplicate = duplicates[0]
                offset = line.find(first_duplicate, match.start(), match.end())
                span = (
                    (offset, offset + len(first_duplicate))
                    if offset != -1
                    else match.span()
                )
                warnings.append(
                    make_warning(
                        i,
                        f"Duplicate citation key: {', '.join(duplicates)}",
                        span,
                    )
                )
    return warnings


def check_multicite(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    pattern = re.compile(r"\\citeA?\{[^}]+\}\s*\\citeA?\{[^}]+\}")
    for i, line in enumerate(doc.lines):
        match = pattern.search(line)
        if match:
            warnings.append(
                warn_from_match(
                    i,
                    r"Multiple \cite commands, use multiple citation keys in one \cite instead",
                    match,
                )
            )
    return warnings


def check_emptycite(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    pattern = re.compile(r"\\citeA?\{\s*\}")
    for i, line in enumerate(doc.lines):
        match = pattern.search(line)
        if match:
            warnings.append(warn_from_match(i, "Empty citation key", match))
    return warnings


def check_conjunction_start(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.clean_lines):
        stripped = line.rstrip()
        match = re.search(r"[.!?]\s+(And|Or|But)[\s,]", stripped)
        if match:
            warnings.append(
                warn_from_match(
                    i,
                    "Starting a sentence with a conjunction is discouraged",
                    match,
                )
            )
        match = re.search(r"^(And|Or|But)[\s,]", stripped)
        if match:
            warnings.append(
                warn_from_match(
                    i,
                    "Starting a sentence with a conjunction is discouraged",
                    match,
                )
            )
    return warnings


def check_brackets_space(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for i, line in enumerate(doc.clean_lines):
        stripped = line.strip()
        if (
            doc.is_in_code(i)
            or doc.is_in_equation(i)
            or (stripped and stripped[0] in {"\\", "%"})
        ):
            continue

        for pattern, message in (
            (
                r"[^\s\{~\\]\([^\s\)]",
                "There must be a space before an opening parenthesis",
            ),
            (r"\(\s", "There must be no space after an opening parenthesis"),
            (r"\s\)", "There must be no space before a closing parenthesis"),
        ):
            match = re.search(pattern, line.rstrip())
            if match and line.rstrip()[: match.end()].count("$") % 2 == 0:
                warnings.append(warn_from_match(i, message, match))
    return warnings


def iter_styled_words(doc: Document) -> Iterable[tuple[int, re.Match[str]]]:
    for i, line in enumerate(doc.clean_lines):
        if "newcommand" in line:
            continue
        for match in TEXT_STYLE_RE.finditer(line):
            yield i, match


def check_acronym_capitalization(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    first_seen: dict[str, int] = {}
    for i, line in enumerate(doc.clean_lines):
        if doc.is_in_code(i):
            continue
        for match in re.finditer(r"\b[A-Z]{3,}\b", line):
            pos = match.start()
            if pos > 0 and line[pos - 1] == "\\":
                continue
            first_seen.setdefault(match.group(), i)

    for i, line in enumerate(doc.clean_lines):
        if doc.is_in_code(i):
            continue
        for acronym, first_line in first_seen.items():
            match = re.search(rf"\b{re.escape(acronym)}\b", line.upper())
            if not match:
                continue
            found = line[match.start() : match.end()]
            if found.endswith("s"):
                found = found[:-1]
            if line[: match.start()].count("{") != line[: match.start()].count("}"):
                continue
            if "@" in line:
                continue
            if match.start() > 0 and line[match.start() - 1] == "\\":
                continue
            if found and not found.isupper():
                warnings.append(
                    make_warning(
                        i,
                        f"(Potential) acronym with wrong capitalization (first defined in Line {first_line + 1})",
                        match.span(),
                    )
                )
    return warnings


def check_numeral(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    replacements = [
        (r"\bthree\b", "3"),
        (r"\bfour\b", "4"),
        (r"\bfive\b", "5"),
        (r"\bsix\b", "6"),
        (r"\bseven\b", "7"),
        (r"\beight\b", "8"),
        (r"\bnine\b", "9"),
        (r"\bten\b", "10"),
        (r"\beleven\b", "11"),
        (r"\btwelve\b", "12"),
    ]
    for i, line in enumerate(doc.lines):
        for pattern, replacement in replacements:
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if match:
                warnings.append(
                    make_warning(
                        i,
                        f'Numeral "{match.group()}" should be replaced with "{replacement}"',
                        match.span(),
                    )
                )
    return warnings


def check_colors(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    color_patterns = [
        r"\bred\b",
        r"\bgreen\b",
        r"\bblue\b",
        r"\byellow\b",
        r"\borange\b",
        r"\bmagenta\b",
        r"\bcyan\b",
        r"\bbrown\b",
        r"\bpink\b",
    ]
    modifiers = [
        r"\bdott?(ed)?\b",
        r"\bdash(ed)?\b",
        r"\bthick\b",
        r"\bthin\b",
        r"\bdash-?dotted\b",
        r"\bhatch\b",
        r"\bcross\b",
        r"\bcheck\b",
        r"\bpattern\b",
    ]
    for i, line in enumerate(doc.lines):
        for pattern in color_patterns:
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if not match:
                continue
            if match.start() > 0 and line[match.start() - 1] in {"=", "{"}:
                continue
            if any(
                re.search(modifier, line, flags=re.IGNORECASE) for modifier in modifiers
            ):
                continue
            warnings.append(
                make_warning(
                    i,
                    f'Colors ("{match.group()}") without a modifier such as dashed/dotted/... should be avoided.',
                    match.span(),
                )
            )
    return warnings


def check_inconsistent_word_style(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    word_style: dict[str, tuple[int, str]] = {}
    for i, match in iter_styled_words(doc):
        word = match.group(2)
        style = match.group(1)
        previous = word_style.get(word)
        if previous is None:
            word_style[word] = (i, style)
            continue
        previous_line, previous_style = previous
        if style != previous_style:
            warnings.append(
                make_warning(
                    i,
                    f"Word '{word}' is styled inconsistently, used with \\text{previous_style} before at line {previous_line + 1}",
                    match.span(),
                )
            )
    return warnings


def check_missing_word_style(doc: Document) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    styled_words: dict[str, dict[str, int | str]] = {}
    for i, match in iter_styled_words(doc):
        word = match.group(2)
        if len(word) <= 3:
            continue
        if word not in styled_words:
            styled_words[word] = {"line": i, "style": match.group(1), "count": 1}
        else:
            styled_words[word]["count"] = int(styled_words[word]["count"]) + 1

    for i, line in enumerate(doc.clean_lines):
        if doc.is_in_code(i):
            continue
        for word, info in styled_words.items():
            styled_count = int(info["count"])
            if styled_count <= 1:
                continue
            match = re.search(rf"\b{re.escape(word)}\b", line)
            if not match:
                continue
            if match.start() > 0 and line[match.start() - 1] == "{":
                continue
            other_locations = styled_count - 1
            plural = "" if other_locations == 1 else "s"
            warnings.append(
                make_warning(
                    i,
                    f"Word '{word}' used without a style, used with \\text{info['style']} before at line {int(info['line']) + 1} (and {other_locations} other location{plural})",
                    match.span(),
                )
            )
    return warnings


RULES = [
    Rule(check_space_before_cite, Category.TYPOGRAPHY, "cite-space"),
    Rule(check_figure_alignment, Category.STYLE, "figure-alignment"),
    Rule(check_table_alignment, Category.STYLE, "table-alignment"),
    Rule(check_listing_alignment, Category.STYLE, "listing-alignment"),
    Rule(check_figure_has_label, Category.REFERENCE, "figure-label"),
    Rule(check_table_has_label, Category.REFERENCE, "table-label"),
    Rule(check_listing_has_label, Category.REFERENCE, "listing-label"),
    Rule(check_figure_has_caption, Category.STYLE, "figure-caption"),
    Rule(check_table_has_caption, Category.STYLE, "table-caption"),
    Rule(check_listing_has_caption, Category.STYLE, "listing-caption"),
    Rule(check_no_resizebox_for_tables, Category.STYLE, "resize-table"),
    Rule(check_weird_units, Category.STYLE, "dimensions"),
    Rule(check_figure_caption_label_order, Category.REFERENCE, "figure-caption-order"),
    Rule(check_table_caption_label_order, Category.REFERENCE, "table-caption-order"),
    Rule(
        check_listing_caption_label_order, Category.REFERENCE, "listing-caption-order"
    ),
    Rule(check_todos, Category.GENERAL, "todo"),
    Rule(check_notes, Category.GENERAL, "note"),
    Rule(check_math_numbers, Category.TYPOGRAPHY, "math-numbers"),
    Rule(check_large_numbers_without_si, Category.TYPOGRAPHY, "si"),
    Rule(check_listing_in_correct_float, Category.REFERENCE, "listing-float"),
    Rule(check_tabular_in_correct_float, Category.REFERENCE, "tabular-float"),
    Rule(check_tikz_in_correct_float, Category.REFERENCE, "tikz-float"),
    Rule(check_comment_has_space, Category.TYPOGRAPHY, "comment-space"),
    Rule(check_percent_without_siunitx, Category.TYPOGRAPHY, "percentage"),
    Rule(check_short_form, Category.GENERAL, "short-form"),
    Rule(check_labels_referenced, Category.REFERENCE, "label-referenced"),
    Rule(check_section_capitalization, Category.VISUAL, "capitalization"),
    Rule(check_quotation, Category.TYPOGRAPHY, "quotes"),
    Rule(check_hline_in_table, Category.VISUAL, "hline"),
    Rule(check_space_before_punctuation, Category.TYPOGRAPHY, "punctuation-space"),
    Rule(check_headers_without_text, Category.VISUAL, "two-header"),
    Rule(check_one_sentence_paragraphs, Category.VISUAL, "single-sentence"),
    Rule(check_multiple_sentences_per_line, Category.GENERAL, "multiple-sentences"),
    Rule(check_unbalanced_brackets, Category.TYPOGRAPHY, "unbalanced-brackets"),
    Rule(check_and_or, Category.TYPOGRAPHY, "and-or"),
    Rule(check_ellipsis, Category.TYPOGRAPHY, "ellipsis"),
    Rule(check_etc, Category.STYLE, "etc"),
    Rule(check_punctuation_end_of_line, Category.TYPOGRAPHY, "punctuation"),
    Rule(check_footnote, Category.TYPOGRAPHY, "footnote"),
    Rule(check_table_vertical_lines, Category.VISUAL, "vline"),
    Rule(check_table_top_caption, Category.STYLE, "table-top-caption"),
    Rule(check_will, Category.GENERAL, "will"),
    Rule(check_subsection_count, Category.VISUAL, "single-subsection"),
    Rule(check_mixed_compact_and_item, Category.VISUAL, "mixed-compact"),
    Rule(check_center_in_float, Category.VISUAL, "float-center"),
    Rule(check_appendix, Category.STYLE, "appendix"),
    Rule(check_eqnarray, Category.VISUAL, "eqnarray"),
    Rule(check_acm_pc, Category.STYLE, "inclusion"),
    Rule(check_cite_noun, Category.STYLE, "cite-noun"),
    Rule(check_cite_duplicate, Category.REFERENCE, "cite-duplicate"),
    Rule(check_conjunction_start, Category.STYLE, "conjunction-start"),
    Rule(check_brackets_space, Category.TYPOGRAPHY, "bracket-spacing"),
    Rule(check_acronym_capitalization, Category.TYPOGRAPHY, "acronym-capitalization"),
    Rule(check_numeral, Category.GENERAL, "numeral"),
    Rule(check_multicite, Category.STYLE, "multiple-cites"),
    Rule(check_emptycite, Category.REFERENCE, "cite-empty"),
    Rule(check_colors, Category.VISUAL, "colors"),
    Rule(check_inconsistent_word_style, Category.TYPOGRAPHY, "inconsistent-textstyle"),
    Rule(check_missing_word_style, Category.TYPOGRAPHY, "missing-textstyle"),
]

CATEGORY_SWITCHES: dict[str, Category] = {
    "all": Category.GENERAL
    | Category.REFERENCE
    | Category.STYLE
    | Category.TYPOGRAPHY
    | Category.VISUAL,
    "general": Category.GENERAL,
    "reference": Category.REFERENCE,
    "style": Category.STYLE,
    "typography": Category.TYPOGRAPHY,
    "visual": Category.VISUAL,
}


def run_rules(
    doc: Document, enabled_rules: set[str]
) -> tuple[list[WarningRecord], int]:
    warnings: list[WarningRecord] = []
    suppressed = 0
    for rule in RULES:
        results = add_category(rule.func(doc), rule.name)
        if rule.name in enabled_rules:
            warnings.extend(results)
        else:
            suppressed += len(results)
    warnings.sort(
        key=lambda item: (item.line, item.category, item.message, item.span or (-1, -1))
    )
    return warnings, suppressed


def print_warnings(
    doc: Document,
    warnings: Sequence[WarningRecord],
    *,
    output: bool = True,
) -> int:
    count = 0
    for warning in warnings:
        if warning.line != -1 and doc.lines[warning.line].strip().startswith("%"):
            continue

        count += 1
        if not output:
            continue

        if warning.line != -1:
            print(
                f"{YELLOW}Warning {count}{RESET}: Line {warning.line + 1}: "
                f"{warning.message}  {GRAY}[{warning.category}]{RESET}"
            )
        else:
            print(
                f"{YELLOW}Warning {count}{RESET}: {warning.message}  "
                f"{GRAY}[{warning.category}]{RESET}"
            )

        if warning.span is not None and warning.line != -1:
            line = doc.lines[warning.line].replace("\t", " ")
            start, end = warning.span
            width = max(1, end - start)
            print(f"    {line}")
            print(f"    {' ' * start}{YELLOW}{'^' * width}{RESET}")
    return count


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        config = parse_cli(argv)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 1
        raise

    total_warnings = 0
    total_suppressed = 0

    for tex_file in config.tex_files:
        doc = Document.from_path(tex_file)
        print(f"Inspecting file {BLUE}'{tex_file}'{RESET}")

        warnings, suppressed = run_rules(doc, config.enabled_rules)
        total_warnings += print_warnings(doc, warnings, output=True)
        total_suppressed += suppressed

    print()
    print(f"{total_warnings} warnings printed; {total_suppressed} suppressed warnings")
    if config.error_exit:
        return 1 if total_warnings > 0 else 0
    return 0


if __name__ == "__main__":
    main()
