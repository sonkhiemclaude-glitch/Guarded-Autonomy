"""The repository must not ship result files presented as real results."""
import json
import hashlib


def test_outputs_dir_is_not_versioned(repo_root):
    """Generated output is git-ignored; only outputs/.gitkeep is part of the repository."""
    lines = (repo_root / ".gitignore").read_text().split()
    assert "outputs/*" in lines and "!outputs/.gitkeep" in lines
    assert (repo_root / "outputs" / ".gitkeep").exists()


def test_demo_outputs_if_present_are_labelled(repo_root):
    for md in (repo_root / "outputs").rglob("synthetic_demo/run_metadata.json"):
        meta = json.loads(md.read_text())
        assert meta["synthetic"] is True and "not a paper result" in meta["label"]
        assert (md.parent / "README_SYNTHETIC.txt").exists()


def test_examples_are_labelled_synthetic(repo_root):
    ex = repo_root / "examples" / "synthetic_data"
    for p in ex.rglob("run_config.json"):
        cfg = json.loads(p.read_text())
        assert cfg["synthetic"] is True and "not a paper result" in cfg["label"]


def test_no_result_tables_in_package_source(repo_root):
    src = repo_root / "src"
    assert not [p for p in src.rglob("*") if p.suffix in (".csv", ".json", ".png", ".pdf")]


def test_legacy_evidence_is_documented(repo_root):
    legacy = repo_root / "paper_evidence_v1"
    if legacy.exists():
        assert (legacy / "results" / "code_sha256.txt").exists()
        for line in (legacy / "results" / "code_sha256.txt").read_text().splitlines():
            expected, relative = line.split(maxsplit=1)
            assert hashlib.sha256((legacy / relative).read_bytes()).hexdigest() == expected
