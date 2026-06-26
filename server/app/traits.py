"""
Trait vocabulary and pseudo-document derivation for server-side inference.

The ``resolve_kits`` pipeline turns a natural-language task into the four
trait lists that :func:`app.kits.select_kits_v2` consumes. To do that
deterministically it needs two things derived from the kit manifests:

* the legal trait **vocabulary** (what tokens a trait can be), and
* a short **pseudo-document** per trait — text that represents the trait
  well enough to match it against task wording (lexically or by embedding).

Both are derived here, from the same manifests the V2 selector already
loads, so inference can never invent a trait the selector does not know.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from app.kits import (
    KitApplicability,
    KitInfo,
    iter_catalog,
    read_kit_outline,
)

_TRAIT_KEYS = ("languages", "frameworks", "capabilities", "contexts")


@dataclass(frozen=True)
class TraitVocabulary:
    """
    The legal trait tokens, grouped by category.

    :param languages: Known language tokens, e.g. ``["python"]``.
    :param frameworks: Known framework tokens, e.g. ``["fastapi"]``.
    :param capabilities: Known capability tokens (kit domains and weak
        optional signals pooled together).
    :param contexts: Known context tokens, e.g. ``["backend"]``.
    """

    languages: list[str]
    frameworks: list[str]
    capabilities: list[str]
    contexts: list[str]

    def all_by_category(self) -> dict[str, list[str]]:
        """Return the vocabulary as a ``{category: tokens}`` mapping."""
        return {
            "languages": self.languages,
            "frameworks": self.frameworks,
            "capabilities": self.capabilities,
            "contexts": self.contexts,
        }

    def flat(self) -> set[str]:
        """Return every known token across all categories as a set."""
        tokens: set[str] = set()
        for values in self.all_by_category().values():
            tokens.update(values)
        return tokens


@dataclass(frozen=True)
class TraitDoc:
    """
    A trait token plus the text used to match it against a task.

    :param category: One of ``languages``/``frameworks``/
        ``capabilities``/``contexts``.
    :param value: The trait token, e.g. ``"fastapi"``.
    :param text: Pseudo-document text: the token plus aggregated phrases
        from every kit that positively declares it.
    """

    category: str
    value: str
    text: str


@dataclass(frozen=True)
class SectionRef:
    """
    A kit section plus the text used to rank it against a task.

    :param kit: Owning kit name.
    :param version: Resolved kit version, e.g. ``"v1"``.
    :param section_id: Section id (the file stem), as accepted by
        :func:`app.kits.read_kit`.
    :param title: Human-readable section title.
    :param gloss: One-line section summary.
    :param always_load: Whether the section holds core invariants.
    :param bytes: Section body size in bytes (for budgeting).
    :param text: Ranking text (title + gloss).
    """

    kit: str
    version: str
    section_id: str
    title: str
    gloss: str
    always_load: bool
    bytes: int
    text: str


def _positive_tokens(
    applicability: KitApplicability,
) -> dict[str, set[str]]:
    """
    Return the tokens a kit *positively* declares, per category.

    Positive membership is the declared lists plus hard ``requires``
    (which also mean "this kit is about that trait"). ``excludes`` are
    deliberately not included here: an excluded trait is one the kit is
    incompatible with, so the kit's text must not pollute that trait's
    pseudo-document.
    """
    return {
        "languages": set(applicability.languages)
        | set(applicability.requires["languages"]),
        "frameworks": set(applicability.frameworks)
        | set(applicability.requires["frameworks"]),
        "capabilities": set(applicability.domains)
        | set(applicability.optional_signals)
        | set(applicability.requires["capabilities"]),
        "contexts": set(applicability.contexts)
        | set(applicability.requires["contexts"]),
    }


def load_vocabulary() -> TraitVocabulary:
    """
    Return the legal trait vocabulary aggregated across all manifests.

    A token is recognised when any kit references it in a category —
    whether it declares, requires, or excludes it — so that task wording
    matching an excluded trait still steers the selector correctly.

    :returns: The aggregated :class:`TraitVocabulary`.
    """
    buckets: dict[str, set[str]] = {key: set() for key in _TRAIT_KEYS}
    for _info, app in iter_catalog():
        positive = _positive_tokens(app)
        for key in _TRAIT_KEYS:
            buckets[key].update(positive[key])
            buckets[key].update(app.excludes[key])
    return TraitVocabulary(
        languages=sorted(buckets["languages"]),
        frameworks=sorted(buckets["frameworks"]),
        capabilities=sorted(buckets["capabilities"]),
        contexts=sorted(buckets["contexts"]),
    )


def build_trait_docs() -> list[TraitDoc]:
    """
    Return one pseudo-document per known trait token.

    For each trait the text aggregates, from every kit that positively
    declares it, the kit ``summary``, its ``domains`` and its
    ``optional_signals``. The token itself is always prefixed so even a
    trait no kit elaborates still has matchable text.

    :returns: A list of :class:`TraitDoc`, one per (category, token).
    """
    # category -> token -> set of phrase strings
    phrases: dict[str, dict[str, set[str]]] = {
        key: {} for key in _TRAIT_KEYS
    }
    vocab = load_vocabulary()
    for key, values in vocab.all_by_category().items():
        for value in values:
            phrases[key].setdefault(value, set())

    for _info, app in iter_catalog():
        positive = _positive_tokens(app)
        kit_phrases: set[str] = {app.summary}
        kit_phrases.update(app.domains)
        kit_phrases.update(app.optional_signals)
        kit_phrases = {p for p in (s.strip() for s in kit_phrases) if p}
        for key in _TRAIT_KEYS:
            for token in positive[key]:
                phrases[key].setdefault(token, set()).update(kit_phrases)

    docs: list[TraitDoc] = []
    for key in _TRAIT_KEYS:
        for token in sorted(phrases[key]):
            joined = " ".join(sorted(phrases[key][token]))
            text = f"{token}. {joined}".strip()
            docs.append(TraitDoc(category=key, value=token, text=text))
    return docs


def build_section_refs(kit_names: list[str]) -> list[SectionRef]:
    """
    Return section references (with ranking text) for the named kits.

    Uses :func:`app.kits.read_kit_outline`, so the latest version of each
    kit is described.

    :param kit_names: Kit names to describe.
    :returns: A flat list of :class:`SectionRef` across all kits, in kit
        then document order.
    """
    refs: list[SectionRef] = []
    for name in kit_names:
        outline = read_kit_outline(name)
        version = outline["version"]
        for section in outline["sections"]:
            title = section["title"]
            gloss = section["gloss"]
            text = f"{title}. {gloss}".strip()
            refs.append(
                SectionRef(
                    kit=name,
                    version=version,
                    section_id=section["id"],
                    title=title,
                    gloss=gloss,
                    always_load=section["always_load"],
                    bytes=section["bytes"],
                    text=text,
                )
            )
    return refs


def catalog_fingerprint() -> str:
    """
    Return a stable hash of the catalog's manifests and section outlines.

    Used to key on-disk embedding caches: editing any manifest or section
    (title/gloss/size) changes the fingerprint, invalidating stale
    embeddings automatically.

    :returns: A hex SHA-256 digest.
    """
    parts: list[str] = []
    for info, app in iter_catalog():
        manifest = asdict(app)
        manifest["__name__"] = info.name
        manifest["__latest__"] = info.latest_version
        parts.append(json.dumps(manifest, sort_keys=True))
        outline = read_kit_outline(info.name)
        parts.append(json.dumps(outline, sort_keys=True))
    blob = "\n".join(parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# Re-exported for callers that only need these names from one module.
__all__ = [
    "KitApplicability",
    "KitInfo",
    "SectionRef",
    "TraitDoc",
    "TraitVocabulary",
    "build_section_refs",
    "build_trait_docs",
    "catalog_fingerprint",
    "load_vocabulary",
]
