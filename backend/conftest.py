# conftest.py — at backend/ root so pytest adds this dir to sys.path
# This means `from app.xxx import yyy` resolves to backend/app/xxx.py
# No Flask app is started here; services are tested with mocked DB.


def init_test_limiter(app):
    """Initialize Flask-Limiter with a project-sized IP cap in isolated unit apps."""
    from app.extensions import limiter

    app.config.setdefault("RATELIMIT_DEFAULT", [])
    app.config.setdefault("RATELIMIT_STORAGE_URI", "memory://")
    limiter.init_app(app)
