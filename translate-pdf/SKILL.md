---
name: translate-pdf
description: >
  Translate an English PDF book into Traditional Chinese (繁體中文) markdown files, one file per chapter.
  Use this skill whenever the user wants to translate a PDF book (or large PDF document with chapters/sections)
  into Traditional Chinese markdown. Also trigger when the user mentions: 翻譯書籍、翻譯PDF、英文書翻中文、
  書籍翻譯成繁體中文、translate book to Chinese, or similar requests involving book-length PDF translation.
  This skill handles the full pipeline: PDF text extraction, chapter detection, parallel translation, and
  quality verification.
context: fork
---

# Translate English PDF Book to Traditional Chinese Markdown

This skill translates an entire English PDF book into per-chapter Traditional Chinese (繁體中文) markdown files. It handles books of any size by extracting text with PyMuPDF, planning chapter splits, and translating in parallel.

## Before You Start

### Ask the user these questions (if not already answered):

1. **Technical term format**: When a technical term first appears, should it be "中文翻譯（English Term）" or just the Chinese translation? (Default: "中文（English）" on first occurrence, then Chinese only)
2. **References**: Should chapter-end reference lists be included or omitted? (Default: omit, but keep inline citation numbers like [1], [2])
3. **Output directory**: Where should the translated files go? (Default: `zh-tw/` in the same directory as the PDF)
4. **Any chapters to skip?**: Sometimes the user only wants specific chapters.

## Step 1: Extract the Book Structure

The PDF `Read` tool is limited to 20 pages per request, and `pdftoppm` may not be installed. Use PyMuPDF (`fitz`) to extract text reliably.

First, install PyMuPDF if needed:

```bash
pip install --break-system-packages PyMuPDF 2>/dev/null || pip install PyMuPDF
```

Then extract the table of contents and identify chapter boundaries:

```python
import fitz

doc = fitz.open("<path-to-pdf>")
toc = doc.get_toc()  # Returns [[level, title, page_number], ...]
print(f"Total pages: {len(doc)}")
for entry in toc:
    print(f"  Level {entry[0]}: {entry[1]} — page {entry[2]}")
```

If the TOC is empty or incomplete, scan page text for chapter headings (look for patterns like "Chapter 1", "CHAPTER 1", or large font text). Build a chapter map:

| File name | Chapter title | Start page | End page | Page count |
|-----------|--------------|------------|----------|------------|

## Step 2: Create a Translation Plan

Present the chapter map to the user and confirm before proceeding. The plan should include:

- Output file naming convention (e.g., `00-preface.md`, `01-chapter-title.md`, `glossary.md`)
- Estimated batch count per chapter (20 pages per batch for text extraction)
- Which chapters are large (50+ pages) and may need special handling

Create the output directory:

```bash
mkdir -p <output-directory>
```

## Step 3: Translate Each Chapter

### Text Extraction

For each chapter, extract text in batches of ~20-25 pages using PyMuPDF:

```python
import fitz

doc = fitz.open("<path-to-pdf>")
text = ""
for page_num in range(start_page - 1, end_page):  # fitz uses 0-indexed pages
    page = doc[page_num]
    text += f"\n--- PAGE {page_num + 1} ---\n"
    text += page.get_text()
```

Write extracted text to a temp file (e.g., `/tmp/ch<N>_part<M>.txt`), then read it into context for translation.

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
- Keep code in the original language (English)
- Translate code comments into Chinese
- Translate all surrounding explanation text

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

Use the Agent tool to translate multiple chapters in parallel. Each agent handles one chapter (or two small chapters).

**For chapters under ~40 pages**, a single agent can handle extraction + translation:

```
Agent prompt: "Translate Chapter N of <book-title> (pages X to Y) from English to Traditional Chinese.

PDF path: <path>
Output file: <output-dir>/<filename>.md

Translation rules:
[include the rules above]

Steps:
1. Use Python with fitz to extract text from pages X to Y, write to /tmp/chN.txt
2. Read the extracted text
3. Translate to Traditional Chinese following the rules
4. Write the complete translated chapter to the output file
5. Verify the file was written and is non-empty"
```

**For chapters over ~40 pages**, the agent's context window may fill up before it finishes writing. Two strategies:

1. **Split into sub-agents**: Have one agent handle pages X to X+20 and another handle X+21 to Y, then combine
2. **Write incrementally**: Instruct the agent to extract and translate in smaller batches, appending to the output file after each batch
3. **Manual fallback**: For very large chapters (60+ pages), extract text to temp files and translate in the main conversation

Experience shows that agents translating 50+ pages of dense technical content often exhaust their context window. If an agent completes without producing output, fall back to manual translation in the main conversation.

## Step 4: Verify Completeness

After all chapters are translated:

1. **Count files**: Verify the expected number of `.md` files exist
2. **Check sizes**: Files should be non-empty and reasonably sized (a 30-page chapter typically produces 40-80 KB of Chinese markdown)
3. **Spot-check sections**: For each file, verify that all major section headings from the original are present
4. **Report to user**: Show a summary table with file names and sizes

```bash
ls -lhS <output-dir>/
```

## Troubleshooting

**PyMuPDF installation fails**: Try `pip install --user PyMuPDF` or `pip install --break-system-packages PyMuPDF`

**Agent produces no output**: The chapter is too large for a single agent's context. Split it into smaller pieces or translate manually.

**PDF text extraction is garbled**: Some PDFs use non-standard encoding. Try `page.get_text("text")` or `page.get_text("dict")` for more structured extraction. If the PDF is scanned images, OCR would be needed (out of scope for this skill).

**Missing sections in translation**: Compare the section headings in the translated file against the original PDF's table of contents. Re-extract and re-translate any missing sections.
