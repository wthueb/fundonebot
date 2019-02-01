from flask import redirect, request, url_for
from flask_admin import BaseView, expose, helpers
import flask_login
from wtforms import form, fields, validators

from base import db


class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    api_key = db.Column(db.String(128))
    api_secret = db.Column(db.String(128))
  
    symbol = db.Column(db.String(10))
   
    position_size_buy = db.Column(db.Integer)
    position_size_sell = db.Column(db.Integer)

    hedge = db.Column(db.Boolean)
    hedge_side = db.Column(db.String(4))
    hedge_multiplier = db.Column(db.Float)

    stop_limit_multiplier = db.Column(db.Float)
    stop_market_multiplier = db.Column(db.Float)


class SettingsForm(form.Form):
    api_key = fields.StringField(validators=[validators.data_required()])
    api_secret = fields.StringField(validators=[validators.data_required()])

    symbol = fields.StringField(validators=[validators.data_required()])

    position_size_buy = fields.StringField(validators=[validators.data_required()])
    position_size_sell = fields.StringField(validators=[validators.data_required()])

    hedge = fields.BooleanField()
    hedge_side = fields.StringField()
    hedge_multiplier = fields.StringField()

    stop_limit_multiplier = fields.StringField()
    stop_market_multiplier = fields.StringField()

    def validate_symbol(self, field):
        if field.data not in ['XBTUSD', 'ETHUSD']:
            raise validators.ValidationError('symbol not supported. supported: XBTUSD, ETHUSD')

    def validate_position_size_buy(self, field):
        try:
            if int(field.data) == 0:
                raise validators.ValidationError('position size must be a non-zero integer')
        except ValueError:
            raise validators.ValidationError('position size must be a non-zero integer')
    
    def validate_position_size_buy(self, field):
        try:
            if int(field.data) == 0:
                raise validators.ValidationError('position size must be a non-zero integer')
        except ValueError:
            raise validators.ValidationError('position size must be a non-zero integer')

    def validate_hedge_side(self, field):
        if self.hedge.data and field.data not in ['Buy', 'Sell']:
            raise validators.ValidationError('hedge side is invalid. valid inputs: Buy, Sell')

    def validate_hedge_multiplier(self, field):
        if self.hedge.data:
            try:
                if float(field.data) <= 0:
                    raise validators.ValidationError('hedge multiplier must be a positive '
                                                     'float value (i.e. 0.5, 1, 2')
            except ValueError:
                raise validators.ValidationError(
                        'hedge multiplier must be a positive float value (i.e. 0.5, 1, 2')


    def validate_stop_limit_multiplier(self, field):
        try:
            if float(field.data) < 0:
                raise validators.ValidationError(
                        'stop limit multiplier must be in the range [0, 1), with 0 to disable '
                        '(i.e. 0, 0.015 (1.5%), .99 (99%)')
        except ValueError:
            raise validators.ValidationError(
                    'stop limit multiplier must be a float value in the range [0, 1), '
                    'with 0 to disable (i.e. 0, 0.015 (1.5%), .99 (99%)')


    def validate_stop_market_multiplier(self, field):
        try:
            if float(field.data) < 0:
                raise validators.ValidationError(
                        'stop market multiplier must be in the range [0, 1), with 0 to disable '
                        '(i.e. 0, 0.015 (1.5%), .99 (99%)')
        except:
            raise validators.ValidationError(
                    'stop market multiplier must be a float value in the range [0, 1), '
                    'with 0 to disable (i.e. 0, 0.015 (1.5%), .99 (99%)')


class SettingsView(BaseView):
    def is_accessible(self):
        return flask_login.current_user.is_authenticated

    @expose('/')
    def index(self):
        settings = db.session.query(Settings).order_by(Settings.id).all()

        self._template_args['settings'] = settings

        return self.render('admin/settings.html')

    @expose('/new/', methods=('GET', 'POST'))
    def new_setting(self):
        form = SettingsForm(request.form)

        if helpers.validate_form_on_submit(form):
            setting = Settings()

            #form.populate_obj(setting)

            setting.api_key = form.api_key.data
            setting.api_secret = form.api_secret.data
            setting.symbol = form.symbol.data
            setting.position_size_buy = int(form.position_size_buy.data)
            setting.position_size_sell = int(form.position_size_sell.data)
            setting.hedge = form.hedge.data

            if setting.hedge:
                setting.hedge_side = form.hedge_side.data
                setting.hedge_multiplier = float(form.hedge_multiplier.data)

            setting.stop_limit_multiplier = float(form.stop_limit_multiplier.data)
            setting.stop_market_multiplier = float(form.stop_market_multiplier.data)

            db.session.add(setting)

            db.session.commit()

            return redirect(url_for('.index'))

        self._template_args['form'] = form
        
        return self.render('admin/new_setting.html')

    @expose('/delete/', methods=('POST',))
    def delete_setting(self):
        data = request.get_json()

        if 'id' not in data:
            return '', 400

        id = data['id']

        db.session.query(Settings).filter(Settings.id == id).delete()

        db.session.commit()

        return ''
