"""The four checks from the PR gate: PCI exposure, data classification, API-contract changes, regulatory surface."""
import pytest

from casefile.gate_mcp.checks import check_pci_exposure, classify_fields, diff_contract, diff_tool_specs, regulatory_surface

PAN = "4532 0151 1283 0366"          # Luhn-valid and NOT on the known test-card list


# ---- PCI exposure ---------------------------------------------------------------------------------------------------
def test_a_real_looking_card_number_is_critical_blocking_and_never_echoed_in_full():
    r = check_pci_exposure(f'customer_card = "{PAN}"\n')
    f = next(f for f in r.findings if f.kind == "pan")
    assert f.severity == "critical" and f.blocking and r.blocking
    assert PAN not in f.excerpt and "4532015112830366" not in f.excerpt and f.excerpt.count("*") >= 12 and "0366" in f.excerpt


def test_luhn_invalid_digit_runs_are_not_card_numbers():
    assert check_pci_exposure("order id 1234 5678 9012 3456\n").findings == []


def test_well_known_test_cards_are_low_severity_and_non_blocking():
    r = check_pci_exposure("card = '4111 1111 1111 1111'\n")
    f = next(f for f in r.findings if f.kind == "test_pan")
    assert f.severity == "low" and not f.blocking and not r.blocking


@pytest.mark.parametrize("text,kind", [("cvv = '123'\n", "cvv"), ("card_verification_value: 4421\n", "cvv"),
                                       ("%B" + PAN.replace(" ", "") + "^DOE/JOHN^2512101?\n", "track_data")])
def test_sensitive_authentication_data_is_always_critical(text, kind):
    r = check_pci_exposure(text)
    assert any(f.kind == kind and f.severity == "critical" and f.blocking for f in r.findings)


def test_card_fields_added_to_schemas_and_logs_are_flagged_high():
    r = check_pci_exposure("+    card_number: str\n+    logger.info('charging %s', card_number)\n")
    kinds = {f.kind for f in r.findings}
    assert {"card_field", "card_data_in_logs"} <= kinds and all(f.severity == "high" for f in r.findings if f.kind in ("card_field", "card_data_in_logs"))


def test_in_a_diff_only_added_lines_count_so_removing_card_fields_passes():
    diff = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,1 @@\n-    card_number: str\n+    token: str\n"
    assert check_pci_exposure(diff).findings == []


def test_clean_text_has_no_findings():
    assert check_pci_exposure("account_id = 'acct_1040'\namount = 4800\n").findings == []


# ---- data classification ---------------------------------------------------------------------------------------------
def test_field_names_are_classified_and_unknown_names_are_reported():
    out = {c.name: c for c in classify_fields(["email", "card_number", "api_key", "account_id", "foo_bar"])}
    assert [out[n].data_class for n in ("email", "card_number", "api_key", "account_id")] == ["pii", "payment", "credential", "internal"]
    assert out["foo_bar"].data_class == "unclassified"


def test_json_schema_properties_are_flattened_with_paths():
    schema = {"type": "object", "properties": {"customer": {"type": "object", "properties": {"email": {"type": "string"}}},
                                               "cvv": {"type": "string"}}}
    names = {c.name: c.data_class for c in classify_fields(schema)}
    assert names == {"customer.email": "pii", "cvv": "payment"}


# ---- API-contract changes -----------------------------------------------------------------------------------------------
OLD = {"type": "object", "required": ["a"], "additionalProperties": False,
       "properties": {"a": {"type": "string"}, "b": {"enum": ["x", "y"]}, "c": {"type": "number"}}}


def kinds(changes):
    return {(c.kind, c.breaking) for c in changes}


def test_breaking_and_non_breaking_schema_changes_are_told_apart():
    new = {"type": "object", "required": ["a", "d"], "additionalProperties": False,
           "properties": {"a": {"type": "integer"}, "b": {"enum": ["x"]}, "d": {"type": "string"}, "e": {"type": "string"}}}
    got = kinds(diff_contract(OLD, new))
    assert {("property_removed", True), ("type_changed", True), ("enum_value_removed", True), ("required_added", True),
            ("property_added", False)} <= got


def test_adding_an_optional_property_or_an_enum_value_is_not_breaking():
    new = {**OLD, "properties": {**OLD["properties"], "z": {"type": "string"}, "b": {"enum": ["x", "y", "w"]}}}
    assert all(not c.breaking for c in diff_contract(OLD, new)) and diff_contract(OLD, OLD) == []


def test_tool_spec_changes_flag_removed_tools_and_permission_expansion():
    old = {"get_x": {"access": "read", "roles": ["investigator"], "version": "1.0"}}
    new = {"get_x": {"access": "write", "roles": ["investigator", "planner"], "version": "1.0"}, "get_y": {"access": "read", "roles": ["planner"], "version": "1.0"}}
    got = {(c.kind, c.breaking) for c in diff_tool_specs(old, new)}
    assert ("access_class_changed", True) in got and ("roles_widened", True) in got and ("tool_added", False) in got
    assert ("tool_removed", True) in {(c.kind, c.breaking) for c in diff_tool_specs(new, old)}


# ---- regulatory surface ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("summary,topic", [("Add a step that freezes the account after escalation", "account_actions"),
                                           ("Send a wire transfer to the beneficiary", "money_movement"),
                                           ("Store the card number for refunds", "card_data"),
                                           ("File a suspicious activity report automatically", "aml_reporting"),
                                           ("Decline the loan application using a model score", "credit_decisioning"),
                                           ("Retain customer emails for two years", "personal_data")])
def test_changes_are_mapped_to_regulatory_topics_with_research_queries(summary, topic):
    r = regulatory_surface(summary, [])
    t = next(t for t in r.topics if t.topic == topic)
    assert t.research_queries and t.possible_regimes and r.needs_research
    assert "not legal advice" in r.notice.lower()


def test_unrelated_changes_have_no_regulatory_surface_and_paths_count():
    assert regulatory_surface("Rename a variable in a test helper", []).topics == []
    assert any(t.topic == "card_data" for t in regulatory_surface("misc", ["src/payments/card_vault.py"]).topics)
