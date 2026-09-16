from parrec2dcm.database.records import ParameterPool, load_parameter_pool


def test_pool_indexes_by_name():
    pool = ParameterPool(
        [
            {"Name": "A", "Value": 1},
            {"Name": "B", "Value": 2},
        ]
    )
    assert len(pool) == 2
    assert pool.has("A")
    assert pool.get("A") == 1
    assert pool.get("C", default="missing") == "missing"


def test_later_source_wins_on_collision():
    pool = ParameterPool([{"Name": "A", "Value": 1}, {"Name": "A", "Value": 2}])
    assert pool.get("A") == 2


def test_load_parameter_pool_merges_multiple_files(tmp_path):
    import json

    file_a = tmp_path / "a.json"
    file_b = tmp_path / "b.json"
    file_a.write_text(json.dumps([{"Name": "RFR_x", "Value": 1}]))
    file_b.write_text(json.dumps([{"Name": "EX_y", "Value": 2}]))

    pool = load_parameter_pool([file_a, file_b])
    assert len(pool) == 2
    assert pool.get("RFR_x") == 1
    assert pool.get("EX_y") == 2
