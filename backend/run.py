"""Local development entry point."""

import os

from app import create_app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.getenv("VYAPRO_HOST", "127.0.0.1"),
        port=int(os.getenv("VYAPRO_PORT", "5000")),
        debug=app.config["DEBUG"],
    )
