#!/usr/bin/env python3
"""
extract_code.py — Walk a source directory and write all code files
into a single output file with clear filename headers.

Usage:
    python extract_code.py [SOURCE_DIR] [OUTPUT_FILE]

Defaults:
    SOURCE_DIR  = . (current directory)
    OUTPUT_FILE = all_code.txt
"""

import sys
import os

# ── configurable ──────────────────────────────────────────────────────────────

SOURCE_DIR  = sys.argv[1] if len(sys.argv) > 1 else "."
OUTPUT_FILE = sys.argv[2] if len(sys.argv) > 2 else "all_code.txt"

# File extensions to include
INCLUDE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css",
    ".json", ".md", ".txt", ".env", ".example", ".toml",
    ".yaml", ".yml", ".sh", ".gitkeep",
}

# Directories to skip entirely
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".nuxt", "coverage",
}

# ── helpers ───────────────────────────────────────────────────────────────────

SEPARATOR = "=" * 80

def should_include(filepath: str) -> bool:
    _, ext = os.path.splitext(filepath)
    # include files with a known extension OR no extension (e.g. .env files)
    return ext.lower() in INCLUDE_EXTENSIONS or ext == ""


def collect_files(root: str):
    """Yield (relative_path, absolute_path) for every included file."""
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        # prune skipped directories in-place so os.walk won't descend into them
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in sorted(filenames):
            abs_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(abs_path, root)
            if should_include(fname):
                yield rel_path, abs_path


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    files = list(collect_files(SOURCE_DIR))

    if not files:
        print(f"No matching files found in '{SOURCE_DIR}'.")
        sys.exit(0)

    with open(OUTPUT_FILE, "w", encoding="utf-8", errors="replace") as out:
        out.write(f"# Code extraction from: {os.path.abspath(SOURCE_DIR)}\n")
        out.write(f"# Total files: {len(files)}\n\n")

        for rel_path, abs_path in files:
            out.write(f"{SEPARATOR}\n")
            out.write(f"FILE: {rel_path}\n")
            out.write(f"{SEPARATOR}\n\n")

            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                out.write(content)
                if content and not content.endswith("\n"):
                    out.write("\n")
            except Exception as e:
                out.write(f"[ERROR reading file: {e}]\n")

            out.write("\n\n")

    print(f"Done! Extracted {len(files)} file(s) → {OUTPUT_FILE}")
    for rel_path, _ in files:
        print(f"  {rel_path}")


if __name__ == "__main__":
    main()
