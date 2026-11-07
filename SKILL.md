---
name: anime-data-manager
description: >-
  Manage, link, merge, complete multilingual titles, and auto-review Project Yuki (有希计划)
  anime and platform mapping data via the local Admin CLI (`pjyk_admin.py`).
  Activate this skill whenever the user asks to process, review, link, merge, translate,
  or inspect anime/mapping data in the admin backend.
---

# Project Yuki Anime Data Manager Skill

This skill equips you to manage Project Yuki's anime and external platform mapping data (`Bangumi`, `AniList`, `MyAnimeList`) by invoking the zero-dependency local CLI [`pjyk_admin.py`](./pjyk_admin.py), which talks to the Spring Boot Admin REST API (`/api/admin/*`).

---

## 1. CLI Quick Reference

Always invoke the CLI directly with `python3 pjyk_admin.py` from the CLI repository root:

### Read / Inspect Commands
```bash
# 1. Check overall or seasonal counts of PENDING/APPROVED/REJECTED animes & unlinked mappings
python3 pjyk_admin.py status
python3 pjyk_admin.py status --year 2026 --season SPRING

# 2. Dump compact JSON of animes + unlinked mappings (omits coverImage URLs to save tokens)
python3 pjyk_admin.py dump --status PENDING --year 2026 --season SPRING
python3 pjyk_admin.py dump --status ALL --year 2026 --season SPRING --no-unlinked

# 3. Search animes or unlinked mappings by keyword
python3 pjyk_admin.py animes --status ALL --keyword "芙莉莲"
python3 pjyk_admin.py unlinked --keyword "Frieren"
```

### Single-Item Write Commands
```bash
# Update an anime's status, titles (partial update preserves existing title fields), or startDate
python3 pjyk_admin.py update-anime <animeId> --status APPROVED --title-cn "中文标题"

# Link or unlink a mapping
python3 pjyk_admin.py link-mapping <mappingId> --anime-id <animeId>
python3 pjyk_admin.py link-mapping <mappingId> --unlink

# Merge duplicate animes (moves all mappings from source to target, then deletes source)
python3 pjyk_admin.py merge-anime <targetAnimeId> <sourceAnimeId>
```

### Batch Write Command (`apply`) — Preferred for Multi-Item Processing
When executing multiple operations, write a JSON plan file to `<appDataDir>/brain/<conversation-id>/scratch/plan.json` (or `/tmp/pjyk_plan.json`) using `write_file` and run:
```bash
# Preview batch plan (Dry-Run)
python3 pjyk_admin.py apply --file /tmp/pjyk_plan.json --dry-run

# Execute batch plan
python3 pjyk_admin.py apply --file /tmp/pjyk_plan.json
```

---

## 2. Batch Plan JSON Schema (`apply --file`)

The JSON file passed to `apply --file` can be a JSON array of action objects (or `{"actions": [...]}`). Supported `op` types:

```json
[
  {
    "op": "link_mapping",
    "mappingId": 501,
    "animeId": 102,
    "reason": "Unlinked MAL mapping matches native title and start date of Anime 102"
  },
  {
    "op": "merge_animes",
    "targetAnimeId": 102,
    "sourceAnimeId": 108,
    "deleteSource": true,
    "reason": "Anime 102 (Bangumi) and Anime 108 (AniList) are the same TV season"
  },
  {
    "op": "update_anime",
    "animeId": 102,
    "title": {
      "titleCn": "葬送的芙莉莲 第二季",
      "titleNative": "葬送のフリーレン 第2期",
      "titleRomaji": "Sousou no Frieren 2nd Season",
      "titleEn": "Frieren: Beyond Journey's End Season 2"
    },
    "reviewStatus": "APPROVED",
    "reason": "All 3 platforms matched consistently; completed 4-language titles and approved"
  },
  {
    "op": "create_anime",
    "title": {
      "titleCn": "某部新番",
      "titleNative": "ある新作アニメ"
    },
    "startDate": "2026-04-05",
    "mappingIds": [509, 510],
    "reason": "Created new anime for orphaned mappings 509 and 510"
  },
  {
    "op": "delete_anime",
    "animeId": 199,
    "reason": "Empty duplicate shell with no mappings"
  },
  {
    "op": "create_mapping",
    "platform": "Bangumi",
    "platformId": "456789",
    "animeId": 102,
    "reason": "Fetched and linked missing Bangumi subject"
  },
  {
    "op": "delete_mapping",
    "mappingId": 999,
    "reason": "Invalid/duplicate mapping"
  }
]
```

