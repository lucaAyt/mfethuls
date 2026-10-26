"""Finding raw data that the registry does not describe yet."""

import os
from pathlib import Path

import pandas as pd

from mfethuls import Registry
from mfethuls.discovery import (
    REGISTRY_COLUMNS,
    chosen_rows,
    discover_unregistered,
    overlapping_folders,
    proposed_rows,
    sync_folder_ticks,
    tree_rows,
)
from mfethuls.examples import DATA_DIR

def _touch(path: Path, text: str = "data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")
    return path


def _registry(*rows: dict) -> Registry:
    return Registry.from_frame(pd.DataFrame(list(rows), columns=["name", "instrument_name", "raw_data_filename"]))


def _items(tmp_path, registry=None):
    return {item.key: item for item in discover_unregistered(registry or _registry(), str(tmp_path))}


def test_top_level_files_are_found_unless_registered_for_that_instrument(tmp_path):
    _touch(tmp_path / "DSC" / "poly1.txt")
    _touch(tmp_path / "DSC" / "poly2.txt")
    _touch(tmp_path / "TGA" / "poly1.txt")
    registry = _registry({"name": "LB_dsc_001", "instrument_name": "dsc", "raw_data_filename": "poly1"})

    # poly1 is registered for DSC only; the TGA file of the same name is still new.
    assert set(_items(tmp_path, registry)) == {"DSC/poly2", "TGA/poly1"}


def test_the_folders_instrument_is_prefilled(tmp_path):
    _touch(tmp_path / "DSC" / "poly1.txt")
    _touch(tmp_path / "TGA" / "poly1.txt")
    items = _items(tmp_path)

    rows = proposed_rows(items.values(), _registry()).set_index("_folder")

    # One instrument per folder, whichever DSC export the file is (its reader is found at ingest).
    assert items["DSC/poly1"].instruments == ["dsc"]
    assert rows.loc["DSC", "instrument_name"] == "dsc"
    assert rows.loc["TGA", "instrument_name"] == "tga"


def test_run_files_in_a_subfolder_default_to_one_row_per_file(tmp_path):
    _touch(tmp_path / "DSC" / "poly1" / "poly1_run2.txt")
    _touch(tmp_path / "DSC" / "poly1" / "poly1_run1.txt")
    (item,) = _items(tmp_path).values()

    assert item.layout == "folder" and item.split_by_default
    assert list(item.runs) == ["poly1_run1", "poly1_run2"]

    rows = proposed_rows([item], _registry())
    assert rows[["raw_data_filename", "run_id", "_folder"]].values.tolist() == [
        ["poly1_run1", "R001", "DSC/poly1"],
        ["poly1_run2", "R002", "DSC/poly1"],
    ]

    whole = proposed_rows([item], _registry(), split=set())
    assert whole[["raw_data_filename", "run_id"]].values.tolist() == [["poly1", "R001"]]


def test_series_folder_defaults_to_one_experiment(tmp_path):
    for i in range(3):
        _touch(tmp_path / "Fluorescence" / "poly3" / f"poly3__{i}.txt")
    _touch(tmp_path / "NMR" / "EXP015" / "1" / "fid")
    _touch(tmp_path / "NMR" / "EXP015" / "1" / "pdata" / "1" / "1r")
    items = _items(tmp_path)

    assert set(items) == {"Fluorescence/poly3", "NMR/EXP015"}  # Bruker subfolders are not experiments
    assert not items["Fluorescence/poly3"].split_by_default
    assert len(items["Fluorescence/poly3"].files) == 3

    rows = proposed_rows(items.values(), _registry()).set_index("raw_data_filename")
    assert rows.loc["poly3", "instrument_name"] == "fluorescence"
    assert rows.loc["EXP015", "instrument_name"] == "nmr"


def test_uv_vis_single_spectrum_and_titration_folder(tmp_path):
    _touch(tmp_path / "UV_Vis" / "compoundA.txt")
    for step in ("step01", "step02", "step03"):
        _touch(tmp_path / "UV_Vis" / "titration_A" / f"{step}.txt")
    items = _items(tmp_path)

    single, titration = items["UV_Vis/compoundA"], items["UV_Vis/titration_A"]
    assert single.layout == "file" and single.suggested == "uv_vis"
    # A folder in UV_Vis is kept whole by default (the Flame records series) ...
    assert titration.layout == "folder" and not titration.split_by_default
    assert titration.suggested == "uv_vis"
    rows = proposed_rows(items.values(), _registry())
    assert sorted(rows["raw_data_filename"]) == ["compoundA", "titration_A"]

    # ... but can still be registered one spectrum per row, on the Shimadzu.
    per_file = proposed_rows([titration], _registry(), split={"UV_Vis/titration_A"})
    assert per_file[["raw_data_filename", "instrument_name", "run_id"]].values.tolist() == [
        ["step01", "uv_vis", "R001"],
        ["step02", "uv_vis", "R002"],
        ["step03", "uv_vis", "R003"],
    ]


