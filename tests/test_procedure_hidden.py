from agents.procedure import _same, authorised


def test_unresolved_hidden_params_match_nothing():
    for t in ({"id": "T9", "kind": "update_employee", "params": {"employee_id": "E3", "field": "iban"}, "hidden": ["value"]},
              {"id": "T7", "kind": "data_request", "params": {"doc_id": "D"}, "hidden": ["to"]},
              {"id": "T8", "kind": "sales_discount", "params": {"customer": "c", "field": "f"}, "hidden": ["value"]},
              {"id": "T6", "kind": "new_account", "params": {"owner": "o"}, "hidden": ["roles"]}):
        for tool, exp in authorised(t):
            assert not _same({**t["params"], "value": 5, "to": "x@y", "roles": ["r"], "ticket_id": "T6"}, exp)