Use an explicit `"animeId": null` to unlink a mapping. For merges, `deleteSource` takes a JSON boolean and defaults to true. Dry-run validates the entire plan locally. Execution makes separate API writes. After a failure, inspect the result IDs and current server state before retrying the remaining steps.

> **Note on `merge_animes` + `update_anime` ordering**:
> When linking or merging mappings into `targetAnimeId`, the backend's `AnimeAggregationService` automatically re-aggregates `targetAnime`'s titles and cover image from its mappings. Therefore, always place `link_mapping` and `merge_animes` **before** `update_anime` for the same `animeId` in the `actions` array so your final `update_anime` title/status adjustments take precedence!

---

## 3. Standard Operating Procedure (SOP) & Domain Rules

When asked to automatically process anime data (e.g., for a given year/season or all `PENDING` items), follow this 4-step workflow:

### Step 1: Dump Data
Run `python3 pjyk_admin.py dump --status PENDING` (with `--year` and `--season` if specified). If you also need to check whether unlinked mappings or duplicate `PENDING` animes belong to an already `APPROVED` anime in the same season, also inspect `--status APPROVED` for that season.

### Step 2: Analyze & Classify (4 Core AI Scenarios)

1. **Smart Mapping Linking (`link_mapping` / `create_anime`)**:
   * Match `unlinkedMappings` against existing animes by comparing `title.native`, `title.romaji`, `title.en`, `title.cn`, and `startDate`.
   * **Date Tolerance**: Advance screenings (先行放送) or timezone differences across Japan/global streaming often cause `startDate` differences of 1–14 days between Bangumi, AniList, and MyAnimeList. Treat them as the same work if the titles and season/format match.
   * **Strict Anti-Collision Rules (CRITICAL)**:
     * **NEVER** merge different seasons/cours (e.g., `Season 1` vs `Season 2`, `Part 1` vs `Part 2`, `第1期` vs `第2期`) into the same Anime.
     * **NEVER** merge TV series with Movies (`劇場版`), OVAs, OADs, Recap specials (`総集編`), or Mini-animes (`ミニアニメ`).
     * Each `Anime` can have **at most 1 Mapping per Platform** (`Bangumi`, `AniList`, `MyAnimeList`).

2. **Duplicate Anime Deduplication (`merge_animes`)**:
   * Because the backend's rule-based linker only matches within `±1` day and Jaro-Winkler `>= 0.95` on `titleNative`, a single work often gets split into two `PENDING` animes (e.g., one with a Bangumi mapping, another with AniList + MAL mappings).
   * When two `PENDING` animes represent the exact same work/season and have disjoint platforms, merge the secondary one into the primary one using `merge_animes`.

3. **Multilingual Title Completion & Normalization (`update_anime`)**:
   * Ensure each anime has clean, accurate titles across all 4 fields (`titleCn`, `titleNative`, `titleRomaji`, `titleEn`) whenever possible:
     * `titleCn`: Standard Simplified Chinese (简体中文) title commonly used on Bangumi/Chinese anime communities. Convert accidental Traditional Chinese to Simplified Chinese.
     * `titleNative`: Official Japanese (or original language) title.
     * `titleRomaji`: Standard Hepburn romaji title.
     * `titleEn`: Official English title (or standard romaji fallback if no official English title exists).

4. **Confidence-Based Auto-Review (`reviewStatus: "APPROVED"` vs `PENDING`)**:
   * **High Confidence → Automatically set `reviewStatus: "APPROVED"`**:
     * All linked mappings clearly refer to the exact same anime & season/format with consistent start dates;
     * No conflicting platform mappings;
     * Essential metadata (`titleNative`, `titleCn`, `startDate`) is present and verified.
   * **Low Confidence / Ambiguous → Keep `reviewStatus: "PENDING"` for Human Review**:
     * Conflicting start dates (e.g., months apart without an obvious advance-screening explanation);
     * Suspected mix-up between Season 1 / Season 2 / OVA / Movie;
     * Obscure/indie entry with only 1 platform mapping, missing `startDate`, or unrecognizable title where you cannot verify its identity with high confidence.

### Step 3: Apply Batch Changes
Write all high-confidence actions (`link_mapping` → `merge_animes` → `update_anime`) into a JSON file and run `python3 pjyk_admin.py apply --file <path>`.

### Step 4: Report Summary & Human Review Queue
Present a concise summary to the user:
* **Executed Automatically**: Count and brief list of linked mappings, merged animes, completed titles, and auto-approved animes.
* **Pending Human Review (低置信度待人工复核)**: A clear table or bullet list of `animeId` / `mappingId` items left in `PENDING`, explaining the exact ambiguity or risk for each.
