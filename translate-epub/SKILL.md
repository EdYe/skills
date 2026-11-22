---
name: translate-epub
description: >
  Translate an English EPUB book into Traditional Chinese (繁體中文) markdown files, one file per chapter.
  Use when the user wants an English EPUB ebook translated into Traditional Chinese markdown,
  in English or Chinese phrasing (e.g. 翻譯 EPUB、電子書翻譯).
  This skill handles the full pipeline: EPUB parsing with ebooklib, chapter detection, parallel translation,
  and quality verification.
---

# Translate English EPUB Book to Traditional Chinese Markdown

This skill translates an entire English EPUB book into per-chapter Traditional Chinese (繁體中文) markdown files. It uses `ebooklib` to parse EPUB structure and translates each chapter (HTML document) in parallel.

## Before You Start

### Ask the user these questions (if not already answered):

1. **Technical term format**: When a technical term first appears, should it be "中文翻譯（English Term）" or just the Chinese translation? (Default: "中文（English）" on first occurrence, then Chinese only)
2. **References**: Should chapter-end reference lists be included or omitted? (Default: omit, but keep inline citation numbers like [1], [2])
3. **Output directory**: Where should the translated files go? (Default: `zh-tw/` in the same directory as the EPUB)
4. **Any chapters to skip?**: Sometimes the user only wants specific chapters (e.g., skip foreword, index).
5. **Chapter split threshold**: At what word count should chapters be automatically split? (Default: 8,000 English words, produces ~15,000 Chinese characters)

## Step 0: Build the Glossary FIRST (do not skip)

**This is the single highest-leverage step.** Parallel translation agents independently coin different Chinese terms for the same English term (observed in practice: one book produced three renderings of "thesaurus" plus divergent reasoner/semantics/linked-data/metadata terms). Unifying them afterwards costs more than the translation itself.

1. Extract the book's core technical terms and standard zh-TW renderings from the book's glossary/index, TOC, and domain-standard translations (30-70 terms typical). If a glossary chapter is among the outputs, translate it first and treat its renderings as canonical.
2. **Inject the full glossary into every translator agent's prompt**: "Use these exact renderings. Do not coin alternatives."
3. **Proper-noun exemption list**: established proper-noun translations (e.g. Getty AAT＝藝術與建築索引典) stay as-is, exempt from unification.
4. If divergence still occurs, unify by **majority vote via grep count** across output files, then sed, then verify count is zero — deterministic, no LLM debate.

## Step 1: Parse the EPUB Structure

First, install ebooklib if needed:

```bash
pip install --break-system-packages ebooklib 2>/dev/null || pip install ebooklib
```

Then extract the EPUB structure and identify chapters:

```python
from ebooklib import epub
import os

book = epub.read_epub("<path-to-epub>")

# Get book metadata
print(f"Title: {book.get_metadata('dc', 'title')[0]}")
print(f"Author: {book.get_metadata('dc', 'creator')[0]}")

# List all items and identify chapters (HTML documents)
chapters = []
for item in book.get_items():
    if item.get_type() == ebooklib.ITEM_DOCUMENT:
        print(f"Chapter: {item.get_name()}")
        chapters.append(item)
```

Build a chapter map:

| File name | Chapter title | Source HTML | Estimated word count |
|-----------|--------------|-------------|---------------------|

**Chapter splitting threshold**: By default, chapters over **8,000 words** (or ~15,000 Chinese characters after translation) will be automatically split by major sections (detected by `##` headings). The user can adjust this threshold.

## Step 2: Create a Translation Plan

Present the chapter map to the user and confirm before proceeding. The plan should include:

- Output file naming convention (e.g., `00-preface.md`, `01-chapter-title.md`, `glossary.md`)
- Which chapters will be translated
- Which chapters exceed the split threshold and will be divided into parts (e.g., `05-long-chapter-part1.md`, `05-long-chapter-part2.md`)
- Estimated time per chapter

Create the output directory:

```bash
mkdir -p <output-directory>
```

## Step 3: Extract and Translate Each Chapter

### Text Extraction and Chapter Splitting

For each chapter, extract HTML content and convert to plain text. **If the chapter exceeds the split threshold (default 8,000 words), automatically split it by major sections**.

