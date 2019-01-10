from datetime import datetime

from flask_admin.contrib.sqla import ModelView
import flask_login
from werkzeug.security import generate_password_hash

from base import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(80), unique=True)
    password = db.Column(db.String(128))
    last_login = db.Column(db.String(64))

    def update_login_time(self):
        self.last_login = datetime.utcnow().isoformat(timespec='seconds') + 'Z'

        db.session.commit()

    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return self.id

    def __unicode__(self):
        return self.username


class UserView(ModelView):
    column_list = ('id', 'login', 'last_login')

    form_create_rules = ('login', 'password')

    can_edit = False

    def is_accessible(self):
        return flask_login.current_user.is_authenticated

    def on_model_change(self, form, model, is_created):
        model.password = generate_password_hash(model.password)
        model.last_login = ''
