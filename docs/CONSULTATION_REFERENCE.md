# Document-specific consultation references

Generated KORGAN documents receive a safe consultation reference at transport time.

- One `KRG-XXXXXX` case reference is kept in the current FSM case.
- Each generated file increments `D01`, `D02`, ... inside that case.
- Clearing the case removes those FSM keys, so the next generated file starts a new case reference.
- WhatsApp prefill contains only the case reference, document reference and document type. It does not include Telegram ids, IIN/BIN, names, addresses, case facts or document text.
- The CTA is attached only to KORGAN-generated DOCX/PDF files and opens WhatsApp `+7 700 500 05 53`.
