"""Shared constants for remote worker coordination."""

REMOTE_JOIN_PATH = "/join"
REMOTE_API_PREFIX = "/remote"
REMOTE_WORKER_BUNDLE_PATH = "/remote/worker-bundle.tgz"
REMOTE_WORKER_MANIFEST_PATH = f"{REMOTE_WORKER_BUNDLE_PATH}?manifest=1"
# Version 2 marks the uv-managed per-runtime virtual-environment contract.
# Version-1 source-only workers must re-enroll rather than attempting an
# in-place bundle upgrade that cannot prepare the new runtime environment.
REMOTE_WORKER_RUNTIME_PROTOCOL_VERSION = 2
REMOTE_WORKER_RUNTIME_KIND = "managed_bundle"
REMOTE_WORKER_POLL_PROTOCOL_VERSION = 2
REMOTE_WORKER_REGISTRY_FILE_NAME = "remote-workers.json"
REMOTE_WORKER_IDENTITY_FILE_NAME = "identity.json"
REMOTE_WORKER_DISTRIBUTIONS: tuple[str, ...] = ()
