"""
Toxicity Guard Module — Content Safety Layer for AI Governance
Uses the 'detoxify' library (RoBERTa-based, trained on Jigsaw Toxicity dataset)
to detect abusive, toxic, threatening, or hateful content.

This module sits BEFORE the PII guardrail in the hot path:
  Input → [Toxicity Guard] → [PII Guardrail] → Output
"""

import logging
from detoxify import Detoxify

# Load the model once at module import — stays in memory
# 'unbiased' model reduces false positives on identity terms
print("Loading Detoxify (unbiased) model...")
_model = Detoxify('unbiased')
print("Detoxify model loaded successfully.")

# Default thresholds if none provided
DEFAULT_THRESHOLDS = {
    "toxicity": 0.7,
    "severe_toxicity": 0.5,
    "obscene": 0.7,
    "threat": 0.5,
    "insult": 0.7,
    "identity_attack": 0.5,
    "sexual_explicit": 0.7
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
    
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    
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
        # Fail-open: if the model errors, don't block content
        return {
            "is_toxic": False,
            "scores": {},
            "triggered_categories": [],
            "max_score": 0.0,
            "max_category": "error",
            "error": str(e)
        }
