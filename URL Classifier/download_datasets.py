"""Backward-compatible launcher. Implementation: ``url_classifier.cli.download_datasets``."""

from url_classifier.cli.download_datasets import main

if __name__ == "__main__":
    raise SystemExit(main())
