import sys

from .remote.worker import run_worker_cli

if __name__ == "__main__":
    run_worker_cli(sys.argv[1:])
