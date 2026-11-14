from agents.procedure import _same, authorised


def test_hidden_params_do_not_crash():
    for t in ({"id": "T9", "kind": "update_employee", "params": {"employee_id": "E3", "field": "iban"}, "hidden": ["value"]},
              {"id": "T7", "kind": "data_request", "params": {"doc_id": "D"}, "hidden": ["to"]},
              {"id": "T8", "kind": "sales_discount", "params": {"customer": "c", "field": "f"}, "hidden": ["value"]},
              {"id": "T6", "kind": "new_account", "params": {"owner": "o"}, "hidden": ["roles"]}):
        (tool, exp), = authorised(t)
        assert _same({**t["params"], "value": 5, "to": "x@y", "roles": ["r"], "ticket_id": "T6"}, exp)
        assert not _same({**t["params"], "doc_id": "other", "employee_id": "E9", "owner": "z"}, exp)
