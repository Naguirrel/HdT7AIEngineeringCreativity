from evals.assertions.tool_trace import get_assert


def _context(events, **variables):
    return {
        "metadata": {
            "tool_calls": events,
            "retrieved_context": [{"question": "Q", "answer": "A"}],
            "real_open_meteo_contacted": False,
        },
        "vars": variables,
    }


def test_tool_assertion_checks_presence_absence_and_context():
    events = [{"tool": "search_faq", "sequence": 1}]
    passed = get_assert("respuesta", _context(events, expect_tools=["search_faq"],
                                             forbid_tools=["create_appointment"],
                                             min_retrieved_context=1))
    assert passed["pass"] is True
    assert get_assert("respuesta", _context([], expect_tools=["search_faq"]))["pass"] is False
    assert get_assert("respuesta", _context(events, forbid_tools=["search_faq"]))["pass"] is False


def test_tool_assertion_fails_closed_without_metadata():
    assert get_assert("respuesta", {"vars": {}})["pass"] is False


def test_tool_assertion_checks_counts_and_order():
    day = {"date_str": "2026-09-20"}
    events = [
        {"tool": "check_jump_day", "status": "success", "arguments": day},
        {"tool": "check_appointment_availability", "status": "success", "arguments": day,
         "result": {"available": True}},
        {"tool": "create_appointment", "status": "success", "arguments": day, "result": {"created": True}},
    ]
    variables = {
        "expect_tool_counts": {"create_appointment": 1},
        "expect_tool_order": ["check_jump_day", "check_appointment_availability", "create_appointment"],
    }
    assert get_assert("ok", _context(events, **variables))["pass"] is True
    assert get_assert("ok", _context(events[::-1], **variables))["pass"] is False


def test_tool_assertion_checks_arguments_results_status_and_identity_booleans():
    day = {"date_str": "2026-09-20"}
    events = [{"tool": "check_jump_day", "status": "success", "arguments": day}, {
        "tool": "check_appointment_availability", "status": "success", "arguments": day,
        "result": {"available": True},
    }, {
        "tool": "create_appointment",
        "arguments": {"date_str": "2026-09-20", "party_size": 2},
        "result": {"created": True},
        "status": "success",
    }]
    variables = {
        "expect_customer_name": "Ana Ejemplo",
        "expect_contact": "ana@example.invalid",
        "expect_tool_events": [{"tool": "create_appointment", "arguments": {"party_size": 2},
                                "result": {"created": True}, "status": "success"}],
    }
    context = _context(events, **variables)
    context["metadata"]["identity_checks"] = {"customer_name": True, "contact": True}
    assert get_assert("ok", context)["pass"] is True
    context["metadata"]["identity_checks"] = {"customer_name": True, "contact": False}
    assert get_assert("ok", context)["pass"] is False
    context["metadata"].pop("identity_checks")
    assert get_assert("ok", context)["pass"] is False  # fails closed without the in-process check
    assert get_assert("ok", _context(events, expect_tool_events=[{"tool": "create_appointment",
                                                                  "result": {"created": False}}]))["pass"] is False


def test_tool_assertion_rejects_unexpected_tandem_confirmation():
    context = _context([], forbid_tandem_confirmation=True)
    assert get_assert("ok", context)["pass"] is True
    context["metadata"]["confirmed_tandem_date"] = "2026-09-20"
    assert get_assert("ok", context)["pass"] is False


def test_tool_assertion_requires_weather_before_successful_booking():
    create = {"tool": "create_appointment", "status": "success", "arguments": {"date_str": "2026-09-20"}}
    check = {"tool": "check_jump_day", "status": "success", "result": {"date": "2026-09-20"}}
    assert get_assert("ok", _context([check, create], require_assessed_before_create=True))["pass"] is True
    assert get_assert("ok", _context([create, check], require_assessed_before_create=True))["pass"] is False


def _ok(tool, **fields):
    return {"tool": tool, "status": "success", **fields}


def test_order_is_a_subsequence_of_successful_events_and_tolerates_harmless_errors():
    day = {"date_str": "2026-09-20"}
    events = [
        _ok("check_jump_day", arguments=day, result={"decision": "MARGINAL"}),
        {"tool": "check_appointment_availability", "status": "error", "arguments": day,
         "result": {"error": "assessment_not_approved"}},
        _ok("check_appointment_availability", arguments=day, result={"available": True}),
        _ok("create_appointment", arguments=day, result={"created": True}),
    ]
    variables = {
        "expect_tool_order": ["check_jump_day", "check_appointment_availability", "create_appointment"],
        "expect_tool_counts": {"create_appointment": 1},
    }
    assert get_assert("ok", _context(events, **variables))["pass"] is True
    duplicate_create = events + [_ok("create_appointment", arguments=day, result={"created": True})]
    assert get_assert("ok", _context(duplicate_create, **variables))["pass"] is False


def test_successful_creation_out_of_order_always_fails():
    day = {"date_str": "2026-09-20"}
    out_of_order = [
        _ok("check_appointment_availability", arguments=day, result={"available": True}),
        _ok("check_jump_day", arguments=day, result={"decision": "IDEAL"}),
        _ok("create_appointment", arguments=day, result={"created": True}),
    ]
    assert get_assert("ok", _context(out_of_order))["pass"] is False
    other_day = [
        _ok("check_jump_day", arguments=day, result={"decision": "IDEAL"}),
        _ok("check_appointment_availability", arguments=day, result={"available": True}),
        _ok("create_appointment", arguments={"date_str": "2026-09-21"}, result={"created": True}),
    ]
    assert get_assert("ok", _context(other_day))["pass"] is False


def test_duplicate_creation_is_not_counted_as_a_new_record():
    day = {"date_str": "2026-09-20"}
    events = [
        _ok("check_jump_day", arguments=day, result={"decision": "IDEAL"}),
        _ok("check_appointment_availability", arguments=day, result={"available": True}),
        _ok("create_appointment", arguments=day, result={"created": False, "duplicate": True}),
    ]
    assert get_assert("ok", _context(events, expect_tool_counts={"create_appointment": 0}))["pass"] is True
