"""Neutral language lint and pseudonymization (default output must not leak real names)."""
import pytest

from casefile.records.neutrality import lint
from casefile.records.pseudonym import Pseudonymizer


@pytest.mark.parametrize("text", ["This was fraud.", "a Fraudulent scheme", "he is guilty", "corrupt dealings",
                                  "they tried to defraud", "a kickback", "criminal conduct", "illegal award"])
def test_lint_flags_wrongdoing_words(text):
    assert lint(text)


@pytest.mark.parametrize("text", ["The award date is 2025-02-14.", "Official A alleged a procurement irregularity.",
                                  'The speaker said "this is fraud" and the record is silent on that.',
                                  "The record does not establish intent."])
def test_lint_allows_neutral_text_and_quoted_words(text):
    assert lint(text) == []


def test_lint_reports_each_violation_once():
    assert sorted(lint("fraud and corrupt and fraud")) == ["corrupt", "fraud"]


MAP = {"Northwind Signal Media LLC": "Contractor B", "Northwind Signal Media": "Contractor B",
       "Jane Q. Official": "Official A"}


def test_apply_replaces_longest_names_first_and_ignores_case():
    p = Pseudonymizer(MAP)
    assert p.apply("northwind signal media llc hired by Jane Q. Official") == "Contractor B hired by Official A"


def test_apply_leaves_other_text_alone():
    assert Pseudonymizer(MAP).apply("No names here.") == "No names here."


def test_leaks_detects_remaining_real_names():
    p = Pseudonymizer(MAP)
    assert p.leaks("Contractor B and Official A") == []
    assert p.leaks("Contractor B and Jane Q. Official") == ["Jane Q. Official"]
