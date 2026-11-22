import pytest

from app.ai.evaluate_scam_classifier import build_metrics


def test_evaluation_metrics_include_false_alarms_abstentions_and_latency():
    metrics = build_metrics(
        expected=["legit", "legit", "scam", "scam"],
        predicted=["legit", "scam", "unsure", "scam"],
        latency_ms=[1.0, 2.0, 3.0, 4.0],
    )

    assert metrics["samples"] == 4
    assert metrics["accuracy"] == 0.5
    assert metrics["false_alarm_rate"] == 0.5
    assert metrics["abstention_rate"] == 0.25
    assert metrics["confusion_matrix_columns"] == ["legit", "scam", "unsure"]
    assert metrics["confusion_matrix"] == [[1, 1, 0], [0, 1, 1]]
    assert metrics["avg_latency_ms"] == 2.5


@pytest.mark.parametrize(
    ("expected", "predicted"),
    [(["legit"], []), (["unknown"], ["scam"]), (["legit"], ["unknown"])],
)
def test_evaluation_rejects_mismatched_or_unknown_labels(expected, predicted):
    with pytest.raises(ValueError):
        build_metrics(expected, predicted, [])
