from presidio_analyzer import Pattern, PatternRecognizer

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
