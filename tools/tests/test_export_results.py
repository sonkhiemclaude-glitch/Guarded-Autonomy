"""Check that numerical releases cannot bypass coverage/integrity or expose reports."""
from pathlib import Path
import csv
import hashlib
import importlib.util
import json
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("result_export", ROOT/"tools/export_results.py")
export=importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)

def digest(data):
    return hashlib.sha256(data).hexdigest()

@pytest.fixture
def analysis(tmp_path):
    folder=tmp_path/"analysis"
    folder.mkdir()
    coverage={"complete":True,"expected":1190,"accepted":1190,
              "analysis_code_sha256":export.sha(ROOT/"scripts/analyse_research_matrix.py")}
    (folder/"coverage.json").write_text(json.dumps(coverage))
    for name in export.ALLOWED-{"coverage.json"}:
        with (folder/name).open("w",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=["payload_file","condition","mean","n_valid"])
            writer.writeheader()
            writer.writerow({"payload_file":"/private/author/project/research_v3/payloads/heldout.json",
                             "condition":json.dumps({"payload_file":"/private/author/project/research_v3/payloads/heldout.json"}),
                             "mean":"-0.07580000000000001","n_valid":"10"})
    (folder/"report.pdf").write_bytes(b"private report fixture")
    (folder/"RESULTS_VI.md").write_text("private narrative fixture")
    rehash(folder)
    return folder

def rehash(folder):
    hashes={p.name:export.sha(p) for p in folder.iterdir() if p.name!="artifact_sha256.json"}
    (folder/"artifact_sha256.json").write_text(json.dumps(hashes))

def run(monkeypatch,analysis,output):
    monkeypatch.setattr(sys,"argv",["export_results.py","--analysis",str(analysis),"--output",str(output)])
    export.main()

def test_release_keeps_numbers_but_excludes_reports_and_private_root(monkeypatch,analysis,tmp_path):
    out=tmp_path/"release"
    run(monkeypatch,analysis,out)
    assert {p.name for p in out.iterdir()}==export.ALLOWED|{"release_manifest.json"}
    for path in out.glob("*.csv"):
        text=path.read_text()
        assert "/private/author/project" not in text
        row=next(csv.DictReader(text.splitlines()))
        assert row["mean"]=="-0.07580000000000001" and row["n_valid"]=="10"
        assert row["payload_file"].startswith("${PROJECT_ROOT}/")
    manifest=json.loads((out/"release_manifest.json").read_text())
    for name,record in manifest["files"].items():
        assert record["source_sha256"]==export.sha(analysis/name)
        assert record["released_sha256"]==export.sha(out/name)

@pytest.mark.parametrize("change",[{"accepted":1189},{"complete":False},{"synthetic":True},{"analysis_code_sha256":"0"*64}])
def test_invalid_coverage_never_creates_release(monkeypatch,analysis,tmp_path,change):
    p=analysis/"coverage.json";coverage=json.loads(p.read_text());coverage.update(change);p.write_text(json.dumps(coverage));rehash(analysis)
    out=tmp_path/"release"
    with pytest.raises(SystemExit):run(monkeypatch,analysis,out)
    assert not out.exists()

def test_tampered_file_never_creates_release(monkeypatch,analysis,tmp_path):
    (analysis/"condition_summary.csv").write_text("tampered")
    out=tmp_path/"release"
    with pytest.raises(SystemExit,match="checksum mismatch"):run(monkeypatch,analysis,out)
    assert not out.exists()

def test_missing_summary_never_creates_release(monkeypatch,analysis,tmp_path):
    (analysis/"condition_summary.csv").unlink();rehash(analysis)
    out=tmp_path/"release"
    with pytest.raises(SystemExit,match="missing"):run(monkeypatch,analysis,out)
    assert not out.exists()

def test_existing_release_is_preserved(monkeypatch,analysis,tmp_path):
    out=tmp_path/"release";out.mkdir();sentinel=out/"earlier.csv";sentinel.write_text("keep")
    with pytest.raises(SystemExit,match="not empty"):run(monkeypatch,analysis,out)
    assert sentinel.read_text()=="keep" and list(out.iterdir())==[sentinel]

def test_manifest_path_traversal_is_rejected(monkeypatch,analysis,tmp_path):
    p=analysis/"artifact_sha256.json";hashes=json.loads(p.read_text());hashes["../secret.txt"]="0"*64;p.write_text(json.dumps(hashes))
    out=tmp_path/"release"
    with pytest.raises(SystemExit,match="Unsafe"):run(monkeypatch,analysis,out)
    assert not out.exists()
