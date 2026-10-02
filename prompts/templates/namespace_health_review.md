Review the health of workloads in namespace {{ namespace }}.

Use available Kubernetes evidence to summarize observed unhealthy workloads and their failure mechanisms.

{% if include_logs %}
Include relevant runtime log findings in the summary if they are already available.
{% endif %}

Summarize:
- unhealthy workload
- observed failure
- supporting evidence
- recommended next action

Do not make changes.
