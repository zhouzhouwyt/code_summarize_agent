"""Local text embedding adapter for question-based research history."""

import hashlib
from pathlib import Path

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class LocalEmbedder:
    """Run a cached SentenceTransformer on CPU, without implicit network downloads."""

    def __init__(self, model: str = DEFAULT_MODEL):
        from huggingface_hub import snapshot_download
        from sentence_transformers import SentenceTransformer

        local = Path(model)
        folder = local.resolve() if local.is_dir() else Path(snapshot_download(model, local_files_only=True))
        # Include actual weights/tokenizer contents so changed models cannot share vectors.
        digest = hashlib.sha256()
        artifacts = sorted(p for p in folder.rglob("*") if p.is_file() and
                           (p.suffix in {".json", ".safetensors", ".bin"}))
        for artifact in artifacts:
            digest.update(artifact.relative_to(folder).as_posix().encode())
            with artifact.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
        self.identity = "sentence-transformers-cpu:" + digest.hexdigest()
        self.model_name = model
        self.model = SentenceTransformer(str(folder), device="cpu", local_files_only=True,
                                         trust_remote_code=False)
        dimension_getter = getattr(self.model, "get_embedding_dimension", None) or self.model.get_sentence_embedding_dimension
        self.dimension = dimension_getter()
        self.max_tokens = self.model.max_seq_length
        self.tokenizer = self.model.tokenizer

    def windows(self, text: str):
        """Split embedding text using real token offsets, retaining overlapping evidence."""
        offsets = self.tokenizer(text, add_special_tokens=False, truncation=False, verbose=False,
                                 return_offsets_mapping=True)["offset_mapping"]
        width = self.max_tokens - self.tokenizer.num_special_tokens_to_add(pair=False)
        if width < 8:
            raise ValueError("Embedding model context is too small")
        overlap = min(24, width // 4)
        start = 0
        while start < len(offsets):
            end = min(start + width, len(offsets))
            left, right = offsets[start][0], offsets[end - 1][1]
            # Slicing through a subword can change tokenization. Recheck the actual
            # substring rather than relying on token counts from the full document.
            while len(self.tokenizer(text[left:right], add_special_tokens=False,
                                     truncation=False, verbose=False)["input_ids"]) > width:
                end -= 1
                if end <= start:
                    raise ValueError("Cannot fit source token into embedding context")
                right = offsets[end - 1][1]
            if right > left:
                yield left, right
            if end == len(offsets):
                break
            start = max(start + 1, end - overlap)

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Embed on CPU using the same model for documents and queries."""
        if not texts:
            return []
        lengths = self.tokenizer(texts, truncation=False, padding=False, verbose=False)["input_ids"]
        if any(len(ids) > self.max_tokens for ids in lengths):
            raise ValueError("Embedding input exceeds model context; split it before encoding")
        return self.model.encode(texts, batch_size=16, normalize_embeddings=True,
                                 show_progress_bar=False).tolist()


