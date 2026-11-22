"""Training & evaluation script for the scam classifier (PROPOSAL.md §8.3).

Usage::

    python backend/app/ai/train_scam_classifier.py

Saves the trained pipeline to backend/app/ai/models/scam_classifier.joblib.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[3]  # …/Hagrid-sHackathon
_DATASET = _REPO_ROOT / "db" / "seed" / "scam_dataset.jsonl"
_MODEL_DIR = Path(__file__).parent / "models"
_MODEL_PATH = _MODEL_DIR / "scam_classifier.joblib"


def load_dataset(path: Path) -> tuple[list[str], list[str]]:
    texts, labels = [], []
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
                texts.append(str(record["text"]))
                labels.append(str(record["label"]))
            except (json.JSONDecodeError, KeyError) as exc:
                print(f"  Skipping line {lineno}: {exc}", file=sys.stderr)
    return texts, labels


def train(dataset_path: Path = _DATASET, model_path: Path = _MODEL_PATH) -> None:
    try:
        import joblib
        import numpy as np
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import classification_report
        from sklearn.model_selection import train_test_split
        from sklearn.pipeline import FeatureUnion, Pipeline
    except ImportError as exc:
        sys.exit(f"Missing dependency: {exc}. Run: pip install scikit-learn joblib numpy")

    print(f"Loading dataset from {dataset_path} …")
    texts, labels = load_dataset(dataset_path)
    print(f"  {len(texts)} examples  |  classes: {sorted(set(labels))}")

    X_train, X_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.2, random_state=42, stratify=labels
    )
    print(f"  train={len(X_train)}  test={len(X_test)}")

    # Feature union: word n-grams + character n-grams
    features = FeatureUnion([
        ("word", TfidfVectorizer(
            analyzer="word",
            ngram_range=(1, 2),
            min_df=1,
            sublinear_tf=True,
        )),
        ("char", TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 4),
            min_df=1,
            sublinear_tf=True,
        )),
    ])

    base_clf = LogisticRegression(
        max_iter=1000,
        C=1.0,
        solver="lbfgs",
        class_weight="balanced",
    )
    calibrated = CalibratedClassifierCV(base_clf, cv=3)

    pipeline = Pipeline([
        ("features", features),
        ("clf", calibrated),
    ])

    print("Training …")
    pipeline.fit(X_train, y_train)

    print("\n=== Evaluation on held-out test set ===")
    y_pred = pipeline.predict(X_test)
    print(classification_report(y_test, y_pred, digits=3))

    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, model_path)
    print(f"\nModel saved → {model_path}")


if __name__ == "__main__":
    train()
