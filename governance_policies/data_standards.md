# Enterprise Data Format Policies

This document outlines the strict official Regex standards for identifying sensitive data within the enterprise.
When creating new rules or suggesting fixes, the following formats MUST be adhered to strictly.

## IBAN (International Bank Account Number)
All European and International Bank Account Numbers (IBAN) must be validated using the following exact pattern:
`\b[A-Z]{2}[0-9]{2}[a-zA-Z0-9]{11,30}\b`
Do not suggest any other pattern for IBANs. It must start with two letters, followed by two numbers, followed by 11 to 30 alphanumeric characters. Ensure word boundaries (\b) are used.

## MRN (Medical Record Number)
Medical Record Numbers within the healthcare network always follow the exact pattern of four digits, a hyphen, and alphanumeric characters.
Approved Pattern: `\b\d{4}-[a-zA-Z0-9]+\b`

## SWIFT Code (BIC)
Standard Bank Identifier Codes (SWIFT) must follow the 8 or 11 character format. 
Approved Pattern: `\b[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?\b`
