import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from lablink.blob_store import BlobStore


class BlobStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = BlobStore.__new__(BlobStore)
        self.store.errors = SimpleNamespace(BlobError=OSError, BlobNotFoundError=FileNotFoundError)
        self.store.api = Mock()
        self.docs = {}
        self.store.api.query_blobs.side_effect = lambda prefix: [
            SimpleNamespace(pathname=p) for p in self.docs if p.startswith(prefix)
        ]
        self.store.api.get_blob.side_effect = lambda p, access: SimpleNamespace(body=self.docs[p])

    def test_concurrent_identical_increment_rechecks_latest_revision(self):
        def put(path, body, **options):
            self.assertEqual(options["access"], "private")
            self.assertFalse(options["allow_overwrite"])
            if not self.docs:
                self.docs[path] = json.dumps({"write_id":"other", "state":{"count":1}}).encode()
                raise OSError("revision exists")
            self.docs[path] = body

        self.store.api.put_blob.side_effect = put
        def increment(state):
            state["count"] += 1
            return state["count"]

        self.assertEqual(self.store.transact("demo", increment, lambda: {"count":0}), 2)
        self.assertEqual(self.store.transact("demo", lambda s: s["count"], dict), 2)
        self.assertEqual(len(self.docs), 2)

    def test_lost_write_response_recovers_same_operation(self):
        def put(path, body, **options):
            self.docs[path] = body
            raise OSError("lost response")

        self.store.api.put_blob.side_effect = put
        self.assertEqual(self.store.transact("demo", lambda s: s.setdefault("item", 1), dict), 1)
        self.assertEqual(self.store.api.put_blob.call_count, 1)
