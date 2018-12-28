from datetime import datetime

from flask import Flask, url_for, redirect, request
import flask_admin as admin
from flask_admin import helpers, expose
from flask_admin.contrib import sqla
import flask_login as login
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from wtforms import form, fields, validators


app = Flask(__name__)

app.config['FLASK_ADMIN_SWATCH'] = 'cerulean'

app.config['SECRET_KEY'] = '450f06e24a6f10509f5d1397c4f8a197d242f350eade3f9e'

app.config['DATABASE_FILE'] = 'users.db'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + app.config['DATABASE_FILE']
app.config['SQLALCHEMY_ECHO'] = False
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(80), unique=True)
    password = db.Column(db.String(128))
    last_login = db.Column(db.String(64))

    def update_login_time(self):
        self.last_login = datetime.now().isoformat(timespec='seconds') + 'Z'

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


class LoginForm(form.Form):
    login = fields.StringField(validators=[validators.data_required()])
    password = fields.PasswordField(validators=[validators.data_required()])

    def validate_login(self, field):
        user = self.get_user()

        if user is None:
            raise validators.ValidationError('invalid user')

        if not check_password_hash(user.password, self.password.data):
            raise validators.ValidationError('invalid password')

    def get_user(self):
        return db.session.query(User).filter_by(login=self.login.data).first()


def init_login():
    login_manager = login.LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.query(User).get(user_id)


class ModelView(sqla.ModelView):
    column_list = {'login', 'last_login'}

    def is_accessible(self):
        return login.current_user.is_authenticated

    def on_model_change(self, form, model, is_created):
        model.password = generate_password_hash(model.password)


class AdminIndexView(admin.AdminIndexView):
    @expose('/')
    def index(self):
        if not login.current_user.is_authenticated:
            return redirect(url_for('.login_view'))
        return super(AdminIndexView, self).index()

    @expose('/login/', methods=('GET', 'POST'))
    def login_view(self):
        form = LoginForm(request.form)

        if helpers.validate_form_on_submit(form):
            user = form.get_user()

            user.update_login_time()

            login.login_user(user)

        if login.current_user.is_authenticated:
            return redirect(url_for('.index'))

        self._template_args['form'] = form

        return super(AdminIndexView, self).index()

    @expose('/logout/')
    def logout_view(self):
        login.logout_user()

        return redirect(url_for('.index'))


@app.route('/')
def index():
    return redirect('/admin/')


init_login()

admin = admin.Admin(app, 'fundonebot', index_view=AdminIndexView(), base_template='master.html')

admin.add_view(ModelView(User, db.session))


def build_db():
    db.drop_all()
    db.create_all()

    user = User(login='wilhueb', password='pbkdf2:sha256:50000$ZP6YHJuy$ab2e65b529e6c6ce9de44309b9c45dee7bff6223b0f89416a9a0d93dc58be0ca', last_login=datetime.now().isoformat(timespec='seconds') + 'Z')

    db.session.add(user)

    db.session.commit()


if __name__ == '__main__':
    import os

    app_dir = os.path.realpath(os.path.dirname(__file__))
    database_path = os.path.join(app_dir, app.config['DATABASE_FILE'])

    if not os.path.exists(database_path):
        build_db()

    app.run('0.0.0.0', 8080, debug=False)