def test_ignores_hidden_parquet_manifest_and_other_extensions(tmp_path):
    _touch(tmp_path / "DSC" / ".hidden.txt")
    _touch(tmp_path / "DSC" / "cached.parquet")
    _touch(tmp_path / "DSC" / ".gitkeep")
    _touch(tmp_path / "DSC" / "notes.docx")
    _touch(tmp_path / "DSC" / ".cache" / "poly9.txt")
    _touch(tmp_path / ".mfethuls_manifest.json")

    assert _items(tmp_path) == {}


def test_same_name_in_two_folders_cannot_be_registered_per_file(tmp_path):
    _touch(tmp_path / "DSC" / "2025" / "poly1.txt")
    _touch(tmp_path / "DSC" / "2025" / "poly3.txt")
    _touch(tmp_path / "DSC" / "2026" / "poly1.txt")
    _touch(tmp_path / "DSC" / "2026" / "poly2.txt")
    items = _items(tmp_path)

    assert "several folders" in items["DSC/2025"].run_issues["poly1"]
    rows = proposed_rows(items.values(), _registry())
    assert sorted(rows["raw_data_filename"]) == ["poly2", "poly3"]  # poly1 is left out in both folders
    # Registering the folders whole is still possible.
    assert sorted(proposed_rows(items.values(), _registry(), split=set())["raw_data_filename"]) == ["2025", "2026"]


def test_top_level_file_with_a_namesake_in_a_subfolder_is_reported(tmp_path):
    _touch(tmp_path / "TGA" / "poly1.txt")
    _touch(tmp_path / "TGA" / "old" / "poly1.txt")
    items = _items(tmp_path)

    assert "several folders" in items["TGA/poly1"].issue
    assert proposed_rows(items.values(), _registry()).empty


def test_folder_around_a_single_file_is_proposed_as_that_file(tmp_path):
    _touch(tmp_path / "DSC" / "LUB055" / "LUB055.txt")
    items = _items(tmp_path)

    assert set(items) == {"DSC/LUB055"}
    assert items["DSC/LUB055"].layout == "file"
    assert list(proposed_rows(items.values(), _registry())["raw_data_filename"]) == ["LUB055"]


def test_run_named_like_its_folder_is_registered_by_file_name(tmp_path):
    _touch(tmp_path / "DSC" / "LUB055" / "LUB055.txt")
    _touch(tmp_path / "DSC" / "LUB055" / "LUB055_b.txt")
    items = _items(tmp_path)

    rows = proposed_rows(items.values(), _registry())  # DSC folders split per file by default
    assert rows[["name", "raw_data_filename"]].values.tolist() == [["LUB055", "LUB055.txt"], ["LUB055_b", "LUB055_b"]]
    whole = proposed_rows(items.values(), _registry(), split=set())
    assert list(whole["raw_data_filename"]) == ["LUB055"]

    # Once registered by file name, that run is not proposed again.
    registry = _registry({"name": "LUB055", "instrument_name": "dsc", "raw_data_filename": "LUB055.txt"})
    assert list(_items(tmp_path, registry)["DSC/LUB055"].runs) == ["LUB055_b"]


def test_files_no_instrument_reads_are_ignored_and_listed(tmp_path):
    _touch(tmp_path / "DSC" / "LUB055" / "LUB055.txt")
    _touch(tmp_path / "DSC" / "LUB055" / "LUB055_plot.svg")
    _touch(tmp_path / "DSC" / "batch" / "poly1.txt")
    _touch(tmp_path / "DSC" / "batch" / "poly2.csv")  # DSC parsers that read .csv make this data
    _touch(tmp_path / "DSC" / "batch" / "notes.docx")
    _touch(tmp_path / "DSC" / "poly3.txt")
    _touch(tmp_path / "DSC" / "poly3.png")
    _touch(tmp_path / "DSC" / "plots" / "overview.svg")  # no data at all: not proposed
    items = _items(tmp_path)

    assert set(items) == {"DSC/LUB055", "DSC/batch", "DSC/poly3"}
    assert items["DSC/LUB055"].layout == "file"  # the plot does not make it a multi-file folder
    assert items["DSC/LUB055"].ignored == [str(Path("LUB055") / "LUB055_plot.svg")]
    assert list(items["DSC/batch"].runs) == ["poly1", "poly2"]
    assert items["DSC/batch"].ignored == [str(Path("batch") / "notes.docx")]
    assert items["DSC/poly3"].ignored == ["poly3.png"]
    assert not any(item.issue for item in items.values())


