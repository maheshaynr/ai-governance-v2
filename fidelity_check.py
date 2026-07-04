import string

class FidelityChecker:
    @staticmethod
    def check_fidelity(original: str, rewrite: str, threshold: float = 0.3) -> tuple[bool, float]:
        """
        A v1 keyword-coverage check. 
        Checks if a certain percentage of important keywords from the original are in the rewrite.
        """
        # Naive implementation for PoC: extract words longer than 4 chars as 'keywords'
        def get_keywords(text):
            text = text.translate(str.maketrans('', '', string.punctuation)).lower()
            return set(word for word in text.split() if len(word) > 4)
            
        orig_keywords = get_keywords(original)
        if not orig_keywords:
            return True, 1.0 # Nothing to lose if original is very short
            
        rewrite_keywords = get_keywords(rewrite)
        
        overlap = orig_keywords.intersection(rewrite_keywords)
        score = len(overlap) / len(orig_keywords)
        
        return score >= threshold, round(score, 2)
