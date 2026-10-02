"""Deterministic catalog and loader for bundled Kubernetes runbooks."""

import re
from pathlib import Path
from typing import TypedDict


class RunbookMetadata(TypedDict):
    title: str
    category: str
    keywords: list[str]
    file: str


class RunbookSearchResult(TypedDict):
    slug: str
    title: str
    category: str
    uri: str
    score: int


class RunbookCatalogEntry(TypedDict):
    slug: str
    title: str
    category: str
    uri: str


RUNBOOK_CATALOG: dict[str, RunbookMetadata] = {
    "00-service-triage": {
        "title": "Kubernetes Service Triage",
        "category": "general-troubleshooting",
        "keywords": [
            "service issue",
            "application issue",
            "namespace issue",
            "service health",
            "deployment issue",
            "pod issue",
            "kubernetes issue",
            "troubleshooting",
            "triage",
            "investigate service",
        ],
        "file": "00-service-triage.md",
    },
    "imagepullbackoff": {
        "title": "ImagePullBackOff",
        "category": "container-startup",
        "keywords": ["imagepullbackoff", "errimagepull", "image pull", "registry", "imagepullsecret"],
        "file": "imagepullbackoff.md",
    },
    "crashloopbackoff": {
        "title": "CrashLoopBackOff",
        "category": "container-runtime",
        "keywords": ["crashloopbackoff", "container restart", "back-off restarting", "exit code", "previous logs"],
        "file": "crashloopbackoff.md",
    },
    "oomkilled": {
        "title": "OOMKilled",
        "category": "container-runtime",
        "keywords": ["oomkilled", "out of memory", "memory", "exit 137", "memory limit"],
        "file": "oomkilled.md",
    },
    "readiness-probe": {
        "title": "Readiness Probe Failure",
        "category": "application-health",
        "keywords": ["readiness probe", "not ready", "readiness failure", "health endpoint", "endpoint removed"],
        "file": "readiness-probe.md",
    },
    "failed-scheduling": {
        "title": "FailedScheduling",
        "category": "scheduling",
        "keywords": ["failedscheduling", "pending pod", "insufficient cpu", "insufficient memory", "taint"],
        "file": "failed-scheduling.md",
    },
    "dns-failure": {
        "title": "DNS Failure",
        "category": "networking",
        "keywords": ["dns", "dns lookup", "nxdomain", "coredns", "name resolution"],
        "file": "dns-failure.md",
    },
    "service-unreachable": {
        "title": "Service Unreachable",
        "category": "networking",
        "keywords": ["service unreachable", "connection refused", "service endpoint", "clusterip", "kube-proxy"],
        "file": "service-unreachable.md",
    },
    "pvc-pending": {
        "title": "PVC Pending",
        "category": "storage",
        "keywords": ["pvc pending", "persistentvolumeclaim", "storageclass", "volume provisioning", "persistentvolume"],
        "file": "pvc-pending.md",
    },
    "cpu-throttling": {
        "title": "CPU Throttling",
        "category": "resource-management",
        "keywords": ["cpu throttling", "cpu limit", "cfs throttle", "latency", "cpu request"],
        "file": "cpu-throttling.md",
    },
    "node-not-ready": {
        "title": "Node NotReady",
        "category": "node-health",
        "keywords": ["node notready", "node not ready", "kubelet", "node condition", "node pressure"],
        "file": "node-not-ready.md",
    },
}

RUNBOOK_DIRECTORY = Path(__file__).parent / "runbooks"


def get_runbook_metadata(slug: str) -> RunbookMetadata:
    """Return known runbook metadata or reject an unknown slug."""
    metadata = RUNBOOK_CATALOG.get(slug)
    if metadata is None:
        raise ValueError(f"Unknown runbook slug: {slug}")
    return metadata


def load_runbook(slug: str) -> str:
    """Load a runbook from the file explicitly named by the catalog."""
    metadata = get_runbook_metadata(slug)
    path = (RUNBOOK_DIRECTORY / metadata["file"]).resolve()
    if RUNBOOK_DIRECTORY.resolve() not in path.parents:
        raise ValueError(f"Invalid runbook file for slug: {slug}")
    return path.read_text(encoding="utf-8")


def list_runbook_catalog() -> list[RunbookCatalogEntry]:
    """Return concise, stable entries for the runbook catalog resource."""
    return [
        {
            "slug": slug,
            "title": metadata["title"],
            "category": metadata["category"],
            "uri": f"k8s://runbooks/{slug}",
        }
        for slug, metadata in sorted(RUNBOOK_CATALOG.items())
    ]


def complete_runbook_slugs(prefix: str, limit: int = 10) -> list[str]:
    """Return bounded, case-insensitive prefix matches for runbook slugs."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
        raise ValueError("limit must be an integer between 1 and 10")

    normalized_prefix = prefix.lower()
    return [
        slug
        for slug in sorted(RUNBOOK_CATALOG)
        if slug.lower().startswith(normalized_prefix)
    ][:limit]


def search_runbook_catalog(
    query: str,
    limit: int = 5,
) -> list[RunbookSearchResult]:
    """Find catalog entries using deterministic metadata-only scoring."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
        raise ValueError("limit must be an integer between 1 and 10")

    terms = set(re.findall(r"[a-z0-9]+", query.lower()))
    if not terms:
        return []

    matches: list[RunbookSearchResult] = []
    for slug, metadata in RUNBOOK_CATALOG.items():
        fields = {
            "slug": slug.lower(),
            "title": metadata["title"].lower(),
            "category": metadata["category"].lower(),
            "keywords": " ".join(metadata["keywords"]).lower(),
        }
        weights = {"slug": 10, "title": 8, "category": 4, "keywords": 6}
        score = sum(
            weights[field]
            for term in terms
            for field, value in fields.items()
            if term in value
        )
        if score:
            matches.append(
                {
                    "slug": slug,
                    "title": metadata["title"],
                    "category": metadata["category"],
                    "uri": f"k8s://runbooks/{slug}",
                    "score": score,
                }
            )

    return sorted(
        matches,
        key=lambda item: (-item["score"], item["slug"]),
    )[:limit]
