import tempfile
import unittest
from pathlib import Path

from memory_store import MemoryStore, normalize_project_category


class MemoryStoreTests(unittest.TestCase):
    def make_store(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name) / "memory"
        index = Path(tmp.name) / "memory_index.db"
        store = MemoryStore(root_dir=root, index_path=index)
        return tmp, store

    def test_normalizes_project_category_legacy_input(self):
        project, category = normalize_project_category("general", "job-search:role_preference")
        self.assertEqual(project, "job-search")
        self.assertEqual(category, "role_preference")

    def test_recent_excludes_expired_memories(self):
        tmp, store = self.make_store()
        self.addCleanup(tmp.cleanup)
        store.add_memory("old job lead", project="job-search", category="job_lead", ttl_days=-1)
        store.add_memory("current job lead", project="job-search", category="job_lead")

        results = store.recent(project="job-search", category="job_lead", limit=10)

        self.assertEqual([memory.text for memory in results], ["current job lead"])

    def test_recent_orders_by_created_at_desc(self):
        tmp, store = self.make_store()
        self.addCleanup(tmp.cleanup)
        store.add_memory(
            "older",
            project="content-refinery",
            category="work_insight",
            created_at="2026-01-01T09:00:00",
        )
        store.add_memory(
            "newer",
            project="content-refinery",
            category="work_insight",
            created_at="2026-01-02T09:00:00",
        )

        results = store.recent(project="content-refinery", limit=10)

        self.assertEqual([memory.text for memory in results], ["newer", "older"])

    def test_search_hard_filters_by_project(self):
        tmp, store = self.make_store()
        self.addCleanup(tmp.cleanup)
        store.add_memory(
            "weekly retrieval summary for Alpha Project",
            project="alpha-project",
            category="work_insight",
        )
        store.add_memory(
            "weekly retrieval summary for Beta Project",
            project="beta-project",
            category="application_insight",
        )

        results = store.search("weekly retrieval summary", project="beta-project", limit=10)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0].project, "beta-project")

    def test_context_pack_uses_exact_project_scope(self):
        tmp, store = self.make_store()
        self.addCleanup(tmp.cleanup)
        store.add_memory("content project context", project="content-refinery", category="work_insight")
        store.add_memory("job project context", project="job-search", category="work_insight")

        pack = store.context_pack(project="content-refinery", workflow="nightly", limit=10)

        self.assertIn("content project context", pack["context"])
        self.assertNotIn("job project context", pack["context"])


if __name__ == "__main__":
    unittest.main()
