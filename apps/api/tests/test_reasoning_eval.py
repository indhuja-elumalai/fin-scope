"""Offline unit tests for app.eval.reasoning_eval.

No provider, no network, no database, no FastAPI app -- every case here
constructs a ReasoningResultInput and EvaluationCase by hand and calls
evaluate() directly, exactly the way the module is designed to be used
against a real persisted InvestigationReasoning row (see
app.eval.reasoning_eval.from_persisted).
"""
from app.eval.reasoning_eval import EvaluationCase, ReasoningResultInput, evaluate


def _hypothesis(**overrides) -> dict:
    base = {
        "hypothesis_id": "h1",
        "rank": 1,
        "title": "Retry storm from a stale webhook",
        "explanation": "Multiple payment_failed events cluster around one merchant window.",
        "confidence": "medium",
        "supporting_evidence": ["e1"],
        "contradicting_evidence": [],
        "uncertainty": "Would be more certain with a second incident window to compare against.",
    }
    base.update(overrides)
    return base


def _category(report, category: str):
    return [c for c in report.checks if c.category == category]


def test_correctly_grounded_hypothesis_passes_evaluation():
    result = ReasoningResultInput(
        status="completed", hypotheses=[_hypothesis()], failure_reason=None
    )
    case = EvaluationCase(
        case_id="c1",
        description="one well-formed, fully-grounded hypothesis",
        expected_status="completed",
        valid_evidence_ids=frozenset({"e1", "e2"}),
        min_hypotheses=1,
    )

    report = evaluate(result, case)

    assert report.passed is True
    assert report.failed_checks() == ()
    # Every category that applies to a completed result actually ran.
    ran_categories = {c.category for c in report.checks}
    assert {
        "evidence_grounding",
        "unsupported_claim_handling",
        "hypothesis_structure",
        "confidence_handling",
        "contradiction_handling",
        "uncertainty_articulation",
        "deterministic_reasoning_boundary",
        "failure_behavior",
    }.issubset(ran_categories)


def test_unsupported_evidence_reference_fails_grounding():
    # Simulates a persisted result whose supporting_evidence cites something
    # outside the case's own controlled evidence set -- exactly the
    # property production validation (app.domain.reasoning) is supposed to
    # prevent from ever being persisted as "completed". This module
    # measures that property directly against whatever was actually
    # persisted, rather than assuming it.
    result = ReasoningResultInput(
        status="completed",
        hypotheses=[_hypothesis(supporting_evidence=["e1", "e999-does-not-exist"])],
        failure_reason=None,
    )
    case = EvaluationCase(
        case_id="c2",
        description="a supporting_evidence id outside the known evidence set",
        expected_status="completed",
        valid_evidence_ids=frozenset({"e1"}),
    )

    report = evaluate(result, case)

    assert report.passed is False
    grounding_checks = _category(report, "evidence_grounding")
    assert len(grounding_checks) == 1
    assert grounding_checks[0].passed is False
    assert "e999-does-not-exist" in grounding_checks[0].detail


def test_unsupported_claim_fails_when_no_supporting_evidence():
    result = ReasoningResultInput(
        status="completed",
        hypotheses=[_hypothesis(supporting_evidence=[])],
        failure_reason=None,
    )
    case = EvaluationCase(
        case_id="c3",
        description="a hypothesis with no supporting evidence at all",
        expected_status="completed",
        valid_evidence_ids=frozenset({"e1"}),
    )

    report = evaluate(result, case)

    assert report.passed is False
    claim_checks = _category(report, "unsupported_claim_handling")
    assert len(claim_checks) == 1
    assert claim_checks[0].passed is False
    assert "h1" in claim_checks[0].detail


def test_contradiction_handling_flags_ungrounded_contradicting_evidence():
    result = ReasoningResultInput(
        status="completed",
        hypotheses=[
            _hypothesis(
                supporting_evidence=["e1"],
                contradicting_evidence=["e404-unknown"],
            )
        ],
        failure_reason=None,
    )
    case = EvaluationCase(
        case_id="c4",
        description="contradicting_evidence citing an id outside the known evidence set",
        expected_status="completed",
        valid_evidence_ids=frozenset({"e1"}),
    )

    report = evaluate(result, case)

    assert report.passed is False
    contradiction_checks = _category(report, "contradiction_handling")
    assert len(contradiction_checks) == 1
    assert contradiction_checks[0].passed is False
    assert "e404-unknown" in contradiction_checks[0].detail
    # Grounding of supporting_evidence is unaffected -- these are
    # independently-scored dimensions, not one bleeding into the other.
    assert _category(report, "evidence_grounding")[0].passed is True


def test_insufficient_evidence_case_matches_persisted_status():
    result = ReasoningResultInput(
        status="insufficient_evidence",
        hypotheses=[],
        failure_reason=(
            "no incident was detected for this investigation -- there is no evidence "
            "pattern to reason about yet"
        ),
    )
    case = EvaluationCase(
        case_id="c5",
        description="no incident detected -- provider never called",
        expected_status="insufficient_evidence",
    )

    report = evaluate(result, case)

    assert report.passed is True
    insufficient_checks = _category(report, "insufficient_evidence_handling")
    assert len(insufficient_checks) >= 1
    assert all(c.passed for c in insufficient_checks)


