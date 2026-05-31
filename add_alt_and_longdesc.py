#!/usr/bin/env python3
"""
Scan HTML files containing "webse", generate alt text and long descriptions
using the describe_image generator function, overwrite `alt` attributes and
create long-description pages with links.

Usage:
  python add_alt_and_longdesc.py --root /path/to/HELM [--sample N]

Options:
  --root: Root directory to scan (default: current directory)
  --sample N: Test on only the first N HTML files instead of all
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from bs4 import BeautifulSoup

from ollama import chat

FEEDBACK_FORM_BASE_URL = "https://forms.cloud.microsoft/Pages/ResponsePage.aspx?id=Ij1-N6FOLUKwrY_MiUBrniyWw9-2i6NOnzQLLWx0jLNUOElVQ0hJU0JDM1g4TEFOVTdJUk00MEtMTy4u"
FEEDBACK_ENTRY_IMAGE_ID = "raf2b02bb0c1c4df5b509e58b27b31c4e"
FEEDBACK_ENTRY_SOURCE_PAGE = "r26f53601ae57427e8dae0dd738a10840"
MODEL = 'gemma4:e4b'

def fix_latex_delimiters(text):
    """Normalise LaTeX delimiters to \\( \\) regardless of what the model output."""
    # Display math first: $$...$$ → \[...\]
    text = re.sub(r'\$\$(.+?)\$\$', r'\\[\1\\]', text, flags=re.DOTALL)
    # Inline math: $...$ → \(...\)
    text = re.sub(r'\$(.+?)\$', r'\\(\1\\)', text, flags=re.DOTALL)
    return text


def fix_json_latex_escapes(text):
    """Repair LaTeX commands broken by json.loads() consuming unescaped backslashes.

    json.loads() converts \\t→TAB, \\f→FF, \\r→CR, \\b→BS. LLMs frequently emit
    LaTeX commands like \\text, \\frac, \\right without doubling the backslash in JSON,
    so these arrive in parsed output as control characters rather than backslashes.
    """
    repairs = [
        ('\text',        r'\text'),
        ('\theta',       r'\theta'),
        ('\tau',         r'\tau'),
        ('\times',       r'\times'),
        ('\tfrac',       r'\tfrac'),
        ('\frac',        r'\frac'),
        ('\forall',      r'\forall'),
        ('\right',       r'\right'),
        ('\rho',         r'\rho'),
        ('\beta',        r'\beta'),
        ('\bar',         r'\bar'),
        ('\binom',       r'\binom'),
        ('\boldsymbol',  r'\boldsymbol'),
    ]
    for broken, fixed in repairs:
        text = text.replace(broken, fixed)
    return text


def bullets_to_html(text):
    """Convert a *-bulleted string (with or without newlines) to a <ul> list."""
    items = [i.strip() for i in re.split(r'\s*\*\s*', text) if i.strip()]
    if not items:
        return f'<p>{text}</p>'
    return '<ul>\n' + ''.join(f'  <li>{item}</li>\n' for item in items) + '</ul>'


def describe_image(image_path, context, mod=MODEL):
    response = chat(
        model=mod,
        format={
            "type": "object",
            "properties": {
                "alt": {"type": "string"},
                "long_description": {"type": "string"}
            },
            "required": ["alt", "long_description"]
        },
        messages=[{
                "role": "system",
                "content": """You are an assistant that produces structured accessibility descriptions for images.

        Rules (must be strictly followed):
        - Output must be valid JSON
        - Always use LaTeX for mathematical expressions with \\( and \\)
        - Do not use plain text math
        - The long_description must be a bulleted list
        - Do not explain concepts, only describe what is visible
        - Spell out all abbreviated units
        """
            },
            {
                "role": "user",
                "content": f"""Describe the image for a visually impaired person.
        Use this context to support interpretation:
        {context}
        Return JSON with:
        - "alt": single sentence
        - "long_description": detailed multi-sentence bulleted description
        """,
                "images": [image_path],
            }]
    )
    result = json.loads(response.message.content)
    result['alt'] = fix_json_latex_escapes(fix_latex_delimiters(result.get('alt', '')))
    result['long_description'] = fix_json_latex_escapes(fix_latex_delimiters(result.get('long_description', '')))
    return result

def find_html_files_with_webse(root_dir):
    files = []
    for root, dirs, names in os.walk(root_dir):
        if os.path.basename(root) == 'longdesc':
            dirs[:] = []
            continue
        for n in names:
            if n.endswith('.html') and 'webse' in n:
                files.append(os.path.join(root, n))
    return sorted(files)


def resolve_image_path(html_file, image_src):
    html_dir = os.path.dirname(html_file)
    # strip any query or fragment
    src = image_src.split('?')[0].split('#')[0]
    candidate = os.path.normpath(os.path.join(html_dir, src))
    if os.path.isfile(candidate):
        return candidate
    return None


def find_png_for_image(resolved_path):
    """Look for an existing PNG for the image. If not found, return None.
    Search order:
      1. Same directory, same basename + .png
      2. png_converted subdir, same basename + .png
    """
    base = os.path.splitext(os.path.basename(resolved_path))[0]
    dirp = os.path.dirname(resolved_path)
    cand1 = os.path.join(dirp, base + '.png')
    cand2 = os.path.join(dirp, 'png_converted', base + '.png')
    if os.path.isfile(cand1):
        return cand1
    if os.path.isfile(cand2):
        return cand2
    return None


def shutil_which(cmd):
    try:
        import shutil
        return shutil.which(cmd)
    except Exception:
        return None


def convert_svg_to_png(svg_path, output_png, converter=None):
    # prefer Inkscape if available, otherwise ImageMagick convert
    if converter is None:
        converter = shutil_which('convert') or shutil_which('inkscape')
    try:
        os.makedirs(os.path.dirname(output_png), exist_ok=True)
        print(f"DEBUG: converter={converter}, cwd={os.getcwd()}, svg_path={svg_path}")
        if converter and 'inkscape' in os.path.basename(converter):
            # this is an unsafe way to call inkscape, but easier for now
            result = subprocess.run(f"{converter} --export-type=png --export-filename={output_png} {svg_path}", shell=True, check=True, timeout=30, capture_output=True, text=True, env=os.environ.copy())
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
            print(f'used inkscape: {converter} and converted {svg_path} to {output_png}')
        else:
            result = subprocess.run([converter, '-verbose', '-depth','8', svg_path, output_png], check=True, timeout=300, capture_output=True, text=True, env=os.environ.copy())
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
            print(f'used convert: {converter} and converted {svg_path} to {output_png}')
        return os.path.isfile(output_png)
    except Exception as e:
        print(f"Conversion error {svg_path} -> {output_png}: {e}", file=sys.stderr)
        return False


def get_context_for_image(img_tag):
    # Provide some textual context to the generator: alt, title, and surrounding text
    ctx = {}
    ctx['orig_alt'] = img_tag.get('alt', '')
    ctx['title'] = img_tag.get('title', '')
    parent = img_tag.parent
    if parent:
        txt = parent.get_text(separator=' ', strip=True)
        ctx['parent_text'] = txt[:1000]
    else:
        ctx['parent_text'] = ''
    return ctx


def make_longdesc_page(html_file, img_basename, long_description, png_path=None, alt_text=None):
    html_dir = os.path.dirname(html_file)
    longdir = os.path.join(html_dir, 'longdesc')
    os.makedirs(longdir, exist_ok=True)
    page_name = f"{Path(html_file).stem}__{img_basename}_longdesc.html"
    page_path = os.path.join(longdir, page_name)
    title = f"Long description: {img_basename}"
    
    # Prepare image HTML if png_path is provided
    image_html = ""
    if png_path:
        img_rel_path = os.path.relpath(png_path, start=longdir).replace(os.path.sep, '/')
        alt = alt_text if alt_text else img_basename
        image_html = f'<figure>\n<img src="{img_rel_path}" alt="{alt}"/>\n</figure>\n'
    
    alt_display_html = ""
    if alt_text:
        alt_display_html = f'<p><strong>Alt text:</strong> {alt_text}</p>'

    back_href = f"../{Path(html_file).name}"
    back_link_html = f'<p><a href="{back_href}">&#8592; Return to source page</a></p>'

    source_page = Path(html_file).stem
    form_url = (
        f"{FEEDBACK_FORM_BASE_URL}"
        f"&{FEEDBACK_ENTRY_IMAGE_ID}={quote(img_basename)}"
        f"&{FEEDBACK_ENTRY_SOURCE_PAGE}={quote(source_page)}"
    )
    feedback_html = f'<hr/>\n<p><a href="{form_url}" target="_blank">Give feedback on this description</a></p>'
    content = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{title}</title>
<meta content="target-densitydpi=device-dpi; width=device-width; initial-scale=1.0; minimum-scale=1.0; user-scalable=yes;" name="viewport"/>
<meta content="True" name="HandheldFriendly"/>
<meta content="TeX4ht (http://www.cse.ohio-state.edu/~gurari/TeX4ht/)" name="generator"/>
<link href="10_2_argnd_diag_n_polar_form-web.css" rel="stylesheet" type="text/css"/>
<link href="additional.css" rel="stylesheet" type="text/css"/>
<script type="text/x-mathjax-config">
   MathJax.Hub.Config({{ mml2jax: {{ preview: ["[maths rendering]"]}}, 
  "fast-preview": {{disabled: true}}, 
  explorer:{{ subtitle: true }}, 
  displayAlign: "center",  
  MatchWebFonts: {{ 
  matchFor: {{ "HTML-CSS": true, NativeMML: false, SVG: false }}, 
  fontCheckDelay: 2000, 
  fontCheckTimeout: 30 * 1000 
  }}, 
  "HTML-CSS": {{ 
  preferredFont: "STIX",  
  availableFonts: ["STIX","TeX"],  
  webFont: "STIX-Web",  
  linebreaks: {{ automatic: true, width: "90% container" }} 
  }}, 
  SVG: {{  
  font: "STIX-Web", 
  linebreaks: {{ automatic: false, width: "90% container" }} 
  }}, 
  menuSettings: {{ collapsible: false, autocollapse: false, explorer: false }} 
  }});
  </script>
<script type="text/x-mathjax-config">
   MathJax.Hub.Register.MessageHook("End Math", function (msg) {{ 
  var nodes = Array.from(msg[1].querySelectorAll('.MJX_Assistive_MathML [id]')); 
  while (nodes.length) {{ 
  nodes.shift().removeAttribute('id'); 
  }} 
  }}, 20);
  </script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.0/MathJax.js?config=TeX-AMS-MML_HTMLorMML-full" type="text/javascript">
</script>
<style type="text/css">
   ".MathJax_MathML" {{text-indent: 0;}}
  </style>
<link href="https://maxcdn.bootstrapcdn.com/bootstrap/3.4.1/css/bootstrap.min.css" rel="stylesheet"/>
<script src="https://ajax.googleapis.com/ajax/libs/jquery/3.5.1/jquery.min.js">
</script>
<script src="https://maxcdn.bootstrapcdn.com/bootstrap/3.4.1/js/bootstrap.min.js">
</script>
<link href="toplayer.css" rel="stylesheet" type="text/css"/>
</head>
<body>
<main>
<div class="container">
<h1>{title}</h1>
{back_link_html}
{image_html}
{alt_display_html}
<div class="long-description">
<p><strong>This description was generated by AI and has not been verified by a human. If you spot an error, please use the feedback link below.</strong></p>
{bullets_to_html(long_description)}
</div>
{feedback_html}
</div>
</main>
</body>
</html>
"""
    with open(page_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return page_path


def relative_href(from_html, to_path):
    return os.path.relpath(to_path, start=os.path.dirname(from_html)).replace(os.path.sep, '/')


def import_generator(spec):
    if ':' not in spec:
        raise SystemExit('Generator must be specified as module:function')
    mod_name, func_name = spec.split(':', 1)
    mod = importlib.import_module(mod_name)
    func = getattr(mod, func_name)
    if not callable(func):
        raise SystemExit('Generator is not callable')
    return func


def log_entry(log_file, status, html_file, image_name):
    with open(log_file, 'a', newline='') as f:
        csv.writer(f).writerow([
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            status, html_file, image_name
        ])


def process_file(html_file, generator, dry_run=False, log_file=None) -> int:
    changed = False
    images_processed = 0
    with open(html_file, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')

    imgs = soup.find_all('img')
    for img in imgs:
        src = img.get('src')
        if not src:
            continue
        resolved = resolve_image_path(html_file, src)
        if not resolved:
            print(f"Image not found for src {src} in {html_file}", file=sys.stderr)
            continue

        png_path = find_png_for_image(resolved)
        if not png_path and resolved.lower().endswith('.svg'):
            # attempt conversion into png_converted
            base = os.path.splitext(os.path.basename(resolved))[0]
            outdir = os.path.join(os.path.dirname(resolved), 'png_converted')
            os.makedirs(outdir, exist_ok=True)
            outpng = os.path.join(outdir, f"{base}.png")
            ok = convert_svg_to_png(resolved, outpng)
            if ok:
                png_path = outpng

        if not png_path:
            print(f"No PNG available for {resolved} (skipping)")
            continue

        base = os.path.splitext(os.path.basename(png_path))[0]
        expected_longdesc = os.path.join(
            os.path.dirname(html_file), 'longdesc',
            f"{Path(html_file).stem}__{base}_longdesc.html"
        )
        if os.path.isfile(expected_longdesc):
            print(f"  Skipping {base} (longdesc already exists)")
            if log_file:
                log_entry(log_file, 'skipped', html_file, base)
            continue

        context = get_context_for_image(img)
        context.update({'html_file': html_file, 'image_src': src})

        try:
            result = generator(png_path, context)
        except Exception as e:
            print(f"Generator error for {png_path}: {e}", file=sys.stderr)
            if log_file:
                log_entry(log_file, 'error', html_file, base)
            continue

        if not isinstance(result, dict):
            print(f"Generator must return dict for {png_path}", file=sys.stderr)
            if log_file:
                log_entry(log_file, 'error', html_file, base)
            continue

        alt = result.get('alt')
        long_description = result.get('long_description')
        if alt:
            img['alt'] = alt
            changed = True

        if long_description:
            page_path = make_longdesc_page(html_file, base, long_description, png_path, alt)
            if log_file:
                log_entry(log_file, 'processed', html_file, base)
            images_processed += 1
            href = relative_href(html_file, page_path)
            # insert link after the image
            a = soup.new_tag('a', href=href)
            a.string = 'Long description'
            #parent = img.parent
            #sp = soup.new_tag('strong')
            #sp.string = f'Inserted after parent of image: {alt}'
            img.parent.insert_after(a)
            #img.insert_after(a)
            changed = True

    if changed:
        if not dry_run:
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(str(soup))
            print(f"Updated {html_file}")
        else:
            print(f"[DRY RUN] Would update {html_file}")

    return images_processed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='.', help='Root directory to scan')
    parser.add_argument('--sample', type=int, help='Test on only the first N HTML files')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without modifying files')
    parser.add_argument('--log-file', default='helm-ai-progress.csv', help='CSV file to log processed images')
    parser.add_argument('--max-images', type=int, default=None,
                        help='Stop after processing this many images (for chunked runs)')
    args = parser.parse_args()

    if not os.path.isfile(args.log_file):
        with open(args.log_file, 'w', newline='') as f:
            csv.writer(f).writerow(['timestamp', 'status', 'html_file', 'image'])

    html_files = find_html_files_with_webse(args.root)
    print(f"Found {len(html_files)} webse HTML files")

    if args.sample:
        html_files = html_files[:args.sample]
        print(f"Testing on sample of {len(html_files)} files")

    if args.dry_run:
        print("[DRY RUN MODE] - Files will not be modified")

    print("-" * 80)

    total_processed = 0
    for hf in html_files:
        n = process_file(hf, describe_image, dry_run=args.dry_run, log_file=args.log_file)
        total_processed += n
        if args.max_images and total_processed >= args.max_images:
            print(f"\nReached --max-images limit ({args.max_images}). Re-run to continue.")
            break

    print("-" * 80)
    print(f"Session complete: {total_processed} image(s) processed.")
    if args.max_images and total_processed >= args.max_images:
        print("There may be more images remaining. Re-run with the same command to continue.")


if __name__ == '__main__':
    main()