def test_registered_folders_and_runs_are_skipped(tmp_path):
    _touch(tmp_path / "Fluorescence" / "poly3" / "a.txt")
    _touch(tmp_path / "DSC" / "poly1" / "poly1_run1.txt")
    _touch(tmp_path / "DSC" / "poly1" / "poly1_run2.txt")
    registry = _registry(
        {"name": "fl", "instrument_name": "fluorescence", "raw_data_filename": "poly3"},
        {"name": "run1", "instrument_name": "dsc", "raw_data_filename": "poly1_run1"},
    )
    items = _items(tmp_path, registry)

    assert set(items) == {"DSC/poly1"}
    assert list(items["DSC/poly1"].runs) == ["poly1_run2"]


def test_invalid_and_placeholder_rows_still_count_as_registered(tmp_path):
    _touch(tmp_path / "DSC" / "typo_row.txt")
    _touch(tmp_path / "DSC" / "placeholder.txt")
    registry = _registry(
        {"name": "typo_row", "instrument_name": "dsc_no_such_model", "raw_data_filename": None},
        {"name": "placeholder", "instrument_name": None, "raw_data_filename": None},
    )
    assert [p.name for p in registry.problems if p.skipped] == ["typo_row"]

    # The placeholder row covers its file; the misspelt instrument is not a DSC model.
    assert set(_items(tmp_path, registry)) == {"DSC/typo_row"}


def test_proposed_names_are_unique_and_columns_follow_the_registry(tmp_path):
    _touch(tmp_path / "TGA" / "poly1.txt")
    _touch(tmp_path / "FTIR" / "poly1.csv")
    registry = Registry.from_frame(
        pd.DataFrame([{"name": "poly1", "instrument_name": "dsc", "raw_data_filename": "other", "operator": "LB"}])
    )

    rows = proposed_rows(discover_unregistered(registry, str(tmp_path)), registry)

    assert sorted(rows["name"]) == ["poly1_2", "poly1_3"]
    assert list(rows.columns) == REGISTRY_COLUMNS + ["operator", "_folder", "_modified"]


def _proposals_for(tmp_path, registry):
    return proposed_rows(discover_unregistered(registry, str(tmp_path)), registry)


def test_validate_proposed_requires_instrument_and_found_data(tmp_path):
    from mfethuls.discovery import validate_proposed

    # A real Mettler Toledo export: the chosen instrument must be able to read it.
    (tmp_path / "DSC").mkdir()
    (tmp_path / "DSC" / "poly2.txt").write_bytes((DATA_DIR / "DSC" / "poly2.txt").read_bytes())
    registry = _registry()
    rows = _proposals_for(tmp_path, registry)

    (ready,) = validate_proposed(registry, rows, str(tmp_path))
    assert ready["valid"], ready["errors"]

    rows.loc[0, "instrument_name"] = None
    (missing_instrument,) = validate_proposed(registry, rows, str(tmp_path))
    assert not missing_instrument["valid"]
    assert any(e["message"] == "Choose the instrument." for e in missing_instrument["errors"])
    rows.loc[0, "instrument_name"] = "dsc"

    rows.loc[0, "raw_data_filename"] = "not_on_disk"
    (missing_data,) = validate_proposed(registry, rows, str(tmp_path))
    assert any(e["field"] == "data_path" for e in missing_data["errors"])


def test_names_with_spaces_and_brackets_can_be_registered(tmp_path):
    from mfethuls.discovery import validate_proposed

    sample = (DATA_DIR / "DSC" / "poly2.txt").read_bytes()
    _touch(tmp_path / "DSC" / "poly 2 (repeat).txt").write_bytes(sample)
    _touch(tmp_path / "DSC" / "My Sample" / "run A.txt").write_bytes(sample)
    _touch(tmp_path / "DSC" / "My Sample" / "run B.txt").write_bytes(sample)
    registry = _registry()
    rows = _proposals_for(tmp_path, registry)
    assert set(rows["instrument_name"]) == {"dsc"}
    assert sorted(rows["raw_data_filename"]) == ["poly 2 (repeat)", "run A", "run B"]
    assert all(result["valid"] for result in validate_proposed(registry, rows, str(tmp_path)))


