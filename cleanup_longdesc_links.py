"""Remove spurious 'Long description' links from longdesc pages.

These were inserted when add_alt_and_longdesc.py incorrectly processed its
own generated longdesc pages (which contain <img> tags).
"""

import os
import sys
import argparse
from bs4 import BeautifulSoup


def clean_file(path, dry_run=False):
    with open(path, encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')

    removed = 0
    for a in soup.find_all('a'):
        if a.get_text(strip=True) == 'Long description':
            a.decompose()
            removed += 1

    if removed:
        if dry_run:
            print(f"[DRY RUN] Would remove {removed} link(s) from {path}")
        else:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(str(soup))
            print(f"Removed {removed} link(s) from {path}")

    return removed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', help='Root directory to search for longdesc pages')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without writing')
    args = parser.parse_args()

    total_files = 0
    total_removed = 0
    for dirpath, dirs, files in os.walk(args.root):
        if os.path.basename(dirpath) != 'longdesc':
            continue
        for name in files:
            if not name.endswith('.html'):
                continue
            path = os.path.join(dirpath, name)
            n = clean_file(path, dry_run=args.dry_run)
            if n:
                total_files += 1
                total_removed += n

    print(f"\nDone: {total_removed} link(s) removed from {total_files} file(s)")


if __name__ == '__main__':
    main()
