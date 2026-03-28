"""Backward-compatible launcher. Implementation: ``url_classifier.cli.build_domain_registry``."""

from url_classifier.cli.build_domain_registry import main

if __name__ == "__main__":
    raise SystemExit(main())
