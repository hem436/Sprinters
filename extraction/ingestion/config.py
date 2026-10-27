"""Extraction settings. Every threshold lives here with its contract 10 section 12 key, never in the rule code.

Sinngam's `config/app.yaml` can hold the same keys (dotted names such as `extract.max_mb`, or nested sections).
`ExtractConfig.from_dict` refuses unknown keys, so a typo cannot pass silently.
"""
import os
from dataclasses import dataclass, field, fields, replace
from decimal import Decimal
from pathlib import Path

# config key (contract 10 section 12) -> field name
_KEYS = {
    "extract.allowed_types": "allowed_types",
    "extract.max_mb": "max_mb",
    "extract.max_pages": "max_pages",
    "extract.max_ocr_pages": "max_ocr_pages",
    "extract.min_text_chars": "min_text_chars",
    "extract.max_garbage_ratio": "max_garbage_ratio",
    "extract.mixed_image_cover": "mixed_image_cover",
    "extract.scanned_image_cover": "scanned_image_cover",
    "extract.blank_max_chars": "blank_max_chars",
    "extract.blank_max_image_cover": "blank_max_image_cover",
    "extract.table_num_ratio": "table_num_ratio",
    "extract.column_gap_pt": "column_gap_pt",
    "extract.review_threshold": "review_threshold",
    "clean.repeat_line_ratio": "repeat_line_ratio",
    "ocr.model": "ocr_model",
    "ocr.max_edge_px": "ocr_max_edge_px",
    "ocr.prompt_version": "ocr_prompt_version",
    "ocr.thinking_level": "ocr_thinking_level",
    "ocr.fallback_models": "ocr_fallback_models",
    "ocr.timeout_s": "ocr_timeout_s",
    "embed.timeout_s": "embed_timeout_s",
    "ocr.attempts": "ocr_attempts",
    "ocr.price_in_per_mtok_usd": "ocr_price_in_per_mtok_usd",
    "ocr.price_out_per_mtok_usd": "ocr_price_out_per_mtok_usd",
    "fin.review_unmapped": "fin_review_unmapped",
    "fin.vision_tables": "fin_vision_tables",
    "fin.mapper_model": "fin_mapper_model",
    "chunk.target_tokens": "chunk_target_tokens",
    "chunk.max_tokens": "chunk_max_tokens",
    "chunk.overlap_tokens": "chunk_overlap_tokens",
    "embed.model": "embed_model",
    "embed.fallback_model": "embed_fallback_model",
    "embed.batch_size": "embed_batch_size",
    "embed.dim": "embed_dim",
    "index.collection": "collection",
}


@dataclass(frozen=True)
class ExtractConfig:
    # X1 intake
    allowed_types: tuple[str, ...] = ("pdf", "docx", "txt", "png", "jpg", "jpeg", "tif", "tiff", "webp")
    max_mb: int = 50
    max_pages: int = 500
    max_ocr_pages: int = 60

    # X3 page classes (order of the rules is fixed in classify.py)
    min_text_chars: int = 80
    max_garbage_ratio: float = 0.05
    mixed_image_cover: float = 0.50
    scanned_image_cover: float = 0.30
    blank_max_chars: int = 5
    blank_max_image_cover: float = 0.05
    table_num_ratio: float = 0.30

    # X4 text
    column_gap_pt: float = 18.0
    repeat_line_ratio: float = 0.5

    # X7 review gate
    review_threshold: float = 0.85

    # X5 OCR
    # A fixed model name, not a "-latest" alias: the alias moved to a slower thinking model under us (27 Oct 2026:
    # gemini-flash-latest timed out at 45 s on one page; gemini-3.5-flash with thinking "low" took about 3 s).
    ocr_model: str = "gemini-3.5-flash"
    ocr_thinking_level: str | None = "low"   # minimal, low, medium, high; None = the model's default
    # the free tier allows only 20 requests a day per model on gemini-3.5-flash; these take over when it runs out
    ocr_fallback_models: tuple[str, ...] = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite")
    ocr_timeout_s: int = 60                  # per call; a timeout is retried like a 503
    ocr_max_edge_px: int = 1600
    ocr_prompt_version: str = "ocr-v1"
    ocr_attempts: int = 3
    # Prices for the ExtractionReport cost. None = "price not set": the cost stays empty, never 0 (contract 11 s.4).
    ocr_price_in_per_mtok_usd: Decimal | None = None
    ocr_price_out_per_mtok_usd: Decimal | None = None

    # contract 14 financial facts
    fin_review_unmapped: bool = True          # F6 / diagram: a table with an unmapped label waits for review
    fin_vision_tables: bool = True            # F1: send numeric pages without a ruled table to the vision model
    fin_mapper_model: str = "gemini-3.1-flash-lite"

    # X8 chunks (tokens are estimated as characters / 4; see chunker.py)
    chunk_target_tokens: int = 400
    chunk_max_tokens: int = 700
    chunk_overlap_tokens: int = 80

    # X9 index
    embed_model: str = "gemini-embedding-2-preview"   # the model the chatbot repo uses today (3072 dims)
    embed_fallback_model: str = "all-mpnet-base-v2"
    embed_batch_size: int = 32
    embed_timeout_s: int = 30
    embed_dim: int | None = None          # None = the model's own size; a change of model or size needs a re-index
    collection: str = "enterprise_kb"

    # where things live (not contract keys; from the environment)
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("EXTRACTION_DATA_DIR", "data")))
    qdrant_url: str | None = field(default_factory=lambda: os.getenv("QDRANT_URL") or None)
    qdrant_api_key: str | None = field(default_factory=lambda: os.getenv("QDRANT_API_KEY") or None)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "knowledge.db"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def qdrant_path(self) -> Path:
        return self.data_dir / "qdrant"

    @classmethod
    def from_dict(cls, values: dict, base: "ExtractConfig | None" = None) -> "ExtractConfig":
        """Accept dotted keys (`extract.max_mb`) or nested sections (`{"extract": {"max_mb": 50}}`)."""
        flat: dict = {}
        for key, value in values.items():
            if isinstance(value, dict):
                for sub, v in value.items():
                    flat[f"{key}.{sub}"] = v
            else:
                flat[key] = value
        unknown = sorted(k for k in flat if k not in _KEYS)
        if unknown:
            raise ValueError(f"unknown extraction config keys: {unknown}")
        kinds = {f.name: f.type for f in fields(cls)}
        changes = {}
        for key, value in flat.items():
            name = _KEYS[key]
            if name == "allowed_types":
                value = tuple(str(v).lower().lstrip(".") for v in value)
            elif name == "ocr_fallback_models":
                value = tuple(value or ())
            elif name.startswith("ocr_price") and value is not None:
                value = Decimal(str(value))
            elif name == "embed_dim":
                value = int(value) if value is not None else None
            elif kinds[name] in (int, "int"):
                value = int(value)
            elif kinds[name] in (float, "float"):
                value = float(value)
            changes[name] = value
        return replace(base or cls(), **changes)


def load_config() -> ExtractConfig:
    """Defaults, then the YAML file named in EXTRACTION_CONFIG (if any)."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    cfg = ExtractConfig()
    path = os.getenv("EXTRACTION_CONFIG")
    if path:
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        # app.yaml may hold other parts' sections; keep only ours
        sections = {"extract", "clean", "ocr", "chunk", "embed", "index", "fin"}
        ours = {k: v for k, v in data.items() if k.split(".")[0] in sections}
        cfg = ExtractConfig.from_dict(ours, cfg)
    return cfg
