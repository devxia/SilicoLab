"""PyInstaller executable entry point."""
import logging
from silicolab.desktop import main, show_error

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        logging.exception("Desktop startup failed")
        show_error(str(error))
        raise SystemExit(1)