```python
from ebooklib import epub
from bs4 import BeautifulSoup

def extract_chapter_text(epub_path, chapter_name):
    """Extract text from a chapter, preserving heading hierarchy."""
    book = epub.read_epub(epub_path)
    
    chapter_item = None
    for item in book.get_items():
        if item.get_name() == chapter_name:
            chapter_item = item
            break
    
    if not chapter_item:
        return None, []
    
    html_content = chapter_item.get_content().decode('utf-8')
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract sections by heading
    sections = []
    current_section = {'heading': 'Introduction', 'content': []}
    
    for elem in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'blockquote', 'pre', 'code']):
        if elem.name in ['h1', 'h2', 'h3']:
            # Save current section and start new one
            if current_section['content']:
                sections.append(current_section)
            current_section = {
                'heading': elem.get_text().strip(),
                'content': []
            }
        else:
            current_section['content'].append(elem.get_text())
    
    if current_section['content']:
        sections.append(current_section)
    
    # Calculate word count
    all_text = ' '.join([' '.join(s['content']) for s in sections])
    word_count = len(all_text.split())
    
    return all_text.strip(), sections, word_count

# Usage
text, sections, word_count = extract_chapter_text("<path-to-epub>", "<chapter-filename>")
print(f"Word count: {word_count}")
print(f"Number of sections: {len(sections)}")
for sec in sections:
    print(f"  - {sec['heading']}: {len(' '.join(sec['content']).split())} words")
```

**Split decision logic:**

```python
SPLIT_THRESHOLD = 8000  # words

if word_count > SPLIT_THRESHOLD and len(sections) >= 2:
    # Chapter will be split into parts
    print(f"Chapter exceeds threshold, will split into {len(sections)} parts")
else:
    # Chapter fits in single file
    print(f"Chapter fits in single file")
```

Write extracted text to temp files:
- For non-split chapters: `/tmp/ch<N>.txt`
- For split chapters: `/tmp/ch<N>_part<M>.txt` (one per section)

### Translation Rules

Apply these rules consistently across all chapters:

**Content completeness — this is the most important rule:**
- Translate every single sentence in the body text, including figure captions, table content, block quotes, footnotes, and chapter summaries
- The only content to omit is the chapter-end References/Bibliography section (unless the user says otherwise)
- Keep inline citation numbers like [1], [2] as-is

**Technical terms:**
- First occurrence: 「中文翻譯（English Term）」
- Subsequent occurrences: use the Chinese translation directly
- Common abbreviations that stay in English: API, SQL, NoSQL, SSTable, RPC, TCP, UDP, HTTP, REST, JSON, XML, YAML, CSV, SSD, HDD, RAID, CPU, GPU, RAM, GC, JVM, VM, MVCC, ACID, BASE, CAD, DNS, NTP, GPS, UTC, AWS, GCP, HDFS, MapReduce, and similar widely-recognized acronyms
- When in doubt about whether to keep English, use the "中文（English）" format

**Code blocks:**
- Fenced code blocks are **verbatim** — do NOT translate code content, strings, or language tags (observed failure: Turtle translated into Chinese while leaving `@en` tags, corrupting the RDF). Only code comments may be translated.
- Translate all surrounding explanation text

**Punctuation (state this in every translator agent prompt):**
- Chinese prose uses fullwidth punctuation: ，：（）；？！「」
- Code blocks, CSV data, URLs, standard codes, English table content keep halfwidth punctuation
- Without this rule, agents pick different styles and the retroactive fix costs hundreds of lines per chapter

**Figures and tables:**
- Format figure captions as: `> **圖 X-Y.** 翻譯後的圖說`
- Translate table headers and content
- Keep any data values, numbers, or identifiers as-is

**Markdown structure:**
- `#` for chapter title
- `##` for section headings
- `###` for subsection headings
- Match the heading hierarchy of the original book
- Use standard markdown for lists, code blocks, blockquotes, etc.

**Quotes and epigraphs:**
- Translate the quote text
- Keep the attribution in the original language (author name, book title)
- Format as blockquote: `> 翻譯的引言\n> ——Author Name, *Book Title*`

### Parallel Translation Strategy

Use the Agent tool to translate multiple chapters in parallel, with `model: "sonnet"` for every translator agent.

**For chapters that fit the threshold (under ~8,000 words)**, a single agent handles the whole chapter:

```
Agent prompt: "Translate Chapter N of <book-title> from English to Traditional Chinese.

EPUB path: <path>
Output file: <output-dir>/<filename>.md
Temp file: /tmp/ch<N>.txt

Translation rules:
[include the rules above]

Steps:
1. Read extracted text from /tmp/ch<N>.txt
2. Translate to Traditional Chinese following the rules
3. Write the complete translated chapter to <output-dir>/<filename>.md
4. Verify the file was written and is non-empty"
```

**For chapters that exceed the threshold (over ~8,000 words)**, split into multiple parts by section:

