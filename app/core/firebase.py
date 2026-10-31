import os
from pathlib import Path

import firebase_admin
from dotenv import load_dotenv
from firebase_admin import credentials, db

# 프로젝트 최상위 폴더
BASE_DIR = Path(__file__).resolve().parents[2]


def initialize_firebase():
    load_dotenv(BASE_DIR / ".env")

    try:
        return firebase_admin.get_app()
    except ValueError:
        key_path = BASE_DIR / os.environ["FIREBASE_CREDENTIALS_PATH"]

        cred = credentials.Certificate(str(key_path))

        return firebase_admin.initialize_app(cred, {
            "databaseURL": os.environ["FIREBASE_DATABASE_URL"]
        })


def get_db_reference(path):
    app = initialize_firebase()
    return db.reference(path, app=app)