"""Optimistic transactions using immutable revisions in a private Vercel Blob store."""
import hashlib
import json
from uuid import uuid4

from fastapi import HTTPException


class BlobStore:
    def __init__(self):
        from vercel import blob
        from vercel.blob import sync

        self.api = sync
        self.errors = blob

    def transact(self, key, action, seed):
        prefix = "workspaces/" + hashlib.sha256(key.encode()).hexdigest() + "/"
        for _ in range(5):
            revision = max((int(item.pathname[len(prefix):]) for item
                            in self.api.query_blobs(prefix=prefix)), default=0)
            if revision:
                entry = self.api.get_blob(prefix + str(revision), access="private")
                state = json.loads(entry.body)["state"]
                previous = json.dumps(state, separators=(",", ":"))
            else:
                state = seed()
                previous = None
            result = action(state)
            if json.dumps(state, separators=(",", ":")) == previous:
                return result

            path = prefix + str(revision + 1)
            updated = json.dumps({"write_id": uuid4().hex, "state": state},
                                 separators=(",", ":")).encode()
            try:
                self.api.put_blob(path, updated, access="private", content_type="application/json",
                                  add_random_suffix=False, allow_overwrite=False)
                return result
            except self.errors.BlobError as error:
                # Another writer can win the same revision. A lost response can
                # also mean our own write succeeded, so check its actual contents.
                try:
                    committed = self.api.get_blob(path, access="private").body
                except self.errors.BlobNotFoundError:
                    raise error
                if committed == updated:
                    return result
        raise HTTPException(409, "The workspace changed. Refresh and try again.")
