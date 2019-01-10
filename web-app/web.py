from datetime import datetime

from flask import Flask, redirect
import flask_admin
import flask_login

from base import db
from models import home, user


app = Flask(__name__)

app.config['FLASK_ADMIN_SWATCH'] = 'cerulean'

app.config['SECRET_KEY'] = '450f06e24a6f10509f5d1397c4f8a197d242f350eade3f9e'

app.config['DATABASE_FILE'] = 'users.db'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + app.config['DATABASE_FILE']
app.config['SQLALCHEMY_ECHO'] = False
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)


from wtforms import form, fields, validators
class SettingsForm(form.Form):
    symbol = fields.StringField(validators=[validators.data_required()])

    position_size = fields.IntegerField(validators=[validators.data_required()])

    hedge = fields.BooleanField(validators=[validators.data_required()])
    hedge_side = fields.StringField(validators=[validators.data_required()])
    hedge_multiplier = fields.StringField(validators=[validators.data_required()])

    stop_limit_multiplier = fields.DecimalField(validators=[validators.data_required()])
    stop_market_multiplier = fields.DecimalField(validators=[validators.data_required()])

    def validate(self):
        if symbol not in ['XBTUSD', 'ETHUSD']:
            raise validators.ValidationError('symbol not supported. supported: XBTUSD, ETHUSD')

        if hedge_side not in ['Buy', 'Sell']:
            raise validators.ValidationError('hedge side is invalid. should be Buy or Sell')

        if hedge_multiplier <= 0:
            raise validators.ValidationError('hedge multipler must be positive')

        if stop_limit_multiplier < 0:
            raise validators.ValidationError(
                    'stop limit multiplier must be positive or 0 to disable')
        if stop_market_multiplier < 0:
            raise validators.ValidationError(
                    'stop market multiplier must be positive or 0 to disable')


def init_login():
    login_manager = flask_login.LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.query(user.User).get(user_id)


init_login()

admin = flask_admin.Admin(
        app, 'fundonebot', index_view=home.HomeView(), base_template='master.html')

admin.add_view(user.UserView(user.User, db.session))


@app.route('/')
def index():
    return redirect('/admin/')


if __name__ == '__main__':
    def build_db():
        db.drop_all()
        db.create_all()

        user = User(login='wilhueb', password='pbkdf2:sha256:50000$ZP6YHJuy$ab2e65b529e6c6ce9de44309b9c45dee7bff6223b0f89416a9a0d93dc58be0ca', last_login=datetime.now().isoformat(timespec='seconds') + 'Z')

        db.session.add(user)

        db.session.commit()

    import os

    app_dir = os.path.realpath(os.path.dirname(__file__))
    database_path = os.path.join(app_dir, app.config['DATABASE_FILE'])

    if not os.path.exists(database_path):
        build_db()

    app.run('0.0.0.0', 8080, debug=False)
