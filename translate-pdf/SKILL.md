---
name: translate-pdf
description: >
  Translate an English PDF book into Traditional Chinese (繁體中文) markdown files, one file per chapter.
  Use when the user wants a book-length English PDF (or a long PDF with chapters/sections) translated
  into Traditional Chinese, in English or Chinese phrasing (e.g. 翻譯書籍、翻譯PDF).
  This skill handles the full pipeline: PDF text extraction, chapter detection, parallel translation, and
  quality verification.
---

# Translate English PDF Book to Traditional Chinese Markdown

This skill translates an entire English PDF book into per-chapter Traditional Chinese (繁體中文) markdown files. It handles books of any size by extracting text with PyMuPDF, planning chapter splits, and translating in parallel.

## Before You Start

### Ask the user these questions (if not already answered):

1. **Technical term format**: When a technical term first appears, should it be "中文翻譯（English Term）" or just the Chinese translation? (Default: "中文（English）" on first occurrence, then Chinese only)
2. **References**: Should chapter-end reference lists be included or omitted? (Default: omit, but keep inline citation numbers like [1], [2])
3. **Output directory**: Where should the translated files go? (Default: `zh-tw/` in the same directory as the PDF)
4. **Any chapters to skip?**: Sometimes the user only wants specific chapters.

### Check for Pre-extracted Text

Before touching the PDF, scan the project for already-extracted text (`.md`/`.txt` files matching the book's chapters). If present (e.g., the output of a prior markitdown/extract run), translate those files directly and skip PDF extraction entirely. Do not re-extract.

## Step 0: Build the Glossary FIRST (do not skip)

**This is the single highest-leverage step.** Parallel translation agents will independently coin different Chinese terms for the same English term (observed in practice: one book produced three renderings of "thesaurus" — 同義詞庫/索引典/同義詞典 — plus divergent reasoner/semantics/linked-data/metadata terms). Unifying them afterwards costs more than the translation itself.

Before launching any translation agent:

1. Extract the book's core technical terms and their standard Chinese renderings. Sources: the book's own glossary/index (best), TOC, plus domain-standard translations. If a Traditional Chinese glossary file is among the outputs (e.g. `glossary.md` is ALSO being translated), translate it first and use its renderings as canonical.
2. Write the glossary as an en→zh table (json or md), e.g. `ontology=本體論, taxonomy=分類法, thesaurus=同義詞庫, metadata=詮釋資料, knowledge graph=知識圖譜, ...` (30-70 terms typical).
3. **Inject the full glossary into every translator agent's prompt** with the rule: "Use these exact renderings. Do not coin alternatives. If a term is missing, keep the English and note it."
4. **Proper-noun exemption list**: established proper-noun translations (e.g. Getty AAT＝藝術與建築索引典) stay as-is and are exempt from term unification. List them explicitly so later sed passes don't clobber them.
5. Term unification after the fact, if still needed: decide by **majority vote via grep count across all translated files** (`grep -o "<term>" *.md | wc -l`), then `sed -i 's/舊譯/標準譯/g' *.md`, then verify grep count is zero. Deterministic and cheap — prefer this over LLM debate.

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
- Fenced code blocks are **verbatim** — do NOT translate code content, strings, or language tags (observed failure mode: Turtle translated into Chinese while leaving `@en` language tags, corrupting the RDF). Only code comments may be translated.
- Translate all surrounding explanation text

**Punctuation (state this in every translator agent prompt):**
- Chinese prose uses fullwidth punctuation: ，：（）；？！「」
- Code blocks, CSV example data, URLs, standard codes (ISO 8601, Z39.19), English table content, and English-only list items keep halfwidth punctuation
- Without this rule, different agents pick different styles and the fix afterwards costs hundreds of lines per chapter

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

Use the Agent tool to translate multiple chapters in parallel, with `model: "sonnet"` for every translator agent. Each agent handles one chapter (or two small chapters).

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

### Split-Chapter Orchestration (assigned ranges, no negotiation)

When a chapter is split across multiple agents, the orchestrator (not the agents) computes the split points and assigns each agent an **explicit, non-overlapping line range** ending at a `###` section boundary. Letting agents negotiate boundaries with each other produced a duplicated-range conflict in practice. Each agent translates exactly `[start_line, end_line]` of the source into a temp file (`.tmp-<chapter>-<part>.md`); the orchestrator then concatenates in order and deletes the temp files.

## Step 4: Verify Completeness

After all chapters are translated:

1. **Count files**: Verify the expected number of `.md` files exist
2. **Check sizes**: Files should be non-empty and reasonably sized (a 30-page chapter typically produces 40-80 KB of Chinese markdown)
3. **Heading-count parity**: `grep -c '^#' source.md` must equal `grep -c '^#' translated.md` for every file. This is the cheapest structural check — it caught assembling errors that prose review missed. (Beware `#` comment lines inside code blocks inflating counts on the translated side; compare section titles, not raw counts, if unsure.)
4. **Assembly-seam check** (split chapters only): at each join, read 2-3 paragraphs before and after the seam against the source. Typical seam defects observed in practice: duplicated characters/words (「的的」), dropped copulas (「X 是 Y」 losing 是), an agent inventing an extra introductory paragraph the source doesn't have, punctuation style switching between halves. Fix seams before anything else.
5. **Simplified-character scan**: the target is Traditional Chinese but agents leak simplified characters (observed: 本体、來/来、採取/采取、個/个、輪/轮、員工/员工). Do NOT hand-roll a character set for this — hand-picked sets produce false positives because many chars are shared between scripts (移/骨/送/群/台/准 are all valid Traditional). Use a simplified-exclusive check or OpenCC s2t round-trip instead:
   ```bash
   python3 -c "import opencc" 2>/dev/null || pip install --user opencc-python-reimplemented
   python3 <skill-dir>/scripts/scan_simplified.py <output-dir>/*.md   # prints file:line: 体→體 ...; exit 1 if any hit
   ```
   The script flags only simplified-exclusive characters (from OpenCC's dictionary), so shared chars like 台/准/里/群 are not reported.
6. **Term-consistency sweep**: `grep -o "<banned-variant>" *.md | wc -l` must be 0 for every non-canonical term from Step 0. This is deterministic; LLM verification adds little here. Reserve LLM/judge agents for what grep can't do: semantic-fidelity spot checks (compare 5-10 paragraphs per file against the source for mistranslation, reversed negation, invented content).
7. **Report to user**: Show a summary table with file names and sizes

```bash
ls -lhS <output-dir>/
```

## Troubleshooting

**PyMuPDF installation fails**: Try `pip install --user PyMuPDF` or `pip install --break-system-packages PyMuPDF`

**Agent produces no output**: The chapter is too large for a single agent's context. Split it into smaller pieces or translate manually.

**PDF text extraction is garbled**: Some PDFs use non-standard encoding. Try `page.get_text("text")` or `page.get_text("dict")` for more structured extraction. If the PDF is scanned images, OCR would be needed (out of scope for this skill).

**Missing sections in translation**: Compare the section headings in the translated file against the original PDF's table of contents. Re-extract and re-translate any missing sections.