```
Agent prompt (one per part): "Translate Part M of Chapter N from English to Traditional Chinese.

EPUB path: <path>
Output file: <output-dir>/<chapter-base-name>-part<M>.md
Temp file: /tmp/ch<N>_part<M>.txt

This is part M of K total parts for this chapter. The output should:
- Start with `# Chapter Title - Part M` for parts 2+, or `# Chapter Title` for part 1
- Include a continuity note if this is not part 1: `> （接上一節）`
- Translate only the content from /tmp/ch<N>_part<M>.txt

Translation rules:
[include the rules above]

Steps:
1. Read extracted text from /tmp/ch<N>_part<M>.txt
2. Translate to Traditional Chinese
3. Write to <output-dir>/<chapter-base-name>-part<M>.md
4. Verify the file was written"
```

**Output file naming for split chapters:**
- Part 1: `05-chapter-title.md`
- Part 2: `05-chapter-title-part2.md`
- Part 3: `05-chapter-title-part3.md`

This keeps the first part as the "main" file while clearly labeling subsequent parts.

**Alternative: concatenate into one file** (avoids renumbering `part` files into one chapter later): translate each part to a temp file (`.tmp-<chapter>-part<M>.md`), then the orchestrator concatenates parts in order into the final `<chapter>.md` and deletes the temp files. **Compute split boundaries once in the orchestrator** — assign each agent an explicit non-overlapping section range. Letting translator agents negotiate boundaries with each other produced a duplicated-range conflict in practice.

**Assembly-seam check (mandatory for concatenated split chapters):** at each join, read 2-3 paragraphs before and after the seam against the source. Observed seam defects: duplicated characters (「的的」), dropped copulas (是), invented introductory paragraphs not in the source, punctuation style switching between halves (halfwidth vs fullwidth). Fix seams before final verification. Also verify `grep -c '^#'` parity chapter files vs source sections — the cheapest structural check for missing or duplicated sections.

## Step 4: Verify Completeness

After all chapters are translated:

1. **Count files**: Verify the expected number of `.md` files exist (include split parts)
2. **Check sizes**: Files should be non-empty and reasonably sized
3. **Spot-check sections**: For each file, verify that all major section headings from the original are present (`grep -c '^#'` parity against the source)
4. **Verify continuity**: For split chapters, check that part 2+ start with `> （接上一節）` continuity notes, and run the assembly-seam check
5. **Simplified-character scan**: the target is Traditional Chinese but agents leak simplified characters (observed: 本体、来、采取、个、轮、员工). Do NOT hand-roll a character set — hand-picked sets false-positive on shared chars (移/骨/送/群/台/准 are valid Traditional). Run the bundled simplified-exclusive check instead (needs `pip install --user opencc-python-reimplemented`):
   ```bash
   python3 <skill-dir>/scripts/scan_simplified.py <output-dir>/*.md   # prints file:line: 体→體 ...; exit 1 if any hit
   ```
6. **Term-consistency sweep**: grep every non-canonical term variant from Step 0 — count must be 0. Deterministic. Reserve LLM spot checks for semantic fidelity (mistranslation, reversed negation, invented content) which grep cannot catch.
7. **Report to user**: Show a summary table with file names and sizes

```bash
ls -lhS <output-dir>/
```

**Expected output pattern for split chapters:**
```
01-introduction.md          (complete chapter)
05-long-chapter.md          (part 1 of split chapter)
05-long-chapter-part2.md    (part 2 of split chapter)
05-long-chapter-part3.md    (part 3 of split chapter)
06-next-chapter.md          (complete chapter)
```

## Troubleshooting

**ebooklib installation fails**: Try `pip install --user ebooklib` or `pip install --break-system-packages ebooklib`

**EPUB has non-standard structure**: Some EPUBs use custom naming. List all items with `book.get_items()` and inspect `item.get_name()` to find the correct chapter files.

**Text extraction loses formatting**: Use BeautifulSoup to preserve heading hierarchy. Check for `<h1>` through `<h6>` tags and convert them to appropriate markdown headers.

**Chapter split produces too many parts**: If a chapter has many small sections, consider raising the split threshold (e.g., 10,000 or 12,000 words) or only splitting at `h1`/`h2` headings.

**Split chapter parts feel disjointed**: Ensure each part after part 1 starts with a continuity note `> （接上一節）`. For heavily interconnected content, consider translating the whole chapter in the main conversation instead of splitting.

**Missing sections in translation**: Compare the section headings in the translated file against the original EPUB's navigation document (NCX or NAV HTML). Re-extract and re-translate any missing sections.