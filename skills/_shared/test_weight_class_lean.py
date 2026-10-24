"""Lean recommend_class rubric (weight-class-lean-default, Behaviors 1-4).

Order: novelty high -> spike; risk or blast radius high -> full;
every axis minimal -> just-do-it; everything else -> light.
Unknown axis value counts as medium and the justification says "warning".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from weight_class import VALID_CLASSES, read_class, recommend_class  # noqa: E402


def test_all_minimal_is_just_do_it():
    klass, why = recommend_class("low", "low", "high", "low")
    assert klass == "just-do-it"
    assert why


def test_novelty_high_is_spike():
    klass, why = recommend_class("low", "low", "high", "high")
    assert klass == "spike"
    assert "novelty" in why


def test_novelty_high_beats_risk_high():
    assert recommend_class("high", "low", "high", "high")[0] == "spike"


def test_risk_high_is_full():
    klass, why = recommend_class("high", "low", "high", "low")
    assert klass == "full"
    assert "risk" in why


def test_blast_radius_high_is_full():
    klass, why = recommend_class("low", "high", "high", "low")
    assert klass == "full"
    assert "blast" in why


def test_one_medium_is_light():
    assert recommend_class("medium", "low", "high", "low")[0] == "light"


def test_two_mediums_is_light():
    assert recommend_class("medium", "medium", "high", "low")[0] == "light"


def test_three_mediums_is_light():
    assert recommend_class("medium", "medium", "medium", "low")[0] == "light"


def test_low_reversibility_only_is_light():
    klass, why = recommend_class("low", "low", "low", "low")
    assert klass == "light"
    assert "reversibility" in why


def test_medium_risk_plus_high_blast_is_full():
    assert recommend_class("medium", "high", "high", "low")[0] == "full"


def test_unknown_axis_counts_as_medium_with_warning():
    for args in (
        ("banana", "low", "high", "low"),
        ("low", "", "high", "low"),
        ("low", "low", None, "low"),
        ("low", "low", "high", "LOWISH"),
    ):
        klass, why = recommend_class(*args)
        assert klass == "light"
        assert "warning" in why


def test_every_class_reachable():
    reached = {
        recommend_class("low", "low", "high", "low")[0],
        recommend_class("low", "low", "high", "high")[0],
        recommend_class("medium", "low", "high", "low")[0],
        recommend_class("high", "high", "low", "low")[0],
    }
    assert reached == set(VALID_CLASSES)


def test_read_class_default_stays_full(tmp_path):
    assert read_class(tmp_path) == ("full", "default")
    (tmp_path / "design.md").write_text("---\nweight-class: enormous\n---\n")
    assert read_class(tmp_path) == ("full", "default")
