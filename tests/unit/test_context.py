"""Context engine unit tests: evidence, chunking, search, embeddings, retrieval."""

from __future__ import annotations

import pytest

from cle.context.chunker import chunk_text
from cle.context.embeddings import EmbeddingStore, _cosine
from cle.evidence import EvidenceSource, assert_no_upgrade
from cle.tools.search import search as exact_search

# -- evidence ---------------------------------------------------------------

def test_evidence_upgrade_forbidden():
    with pytest.raises(ValueError):
        assert_no_upgrade(EvidenceSource.LOCAL, EvidenceSource.LIVE)
    with pytest.raises(ValueError):
        assert_no_upgrade(EvidenceSource.CACHED, EvidenceSource.LIVE)


def test_evidence_same_or_downgrade_ok():
    assert_no_upgrade(EvidenceSource.LIVE, EvidenceSource.CACHED)
    assert_no_upgrade(EvidenceSource.LOCAL, EvidenceSource.LOCAL)


# -- chunker ----------------------------------------------------------------

def test_chunk_text_windows_and_overlap():
    text = "\n".join(f"line{i}" for i in range(1, 101))
    chunks = chunk_text("f.py", text, window=30, overlap=10)
    assert chunks[0].start == 1 and chunks[0].end == 30
    # step = 20, so second chunk starts at line 21
    assert chunks[1].start == 21
    # covers to the end
    assert chunks[-1].end == 100


def test_chunk_empty():
    assert chunk_text("f.py", "") == []


# -- exact search -----------------------------------------------------------

def test_exact_search_finds_matches(tmp_path):
    (tmp_path / "a.txt").write_text("hello world\nfoo bar\nhello again\n", encoding="utf-8")
    matches = exact_search(tmp_path, "hello")
    assert len(matches) == 2
    assert all(m.source == EvidenceSource.LOCAL for m in matches)
    assert matches[0].line == 1


def test_exact_search_excludes_vendor_dirs(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "src" / "a.txt").write_text("needle\n", encoding="utf-8")
    (tmp_path / "node_modules" / "b.txt").write_text("needle\n", encoding="utf-8")
    matches = exact_search(tmp_path, "needle")
    paths = {m.path for m in matches}
    assert "src/a.txt" in paths
    assert not any("node_modules" in p for p in paths)


def test_python_search_fallback_when_no_ripgrep(tmp_path, monkeypatch):
    # Force the pure-Python path (rg is normally always present in CI/dev), so
    # the documented "works offline without ripgrep" guarantee is exercised.
    import cle.tools.search as search_mod
    monkeypatch.setattr(search_mod, "ripgrep_available", lambda: False)

    (tmp_path / "src").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "a.py").write_text("HELLO world\nfoo\nhello again\n", encoding="utf-8")
    (tmp_path / "node_modules" / "b.py").write_text("hello vendor\n", encoding="utf-8")

    # case-insensitive matches both HELLO and hello, and skips vendor dirs
    ci = exact_search(tmp_path, "hello", ignore_case=True)
    assert {m.line for m in ci} == {1, 3}
    assert all(m.source == EvidenceSource.LOCAL for m in ci)
    assert not any("node_modules" in m.path for m in ci)

    # fixed-string treats regex metachars literally
    (tmp_path / "c.py").write_text("a.b\naxb\n", encoding="utf-8")
    lit = exact_search(tmp_path, "a.b", fixed_string=True)
    assert [m.line for m in lit if m.path == "c.py"] == [1]


# -- embeddings (fake provider) ---------------------------------------------

def test_cosine():
    assert _cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert _cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert _cosine([], [1]) == 0.0


class _DirectionalProvider:
    """Embeds text to a 2D vector so similarity is deterministic and testable."""

    def embed(self, model, text):
        # "cat"-ish → [1,0]; "dog"-ish → [0,1]; else mixed.
        t = text.lower()
        return [float(t.count("cat")) + 1.0, float(t.count("dog")) + 1.0]

    # unused interface members
    def health(self): ...
    def list_models(self): ...
    def generate(self, *a, **k): ...
    def chat(self, *a, **k): ...
    def stream(self, *a, **k): ...


def test_embedding_store_build_and_search(tmp_path):
    from cle.indexing.database import IndexDatabase

    (tmp_path / "cats.py").write_text("cat cat cat\n" * 3, encoding="utf-8")
    (tmp_path / "dogs.py").write_text("dog dog dog\n" * 3, encoding="utf-8")
    db = IndexDatabase(tmp_path / ".cle" / "index" / "index.db")
    store = EmbeddingStore(db, _DirectionalProvider(), "fake-embed")
    count = store.build(tmp_path)
    assert count >= 2
    assert store.is_built()

    hits = store.search("cat cat cat", top_k=2)
    assert hits[0].path == "cats.py"
    db.close()


def test_search_rejects_embedding_model_mismatch(tmp_path):
    # Built with 'fake-embed'; querying under a different model would compare
    # incompatible vectors (all-zero cosine). Must fail loud, not silently.
    from cle.errors import ProviderError
    from cle.indexing.database import IndexDatabase

    (tmp_path / "cats.py").write_text("cat cat cat\n" * 3, encoding="utf-8")
    db = IndexDatabase(tmp_path / ".cle" / "index" / "index.db")
    EmbeddingStore(db, _DirectionalProvider(), "fake-embed").build(tmp_path)

    stale = EmbeddingStore(db, _DirectionalProvider(), "a-different-model")
    with pytest.raises(ProviderError) as exc:
        stale.search("cat cat cat")
    assert "cle embed" in (exc.value.remedy or "")
    db.close()


# -- context manager (token budget) -----------------------------------------

def test_context_manager_truncates_to_token_budget(tmp_path):
    from cle.config import init_project_config, load_config, set_project_value
    from cle.context.manager import ContextManager
    from cle.context.retrieval import ContextItem

    init_project_config(tmp_path)
    set_project_value(tmp_path, "context.max_tokens", 50)   # ~200 char budget
    cfg = load_config(tmp_path)

    items = [
        ContextItem(path=f"f{i}.py", line_start=1, line_end=2, kind="chunk",
                    symbol=None, relevance=1.0, reason="r", text="x" * 150)
        for i in range(5)
    ]
    block, included = ContextManager(cfg).build_block(items)
    assert 1 <= len(included) < len(items)   # first always kept, rest truncated
    assert block.count("```") == len(included) * 2


def test_context_manager_keeps_all_within_budget(tmp_path):
    from cle.config import init_project_config, load_config
    from cle.context.manager import ContextManager
    from cle.context.retrieval import ContextItem

    init_project_config(tmp_path)   # default budget is generous (8000 tokens)
    cfg = load_config(tmp_path)
    items = [
        ContextItem(path=f"f{i}.py", line_start=1, line_end=2, kind="chunk",
                    symbol=None, relevance=1.0, reason="r", text="small")
        for i in range(3)
    ]
    _, included = ContextManager(cfg).build_block(items)
    assert len(included) == 3
