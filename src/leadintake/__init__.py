"""leadintake: the Python engine behind the n8n-lead-intake workflows.

n8n does the wiring (webhook in, Telegram approval, email out, error handling). This package does
the parts that need a database and tests: normalising an enquiry, finding the same person twice,
an idempotent CRM upsert, scoring against the owner's criteria, drafting a reply, and a small state
machine that makes sure nothing is sent before a person approves it.
"""

__version__ = "0.2.0"
