from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any


EMBEDDING_MODEL_ENV = "CHAT_EMBEDDING_MODEL"
EMBEDDING_DEVICE_ENV = "CHAT_EMBEDDING_DEVICE"
EMBEDDING_BATCH_SIZE_ENV = "CHAT_EMBEDDING_BATCH_SIZE"
DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
DEFAULT_EMBEDDING_DIMENSION = 1024
DEFAULT_EMBEDDING_MAX_TOKENS = 512
DEFAULT_EMBEDDING_BATCH_SIZE = 8


class EmbeddingService(ABC):
    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError


class MultilingualE5EmbeddingService(EmbeddingService):
    """Local multilingual-e5-large adapter with required E5 prefixes."""

    def __init__(
        self,
        *,
        model_name: str | None = None,
        device: str | None = None,
        batch_size: int | None = None,
        max_tokens: int = DEFAULT_EMBEDDING_MAX_TOKENS,
    ) -> None:
        self.model_name = (
            model_name
            or os.getenv(EMBEDDING_MODEL_ENV, "").strip()
            or DEFAULT_EMBEDDING_MODEL
        )
        self.configured_device = (
            device or os.getenv(EMBEDDING_DEVICE_ENV, "").strip() or "auto"
        )
        self.batch_size = batch_size or self._configured_batch_size()
        self.max_tokens = max_tokens
        self.embedding_dimension = DEFAULT_EMBEDDING_DIMENSION
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._device: Any | None = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(
            [f"passage: {text}" for text in texts],
            allow_truncation=False,
        )

    def embed_query(self, text: str) -> list[float]:
        normalized = text.strip()
        if not normalized:
            raise ValueError("Embedding query cannot be empty.")
        return self._embed([f"query: {normalized}"], allow_truncation=True)[0]

    def _embed(
        self,
        input_texts: list[str],
        *,
        allow_truncation: bool,
    ) -> list[list[float]]:
        if not input_texts:
            return []
        self._load()
        import torch
        import torch.nn.functional as functional

        vectors: list[list[float]] = []
        for start in range(0, len(input_texts), self.batch_size):
            batch = input_texts[start : start + self.batch_size]
            tokenizer_arguments: dict[str, Any] = {
                "padding": True,
                "return_tensors": "pt",
            }
            if allow_truncation:
                tokenizer_arguments.update(
                    {"max_length": self.max_tokens, "truncation": True}
                )
            encoded = self._tokenizer(batch, **tokenizer_arguments)
            if not allow_truncation and encoded["input_ids"].shape[1] > self.max_tokens:
                raise ValueError(
                    "Document embedding input exceeds the E5 token limit; "
                    "run it through E5EmbeddingInputSegmenter first."
                )
            encoded = {key: value.to(self._device) for key, value in encoded.items()}
            with torch.inference_mode():
                output = self._model(**encoded)
                attention_mask = encoded["attention_mask"]
                hidden = output.last_hidden_state.masked_fill(
                    ~attention_mask[..., None].bool(),
                    0.0,
                )
                pooled = hidden.sum(dim=1) / attention_mask.sum(dim=1)[..., None]
                normalized = functional.normalize(pooled, p=2, dim=1)
            vectors.extend(normalized.detach().cpu().float().tolist())
        return vectors

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModel, AutoTokenizer

        self._device = self._resolve_device(torch)
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModel.from_pretrained(self.model_name)
        self._model.to(self._device)
        self._model.eval()
        configured_dimension = int(getattr(self._model.config, "hidden_size", 0))
        if configured_dimension != self.embedding_dimension:
            raise ValueError(
                f"Embedding model dimension is {configured_dimension}; "
                f"expected {self.embedding_dimension}."
            )

    def _resolve_device(self, torch: Any) -> Any:
        if self.configured_device != "auto":
            return torch.device(self.configured_device)
        if torch.cuda.is_available():
            return torch.device("cuda")
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")

    @staticmethod
    def _configured_batch_size() -> int:
        try:
            value = int(os.getenv(EMBEDDING_BATCH_SIZE_ENV, "").strip())
        except ValueError:
            return DEFAULT_EMBEDDING_BATCH_SIZE
        return value if value > 0 else DEFAULT_EMBEDDING_BATCH_SIZE
