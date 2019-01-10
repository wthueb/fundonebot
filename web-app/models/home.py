from flask import redirect, request, url_for
import flask_admin
from flask_admin import expose, helpers
import flask_login as login
from werkzeug.security import check_password_hash
from wtforms import fields, form, validators

from base import db
from models import user


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
        return db.session.query(user.User).filter_by(login=self.login.data).first()


class HomeView(flask_admin.AdminIndexView):
    @expose('/')
    def index(self):
        if not login.current_user.is_authenticated:
            return redirect(url_for('.login_view'))
        
        return super().index()

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

        return super().index()

    @expose('/logout/')
    def logout_view(self):
        login.logout_user()

        return redirect(url_for('.login_view'))
