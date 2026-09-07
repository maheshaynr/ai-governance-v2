"""
Toxicity Guard Module — Content Safety Layer for AI Governance
Uses the 'detoxify' library (RoBERTa-based, trained on Jigsaw Toxicity dataset)
to detect abusive, toxic, threatening, or hateful content.

This module sits BEFORE the PII guardrail in the hot path:
  Input → [Toxicity Guard] → [PII Guardrail] → Output
"""

import logging

# Load the model once at module import — stays in memory
# 'unbiased' model reduces false positives on identity terms
#
# A load failure is recorded rather than raised, so the API can still start, report the
# guard as unavailable through /system_status, and fail closed on the hot path -- instead
# of the whole service refusing to import.
_model = None
_load_error = None

try:
    from detoxify import Detoxify

    print("Loading Detoxify (unbiased) model...")
    _model = Detoxify('unbiased')
    print("Detoxify model loaded successfully.")
except Exception as _e:
    _load_error = str(_e)
    logging.error(f"Toxicity Guard: model failed to load -- {_e}")


def is_available() -> bool:
    """Whether the model loaded. Used by the startup self-test."""
    return _model is not None


def load_error() -> str:
    return _load_error or ""

# Default thresholds if none provided
DEFAULT_THRESHOLDS = {
    "toxicity": 0.4, #7
    "severe_toxicity": 0.5,
    "obscene": 0.4, #7
    "threat": 0.5,
    "insult": 0.4, #7
    "identity_attack": 0.5,
    "sexual_explicit": 0.4 #7
}


def analyze(text: str, thresholds: dict = None) -> dict:
    """
    Analyze text for toxicity using the detoxify RoBERTa model.
    
    Args:
        text: The text to analyze
        thresholds: Dict of category -> threshold (0.0-1.0). 
                    Categories exceeding their threshold are flagged.
    
    Returns:
        {
            "is_toxic": bool,
            "scores": {"toxicity": 0.98, "insult": 0.45, ...},
            "triggered_categories": ["toxicity", "insult"],
            "max_score": 0.98,
            "max_category": "toxicity"
        }
    """
    if not text or len(text.strip()) == 0:
        return {
            "is_toxic": False,
            "scores": {},
            "triggered_categories": [],
            "max_score": 0.0,
            "max_category": "none"
        }
    
    if not thresholds:  # Check for None or empty dict
        thresholds = DEFAULT_THRESHOLDS

    if _model is None:
        return {
            "is_toxic": False,
            "scores": {},
            "triggered_categories": [],
            "max_score": 0.0,
            "max_category": "unavailable",
            "guard_failed": True,
            "error": f"model unavailable: {_load_error or 'not loaded'}"
        }

    try:
        raw_scores = _model.predict(text)
        
        # raw_scores is a dict like {"toxicity": 0.98, "severe_toxicity": 0.01, ...}
        # Values may be numpy floats — convert to native Python floats
        scores = {}
        for key, value in raw_scores.items():
            scores[key] = round(float(value), 4)
        
        # Determine which categories exceeded their threshold
        triggered = []
        for category, score in scores.items():
            threshold = thresholds.get(category, DEFAULT_THRESHOLDS.get(category, 0.7))
            if score >= threshold:
                triggered.append(category)
        
        # Find the highest scoring category
        max_category = max(scores, key=scores.get)
        max_score = scores[max_category]
        
        return {
            "is_toxic": len(triggered) > 0,
            "scores": scores,
            "triggered_categories": triggered,
            "max_score": max_score,
            "max_category": max_category
        }
    except Exception as e:
        logging.error(f"Toxicity Guard Error: {str(e)}")
        # Fail CLOSED. This used to return is_toxic=False, which made "the text is clean"
        # and "the check never ran" the same answer -- so a model load failure silently
        # disabled the guard. The caller inspects guard_failed and blocks; see
        # api.apply_toxicity_check.
        return {
            "is_toxic": False,
            "scores": {},
            "triggered_categories": [],
            "max_score": 0.0,
            "max_category": "error",
            "guard_failed": True,
            "error": str(e)
        }
