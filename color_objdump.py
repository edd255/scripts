#!/usr/bin/env python3

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from typing import Final


def esc(code: str) -> str:
    return f"\033[{code}m"


def color(index: int) -> str:
    return esc(f"38;5;{index}")


def bgcolor(index: int) -> str:
    return esc(f"48;5;{index}")


RESET: Final = esc("0")
BOLD: Final = esc("1")

ADDR_FG: Final = color(241)
BRACKET_FG: Final = color(22)
SYMBOL_FG: Final = color(76)
COMMENT_FG: Final = color(99)
IMMEDIATE_FG: Final = color(202)
FILENAME_FG: Final = color(33)
FILE_LINE_FG: Final = color(87)
FALLBACK_FG: Final = color(159)
FALLBACK_BG: Final = bgcolor(195)
MNEMONIC_FG: Final = color(226)
SECTION_BG: Final = bgcolor(89)
HEADER_FG: Final = color(210)

LT: Final = f"{BRACKET_FG}{BOLD}<{RESET}"
GT: Final = f"{BRACKET_FG}{BOLD}>{RESET}"

HEX_ADDRESS: Final = r"[0-9a-f]+"
SYMBOL_NAME: Final = r"[a-zA-Z_@.][a-zA-Z0-9_@.]*"
ANSI_GAP: Final = r"[\s\\/|,\-+>'\[m0-9;\033]+"
MNEMONIC: Final = r"[a-z][a-z0-9.]*"
CODE_CONTEXT_LINE_TYPES: Final = frozenset(("file spec", "code"))


@dataclass(frozen=True)
class Rule:
    line_type: str
    pattern: re.Pattern[str]
    replacement: str


RULES: Final[tuple[Rule, ...]] = (
    Rule(
        "id",
        re.compile(rf"^({HEX_ADDRESS}) <({SYMBOL_NAME})>:$"),
        rf"{ADDR_FG}\1{RESET} {LT}{SYMBOL_FG}\2{RESET}{GT}:",
    ),
    Rule(
        "id",
        re.compile(rf"^({HEX_ADDRESS}) <({SYMBOL_NAME})(\+|-)0x([0-9a-f]+)>:$"),
        rf"{ADDR_FG}\1{RESET} {LT}{SYMBOL_FG}\2{RESET}\3{IMMEDIATE_FG}0x\4{RESET}{GT}:",
    ),
    Rule(
        "func spec",
        re.compile(rf"^({SYMBOL_NAME})\("),
        rf"{SYMBOL_FG}\1{RESET}(",
    ),
    Rule(
        "instruction",
        re.compile(
            rf"^(\s*)({HEX_ADDRESS}):"
            rf"({ANSI_GAP})"
            rf"(([0-9a-f]{{2}}\s)+\s*)"
            rf"(({MNEMONIC})\b)"
        ),
        rf"\1\2:\3\4{MNEMONIC_FG}\6{RESET}",
    ),
    Rule(
        "instruction",
        re.compile(rf"^(\s*)({HEX_ADDRESS}):"),
        rf"\1{ADDR_FG}\2{RESET}:",
    ),
    Rule(
        "instruction",
        re.compile(rf"#\s({HEX_ADDRESS}) <({SYMBOL_NAME})>"),
        rf"{COMMENT_FG}#{RESET} {ADDR_FG}\1{RESET} {LT}{SYMBOL_FG}\2{RESET}{GT}",
    ),
    Rule(
        "instruction",
        re.compile(rf"#\s({HEX_ADDRESS}) <({SYMBOL_NAME})\+0x([0-9a-f]+)>"),
        rf"{COMMENT_FG}#{RESET} {ADDR_FG}\1{RESET} {LT}{SYMBOL_FG}\2{RESET}+{IMMEDIATE_FG}0x\3{RESET}{GT}",
    ),
    Rule(
        "file spec",
        re.compile(r"^([^:\n]+):(\d+)( \(.*\))?$"),
        rf"{FILENAME_FG}\1{RESET}:{FILE_LINE_FG}\2{RESET}\3",
    ),
    Rule(
        "section spec",
        re.compile(r"^(Disassembly of section \..*:)$"),
        rf"{SECTION_BG}\1{RESET}",
    ),
    Rule(
        "header",
        re.compile(r"^(.*):(\s*)file format (.*)$"),
        rf"{BOLD}{HEADER_FG}\1{RESET}{BOLD}:\2file format {HEADER_FG}\3{RESET}",
    ),
)


def handle_broken_pipe() -> int:
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, sys.stdout.fileno())
    finally:
        os.close(devnull)
    return 1


def style_line(line: str, last_line_type: str | None) -> tuple[str, str | None]:
    matched_regular_rule = False
    for rule in RULES:
        line, replacements = rule.pattern.subn(rule.replacement, line)
        if replacements:
            matched_regular_rule = True
            last_line_type = rule.line_type
    if not matched_regular_rule and (
        line.strip() or last_line_type in CODE_CONTEXT_LINE_TYPES
    ):
        line = f"{FALLBACK_BG} {RESET} {FALLBACK_FG}{line}{RESET}"
        last_line_type = "code"
    return line, last_line_type


def main() -> int:
    last_line_type: str | None = None
    try:
        for line in sys.stdin:
            styled_line, last_line_type = style_line(line, last_line_type)
            sys.stdout.write(styled_line)
        sys.stdout.flush()
        return 0
    except BrokenPipeError:
        return handle_broken_pipe()


if __name__ == "__main__":
    raise SystemExit(main())
