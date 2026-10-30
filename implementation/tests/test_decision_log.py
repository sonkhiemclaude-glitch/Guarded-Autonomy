from guarded_autonomy.decision_log import HashChainLog


def test_detects_edit_against_anchor(tmp_path):
    log = HashChainLog()
    for k in range(5):
        log.append({"k": k})
    head = log.anchor()["head"]
    assert log.verify(head)
    log.entries[2]["body"] = '{"k": 99}'
    assert not log.verify(head)


def test_full_rewrite_undetected_without_anchor():
    real, forged = HashChainLog(), HashChainLog()
    for k in range(3):
        real.append({"k": k})
    for k in (0, 99, 2):
        forged.append({"k": k})
    assert forged.verify() and not forged.verify(real.head)


def test_jsonl_roundtrip(tmp_path):
    log = HashChainLog()
    for k in range(4):
        log.append({"k": k, "tier": "base"})
    p = tmp_path / "log.jsonl"
    log.save_jsonl(p)
    back = HashChainLog.load_jsonl(p)
    assert back.head == log.head and back.verify(log.head)
