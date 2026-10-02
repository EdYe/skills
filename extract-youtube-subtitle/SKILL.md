---
name: extract-youtube-subtitle
description: >
  YouTube 字幕翻譯成繁體中文 markdown。Use when the user gives a YouTube URL and wants its subtitles in Chinese.
context: fork
---

# YouTube 字幕 → 繁體中文 Markdown

`scripts/yt_subs.py`（位於本 skill 的 base directory）負責所有確定性工作：選字幕軌、下載、切段落、切 chunk、合併與驗證。你只負責翻譯。

每個段落都以一行**時間戳錨點**開頭，例如 `[00:01:23](https://youtu.be/ID?t=83)`。錨點是翻譯與合併之間的契約：`merge` 會逐一比對，少一個就拒絕產出。

## Step 1：fetch

```bash
python3 <skill-dir>/scripts/yt_subs.py fetch "<YouTube URL>" --out <工作目錄>
```

預設工作目錄是 `./yt-<video id>`。script 印出 JSON，記下 `workdir`、`mode`、`chunks`、`kind`。

選軌順序（script 自動決定）：人工繁中 → 人工簡中 → 人工原文 → 原文自動字幕（`<lang>-orig`，有 AI 配音的影片會挑影片原語言那一軌）→ **語音轉錄**。YouTube 的機器翻譯軌一律不用。

**語音轉錄備用流程**：影片完全沒有字幕時，script 自動下載原語言音軌，用 whisper.cpp（`whisper-cli`）轉錄，`kind=transcribed`。也可加 `--transcribe` 強制轉錄（例如自動字幕品質太差時）。

- 需要 `brew install whisper-cpp`；沒裝時 script 會報錯並提示安裝指令。
- 模型預設 `large-v3-turbo`（約 1.6 GB），第一次使用時自動下載到 `~/.cache/whisper-cpp/`；可用 `--whisper-model base`（約 150 MB，較快但較不準）或指定 `.bin` 路徑。
- 第一次轉錄要下載模型再跑完整支影片，可能超過前景指令的時間上限：fetch 一律用 Bash 的 `run_in_background: true` 執行，等完成通知再讀輸出（有字幕時幾秒就結束，沒有額外成本）。

**完成條件**：`<workdir>/source/` 內有 `chunks` 個 `NN.md`，`translated/` 目錄存在。

## Step 2：翻譯每個 chunk

依 `mode` 處理每個 `source/NN.md`，寫到同名的 `translated/NN.md`：

| mode | 做法 |
|------|------|
| `translate` | 翻成繁體中文 |
| `to-trad` | 簡體轉繁體，並把用語改成台灣慣用詞 |
| `copy` | 原文已是繁中，fetch 已預先複製到 `translated/`：只修標點與斷句 |

`kind=transcribed` 的中文影片一律是 `to-trad`，因為 Whisper 常輸出簡體或繁簡混雜。

chunk 超過 3 個時，用 Agent tool 平行處理，每個 agent 負責一個 chunk，prompt 附上下方規則。

翻譯規則：

- **錨點行原樣保留**，一字不改、不增不刪，順序不變；每個錨點下面接該段譯文。
- 譯文要是通順的中文段落，補上標點。`kind=auto` 的自動字幕沒有標點，句子常被段落切斷：把被切斷的半句移到相鄰段落接完整，錨點位置不動。
- chunk 開頭或結尾的半句，讀相鄰 chunk 的頭尾來接完整意思，譯文仍各自留在原本的 chunk。
- 刪掉語助詞（uh、um、you know）和 `[Music]`、`[Applause]` 這類音效標記；音效對理解有幫助時改寫成 `（掌聲）`。
- 專有名詞第一次出現時寫成「中文（English）」，之後只用中文；人名、品牌、產品名保留原文。
- 自動字幕與語音轉錄（`kind=auto` / `transcribed`）的明顯聽寫錯誤，依上下文更正，例如把 "cloud code" 改回 "Claude Code"。轉錄稿通常已有標點，但段落仍可能切在半句。

**完成條件**：每個 `source/NN.md` 都有對應的 `translated/NN.md`，全文為繁體中文。

## Step 3：merge

```bash
python3 <skill-dir>/scripts/yt_subs.py merge <workdir>
```

**完成條件**：輸出 `OK: ... 0 missing`。若輸出 `MERGE FAILED`，依清單補上缺漏的錨點或 chunk，再跑一次 merge，直到 OK。

把最終檔路徑（`<workdir>/<影片標題>.zh-TW.md`）告訴使用者，附上字幕來源（人工、自動或語音轉錄）。

## Troubleshooting

- **yt-dlp 報錯或抓不到字幕**：先更新 `pip install -U yt-dlp`（或 `brew upgrade yt-dlp`），YouTube 改版後舊版常會失效。
- **Sign in to confirm you're not a bot / HTTP 429**：加上 `--cookies-from-browser chrome`。
- **想用別的字幕軌**：`yt-dlp --list-subs <URL>` 查 key，再用 `fetch --track <key>` 指定。
- **chunk 太大或太小**：調整 `--chunk-chars`（預設 8000 個原文字元）。
- **影片沒有任何字幕**：script 自動改走語音轉錄。若報 `whisper-cli is missing`，請使用者執行 `brew install whisper-cpp` 後重跑 fetch。
- **下載音訊 HTTP 403**：yt-dlp 太舊，先升級（見第一條）。
