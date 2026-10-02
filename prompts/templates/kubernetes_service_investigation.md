Investigate Deployment {{ deployment }} in namespace {{ namespace }}.

Use available Kubernetes evidence to describe its health and observed failure mechanism.

Summarize the established cause, supporting evidence, and recommended next action.

{% if use_runbook %}
Include relevant runbook guidance when available. Identify the runbook title and URI, and distinguish a runbook that was read from one that was only discovered.
{% endif %}

Do not make changes.