def test_uncertainty_not_articulated_fails_that_category_only():
    result = ReasoningResultInput(
        status="completed",
        hypotheses=[_hypothesis(uncertainty="")],
        failure_reason=None,
    )
    case = EvaluationCase(
        case_id="c6",
        description="a hypothesis that never names what would change its certainty",
        expected_status="completed",
        valid_evidence_ids=frozenset({"e1"}),
    )

    report = evaluate(result, case)

    assert report.passed is False
    uncertainty_checks = _category(report, "uncertainty_articulation")
    assert len(uncertainty_checks) == 1
    assert uncertainty_checks[0].passed is False
    # Grounding and claim-support are otherwise fine -- only this dimension
    # should fail for this specific input.
    assert _category(report, "evidence_grounding")[0].passed is True
    assert _category(report, "unsupported_claim_handling")[0].passed is True


def test_malformed_reasoning_result_fails_hypothesis_structure():
    # A hypothesis missing required shape entirely (no rank, no title) --
    # the kind of thing app.domain.reasoning._validate_hypotheses is
    # supposed to reject before persistence. This module measures the
    # property independently of whether the pipeline actually enforced it.
    result = ReasoningResultInput(
        status="completed",
        hypotheses=[{"hypothesis_id": "", "supporting_evidence": ["e1"]}],
        failure_reason=None,
    )
    case = EvaluationCase(
        case_id="c7",
        description="a structurally malformed hypothesis",
        expected_status="completed",
        valid_evidence_ids=frozenset({"e1"}),
    )

    report = evaluate(result, case)

    assert report.passed is False
    structure_checks = _category(report, "hypothesis_structure")
    assert len(structure_checks) == 1
    assert structure_checks[0].passed is False
    assert "hypothesis_id" in structure_checks[0].detail or "rank" in structure_checks[0].detail


def test_expected_invalid_output_status_matches_rejection():
    # The system correctly rejected the whole response (whole-response
    # rejection, per app.domain.reasoning) -- evaluated against a case that
    # expects exactly that outcome for this scenario. "Invalid evidence
    # reference handling" is exactly this status match: a case that
    # expects "invalid_output" IS a case that expects the hallucinated
    # reference to have been rejected.
    result = ReasoningResultInput(
        status="invalid_output",
        hypotheses=[],
        failure_reason="hypothesis 'h1' cites an evidence event_id that does not exist",
    )
    case = EvaluationCase(
        case_id="c8",
        description="a scenario known to contain a hallucinated evidence reference",
        expected_status="invalid_output",
    )

    report = evaluate(result, case)

    assert report.passed is True
    assert report.expected_status_matched is True
    assert report.actual_status == "invalid_output"
    # failure_behavior still independently verifies the failure_reason
    # itself is sanitized for this rejected-response status.
    assert all(c.passed for c in _category(report, "failure_behavior"))


def test_status_mismatch_alone_fails_the_report_even_if_no_check_fails():
    # A case expecting rejection ("invalid_output") but the system actually
    # persisted "completed" with an otherwise perfectly well-formed
    # hypothesis -- every per-category check on that hypothesis would pass
    # in isolation, but the report must still fail overall: the whole point
    # of this scenario was that the response should have been rejected.
    result = ReasoningResultInput(
        status="completed", hypotheses=[_hypothesis()], failure_reason=None
    )
    case = EvaluationCase(
        case_id="c12",
        description="a scenario expected to be rejected, but the system accepted it",
        expected_status="invalid_output",
        valid_evidence_ids=frozenset({"e1"}),
    )

    report = evaluate(result, case)

    assert report.expected_status_matched is False
    assert report.passed is False


def test_deterministic_boundary_fails_if_a_hypothesis_carries_a_financial_field():
    # Structural guard: even if something upstream regressed and let a
    # financial-authority field leak into a hypothesis dict, this category
    # must catch it -- this is the one check that always runs regardless
    # of status or case.
    result = ReasoningResultInput(
        status="completed",
        hypotheses=[_hypothesis(amount="500.00")],
        failure_reason=None,
    )
    case = EvaluationCase(
        case_id="c9",
        description="a hypothesis that should never carry a financial-authority field",
        expected_status="completed",
        valid_evidence_ids=frozenset({"e1"}),
    )

    report = evaluate(result, case)

    assert report.passed is False
    boundary_checks = _category(report, "deterministic_reasoning_boundary")
    assert len(boundary_checks) == 1
    assert boundary_checks[0].passed is False
    assert "amount" in boundary_checks[0].detail


def test_failure_behavior_fails_if_failure_reason_leaks_upstream_detail():
    result = ReasoningResultInput(
        status="unavailable",
        hypotheses=[],
        failure_reason="account (acct_secret_123) has insufficient credits",
    )
    case = EvaluationCase(
        case_id="c10",
        description="a sanitized failure_reason must not leak account detail",
        expected_status="unavailable",
    )

    report = evaluate(result, case)

    assert report.passed is False
    failure_checks = _category(report, "failure_behavior")
    assert any(not c.passed for c in failure_checks)


def test_no_valid_hypotheses_status_carries_no_hypotheses():
    result = ReasoningResultInput(status="no_valid_hypotheses", hypotheses=[], failure_reason=None)
    case = EvaluationCase(
        case_id="c11",
        description="the provider judged the evidence too ambiguous",
        expected_status="no_valid_hypotheses",
    )

    report = evaluate(result, case)

    assert report.passed is True
