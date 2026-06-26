from __future__ import annotations

import difflib
import hashlib
import html
import json
import os
import posixpath
import random
import re
import shutil
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from mdx_reader import MdxDictionary


ROOT = Path(__file__).resolve().parent
WORKBOOK = ROOT / "organized_vocabulary_notes.xlsx"
CACHE_FILE = ROOT / "definitions_cache.json"
WRONG_FILE = ROOT / "wrong_answers.json"
PROGRESS_FILE = ROOT / "progress.json"
PROGRESS_BACKUP_FILE = ROOT / "progress.backup.json"
STATIC_DIR = ROOT / "static"
LOCAL_OXFORD_MDX = Path(
    os.environ.get(
        "LOCAL_OXFORD_MDX",
        r"C:\Users\eason\Desktop\package\oxford\牛津9英英(推荐)\Oxford ALD_9th_En-En.mdx",
    )
)
LOCAL_OXFORD_INDEX = ROOT / "oxford_mdx_index.json"
LOCAL_LONGMAN_MDX = Path(
    os.environ.get(
        "LOCAL_LONGMAN_MDX",
        r"C:\Users\eason\Desktop\package\longmang\朗文当代6英英(推荐\longman_dictionary_of_contemporary_english_6th_edition.mdx",
    )
)
LOCAL_LONGMAN_INDEX = ROOT / "longman_mdx_index.json"
LOCAL_LONGMAN_PHRASAL_MDX = Path(
    os.environ.get(
        "LOCAL_LONGMAN_PHRASAL_MDX",
        r"C:\Users\eason\Desktop\package\longmang\Longman Phrasal Verbs Dictionary 2nd Edition\[英-英] Longman Phrasal Verbs Dictionary 2nd Edition.mdx",
    )
)
LOCAL_LONGMAN_PHRASAL_INDEX = ROOT / "longman_phrasal_mdx_index.json"

NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

POS_NAMES = {
    "n": "noun",
    "v": "verb",
    "adj": "adjective",
    "adv": "adverb",
}

OXFORD_APP_ID = os.environ.get("OXFORD_APP_ID", "").strip()
OXFORD_APP_KEY = os.environ.get("OXFORD_APP_KEY", "").strip()
OXFORD_LANGUAGE = os.environ.get("OXFORD_LANGUAGE", "en-us").strip() or "en-us"
OXFORD_BASE_URL = "https://od-api.oxforddictionaries.com/api/v2"
WIKTIONARY_DICTIONARY_BASE_URL = "https://freedictionaryapi.com/api/v1/entries/en"
FREE_DICTIONARY_BASE_URL = "https://api.dictionaryapi.dev/api/v2/entries/en"
LOCAL_OXFORD = MdxDictionary(LOCAL_OXFORD_MDX, LOCAL_OXFORD_INDEX)
LOCAL_LONGMAN = MdxDictionary(LOCAL_LONGMAN_MDX, LOCAL_LONGMAN_INDEX)
LOCAL_LONGMAN_PHRASAL = MdxDictionary(LOCAL_LONGMAN_PHRASAL_MDX, LOCAL_LONGMAN_PHRASAL_INDEX)
FILE_WRITE_LOCK = threading.RLock()


@dataclass
class VocabRow:
    source_sheet: str
    row: int
    category: str
    word: str
    pos: str
    chinese: str
    note: str


def col_to_idx(ref: str) -> int | None:
    match = re.match(r"([A-Z]+)", ref or "")
    if not match:
        return None
    n = 0
    for ch in match.group(1):
        n = n * 26 + ord(ch) - 64
    return n