def test_validate_proposed_checks_against_existing_rows_and_bad_ids(tmp_path):
    from mfethuls.discovery import validate_proposed

    _touch(tmp_path / "TGA" / "poly2.txt")
    registry = _registry({"name": "poly2", "instrument_name": "dsc", "raw_data_filename": "other"})
    rows = _proposals_for(tmp_path, registry)
    rows.loc[0, "name"] = "poly2"  # clashes with the existing row
    rows.loc[0, "sample_id"] = "S1"  # malformed

    (result,) = validate_proposed(registry, rows, str(tmp_path))

    messages = " ".join(e["message"] for e in result["errors"])
    assert "'poly2' is used by more than one row" in messages
    assert "Invalid sample_id: 'S1'" in messages


def test_folder_whose_runs_are_all_registered_is_not_new(tmp_path):
    _touch(tmp_path / "DSC" / "polyX" / "polyX_run1.txt")
    _touch(tmp_path / "DSC" / "polyX" / "polyX_run2.txt")
    registry = _registry(
        {"name": "r1", "instrument_name": "dsc", "raw_data_filename": "polyX_run1"},
        {"name": "r2", "instrument_name": "dsc", "raw_data_filename": "polyX_run2"},
    )

    assert _items(tmp_path, registry) == {}


def _aged(path: Path, days_old: float) -> Path:
    import os
    import time

    stamp = time.time() - days_old * 86400
    os.utime(path, (stamp, stamp))
    return path


def _filter_fixture(tmp_path):
    _aged(_touch(tmp_path / "DSC" / "old_run.txt"), 90)
    _aged(_touch(tmp_path / "TGA" / "recent.txt"), 2)
    _aged(_touch(tmp_path / "DSC" / "projectA" / "chitosan_run1.txt"), 10)
    _aged(_touch(tmp_path / "DSC" / "projectA" / "chitosan_run2.txt"), 12)
    return discover_unregistered(_registry(), str(tmp_path))


def test_filter_new_data_without_filters_returns_everything_newest_first(tmp_path):
    from mfethuls.discovery import filter_new_data

    items = filter_new_data(_filter_fixture(tmp_path))

    assert [item.key for item in items] == ["TGA/recent", "DSC/projectA", "DSC/old_run"]


def test_filter_new_data_by_age_folder_and_text(tmp_path):
    from datetime import datetime, timedelta

    from mfethuls.discovery import filter_new_data

    items = _filter_fixture(tmp_path)
    month_ago = datetime.now() - timedelta(days=30)

    assert [i.key for i in filter_new_data(items, modified_since=month_ago)] == ["TGA/recent", "DSC/projectA"]
    assert [i.key for i in filter_new_data(items, folders={"DSC"})] == ["DSC/projectA", "DSC/old_run"]
    # Matches a file inside the subfolder, case-insensitively.
    assert [i.key for i in filter_new_data(items, text="CHITOSAN")] == ["DSC/projectA"]
    assert [i.key for i in filter_new_data(items, text="run")] == ["DSC/projectA", "DSC/old_run"]
    assert filter_new_data(items, folders={"DSC"}, modified_since=month_ago, text="old") == []


def test_the_storage_folder_is_not_an_instrument_folder(tmp_path):
    from mfethuls.discovery import instrument_folders, unclaimed_folders

    for folder in ("_storage", "Mystery", ".mfethuls"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "a.txt").write_text("1 2\n", encoding="utf-8")
    assert [entry.name for entry in instrument_folders(str(tmp_path))] == ["Mystery"]
    assert [folder.folder_name for folder in unclaimed_folders(str(tmp_path))] == ["Mystery"]


def test_counting_an_unclaimed_folder_stops_at_max_count(tmp_path, monkeypatch):
    from mfethuls.discovery import unclaimed_folders

    monkeypatch.setenv("PATH_TO_DATA", str(tmp_path))
    archive = tmp_path / "Archive"
    for sub in ("a", "b"):
        (archive / sub).mkdir(parents=True)
        for i in range(6):
            (archive / sub / f"f{i}.txt").write_text("x")
    (folder,) = unclaimed_folders(str(tmp_path), limit=3, max_count=5)
    assert (folder.file_count, folder.more, folder.count_label, len(folder.files)) == (5, True, "5+", 3)
    (folder,) = unclaimed_folders(str(tmp_path))
    assert (folder.file_count, folder.more, folder.count_label) == (12, False, "12")


