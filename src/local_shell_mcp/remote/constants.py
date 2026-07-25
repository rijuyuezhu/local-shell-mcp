"""Shared constants for remote worker coordination."""

REMOTE_JOIN_PATH = "/join"
REMOTE_API_PREFIX = "/remote"
REMOTE_WORKER_BUNDLE_PATH = "/remote/worker-bundle.tgz"
REMOTE_WORKER_MANIFEST_PATH = f"{REMOTE_WORKER_BUNDLE_PATH}?manifest=1"
REMOTE_WORKER_POLL_PROTOCOL_VERSION = 1
REMOTE_WORKER_REGISTRY_FILE_NAME = "remote-workers.json"
REMOTE_WORKER_IDENTITY_FILE_NAME = "identity.json"
REMOTE_WORKER_DISTRIBUTIONS: tuple[str, ...] = ()
