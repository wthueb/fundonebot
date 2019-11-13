# this is an absolutely terrible way to implement something like this.
# it's only a temporary solution, as it is easier than a re-write of the entire project
# that supports multiple accounts at the same time


from hashlib import sha1
import logging
import os
import shutil
import sqlite3
import subprocess
from time import sleep


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

conn = sqlite3.connect('fundonebot.db')

c = conn.cursor()

keys = ('id', 'api_key', 'api_secret', 'symbol', 'position_size_buy', 'position_size_sell',
        'hedge', 'hedge_side', 'hedge_multiplier', 'stop_limit_multiplier',
        'stop_market_multiplier')

bots_location = os.path.expanduser('/home/ubuntu/')


def create_settings_str(setting) -> str:
    new_settings = ('import logging\n'
            + "BASE_URL = 'https://www.bitmex.com/api/v1/'\n")

    for key in keys:
        new_settings += key.upper() + ' = ' + repr(setting[key]) + '\n'

    new_settings += ('LOOP_INTERVAL = .5\n'
                     'API_REST_INTERVAL = 3\n'
                     'TIMEOUT = 10\n'
                     'LOG_LEVEL = logging.INFO\n'
                     "ORDERID_PREFIX = 'mm_'\n")

    return new_settings


def run_loop() -> None:
    while True:
        c.execute('SELECT * FROM settings')

        values = c.fetchall()

        settings = [dict(zip(keys, value)) for value in values]

        logging.info('got settings from db: %s' % settings)

        last_id = 0

        for setting in settings:
            logging.info('working on setting id: %i' % setting['id'])

            # use id as directory postfix (i.e. fundonebot1, fundonebot4)
            directory = os.path.join(bots_location, 'fundonebot%i/' % setting['id'])

            logging.info(' ~ directory: %s' % directory)

            service_name = 'bitmex-funding%i' % setting['id']
            service_path = '/etc/systemd/system/%s.service' % service_name

            if os.path.exists(directory):
                logging.info(' ~ directory exists, checking if settings have changed')

                # hash current settings file
                settings_path = os.path.join(directory, 'settings.py')

                with open(settings_path, 'r') as f:
                    content = f.read()

                old_hash = sha1(content.encode('utf-8'))

                logging.info(' ~ old hash: %s' % old_hash.hexdigest())

                # create and hash new settings string
                new_settings = create_settings_str(setting)

                new_hash = sha1(new_settings.encode('utf-8'))

                logging.info(' ~ new hash: %s' % new_hash.hexdigest())

                # if hashes have changed, change settings & restart the bot
                if new_hash.digest() != old_hash.digest():
                    logging.info(' ~ hashes have changed, changing settings and restarting')

                    os.remove(settings_path)

                    with open(settings_path, 'w') as f:
                        f.write(new_settings)

                    logging.info(' ~ wrote new settings, restarting')

                    subprocess.run(('sudo systemctl restart %s' % service_name).split())
                    subprocess.run(('sudo systemctl enable %s' % service_name).split())

                subprocess.run(('sudo systemctl is-active --quiet %s || sudo systemctl restart %s' %
                    (service_name, service_name)).split())
            else:
                logging.info(' ~ directory doesn\'t exist, creating')

                # create directory
                base_dir = os.path.join(bots_location, 'fundonebot/')
        
                def skip_env(*args):
                    return 'env', '__pycache__', '.git'

                shutil.copytree(base_dir, directory, ignore=skip_env)

                logging.info(' ~ initializing virtualenv')

                subprocess.run('python3 -m venv env'.split(), cwd=directory)

                subprocess.run('env/bin/pip3 install -r requirements.txt'.split(), cwd=directory)

                # create settings file
                settings_str = create_settings_str(setting)

                with open(os.path.join(directory, 'settings.py'), 'w') as f:
                    f.write(settings_str)

                logging.info(' ~ wrote settings.py')

                # create systemd service file
                service_str = ('[Unit]\n'
                               'Description=bitmex market bot\n'
                               'After=network.target\n\n'
                               '[Service]\n'
                               'User=ubuntu\n'
                              f'WorkingDirectory={directory}\n'
                              f'ExecStart={directory}env/bin/python3 {directory}strat.py\n'
                               'Restart=no\n\n'
                               '[Install]\n'
                               'WantedBy=multi-user.target')

                #with open(service_path, 'w') as f:
                #    f.write(service_str)

                os.system(f'echo "{service_str}" | sudo tee -a {service_path}')

                logging.info(' ~ wrote systemd service file, starting')

                # enable and start systemd service 
                subprocess.run('sudo systemctl daemon-reload'.split())
                subprocess.run((f'sudo systemctl start {service_name}').split())
                subprocess.run((f'sudo systemctl enable {service_name}').split())

                logging.info(' ~ started systemd service')

                with open('/home/ubuntu/.customrc', 'r+') as f:
                    if f'monitor{setting["id"]}' not in f.read():
                        f.write(f"alias monitor{setting['id']}='journalctl -fu bitmex-funding{setting['id']}'")

                        logging.info(f' ~ bash alias "monitor{setting["id"]}" created')
            
            last_id = setting['id']

        logging.info(f'last id: {last_id}')

        last_id += 1

        while os.path.exists('/etc/systemd/system/bitmex-funding%i.service' % last_id):
            logging.info('deleting bitmex-funding%i' % last_id)

            logging.info(' ~ stopping and disabling systemd service')

            subprocess.run(('sudo systemctl stop bitmex-funding%i' % last_id).split())
            subprocess.run(('sudo systemctl disable bitmex-funding%i' % last_id).split())

            directory = os.path.join(bots_location, 'fundonebot%i/' % last_id)

            logging.info(' ~ deleting %s' % directory)

            subprocess.run(('sudo rm -rf %s' % directory).split())

            logging.info(' ~ deleting service file')

            subprocess.run(('sudo rm /etc/systemd/system/bitmex-funding%i.service' %
                last_id).split())

            last_id += 1

        sleep(5)


if __name__ == '__main__':
    run_loop()

    conn.close()