def _tree(tmp_path, same_age=True):
    """The tree of everything under ``tmp_path``; files written in one go get one time, so rows are in path order."""
    if same_age:
        for path in tmp_path.rglob("*"):
            if path.is_file():
                os.utime(path, (1_700_000_000, 1_700_000_000))
    rows = tree_rows(discover_unregistered(_registry(), str(tmp_path)), _registry(), str(tmp_path))
    rows.insert(0, "include", False)
    return rows


def test_tree_rows_are_newest_first_with_run_ids_in_file_name_order(tmp_path):
    _aged(_touch(tmp_path / "DSC" / "aaa.txt"), 5)
    _aged(_touch(tmp_path / "DSC" / "batch" / "b_run1.txt"), 3)
    _aged(_touch(tmp_path / "DSC" / "batch" / "b_run2.txt"), 1)
    _aged(_touch(tmp_path / "DSC" / "poly2.txt"), 2)
    rows = _tree(tmp_path, same_age=False)

    # The folder counts from its newest file; its files are newest first, still numbered by name.
    assert rows[["_kind", "raw_data_filename", "run_id"]].values.tolist() == [
        ["folder", "batch", "R001"],
        ["run", "b_run2", "R002"],
        ["run", "b_run1", "R001"],
        ["file", "poly2", "R001"],
        ["file", "aaa", "R001"],
    ]


def test_tree_rows_show_each_folder_followed_by_its_files(tmp_path):
    _touch(tmp_path / "DSC" / "poly2.txt")
    _touch(tmp_path / "DSC" / "batch" / "b_run2.txt")
    _touch(tmp_path / "DSC" / "batch" / "b_run1.txt")
    _touch(tmp_path / "DSC" / "aaa.txt")
    rows = _tree(tmp_path)

    # Same age: in path order, each folder followed by its files; a DSC folder is not one experiment.
    assert rows[["_kind", "raw_data_filename", "run_id", "_folder", "_whole"]].values.tolist() == [
        ["file", "aaa", "R001", "DSC", False],
        ["folder", "batch", "R001", "DSC/batch", False],
        ["run", "b_run1", "R001", "DSC/batch", False],
        ["run", "b_run2", "R002", "DSC/batch", False],
        ["file", "poly2", "R001", "DSC", False],
    ]
    assert rows["_data"].tolist()[:3] == ["DSC/aaa.txt", "\U0001f4c1 DSC/batch/  \xb7  2 files",
                                          "\u2003\u2003\u2514 b_run1.txt"]


def test_ticking_a_folder_ticks_its_files(tmp_path):
    _touch(tmp_path / "DSC" / "aaa.txt")
    _touch(tmp_path / "DSC" / "batch" / "b_run1.txt")
    _touch(tmp_path / "DSC" / "batch" / "b_run2.txt")
    before = _tree(tmp_path)

    after = before.copy()
    after.loc[1, "include"] = True  # the folder
    ticked = sync_folder_ticks(before, after)
    assert ticked["include"].tolist() == [False, True, True, True]
    # The folder itself is not an experiment: its files are.
    assert chosen_rows(ticked)["raw_data_filename"].tolist() == ["b_run1", "b_run2"]

    # A file can then be unticked on its own; unticking the folder unticks the rest.
    edited = ticked.copy()
    edited.loc[3, "include"] = False
    one_off = sync_folder_ticks(ticked, edited)
    assert one_off["include"].tolist() == [False, True, True, False]
    assert chosen_rows(one_off)["raw_data_filename"].tolist() == ["b_run1"]
    unticked = one_off.copy()
    unticked.loc[1, "include"] = False
    assert sync_folder_ticks(one_off, unticked)["include"].tolist() == [False, False, False, False]


def test_a_series_folder_is_one_experiment_and_flagged_when_its_files_are_ticked_too(tmp_path):
    for step in ("step01", "step02"):
        _touch(tmp_path / "UV_Vis" / "titration_A" / f"{step}.txt")
    before = _tree(tmp_path)
    assert before[["_kind", "_whole"]].values.tolist() == [["folder", True], ["run", False], ["run", False]]

    after = before.copy()
    after.loc[0, "include"] = True
    ticked = sync_folder_ticks(before, after)
    assert ticked["include"].tolist() == [True, False, False]  # its files are left alone
    assert chosen_rows(ticked)["raw_data_filename"].tolist() == ["titration_A"]

    both = ticked.copy()
    both.loc[1, "include"] = True
    assert overlapping_folders(chosen_rows(sync_folder_ticks(ticked, both))) == ["UV_Vis/titration_A"]


