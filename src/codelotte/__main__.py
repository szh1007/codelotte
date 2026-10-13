"""允许以 `python -m codelotte` 方式运行。"""

from codelotte.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
