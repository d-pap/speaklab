import hashlib
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "coaching_data", Path(__file__).resolve().parents[2] / "scripts" / "prepare-coaching-data.py"
)
corpus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(corpus)


@pytest.fixture
def reference(tmp_path):
    source = "Original complete user input.\nOriginal complete assistant response."
    (tmp_path / "reference.md").write_text(source)
    example = {
        "id": "one", "source": "reference.md", "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "task": "review", "split": "eval", "context_verified": True, "quality_reviewed": True,
        "messages": [
            {"role": "user", "content": "Original complete user input."},
            {"role": "assistant", "content": "Original complete assistant response."},
        ],
    }
    return tmp_path, example


def test_inventory_does_not_enroll_references_in_training(reference):
    directory, _ = reference
    manifest, train, evaluation = corpus.prepare(directory, [])
    assert len(manifest["sources"]) == 1
    assert train == evaluation == []
    assert manifest["sources"][0]["split"] == "unassigned"


def test_reviewed_examples_keep_provenance_and_chosen_split(reference):
    directory, example = reference
    manifest, train, evaluation = corpus.prepare(directory, [example])
    assert not train
    assert evaluation[0]["messages"] == example["messages"]
    assert evaluation[0]["source_sha256"] == example["source_sha256"]
    assert manifest["sources"][0]["split"] == "eval"


def test_same_conversation_cannot_cross_split(reference):
    directory, example = reference
    with pytest.raises(ValueError, match="both training and evaluation"):
        corpus.prepare(directory, [example, {**example, "id": "two", "split": "train"}])


@pytest.mark.parametrize("change", [
    {"quality_reviewed": False}, {"context_verified": False}, {"source_sha256": "changed"},
    {"messages": [{"role": "user", "content": "Original complete user input."},
                  {"role": "assistant", "content": "Invented target"}]},
])
def test_unverified_or_modified_examples_cannot_be_exported(reference, change):
    directory, example = reference
    with pytest.raises(ValueError):
        corpus.prepare(directory, [{**example, **change}])
