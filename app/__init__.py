from flask import Flask

def create_app():
    app = Flask(__name__)
    app.secret_key = "dev-secret-key"

    from app.routes import main
    from app.api import api
    app.register_blueprint(main)
    app.register_blueprint(api, url_prefix="/api")

    return app
