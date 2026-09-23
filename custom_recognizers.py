import logging
import re

import spacy
from presidio_analyzer import EntityRecognizer, Pattern, PatternRecognizer, RecognizerResult

# Loaded once at import, module-level -- same reason Detoxify and the injection
# classifier are loaded once each rather than per-request: it's a real model load.
#
# This is deliberately its OWN standalone spaCy pipeline, separate from the general
# 'en_core_web_lg' pipeline Presidio's shared nlp_engine uses. Both used to be
# registered under the same lang_code ("en") in get_nlp_engine() (api.py), which
# Presidio's engine keys by language code -- the second entry silently overwrote the
# first, so only this medical model was ever actually running, and general-purpose
# entities like PERSON never fired at all regardless of any rule's is_active flag.
# Giving this its own pipeline here is what lets both run at once.
_medical_nlp = None
_medical_nlp_error = None

try:
    print("Loading medical entity model (en_ner_bc5cdr_md)...")
    _medical_nlp = spacy.load("en_ner_bc5cdr_md")
    print("Medical entity model loaded successfully.")
except Exception as e:
    _medical_nlp_error = str(e)
    logging.error(f"MedicalEntityRecognizer: model failed to load -- {e}")


class MedicalEntityRecognizer(EntityRecognizer):
    """
    CHEMICAL/DISEASE detection via a dedicated en_ner_bc5cdr_md pipeline, decoupled
    from Presidio's shared nlp_engine (see the module-level comment above for why).

    This model was trained exclusively on biomedical journal text (the BC5CDR corpus),
    so it has never seen brand or product names during training -- an unfamiliar
    capitalized token that isn't a common English word can pattern-match its idea of
    "chemical" regardless of context. Confirmed directly: run standalone, outside
    Presidio entirely, it tags "Jio" as CHEMICAL. That is a property of the model
    itself, not something a pipeline fix corrects.

    No denylist here -- one turned out not to be enough on its own. Confirmed directly:
    once the general-purpose PERSON recognizer started working too, it independently
    misread "Jio" as a person's name, a completely different false positive from a
    completely different model. A denylist scoped to just this recognizer would have
    missed that. See api.py's apply_egress_guardrail for where filtering actually
    happens now -- one place, applied after every recognizer (this one, spaCy's PERSON,
    the regex rules) has already run, rather than duplicated per-recognizer.
    """

    ENTITIES = ["CHEMICAL", "DISEASE"]
    DEFAULT_SCORE = 0.85

    def __init__(self):
        super().__init__(supported_entities=self.ENTITIES, name="MedicalEntityRecognizer")

    def load(self) -> None:
        pass  # the model is already loaded at module import time

    def analyze(self, text, entities, nlp_artifacts=None):
        if _medical_nlp is None:
            return []

        wanted = set(entities) & set(self.ENTITIES)
        if not wanted:
            return []

        results = []
        doc = _medical_nlp(text)
        for ent in doc.ents:
            if ent.label_ not in wanted:
                continue
            results.append(RecognizerResult(
                entity_type=ent.label_,
                start=ent.start_char,
                end=ent.end_char,
                score=self.DEFAULT_SCORE,
            ))
        return results


_CURRENCY_CONTEXT_RE = re.compile(r"(?i)\b(?:rs\.?|inr|rupees?|₹|\$|usd|eur|€)\b")
_INDIAN_PREFIX_AMOUNT_RE = re.compile(r"(?i)\b(?:rs\.?|inr|₹)\s?[\d,]+(?:\.\d+)?\b")
_LAKH_CRORE_AMOUNT_RE = re.compile(r"(?i)\b[\d,]+(?:\.\d+)?\s*(?:lakh|lakhs|crore|crores)\b")
_INDIAN_GROUPED_DIGITS_RE = re.compile(r"\b\d{1,2}(?:,\d{2}){1,}(?:,\d{3})\b")
_SHORTHAND_K_RE = re.compile(r"(?i)\b\d+(?:\.\d+)?k\b")


