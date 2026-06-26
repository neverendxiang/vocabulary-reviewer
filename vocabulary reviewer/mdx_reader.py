from __future__ import annotations

import html
import json
import re
import struct
import zlib
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


U64 = struct.Struct(">Q")
U32 = struct.Struct(">I")
U16 = struct.Struct(">H")


def rol(value: int, bits: int) -> int:
    value &= 0xFFFFFFFF
    return ((value << bits) | (value >> (32 - bits))) & 0xFFFFFFFF


def ripemd128(data: bytes) -> bytes:
    r = [
        0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
        7, 4, 13, 1, 10, 6, 15, 3, 12, 0, 9, 5, 2, 14, 11, 8,
        3, 10, 14, 4, 9, 15, 8, 1, 2, 7, 0, 6, 13, 11, 5, 12,
        1, 9, 11, 10, 0, 8, 12, 4, 13, 3, 7, 15, 14, 5, 6, 2,
    ]
    rp = [
        5, 14, 7, 0, 9, 2, 11, 4, 13, 6, 15, 8, 1, 10, 3, 12,
        6, 11, 3, 7, 0, 13, 5, 10, 14, 15, 8, 12, 4, 9, 1, 2,
        15, 5, 1, 3, 7, 14, 6, 9, 11, 8, 12, 2, 10, 0, 4, 13,
        8, 6, 4, 1, 3, 11, 15, 0, 5, 12, 2, 13, 9, 7, 10, 14,
    ]
    s = [
        11, 14, 15, 12, 5, 8, 7, 9, 11, 13, 14, 15, 6, 7, 9, 8,
        7, 6, 8, 13, 11, 9, 7, 15, 7, 12, 15, 9, 11, 7, 13, 12,
        11, 13, 6, 7, 14, 9, 13, 15, 14, 8, 13, 6, 5, 12, 7, 5,
        11, 12, 14, 15, 14, 15, 9, 8, 9, 14, 5, 6, 8, 6, 5, 12,
    ]
    sp = [
        8, 9, 9, 11, 13, 15, 15, 5, 7, 7, 8, 11, 14, 14, 12, 6,
        9, 13, 15, 7, 12, 8, 9, 11, 7, 7, 12, 7, 6, 15, 13, 11,
        9, 7, 15, 11, 8, 6, 6, 14, 12, 13, 5, 14, 13, 13, 7, 5,
        15, 5, 8, 11, 14, 14, 6, 14, 6, 9, 12, 9, 12, 5, 15, 8,
    ]
    k = [0x00000000, 0x5A827999, 0x6ED9EBA1, 0x8F1BBCDC]
    kp = [0x50A28BE6, 0x5C4DD124, 0x6D703EF3, 0x00000000]

    def f(j: int, x: int, y: int, z: int) -> int:
        if j < 16:
            return x ^ y ^ z
        if j < 32:
            return (x & y) | (~x & z)
        if j < 48:
            return (x | ~y) ^ z
        return (x & z) | (y & ~z)

    msg = bytearray(data)
    bit_len = (len(msg) * 8) & 0xFFFFFFFFFFFFFFFF
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0)
    msg.extend(struct.pack("<Q", bit_len))

    h0, h1, h2, h3 = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476
    for offset in range(0, len(msg), 64):
        x = list(struct.unpack("<16L", msg[offset : offset + 64]))
        al, bl, cl, dl = h0, h1, h2, h3
        ar, br, cr, dr = h0, h1, h2, h3
        for j in range(64):
            t = rol(al + f(j, bl, cl, dl) + x[r[j]] + k[j // 16], s[j])
            al, dl, cl, bl = dl, cl, bl, t
            t = rol(ar + f(63 - j, br, cr, dr) + x[rp[j]] + kp[j // 16], sp[j])
            ar, dr, cr, br = dr, cr, br, t
        t = (h1 + cl + dr) & 0xFFFFFFFF
        h1 = (h2 + dl + ar) & 0xFFFFFFFF
        h2 = (h3 + al + br) & 0xFFFFFFFF
        h3 = (h0 + bl + cr) & 0xFFFFFFFF
        h0 = t
    return struct.pack("<4L", h0, h1, h2, h3)


def mdx_decrypt(data: bytes, key: bytes) -> bytes:
    previous = 0x36
    output = bytearray()
    for i, value in enumerate(data):
        current = value
        value = (((value >> 4) | (value << 4)) & 0xFF) ^ previous ^ (i & 0xFF) ^ key[i % len(key)]
        output.append(value)
        previous = current
    return bytes(output)


def decompress_block(block: bytes) -> bytes:
    compression = block[:4]
    payload = block[8:]
    if compression == b"\x00\x00\x00\x00":
        return payload
    if compression == b"\x02\x00\x00\x00":
        return zlib.decompress(payload)
    raise ValueError(f"Unsupported MDX compression block: {compression.hex()}")


def parse_header(raw: bytes) -> dict[str, str]:
    text = raw.decode("utf-16", errors="ignore").rstrip("\x00\r\n")
    root = ET.fromstring(text)
    return {k: html.unescape(v) for k, v in root.attrib.items()}


def normalize_key(key: str) -> str:
    return re.sub(r"\s+", " ", key.strip().lower())


def strip_html_to_text(record: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", record, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"</(div|p|li|span|h[1-6])>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[\u4e00-\u9fff]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class MdxDictionary:
    def __init__(self, mdx_path: Path, index_path: Path):
        self.mdx_path = Path(mdx_path)
        self.index_path = Path(index_path)
        self.index: dict[str, Any] | None = None

    def lookup(self, word: str) -> str | None:
        self.ensure_index()
        assert self.index is not None
        key = normalize_key(word)
        entry = self.index["entries"].get(key)
        if not entry:
            return None
        start, end = entry["start"], entry["end"]
        block = self._record_block_for(start)
        if not block:
            return None
        block_start, comp_start, comp_size = block
        with self.mdx_path.open("rb") as file:
            file.seek(comp_start)
            raw = decompress_block(file.read(comp_size))
        record = raw[start - block_start : end - block_start]
        return record.decode(self.index["encoding"], errors="replace")

    def definition(self, word: str) -> str | None:
        record = self.lookup(word)
        if not record:
            return None
        return best_definition_text(record)

    def example(self, word: str) -> str | None:
        record = self.lookup(word)
        if not record:
            return None
        return best_example_text(record)

    def ensure_index(self) -> None:
        stat = self.mdx_path.stat()
        if self.index_path.exists():
            try:
                cached = json.loads(self.index_path.read_text(encoding="utf-8"))
                if (
                    cached.get("path") == str(self.mdx_path)
                    and cached.get("size") == stat.st_size
                    and cached.get("mtime") == stat.st_mtime
                ):
                    self.index = cached
                    return
            except (OSError, json.JSONDecodeError):
                pass
        self.index = self._build_index(stat.st_size, stat.st_mtime)
        self.index_path.write_text(json.dumps(self.index, ensure_ascii=False), encoding="utf-8")

    def _read_key_block_info(self, file: Any, header: dict[str, str]) -> tuple[list[dict[str, Any]], int, int]:
        num_key_blocks = U64.unpack(file.read(8))[0]
        _num_entries = U64.unpack(file.read(8))[0]
        key_info_decomp_size = U64.unpack(file.read(8))[0]
        key_info_comp_size = U64.unpack(file.read(8))[0]
        key_blocks_total_size = U64.unpack(file.read(8))[0]
        file.read(4)
        comp = file.read(key_info_comp_size)
        if header.get("Encrypted") == "2":
            key = ripemd128(comp[4:8] + struct.pack("<L", 0x3695))
            comp = comp[:8] + mdx_decrypt(comp[8:], key)
        info = decompress_block(comp)
        if len(info) != key_info_decomp_size:
            raise ValueError("Unexpected MDX key info size")

        encoding = header.get("Encoding", "UTF-8")
        term_size = 2 if encoding.upper().startswith("UTF-16") else 1
        pos = 0
        blocks: list[dict[str, Any]] = []
        for _ in range(num_key_blocks):
            entries = U64.unpack(info[pos : pos + 8])[0]
            pos += 8
            first_len = U16.unpack(info[pos : pos + 2])[0]
            pos += 2 + first_len + term_size
            last_len = U16.unpack(info[pos : pos + 2])[0]
            pos += 2 + last_len + term_size
            comp_size = U64.unpack(info[pos : pos + 8])[0]
            pos += 8
            decomp_size = U64.unpack(info[pos : pos + 8])[0]
            pos += 8
            blocks.append({"entries": entries, "comp_size": comp_size, "decomp_size": decomp_size})
        return blocks, file.tell(), key_blocks_total_size

    def _parse_key_blocks(self, file: Any, blocks: list[dict[str, Any]], encoding: str) -> list[tuple[str, int]]:
        keys: list[tuple[str, int]] = []
        term = b"\x00\x00" if encoding.upper().startswith("UTF-16") else b"\x00"
        for block in blocks:
            raw = decompress_block(file.read(block["comp_size"]))
            pos = 0
            for _ in range(block["entries"]):
                record_offset = U64.unpack(raw[pos : pos + 8])[0]
                pos += 8
                end = raw.find(term, pos)
                if end < 0:
                    break
                key = raw[pos:end].decode(encoding, errors="replace")
                pos = end + len(term)
                keys.append((key, record_offset))
        return keys

    def _build_index(self, size: int, mtime: float) -> dict[str, Any]:
        with self.mdx_path.open("rb") as file:
            header_len = U32.unpack(file.read(4))[0]
            header = parse_header(file.read(header_len))
            file.read(4)
            key_blocks, key_blocks_start, key_blocks_total_size = self._read_key_block_info(file, header)
            encoding = header.get("Encoding", "UTF-8")
            keys = self._parse_key_blocks(file, key_blocks, encoding)
            record_header_start = key_blocks_start + key_blocks_total_size
            file.seek(record_header_start)
            num_record_blocks = U64.unpack(file.read(8))[0]
            _num_entries = U64.unpack(file.read(8))[0]
            record_info_size = U64.unpack(file.read(8))[0]
            _record_blocks_total_size = U64.unpack(file.read(8))[0]
            record_blocks = []
            decomp_start = 0
            for _ in range(num_record_blocks):
                comp_size = U64.unpack(file.read(8))[0]
                decomp_size = U64.unpack(file.read(8))[0]
                record_blocks.append(
                    {
                        "decomp_start": decomp_start,
                        "decomp_end": decomp_start + decomp_size,
                        "comp_size": comp_size,
                    }
                )
                decomp_start += decomp_size
            record_data_start = record_header_start + 32 + record_info_size
            comp_start = record_data_start
            for block in record_blocks:
                block["comp_start"] = comp_start
                comp_start += block["comp_size"]

        entries: dict[str, dict[str, Any]] = {}
        total_decomp_size = record_blocks[-1]["decomp_end"] if record_blocks else 0
        for i, (key, start) in enumerate(keys):
            end = keys[i + 1][1] if i + 1 < len(keys) else total_decomp_size
            norm = normalize_key(key)
            entries.setdefault(norm, {"key": key, "start": start, "end": end})

        return {
            "path": str(self.mdx_path),
            "size": size,
            "mtime": mtime,
            "encoding": encoding,
            "header": header,
            "record_blocks": record_blocks,
            "entries": entries,
        }

    def _record_block_for(self, offset: int) -> tuple[int, int, int] | None:
        assert self.index is not None
        for block in self.index["record_blocks"]:
            if block["decomp_start"] <= offset < block["decomp_end"]:
                return block["decomp_start"], block["comp_start"], block["comp_size"]
        return None


def best_definition_text(record: str) -> str | None:
    candidates = re.findall(
        r"<(?:span|div|p)[^>]+class=[\"'][^\"']*(?:def|definition)[^\"']*[\"'][^>]*>(.*?)</(?:span|div|p)>",
        record,
        flags=re.I | re.S,
    )
    for candidate in candidates:
        text = strip_html_to_text(candidate)
        lower = text.lower()
        is_origin_fragment = bool(
            re.match(r"^(?:early|mid|late)?\s*\d{1,2}(?:st|nd|rd|th)\s+cent\.", lower)
            or re.match(r"^\d{4}s?\b", lower)
        )
        if text and not is_origin_fragment:
            return text
    text = strip_html_to_text(record)
    if not text:
        return None
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sentence in sentences:
        sentence = sentence.strip()
        if 20 <= len(sentence) <= 260 and not sentence.lower().startswith(("oxford", "see also")):
            return sentence
    return text[:260].strip()


def best_example_text(record: str) -> str | None:
    patterns = [
        r"<span[^>]+class=[\"'][^\"']*\bx\b[^\"']*[\"'][^>]*>(.*?)</span>",
        r"<li\b[^>]*>(.*?)</li>",
        r"<font[^>]+color=[\"']?darkgreen[\"']?[^>]*>(.*?)</font>",
        r"<(?:span|div|p)[^>]+class=[\"'][^\"']*\b(?:exa|example)\b[^\"']*[\"'][^>]*>(.*?)</(?:span|div|p)>",
    ]
    candidates: list[str] = []
    for pattern in patterns:
        for candidate in re.findall(pattern, record, flags=re.I | re.S):
            text = strip_html_to_text(candidate)
            text = re.sub(r"^[▪•]\s*", "", text).strip()
            if text and text not in candidates:
                candidates.append(text)

    for text in candidates:
        words = text.split()
        if len(words) >= 4 and re.search(r"[.!?][\"']?$", text):
            return text
    for text in candidates:
        if len(text.split()) >= 5:
            return text
    return None
