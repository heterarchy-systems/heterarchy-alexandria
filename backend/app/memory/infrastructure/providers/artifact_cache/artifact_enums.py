"""Finite artifact names accepted by the pinned multilingual-E5 snapshot."""

from enum import StrEnum


class AssetName(StrEnum):
    """The five files that form the supported model snapshot."""

    ONNX_MODEL = "onnx/model.onnx"
    TOKENIZER = "tokenizer.json"
    CONFIG = "config.json"
    SPECIAL_TOKENS_MAP = "special_tokens_map.json"
    TOKENIZER_CONFIG = "tokenizer_config.json"


ASSET_NAMES: tuple[str, ...] = tuple(name.value for name in AssetName)
