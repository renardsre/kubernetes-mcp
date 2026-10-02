import unittest

from resources.catalog import (
    complete_runbook_slugs,
    get_runbook_metadata,
    list_runbook_catalog,
    load_runbook,
    search_runbook_catalog,
)


class RunbookCatalogTests(unittest.TestCase):
    def test_catalog_lookup(self) -> None:
        metadata = get_runbook_metadata("imagepullbackoff")
        self.assertEqual(metadata["title"], "ImagePullBackOff")

    def test_search_ranks_image_pull_runbook_first(self) -> None:
        results = search_runbook_catalog("pod cannot pull image from registry")
        self.assertEqual(results[0]["slug"], "imagepullbackoff")

    def test_search_finds_oomkilled(self) -> None:
        results = search_runbook_catalog("memory exit 137")
        self.assertEqual(results[0]["slug"], "oomkilled")

    def test_general_service_query_ranks_triage_first(self) -> None:
        results = search_runbook_catalog(
            "investigate service issue in namespace"
        )
        self.assertEqual(results[0]["slug"], "00-service-triage")

    def test_specific_symptoms_keep_specific_runbooks_first(self) -> None:
        cases = {
            "ImagePullBackOff": "imagepullbackoff",
            "exit code 137 memory limit": "oomkilled",
            "FailedScheduling pending pod": "failed-scheduling",
        }
        for query, slug in cases.items():
            with self.subTest(query=query):
                results = search_runbook_catalog(query)
                self.assertEqual(results[0]["slug"], slug)

    def test_search_rejects_invalid_limit(self) -> None:
        with self.assertRaises(ValueError):
            search_runbook_catalog("dns", 0)

    def test_unknown_slug_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            get_runbook_metadata("../../etc/passwd")

    def test_runbook_file_loading(self) -> None:
        content = load_runbook("oomkilled")
        self.assertIn("# OOMKilled", content)

    def test_triage_runbook_file_loading(self) -> None:
        content = load_runbook("00-service-triage")
        self.assertIn("# Kubernetes Service Triage", content)

    def test_catalog_entries_are_concise_and_sorted(self) -> None:
        entries = list_runbook_catalog()
        self.assertEqual(len(entries), 11)
        self.assertEqual(entries, sorted(entries, key=lambda entry: entry["slug"]))
        self.assertEqual(
            entries[0],
            {
                "slug": "00-service-triage",
                "title": "Kubernetes Service Triage",
                "category": "general-troubleshooting",
                "uri": "k8s://runbooks/00-service-triage",
            },
        )

    def test_slug_completion_uses_case_insensitive_prefixes(self) -> None:
        self.assertEqual(complete_runbook_slugs("o"), ["oomkilled"])
        self.assertEqual(
            complete_runbook_slugs("IMAGE"),
            ["imagepullbackoff"],
        )


if __name__ == "__main__":
    unittest.main()
