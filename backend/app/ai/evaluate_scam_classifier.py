"""Evaluate the committed scam model on its deterministic held-out split.

Run from the repository root with:
    backend/venv/bin/python backend/app/ai/evaluate_scam_classifier.py

The script stores aggregate-only metrics in ``eval_runs`` for the dashboard.
"""

from __future__ import annotations

import sys
from pathlib import Path
from time import perf_counter
from typing import Sequence

from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.ai.scam_classifier import load_classifier  # noqa: E402
from app.ai.train_scam_classifier import load_dataset  # noqa: E402

DATASET_PATH = REPO_ROOT / "db" / "seed" / "scam_dataset.jsonl"
LABELS = ["legit", "scam"]
PREDICTION_LABELS = ["legit", "scam", "unsure"]


def build_metrics(
    expected: Sequence[str], predicted: Sequence[str], latency_ms: Sequence[float]
) -> dict:
    """Create the aggregate metric shape consumed by ``eval_runs``."""
    if len(expected) != len(predicted):
        raise ValueError("expected and predicted must have the same number of labels")
    matrix = [[0 for _ in PREDICTION_LABELS] for _ in LABELS]
    for actual, guess in zip(expected, predicted, strict=True):
        if actual not in LABELS or guess not in PREDICTION_LABELS:
            raise ValueError("evaluation contains an unknown scam label")
        matrix[LABELS.index(actual)][PREDICTION_LABELS.index(guess)] += 1

    true_legit, false_alarm, _legit_unsure = (int(value) for value in matrix[0])
    legit_count = sum(matrix[0])
    return {
        "samples": len(expected),
        "accuracy": round(float(accuracy_score(expected, predicted)), 4),
        "precision_macro": round(float(precision_score(expected, predicted, labels=LABELS, average="macro", zero_division=0)), 4),
        "recall_macro": round(float(recall_score(expected, predicted, labels=LABELS, average="macro", zero_division=0)), 4),
        "f1_macro": round(float(f1_score(expected, predicted, labels=LABELS, average="macro", zero_division=0)), 4),
        "false_alarm_rate": round(false_alarm / legit_count, 4) if legit_count else 0.0,
        "confusion_matrix_labels": LABELS,
        "confusion_matrix_columns": PREDICTION_LABELS,
        "confusion_matrix": matrix,
        "abstention_rate": round(sum(guess == "unsure" for guess in predicted) / len(predicted), 4) if predicted else 0.0,
        "avg_latency_ms": round(sum(latency_ms) / len(latency_ms), 3) if latency_ms else 0.0,
    }


def evaluate() -> dict:
    texts, labels = load_dataset(DATASET_PATH)
    _, test_texts, _, test_labels = train_test_split(
        texts, labels, test_size=0.2, random_state=42, stratify=labels
    )
    classifier = load_classifier()
    if classifier is None:
        raise RuntimeError("Scam classifier artifact is missing or could not be loaded.")

    predictions = []
    latencies = []
    for text in test_texts:
        started = perf_counter()
        predictions.append(classifier(text)["label"])
        latencies.append((perf_counter() - started) * 1000)
    return build_metrics(test_labels, predictions, latencies)


def save_metrics(metrics: dict) -> None:
    from app import create_app
    from app.extensions import db
    from app.models.eval_run import EvalRun

    app = create_app()
    with app.app_context():
        db.session.add(EvalRun(name="scam_classifier", metrics=metrics))
        db.session.commit()


def main() -> int:
    metrics = evaluate()
    save_metrics(metrics)
    print(f"Saved scam_classifier evaluation ({metrics['samples']} held-out examples).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
