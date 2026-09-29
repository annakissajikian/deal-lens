"""
AI analyst (Step 6). The LLM interprets engine outputs; it never calculates.

    payload.py        the only data the model sees, every item tagged with its provenance
    number_checker.py rejects any statement containing a figure the engine did not produce
    analyst.py        the Claude API call (structured output) + validation of the answer

finance/ never imports from ai/.
"""
