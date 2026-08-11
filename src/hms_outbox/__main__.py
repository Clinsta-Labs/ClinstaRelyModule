"""Module entrypoint: ``python -m hms_outbox``."""

from hms_outbox.cli.main import main

if __name__ == "__main__":
    raise SystemExit(main())