def test_tree_rows_of_nothing_new(tmp_path):
    (tmp_path / "DSC").mkdir()
    assert tree_rows(discover_unregistered(_registry(), str(tmp_path)), _registry(), str(tmp_path)).empty


def test_closed_folders_hide_their_files_and_show_their_ticks(tmp_path):
    from mfethuls.discovery import visible_rows

    _touch(tmp_path / "DSC" / "aaa.txt")
    _touch(tmp_path / "DSC" / "batch" / "b_run1.txt")
    _touch(tmp_path / "DSC" / "batch" / "b_run2.txt")
    tree = _tree(tmp_path)
    assert tree["_open"].tolist() == [None, False, None, None]  # only folders open and close

    closed = visible_rows(tree)
    assert closed["_kind"].tolist() == ["file", "folder"]
    assert closed["_data"].tolist()[1] == "▸ \U0001f4c1 DSC/batch/  \xb7  2 files"

    edited = tree.copy()
    edited.loc[1, ["include", "_open"]] = [True, True]
    opened = visible_rows(sync_folder_ticks(tree, edited))
    assert opened.index.tolist() == [0, 1, 2, 3]  # labels kept: edits go back to the right rows
    assert opened["_data"].tolist()[1] == "▾ \U0001f4c1 DSC/batch/  \xb7  2 files  \xb7  2 of 2 ticked"

    # Opening a file row does nothing.
    stray = tree.copy()
    stray.loc[0, "_open"] = True
    assert sync_folder_ticks(tree, stray)["_open"].tolist() == [None, False, None, None]


def test_a_value_typed_in_a_folder_row_fills_in_its_files(tmp_path):
    _touch(tmp_path / "DSC" / "batch" / "b_run1.txt")
    _touch(tmp_path / "DSC" / "batch" / "b_run2.txt")
    _touch(tmp_path / "DSC" / "batch" / "b_run3.txt")
    tree = _tree(tmp_path)  # the folder, then its three files
    edited = tree.copy()
    edited.loc[3, "sample_id"] = "S002"  # one file has its own sample
    tree = sync_folder_ticks(tree, edited)

    edited = tree.copy()
    edited.loc[0, ["sample_id", "instrument_name", "name"]] = ["S001", "dsc", "renamed"]
    filled = sync_folder_ticks(tree, edited)
    assert filled["sample_id"].tolist() == ["S001", "S001", "S001", "S002"]
    assert filled["instrument_name"].tolist()[1:] == ["dsc"] * 3
    assert filled["name"].tolist()[1:] == ["b_run1", "b_run2", "b_run3"]  # each experiment keeps its own

    edited = filled.copy()
    edited.loc[0, "sample_id"] = "S003"  # files that followed the folder follow again
    assert sync_folder_ticks(filled, edited)["sample_id"].tolist() == ["S003", "S003", "S003", "S002"]


def test_one_file_per_folder_is_read_in_full_the_others_checked_quickly(tmp_path, monkeypatch):
    import mfethuls.discovery as discovery
    from mfethuls.discovery import validate_proposed

    sample = (DATA_DIR / "DSC" / "poly2.txt").read_bytes()
    for name in ("run1", "run2", "run3"):
        _touch(tmp_path / "DSC" / "batch" / f"{name}.txt").write_bytes(sample)
    _touch(tmp_path / "DSC" / "batch" / "run4.txt", "Curve Values:\n1\t2\n")  # another export kind
    read = []
    probe = discovery._probe_file

    def counted(*args):
        read.append(args[1])
        return probe(*args)

    monkeypatch.setattr(discovery, "_probe_file", counted)
    registry = _registry()
    rows = proposed_rows(discover_unregistered(registry, str(tmp_path)), registry, split={"DSC/batch"})
    rows["instrument_name"] = "dsc"

    results = validate_proposed(registry, rows, str(tmp_path))
    assert len(read) == 1 and read[0].endswith("run1.txt")
    assert [result["valid"] for result in results] == [True, True, True, False]
    assert "run4.txt is none of the dsc formats mfethuls reads" in results[3]["errors"][0]["message"]
