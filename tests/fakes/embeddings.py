"""Fake de EmbeddingProvider: vectores deterministas por bolsa de palabras con hash."""

import hashlib
import math
import re
from dataclasses import dataclass


@dataclass
class FakeEmbeddingProvider:
    """Textos con palabras en común obtienen vectores parecidos (coseno); sin red ni modelos."""

    model_name: str = "fake-embeddings"
    dimensions: int = 32

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for word in re.findall(r"\w{3,}", text.lower()):
            digest = hashlib.sha256(word.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dimensions] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]
