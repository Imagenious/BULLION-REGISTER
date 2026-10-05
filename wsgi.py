"""Entry point for cloud servers: gunicorn wsgi:app"""
from app import create_app

app = create_app()