class TransactionAmountRecognizer(EntityRecognizer):
    """
    TRANSACTION_AMOUNT detection -- confirmed directly (see the Reports/awareness-email
    work this session) that the shared nlp_engine's own en_core_web_lg model tags common
    Western-style amounts ("50,000 rupees", "$500", "2500.50 EUR") as MONEY out of the
    box, but misses "Rs. 50000", Indian-style digit grouping ("1,25,000"), "500k"
    shorthand, and "12 lakh rupees" entirely -- it's trained on general English text, not
    Indian financial conventions. Combines two signals rather than betting on either
    alone: the shared model's own MONEY/CARDINAL tagging (reused via nlp_artifacts, no
    second spaCy pass) for what it already gets right, plus a handful of India-specific
    regex patterns for what it doesn't.

    A bare CARDINAL number or "500k" shorthand is too ambiguous to count as an amount on
    its own (could be a phone number, a quantity, anything) -- both only count when a
    currency word/symbol appears within CONTEXT_WINDOW characters either side.
    """

    ENTITIES = ["TRANSACTION_AMOUNT"]
    SCORE_SPACY_MONEY = 0.85
    SCORE_SPACY_CARDINAL_WITH_CONTEXT = 0.6
    SCORE_REGEX = 0.6
    CONTEXT_WINDOW = 25

    def __init__(self):
        super().__init__(supported_entities=self.ENTITIES, name="TransactionAmountRecognizer")

    def load(self) -> None:
        pass  # reuses the shared nlp_engine's own parse via nlp_artifacts -- nothing to load

    def _has_currency_context(self, text: str, start: int, end: int) -> bool:
        window_start = max(0, start - self.CONTEXT_WINDOW)
        window_end = min(len(text), end + self.CONTEXT_WINDOW)
        return bool(_CURRENCY_CONTEXT_RE.search(text[window_start:window_end]))

    def analyze(self, text, entities, nlp_artifacts=None):
        if "TRANSACTION_AMOUNT" not in entities:
            return []

        results = []
        seen_spans = set()

        if nlp_artifacts is not None:
            for ent in nlp_artifacts.entities:
                if ent.label_ == "MONEY":
                    results.append(RecognizerResult(
                        entity_type="TRANSACTION_AMOUNT", start=ent.start_char,
                        end=ent.end_char, score=self.SCORE_SPACY_MONEY,
                    ))
                    seen_spans.add((ent.start_char, ent.end_char))
                elif ent.label_ == "CARDINAL" and self._has_currency_context(text, ent.start_char, ent.end_char):
                    results.append(RecognizerResult(
                        entity_type="TRANSACTION_AMOUNT", start=ent.start_char,
                        end=ent.end_char, score=self.SCORE_SPACY_CARDINAL_WITH_CONTEXT,
                    ))
                    seen_spans.add((ent.start_char, ent.end_char))

        for pattern in (_INDIAN_PREFIX_AMOUNT_RE, _LAKH_CRORE_AMOUNT_RE, _INDIAN_GROUPED_DIGITS_RE):
            for m in pattern.finditer(text):
                span = (m.start(), m.end())
                if span in seen_spans:
                    continue
                results.append(RecognizerResult(
                    entity_type="TRANSACTION_AMOUNT", start=span[0], end=span[1],
                    score=self.SCORE_REGEX,
                ))
                seen_spans.add(span)

        for m in _SHORTHAND_K_RE.finditer(text):
            span = (m.start(), m.end())
            if span in seen_spans:
                continue
            if self._has_currency_context(text, span[0], span[1]):
                results.append(RecognizerResult(
                    entity_type="TRANSACTION_AMOUNT", start=span[0], end=span[1],
                    score=self.SCORE_REGEX,
                ))
                seen_spans.add(span)

        return results


class AadhaarRecognizer(PatternRecognizer):
    """
    Custom recognizer for India Aadhaar using Verhoeff Checksum.
    """
    def __init__(self):
        # Base score is 0.4. Context words will bump it above the threshold if present.
        patterns = [Pattern(name="aadhaar_pattern", regex=r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", score=0.4)]
        super().__init__(
            supported_entity="IN_AADHAAR", 
            patterns=patterns, 
            context=["aadhaar", "uid", "uidai"]
        )

    def validate_result(self, pattern_text: str) -> bool:
        """
        Validates the 12-digit string using the Verhoeff algorithm.
        This overrides the default validation to completely eliminate false positives.
        """
        digits = pattern_text.replace("-", "").replace(" ", "")
        if len(digits) != 12:
            return False
            
        # Verhoeff mathematical tables
        d = [
            [0,1,2,3,4,5,6,7,8,9], [1,2,3,4,0,6,7,8,9,5], [2,3,4,0,1,7,8,9,5,6],
            [3,4,0,1,2,8,9,5,6,7], [4,0,1,2,3,9,5,6,7,8], [5,9,8,7,6,0,4,3,2,1],
            [6,5,9,8,7,1,0,4,3,2], [7,6,5,9,8,2,1,0,4,3], [8,7,6,5,9,3,2,1,0,4],
            [9,8,7,6,5,4,3,2,1,0]
        ]
        p = [
            [0,1,2,3,4,5,6,7,8,9], [1,5,7,6,2,8,3,0,9,4], [5,8,0,3,7,9,6,1,4,2],
            [8,9,1,6,0,4,3,5,2,7], [9,4,5,3,1,2,6,8,7,0], [4,2,8,6,5,7,3,9,0,1],
            [2,7,9,3,8,0,6,4,1,5], [7,0,4,6,9,1,3,2,5,8]
        ]
        
        c = 0
        num_array = [int(x) for x in digits]
        num_array.reverse()
        for i in range(len(num_array)):
            c = d[c][p[i % 8][num_array[i]]]
        
        # A mathematically valid verhoeff checksum results in 0
        return c == 0
