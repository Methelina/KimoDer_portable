# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Deterministic fallback text encoder used when the gated LLM2Vec base model is unavailable."""

from __future__ import annotations

import hashlib

import numpy as np
import torch

from kimodo.sanitize import sanitize_texts


class HashTextEncoder:
    """Deterministic prompt-to-vector encoder.

    This is a degraded fallback for local installs where the gated Meta-Llama base
    model is unavailable. It preserves the text encoder API contract so the demo can
    launch and generate motions, but prompt quality will be worse than the real
    LLM2Vec encoder.
    """

    def __init__(self, llm_dim: int = 4096, dtype: str = "float32") -> None:
        self.llm_dim = llm_dim
        self.device = torch.device("cpu")
        self.dtype = getattr(torch, dtype)

    def to(self, device=None, dtype=None):
        if device is not None:
            self.device = torch.device(device)
        if dtype is not None:
            self.dtype = dtype
        return self

    def eval(self):
        return self

    def get_device(self):
        return self.device

    def _embed_text(self, text: str) -> np.ndarray:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], "big", signed=False)
        rng = np.random.default_rng(seed)
        vector = rng.standard_normal(self.llm_dim, dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector /= norm
        return vector

    def __call__(self, text: list[str] | str):
        is_string = isinstance(text, str)
        texts = [text] if is_string else list(text)
        texts = sanitize_texts(texts)

        vectors = [self._embed_text(item) for item in texts]
        encoded = np.stack(vectors, axis=0)[:, None, :]
        lengths = [1 for _ in texts]

        tensor = torch.from_numpy(encoded).to(device=self.device, dtype=self.dtype)
        if is_string:
            return tensor[0], 1
        return tensor, lengths
