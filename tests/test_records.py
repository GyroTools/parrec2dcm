from parrec2dcm.database.records import ParameterPool, load_parameter_pool, load_records


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


def test_load_records_flattens_agora_task_parametersets_file(tmp_path):
    # Shape a real Agora task's parameters.json takes (one entry per
    # ParameterSet attached to the dataset -- see
    # DataSetBaseSerializer.get_parameters_path in agora-web).
    import json

    path = tmp_path / "parameters.json"
    path.write_text(
        json.dumps(
            [
                {"name": "database", "parameters": [{"Name": "RFR_x", "Value": 1}]},
                {"name": "goal", "parameters": [{"Name": "EX_y", "Value": 2}]},
            ]
        )
    )

    records = load_records(path)
    assert {r["Name"]: r["Value"] for r in records} == {"RFR_x": 1, "EX_y": 2}


def test_load_parameter_pool_accepts_agora_task_parametersets_file(tmp_path):
    import json

    path = tmp_path / "parameters.json"
    path.write_text(
        json.dumps(
            [
                {"name": "database", "parameters": [{"Name": "RFR_x", "Value": 1}]},
                {"name": "goal", "parameters": [{"Name": "EX_y", "Value": 2}]},
            ]
        )
    )

    pool = load_parameter_pool([path])
    assert len(pool) == 2
    assert pool.get("RFR_x") == 1
    assert pool.get("EX_y") == 2


def test_load_records_handles_empty_parametersets_file(tmp_path):
    import json

    path = tmp_path / "parameters.json"
    path.write_text(json.dumps([]))

    assert load_records(path) == []


def test_load_records_parameterset_with_empty_parameters_list(tmp_path):
    # A ParameterSet with no parameters (get_parameters() returned []) --
    # still a valid parameter-set entry, just contributing nothing.
    import json

    path = tmp_path / "parameters.json"
    path.write_text(json.dumps([{"name": "empty_set", "parameters": []}]))

    assert load_records(path) == []
