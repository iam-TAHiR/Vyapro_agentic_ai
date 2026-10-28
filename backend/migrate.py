"""Apply pending database migrations."""

from dotenv import load_dotenv

from app import create_app
from app.migrations import apply_migrations


if __name__ == "__main__":
    load_dotenv()
    with create_app().app_context():
        apply_migrations()
    print("Database migrations are up to date.")
