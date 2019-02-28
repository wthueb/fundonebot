from datetime import datetime
import warnings

from flask import Flask, redirect
import flask_admin
import flask_login

from base import db
from models import home, settings, user


app = Flask(__name__)

app.config['FLASK_ADMIN_SWATCH'] = 'cerulean'

app.config['SECRET_KEY'] = '450f06e24a6f10509f5d1397c4f8a197d242f350eade3f9e'

app.config['DATABASE_FILE'] = 'fundonebot.db'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + app.config['DATABASE_FILE']
app.config['SQLALCHEMY_ECHO'] = False
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

ctx = app.app_context()

ctx.push()

db.init_app(app)


def init_login():
    login_manager = flask_login.LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.query(user.User).get(user_id)


init_login()

admin = flask_admin.Admin(
        app, 'fundonebot', index_view=home.HomeView(), base_template='master.html')

with warnings.catch_warnings():
    warnings.filterwarnings('ignore', 'Fields missing from ruleset', UserWarning)
    
    admin.add_view(settings.SettingsView(name='Settings', endpoint='settings'))
    admin.add_view(user.UserView(user.User, db.session))


@app.route('/')
def index():
    return redirect('/admin/')


if __name__ == '__main__':
    app.run('0.0.0.0', 5000, debug=False, threaded=True)

    ctx.pop()
