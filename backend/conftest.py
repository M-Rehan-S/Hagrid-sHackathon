# conftest.py — at backend/ root so pytest adds this dir to sys.path
# This means `from app.xxx import yyy` resolves to backend/app/xxx.py
# No Flask app is started here; services are tested with mocked DB.