def text_of(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return "".join(node.itertext())


def resolve_xl_target(target: str) -> str:
    target = target.lstrip("/")
    if target.startswith("xl/"):
        return target
    return posixpath.normpath(posixpath.join("xl", target))


def read_xlsx(path: Path) -> dict[str, list[tuple[int, dict[int, str]]]]:
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("main:si", NS):
                shared.append("".join(t.text or "" for t in si.findall(".//main:t", NS)))

        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rid_to_target = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

        sheets: dict[str, list[tuple[int, dict[int, str]]]] = {}
        for sheet in workbook.findall("main:sheets/main:sheet", NS):
            title = sheet.attrib["name"]
            rid = sheet.attrib.get(f"{{{NS['rel']}}}id")
            if not rid:
                continue
            sheet_xml = ET.fromstring(zf.read(resolve_xl_target(rid_to_target[rid])))
            rows: list[tuple[int, dict[int, str]]] = []
            for row in sheet_xml.findall(".//main:sheetData/main:row", NS):
                rownum = int(row.attrib.get("r", "0"))
                values: dict[int, str] = {}
                for cell in row.findall("main:c", NS):
                    col = col_to_idx(cell.attrib.get("r", ""))
                    if not col:
                        continue
                    typ = cell.attrib.get("t")
                    value = ""
                    if typ == "inlineStr":
                        value = text_of(cell.find("main:is", NS))
                    else:
                        v = cell.find("main:v", NS)
                        if v is not None and v.text is not None:
                            if typ == "s":
                                try:
                                    value = shared[int(v.text)]
                                except (ValueError, IndexError):
                                    value = v.text
                            else:
                                value = v.text
                    value = str(value).strip()
                    if value:
                        values[col] = value
                if values:
                    rows.append((rownum, values))
            sheets[title] = rows
        return sheets


def is_vocab_sheet(title: str, rows: list[tuple[int, dict[int, str]]]) -> bool:
    if "review" in title.lower() or "summary" in title.lower():
        return False
    if not rows:
        return False
    header = {v.lower(): k for k, v in rows[0][1].items()}
    return "word / phrase" in header and "chinese meaning" in header


def load_vocab_rows() -> list[VocabRow]:
    sheets = read_xlsx(WORKBOOK)
    output: list[VocabRow] = []
    for title, rows in sheets.items():
        if not is_vocab_sheet(title, rows):
            continue
        for rownum, values in rows[1:]:
            word = values.get(2, "").strip()
            if not word:
                continue
            output.append(
                VocabRow(
                    source_sheet=title,
                    row=rownum,
                    category=values.get(1, "").strip(),
                    word=word,
                    pos=values.get(3, "").strip(),
                    chinese=values.get(4, "").strip(),
                    note=values.get(5, "").strip(),
                )
            )
    return output


def split_senses(chinese: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[;；]", chinese or "") if p.strip()]
    return parts or [chinese.strip()]


def split_answer_variants(word: str) -> list[str]:
    # Split explicit word-form alternatives such as "focus / foci", but keep
    # compact phrase text such as "good/bad news" together.
    parts = [p.strip() for p in re.split(r"\s+/\s+", word) if p.strip()]
    return parts or [word.strip()]


def lookup_word(word: str) -> str:
    first = split_answer_variants(word)[0]
    first = re.sub(r"\([^)]*\)", "", first).strip()
    return first


def pos_labels(pos: str) -> list[str]:
    labels: list[str] = []
    for chunk in re.split(r"[/\s.]+", pos.lower()):
        chunk = chunk.strip()
        if chunk in POS_NAMES:
            labels.append(POS_NAMES[chunk])
        elif chunk in POS_NAMES.values():
            labels.append(chunk)
    return labels


def item_id(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def relatedness(a: str, b: str) -> float:
    a = a.lower()
    b = b.lower()
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    common = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        common += 1
    prefix_bonus = min(common, 6) / 20
    return ratio + prefix_bonus


def choice_score(item: dict[str, Any], candidate: dict[str, Any]) -> float:
    score = relatedness(item["display_word"], candidate["display_word"])
    if item["category"] == candidate["category"]:
        score += 0.35
    if set(item["pos_labels"]) & set(candidate["pos_labels"]):
        score += 0.25
    if item["meaning"] and candidate["meaning"]:
        if item["meaning"][0] == candidate["meaning"][0]:
            score += 0.05
    return score


def build_meaning_items(rows: list[VocabRow]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_words: set[str] = set()
    for row in rows:
        canonical_word = lookup_word(row.word).lower()
        if canonical_word in seen_words:
            continue
        seen_words.add(canonical_word)
        variants = split_answer_variants(row.word)
        items.append(
            {
                "id": item_id("mc", canonical_word),
                "type": "multiple_choice",
                "source_sheet": row.source_sheet,
                "row": row.row,
                "category": row.category,
                "word": row.word,
                "display_word": row.word,
                "lookup_word": lookup_word(row.word),
                "accepted_answers": variants,
                "pos": row.pos,
                "pos_labels": pos_labels(row.pos),
                "meaning": row.chinese,
                "sense_index": 0,
                "note": row.note,
            }
        )
    return items


def add_choices(items: list[dict[str, Any]]) -> None:
    for item in items:
        all_candidates = [
            c
            for c in items
            if c["id"] != item["id"] and c["display_word"].lower() != item["display_word"].lower()
        ]
        same_pos = lambda c: bool(set(item["pos_labels"]) & set(c["pos_labels"])) or item["pos"] == c["pos"]
        pools = [
            [c for c in all_candidates if c["category"] == item["category"] and same_pos(c)],
            [c for c in all_candidates if c["category"] == item["category"]],
            [c for c in all_candidates if same_pos(c)],
            all_candidates,
        ]
        candidates: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for pool in pools:
            pool.sort(key=lambda c: choice_score(item, c), reverse=True)
            for candidate in pool:
                if candidate["id"] not in seen_ids:
                    candidates.append(candidate)
                    seen_ids.add(candidate["id"])
                if len(candidates) >= 32:
                    break
            if len(candidates) >= 8:
                break
        top = candidates[:24]
        rng = random.Random(int(item["id"][:8], 16))
        selected = top[:4]
        if len(selected) < 4:
            selected = candidates[:4]
        choices = [item["display_word"]] + [c["display_word"] for c in selected[:4]]
        deduped: list[str] = []
        for choice in choices:
            if choice.lower() not in {c.lower() for c in deduped}:
                deduped.append(choice)
        while len(deduped) < 5:
            fallback = rng.choice(candidates)["display_word"]
            if fallback.lower() not in {c.lower() for c in deduped}:
                deduped.append(fallback)
        rng.shuffle(deduped)
        item["choices"] = deduped[:5]


def note_form_questions(rows: list[VocabRow]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    pattern = re.compile(r"\b(plural|noun|verb|adjective|adverb)\s*:\s*([A-Za-z][A-Za-z -]*)", re.I)
    for row in rows:
        for label, answer in pattern.findall(row.note or ""):
            answer = answer.strip().split("/")[0].strip()
            if not answer or answer.lower() == row.word.lower():
                continue
            questions.append(
                form_item(
                    row=row,
                    source_word=lookup_word(row.word),
                    source_pos=row.pos,
                    target_pos=label.lower(),
                    answer=answer,
                    reason="note",
                )
            )
    return questions


def slash_form_questions(rows: list[VocabRow]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for row in rows:
        variants = split_answer_variants(row.word)
        if len(variants) < 2:
            continue
        first = variants[0]
        for target in variants[1:]:
            target_pos = "related form"
            if target.endswith("s") or target.endswith("i") or target.endswith("ae"):
                target_pos = "plural"
            questions.append(
                form_item(
                    row=row,
                    source_word=first,
                    source_pos=row.pos,
                    target_pos=target_pos,
                    answer=target,
                    reason="variant",
                )
            )
    return questions


def family_form_questions(rows: list[VocabRow]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    by_meaning: dict[str, list[VocabRow]] = {}
    for row in rows:
        for sense in split_senses(row.chinese):
            by_meaning.setdefault(sense, []).append(row)

    seen: set[tuple[str, str, str]] = set()
    for group in by_meaning.values():
        if len(group) < 2:
            continue
        for source in group:
            for target in group:
                if source.word.lower() == target.word.lower():
                    continue
                source_labels = pos_labels(source.pos)
                target_labels = pos_labels(target.pos)
                if not source_labels or not target_labels:
                    continue
                if set(source_labels) == set(target_labels):
                    continue
                if relatedness(source.word, target.word) < 0.58:
                    continue
                target_pos = target_labels[0]
                key = (source.word.lower(), target.word.lower(), target_pos)
                if key in seen:
                    continue
                seen.add(key)
                questions.append(
                    form_item(
                        row=source,
                        source_word=lookup_word(source.word),
                        source_pos=source.pos,
                        target_pos=target_pos,
                        answer=lookup_word(target.word),
                        reason="family",
                    )
                )
    return questions


def form_item(
    row: VocabRow,
    source_word: str,
    source_pos: str,
    target_pos: str,
    answer: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "id": item_id("form", row.source_sheet, row.row, source_word, target_pos, answer, reason),
        "type": "word_form",
        "source_sheet": row.source_sheet,
        "row": row.row,
        "category": row.category,
        "source_word": source_word,
        "source_pos": source_pos,
        "target_pos": target_pos,
        "answer": answer,
        "accepted_answers": [answer],
        "meaning": row.chinese,
        "note": row.note,
        "reason": reason,
    }


def build_items() -> list[dict[str, Any]]:
    rows = load_vocab_rows()
    meaning_items = build_meaning_items(rows)
    add_choices(meaning_items)

    form_items = note_form_questions(rows) + slash_form_questions(rows) + family_form_questions(rows)
    unique_forms: dict[str, dict[str, Any]] = {}
    for item in form_items:
        unique_forms[item["id"]] = item
    return meaning_items + list(unique_forms.values())


def load_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_json_file(path: Path, data: Any) -> None:
    with FILE_WRITE_LOCK:
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)


def load_progress_file() -> Any:
    primary = load_json_file(PROGRESS_FILE, None)
    if primary is not None:
        return primary
    return load_json_file(PROGRESS_BACKUP_FILE, None)


def save_progress_file(data: Any) -> None:
    with FILE_WRITE_LOCK:
        if PROGRESS_FILE.exists():
            try:
                shutil.copy2(PROGRESS_FILE, PROGRESS_BACKUP_FILE)
            except OSError:
                pass
        save_json_file(PROGRESS_FILE, data)


def fetch_wiktionary_dictionary(word: str) -> dict[str, Any]:
    cache = load_json_file(CACHE_FILE, {})
    key = f"wiktionary_dictionary:en:{word.lower()}"
    if key in cache and cache[key].get("ok"):
        return cache[key]

    url = f"{WIKTIONARY_DICTIONARY_BASE_URL}/{urllib.parse.quote(word)}"
    request = urllib.request.Request(url, headers={"User-Agent": "vocabulary-reviewer/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        result = {
            "ok": True,
            "provider": "FreeDictionaryAPI.com",
            "payload": payload,
            "fetched_at": int(time.time()),
        }
        cache[key] = result
        save_json_file(CACHE_FILE, cache)
        return result
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "provider": "FreeDictionaryAPI.com",
            "status": exc.code,
            "error": str(exc),
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "provider": "FreeDictionaryAPI.com",
            "error": str(exc),
        }


def extract_wiktionary_entries(payload: Any) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []

    def walk_senses(senses: list[Any], part: str) -> None:
        for sense in senses:
            if not isinstance(sense, dict):
                continue
            definition = str(sense.get("definition", "")).strip()
            examples = sense.get("examples", []) or []
            example = next((str(value).strip() for value in examples if str(value).strip()), "")
            if definition:
                output.append(
                    {
                        "partOfSpeech": part,
                        "definition": definition,
                        "example": example,
                    }
                )
            walk_senses(sense.get("subsenses", []) or [], part)

    if not isinstance(payload, dict):
        return output
    for entry in payload.get("entries", []) or []:
        if not isinstance(entry, dict):
            continue
        part = str(entry.get("partOfSpeech", "")).lower()
        walk_senses(entry.get("senses", []) or [], part)
    return output


def fetch_free_dictionary(word: str) -> dict[str, Any]:
    cache = load_json_file(CACHE_FILE, {})
    key = f"free_dictionary:en:{word.lower()}"
    if key in cache and cache[key].get("ok"):
        return cache[key]

    url = f"{FREE_DICTIONARY_BASE_URL}/{urllib.parse.quote(word)}"
    request = urllib.request.Request(url, headers={"User-Agent": "vocabulary-reviewer/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        result = {
            "ok": True,
            "provider": "Free Dictionary API",
            "payload": payload,
            "fetched_at": int(time.time()),
        }
        cache[key] = result
        save_json_file(CACHE_FILE, cache)
        return result
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "provider": "Free Dictionary API",
            "status": exc.code,
            "error": str(exc),
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "provider": "Free Dictionary API",
            "error": str(exc),
        }


def extract_free_dictionary_entries(payload: Any) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    if not isinstance(payload, list):
        return entries
    for result in payload:
        if not isinstance(result, dict):
            continue
        for meaning in result.get("meanings", []) or []:
            part = str(meaning.get("partOfSpeech", "")).lower()
            for definition in meaning.get("definitions", []) or []:
                text = str(definition.get("definition", "")).strip()
                example = str(definition.get("example", "")).strip()
                if text:
                    entries.append(
                        {
                            "partOfSpeech": part,
                            "definition": text,
                            "example": example,
                        }
                    )
    return entries


def fetch_oxford_dictionary(word: str) -> dict[str, Any]:
    if not OXFORD_APP_ID or not OXFORD_APP_KEY:
        return {
            "ok": False,
            "provider": "Oxford Dictionaries API",
            "error": "Oxford API credentials are not configured.",
        }

    cache = load_json_file(CACHE_FILE, {})
    key = f"oxford:{OXFORD_LANGUAGE}:{word.lower()}"
    if key in cache and cache[key].get("ok"):
        return cache[key]

    query = urllib.parse.urlencode({"q": word.lower(), "fields": "definitions,examples"})
    url = f"{OXFORD_BASE_URL}/words/{urllib.parse.quote(OXFORD_LANGUAGE)}?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "app_id": OXFORD_APP_ID,
            "app_key": OXFORD_APP_KEY,
            "User-Agent": "vocabulary-reviewer/1.0",
        },
    )
    result: dict[str, Any]
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        result = {
            "ok": True,
            "provider": "Oxford Dictionaries API",
            "language": OXFORD_LANGUAGE,
            "payload": payload,
            "fetched_at": int(time.time()),
        }
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        result = {
            "ok": False,
            "provider": "Oxford Dictionaries API",
            "status": exc.code,
            "error": detail or str(exc),
            "fetched_at": int(time.time()),
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        result = {
            "ok": False,
            "provider": "Oxford Dictionaries API",
            "error": str(exc),
            "fetched_at": int(time.time()),
        }

    if result.get("ok"):
        cache[key] = result
        save_json_file(CACHE_FILE, cache)
    return result


def lexical_category_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("text") or value.get("id") or "").lower()
    return str(value or "").lower()


def extract_oxford_definitions(payload: Any) -> list[dict[str, str]]:
    definitions: list[dict[str, str]] = []

    def walk_senses(senses: list[Any], part: str) -> None:
        for sense in senses:
            if not isinstance(sense, dict):
                continue
            for text in sense.get("definitions", []) or []:
                text = str(text).strip()
                if text:
                    definitions.append({"partOfSpeech": part, "definition": text})
            walk_senses(sense.get("subsenses", []) or [], part)

    results = payload.get("results", []) if isinstance(payload, dict) else []
    for result in results:
        if not isinstance(result, dict):
            continue
        for lexical_entry in result.get("lexicalEntries", []) or []:
            if not isinstance(lexical_entry, dict):
                continue
            part = lexical_category_name(lexical_entry.get("lexicalCategory"))
            for entry in lexical_entry.get("entries", []) or []:
                if isinstance(entry, dict):
                    walk_senses(entry.get("senses", []) or [], part)
            for word_entry in lexical_entry.get("words", []) or []:
                if isinstance(word_entry, dict):
                    walk_senses(word_entry.get("senses", []) or [], part)
    return definitions


def choose_definition(word: str, pos: str, sense_index: int, fallback_meaning: str, note: str) -> dict[str, str]:
    if LOCAL_OXFORD_MDX.exists():
        local_definition = LOCAL_OXFORD.definition(word)
        if local_definition:
            return {
                "source": "local_oxford",
                "definition": local_definition,
                "partOfSpeech": "",
            }

    local_longman_sources = [
        ("local_longman", LOCAL_LONGMAN_MDX, LOCAL_LONGMAN),
        ("local_longman_phrasal", LOCAL_LONGMAN_PHRASAL_MDX, LOCAL_LONGMAN_PHRASAL),
    ]
    for source, path, dictionary in local_longman_sources:
        if path.exists():
            local_definition = dictionary.definition(word)
            if local_definition:
                return {
                    "source": source,
                    "definition": local_definition,
                    "partOfSpeech": "",
                }

    wiktionary_result = fetch_wiktionary_dictionary(word)
    if wiktionary_result.get("ok"):
        definitions = extract_wiktionary_entries(wiktionary_result.get("payload"))
        labels = set(pos_labels(pos))
        matched = [d for d in definitions if not labels or d["partOfSpeech"] in labels]
        pool = matched or definitions
        if pool:
            selected = pool[min(sense_index, len(pool) - 1)]
            payload = wiktionary_result.get("payload") or {}
            source = payload.get("source") if isinstance(payload, dict) else {}
            return {
                "source": "wiktionary_dictionary",
                "definition": selected["definition"],
                "partOfSpeech": selected["partOfSpeech"],
                "sourceUrl": source.get("url", "") if isinstance(source, dict) else "",
            }

    free_result = fetch_free_dictionary(word)
    if free_result.get("ok"):
        definitions = extract_free_dictionary_entries(free_result.get("payload"))
        labels = set(pos_labels(pos))
        matched = [d for d in definitions if not labels or d["partOfSpeech"] in labels]
        pool = matched or definitions
        if pool:
            selected = pool[min(sense_index, len(pool) - 1)]
            return {
                "source": "free_dictionary",
                "definition": selected["definition"],
                "partOfSpeech": selected["partOfSpeech"],
            }

    result = fetch_oxford_dictionary(word)
    if result.get("ok"):
        definitions = extract_oxford_definitions(result.get("payload"))
        labels = set(pos_labels(pos))
        matched = [d for d in definitions if not labels or d["partOfSpeech"] in labels]
        pool = matched or definitions
        if pool:
            selected = pool[min(sense_index, len(pool) - 1)]
            return {
                "source": "oxford",
                "definition": selected["definition"],
                "partOfSpeech": selected["partOfSpeech"],
            }
    elif result.get("error") == "Oxford API credentials are not configured.":
        return {
            "source": "missing",
            "definition": "No English definition was found in Oxford, Longman, or the alternative dictionary API.",
            "partOfSpeech": "",
        }

    return {
        "source": "missing",
        "definition": "No English definition was found in Oxford, Longman, or the alternative dictionary API.",
        "partOfSpeech": "",
    }


def choose_example(word: str) -> dict[str, str]:
    local_sources = [
        ("local_oxford", LOCAL_OXFORD_MDX, LOCAL_OXFORD),
        ("local_longman", LOCAL_LONGMAN_MDX, LOCAL_LONGMAN),
        ("local_longman_phrasal", LOCAL_LONGMAN_PHRASAL_MDX, LOCAL_LONGMAN_PHRASAL),
    ]
    for source, path, dictionary in local_sources:
        if path.exists():
            example = dictionary.example(word)
            if example:
                return {"source": source, "example": example}

    wiktionary_result = fetch_wiktionary_dictionary(word)
    if wiktionary_result.get("ok"):
        for entry in extract_wiktionary_entries(wiktionary_result.get("payload")):
            if entry["example"]:
                payload = wiktionary_result.get("payload") or {}
                source = payload.get("source") if isinstance(payload, dict) else {}
                return {
                    "source": "wiktionary_dictionary",
                    "example": entry["example"],
                    "sourceUrl": source.get("url", "") if isinstance(source, dict) else "",
                }

    free_result = fetch_free_dictionary(word)
    if free_result.get("ok"):
        for entry in extract_free_dictionary_entries(free_result.get("payload")):
            if entry["example"]:
                return {"source": "free_dictionary", "example": entry["example"]}

    result = fetch_oxford_dictionary(word)
    if result.get("ok"):
        payload = result.get("payload")
        results = payload.get("results", []) if isinstance(payload, dict) else []
        for result_item in results:
            for lexical_entry in result_item.get("lexicalEntries", []) or []:
                for entry in lexical_entry.get("entries", []) or []:
                    for sense in entry.get("senses", []) or []:
                        for example_item in sense.get("examples", []) or []:
                            text = str(example_item.get("text", "")).strip()
                            if text:
                                return {"source": "oxford", "example": text}
    return {"source": "missing", "example": "No example sentence is available for this word."}


class AppHandler(BaseHTTPRequestHandler):
    server_version = "VocabularyReviewer/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text: str, content_type: str) -> None:
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/":
            self.serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path == "/styles.css":
            self.serve_file(STATIC_DIR / "styles.css", "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self.serve_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        if path == "/api/items":
            items = build_items()
            self.send_json({"items": items, "count": len(items)})
            return
        if path == "/api/definition":
            query = urllib.parse.parse_qs(parsed.query)
            word = query.get("word", [""])[0]
            pos = query.get("pos", [""])[0]
            meaning = query.get("meaning", [""])[0]
            note = query.get("note", [""])[0]
            try:
                sense_index = int(query.get("sense", ["0"])[0])
            except ValueError:
                sense_index = 0
            if not word:
                self.send_json({"error": "Missing word"}, status=400)
                return
            self.send_json(choose_definition(word, pos, sense_index, meaning, note))
            return
        if path == "/api/example":
            query = urllib.parse.parse_qs(parsed.query)
            word = query.get("word", [""])[0]
            if not word:
                self.send_json({"error": "Missing word"}, status=400)
                return
            self.send_json(choose_example(word))
            return
        if path == "/api/wrong":
            self.send_json({"wrong_answers": load_json_file(WRONG_FILE, [])})
            return
        if path == "/api/progress":
            self.send_json({"progress": load_progress_file()})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in {"/api/answer", "/api/progress"}:
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body or "{}")
        except (ValueError, json.JSONDecodeError):
            self.send_json({"error": "Invalid JSON"}, status=400)
            return

        if parsed.path == "/api/progress":
            payload["saved_at"] = int(time.time())
            save_progress_file(payload)
            self.send_json({"ok": True})
            return

        if not payload.get("correct"):
            wrong = load_json_file(WRONG_FILE, [])
            wrong.append(
                {
                    "saved_at": int(time.time()),
                    "item": payload.get("item"),
                    "user_answer": payload.get("user_answer"),
                    "correct_answer": payload.get("correct_answer"),
                    "definition": payload.get("definition"),
                    "choices": payload.get("choices", []),
                }
            )
            save_json_file(WRONG_FILE, wrong)
        self.send_json({"ok": True})

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/answer":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8")
                payload = json.loads(body or "{}")
            except (ValueError, json.JSONDecodeError):
                self.send_json({"error": "Invalid JSON"}, status=400)
                return
            item_id = str(payload.get("item_id", ""))
            wrong = load_json_file(WRONG_FILE, [])
            for index in range(len(wrong) - 1, -1, -1):
                saved_item = wrong[index].get("item") or {}
                if str(saved_item.get("id", "")) == item_id:
                    del wrong[index]
                    save_json_file(WRONG_FILE, wrong)
                    break
            self.send_json({"ok": True})
            return
        if parsed.path != "/api/progress":
            self.send_error(404)
            return
        try:
            PROGRESS_FILE.unlink(missing_ok=True)
            PROGRESS_BACKUP_FILE.unlink(missing_ok=True)
        except OSError as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        self.send_json({"ok": True})

    def serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(404)
            return
        self.send_text(path.read_text(encoding="utf-8"), content_type)


def main() -> None:
    host = os.environ.get("VOCAB_HOST", "0.0.0.0")
    port = int(os.environ.get("VOCAB_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"Vocabulary reviewer running locally at http://127.0.0.1:{port}")
    try:
        addresses = {
            result[4][0]
            for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
            if not result[4][0].startswith("127.")
        }
        for address in sorted(addresses):
            print(f"Phone/LAN access: http://{address}:{port}")
    except OSError:
        pass
    server.serve_forever()


if __name__ == "__main__":
    if not WORKBOOK.exists():
        raise SystemExit(f"Workbook not found: {WORKBOOK}")
    main()
