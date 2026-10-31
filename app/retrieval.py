from __future__ import annotations
from datetime import date
from pathlib import Path
import re
from app.config import settings

TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)
SECTION_RE = re.compile(r"(?m)^##\s+\[([^\]]+)\]\s*(.*?)\s*$")
META_RE = re.compile(r"(?m)^([A-Za-z_]+):\s*(.*?)\s*$")
REFERENCE_DATE = date.fromisoformat(settings.reference_date)
TYPE_RANK = {"policy": 5, "agent_guide": 4, "help": 3, "faq": 2, "marketing": 1, "meta": 0}

SYNONYMS = {
    "refund": {"refund", "money", "cash", "rrn", "reversal", "reimburse", "paisa", "paise"},
    "return": {"return", "send", "back", "wapas", "lautana", "lauta", "exchange"},
    "pickup": {"pickup", "collection", "collect", "fee", "charge"},
    "shipping": {"shipping", "delivery", "courier", "ship", "dispatch", "arrive"},
    "cancel": {"cancel", "cancellation", "stop", "refuse"},
    "warranty": {"warranty", "assured", "claim", "guarantee", "repair"},
    "damaged": {"damaged", "damage", "broken", "crack", "torn", "wrong", "missing", "defective"},
    "verification": {"verify", "verification", "phone", "pincode", "identity"},
    "coupon": {"coupon", "offer", "discount", "promo"},
}

def tokenize(text: str) -> set[str]:
    words = {w.casefold() for w in TOKEN_RE.findall(text or "") if len(w) > 1}
    expanded = set(words)
    for group in SYNONYMS.values():
        if words & group: expanded |= group
    return expanded

def _metadata(text: str) -> dict:
    meta = {}
    front = text.split("---", 2)
    if len(front) >= 3:
        for key, value in META_RE.findall(front[1]):
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta

def _valid(meta: dict, ref_date: date) -> bool:
    status = meta.get("status", "current").casefold()
    if status == "superseded":
        return False
    start = meta.get("effective_from")
    end = meta.get("effective_to")
    try:
        if start and date.fromisoformat(start[:10]) > ref_date: return False
        if end and date.fromisoformat(end[:10]) < ref_date: return False
    except ValueError:
        return False
    return True

def split_document(text: str, source: str) -> list[dict]:
    meta = _metadata(text)
    matches = list(SECTION_RE.finditer(text))
    chunks = []
    for i, match in enumerate(matches):
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        chunks.append({
            "source": source, "section_id": match.group(1).strip(),
            "heading": match.group(2).strip(),
            "content": text[match.start():end].strip(),
            **meta,
        })
    if not chunks:
        body = text.split("---", 2)[-1].strip() if text.startswith("---") else text
        chunks.append({"source": source, "section_id": None, "heading": source,
                       "content": body, **meta})
    return chunks

def retrieve_kb(query: str, dataset_dir: Path | None = None, top_k: int = 5,
                reference_date: date = REFERENCE_DATE) -> list[dict]:
    kb_dir = Path(dataset_dir or settings.dataset_dir) / "kb"
    if not kb_dir.is_dir(): return []
    qtokens = tokenize(query)
    if not qtokens: return []
    results = []
    for path in sorted(kb_dir.glob("*.md")):
        try: text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError): continue
        for chunk in split_document(text, path.name):
            if not _valid(chunk, reference_date): continue
            body_tokens = tokenize(chunk["heading"] + " " + chunk["content"])
            overlap = qtokens & body_tokens
            if not overlap: continue
            # Coverage dominates document length; rank policy over lower-precedence sources.
            coverage = len(overlap) / max(1, len(qtokens))
            density = len(overlap) / max(1, len(body_tokens) ** 0.35)
            score = 0.75 * coverage + 0.25 * density
            score += TYPE_RANK.get(chunk.get("doc_type", ""), 0) * 0.006
            results.append({**chunk, "score": round(score, 5)})
    results.sort(key=lambda x: (-x["score"], -TYPE_RANK.get(x.get("doc_type", ""), 0),
                                x.get("section_id") or "", x["source"]))
    return results[:max(1, min(int(top_k), 10))]
