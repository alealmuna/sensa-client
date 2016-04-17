#!/usr/bin/python
import argparse
import json
import logging
import requests
import serial
import sqlite3
import sys
import time
from ast import literal_eval
from ConfigParser import SafeConfigParser
from datetime import datetime
from hashlib import md5
from subprocess import call
from threading import Thread
from urllib import URLopener
from zipfile import ZipFile

sys.path.insert(0, '/usr/lib/python2.7/websocket/')
sys.path.insert(0, '/usr/lib/python2.7/bridge/')

from websocket import create_connection
from websocket import WebSocketConnectionClosedException


class Client():
    def __init__(self,
                 config_filename='/etc/sensa.ini',
                 store_data=True,
                 serial_comm=True,
                 db_file='/mnt/sd/db/sensa.db'):
        # Device status
        self.DISCONNECTED, self.CONNECTED = range(2)
        # MCU serial commands
        self.cmds = {
            'sampling': '0',
            'activate': 'activate'
        }
        self.config_filename = config_filename
        self.load_config(config_filename)
        if serial_comm:
            self.activateIOs()
        self.initialize_switches()
        self.store_data = store_data
        self.db_file = db_file
        logging.info('Client started')

    def load_config(self, config_filename):
        # Parse config file
        config = SafeConfigParser()
        config.read(config_filename)

        self.socket_url = config.get('server', 'socket_url')
        self.api_url = config.get('server', 'api_url')
        self.api_token = config.get('server', 'api_token')
        self.device_id = config.get('device', 'device_id')
        self.dev_baud = config.get('device', 'baud')
        self.dev_sampling_period = int(config.get('device', 'sampling_period'))
        self.dev_port = config.get('device', 'port')
        self.device_url = '%s/devices/%s/' % (self.api_url, self.device_id)
        self.datastreams = literal_eval(config.get('device', 'datastreams'))
        self.datastream_suscriptions = literal_eval(
            config.get('suscriptions', 'datastreams'))
        self.firmware_version = config.get('device', 'firmware_version')
        # self.fw_version_url = '%sfirmware/' % self.device_url
        # Headers used by each request
        self.api_hdrs = {'Content-Type': 'application/json',
                         'Authorization': 'Token token="%s"' % self.api_token}

    def connect_socket(self):
        while(1):
            try:
                self.ws = create_connection(self.socket_url)
                break
            except:
                logging.error('Sensa socket server connection error')
                time.sleep(15)

        logging.info('Connected to server')
        # Set datastreams to listen from server
        susc_ids = [ds['id'] for ds in self.datastream_suscriptions]
        logging.debug('Suscribed to datastreams {}'.format(susc_ids))
        msg = {
            'device_id': self.device_id,
            'datastream_suscriptions': susc_ids,
            'api_token': self.api_token
        }
        self.ws.send(json.dumps(msg))
        response = json.loads(self.ws.recv())
        logging.debug('Connection response: {}'.format(response))

        # Update status on web server
        payload = json.dumps({'status': self.CONNECTED})
        requests.patch(self.device_url, data=payload, headers=self.api_hdrs)

    def take_sample(self):
        logging.debug('Sampling')
        try:
            mcu = serial.Serial(self.dev_port, self.dev_baud, timeout=6)
        except serial.SerialException:
            logging.error('MCU can not be found or can not be configured')
            return 0
        time.sleep(1)

        mcu.write(self.cmds['sampling'])
        line = mcu.readline()
        ivalues = line.split(',')[:-1]  # Separate values and discard EOL
        values = [int(v)/100.0 for v in ivalues]
        if len(values) == 0:
            logging.error('No value received from MCU.')
            mcu.close()
            # Reset Arduino
            call('reset-mcu')
            return

        datastream_ids = [ds['id'] for ds in self.datastreams]
        payload = {'values': dict(zip(datastream_ids, values))}
        logging.debug(payload)
        try:
            r = requests.post(self.device_url, data=json.dumps(payload),
                              headers=self.api_hdrs)
        except requests.ConnectionError:
            logging.error('Connection error. Values were not logged.')
            mcu.close()
            return
        if (r.status_code != 201):
            logging.error(r.text)

        mcu.close()

        # Store data
        '''
        if (self.store_data):
            local_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn = sqlite3.connect(self.db_file)
            with conn:
                db = conn.cursor()
                db.execute('INSERT INTO IO(id, type, pin, time, value)
                    VALUES(?,?,?,?,?)', (local_time))
                db.commit()
        '''

    def sampling(self, period):
        last_sample_time = time.time()
        self.take_sample()
        while True:
            this_time = time.time()
            if((this_time - last_sample_time) > self.dev_sampling_period):
                last_sample_time = this_time
                self.take_sample()

    def activateIOs(self):
        ds = self.datastreams
        dss = self.datastream_suscriptions
        logging.debug('Activating IOs')
        try:
            mcu = serial.Serial(self.dev_port, self.dev_baud, timeout=4)
        except serial.SerialException:
            logging.error('MCU can not be found or can not be configured')
            return 0
        time.sleep(1)

        ds_num = len(ds)
        for d in range(ds_num):
            cmd = '{}/{}/{}/{}/'.format(
                self.cmds['activate'], d, ds[d]['type'], ds[d]['pin'])
            mcu.write(cmd)
            mcu.readline()
            logging.debug('MCU Command: {}'.format(cmd))
            time.sleep(0.2)
        for d in range(len(dss)):
            cmd = '{}/{}/{}/{}/'.format(
                self.cmds['activate'], ds_num+d, dss[d]['type'], dss[d]['pin'])
            mcu.write(cmd)
            mcu.readline()
            time.sleep(0.2)
            logging.debug('MCU Command: {}'.format(cmd))

    def activateIO(self, datastream_id, io_type, io_pin):
        dstreams = self.datastreams
        logging.debug('Activating {} as {} on pin {} with id {}.'.format(
            datastream_id, io_type, io_pin, len(dstreams)))
        ds = next((ds for ds in dstreams if ds['id'] == datastream_id), None)
        if ds:
            # Datastream in memory, update
            mcu_id = dstreams.index(datastream_id)
            ds['type'] = io_type,
            ds['pin'] = io_pin
        else:
            # New datastream
            mcu_id = len(dstreams) + len(self.datastream_suscriptions)
            dstreams.append({
                'id': datastream_id,
                'type': io_type,
                'pin': io_pin
            })

        conf = SafeConfigParser()
        conf.read(self.config_filename)
        conf.set('device', 'datastreams', str(dstreams))
        try:
            conf_file = open(self.config_filename, 'wb')
            conf.write(conf_file)
        except IOError:
            logging.error('Error updating version on config file')
        else:
            conf_file.close()
            logging.debug('IO added to config file')

        try:
            mcu = serial.Serial(self.dev_port, self.dev_baud, timeout=3)
        except serial.SerialException:
            logging.error('MCU can not be found or can not be configured')
            return 0
        time.sleep(1)
        cmd = '{}/{}/{}'.format(self.cmds['activate'], mcu_id, io_type, io_pin)
        mcu.write(cmd)
        response = mcu.readline()
        if(response):
            logging.debug('IO activated on MCU')
        else:
            logging.error('Error activating IO on MCU')
        mcu.close()

    def write_actuator(self, io_id, value):
        ds = [ds for ds in
              self.datastream_suscriptions if ds['id'] == io_id][0]
        mcu_id = self.datastream_suscriptions.index(ds)
        mcu_id += len(self.datastreams)
        try:
            mcu = serial.Serial(self.dev_port, self.dev_baud, timeout=3)
        except serial.SerialException:
            logging.error('MCU can not be found or can not be configured')
            return 0
        # cmd = 'd/%s/%s' % (pin, value)
        msg = 'Writing actuator. ID: %s, Value: %s' % (mcu_id, value)
        logging.debug(msg)
        cmd = 'write/%s/%s' % (mcu_id, value)
        mcu.write(cmd.encode())
        mcu.close()

    def start_sampling(self):
        # Sampling using thread
        try:
            sampling_t = Thread(target=self.sampling,
                                args=(self.dev_sampling_period,))
            sampling_t.setDaemon(True)
            listening_t = Thread(target=self.listen_socket)
            listening_t.setDaemon(True)
            sampling_t.start()
            listening_t.start()
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.ws.close()
            logging.error('Client terminated')
        except:
            logging.error('Sampling thread error')

    def listen_socket(self):
        # Socket listening
        logging.debug('Listening socket')
        while(True):
            try:
                msg = json.loads(self.ws.recv())
            except WebSocketConnectionClosedException:
                logging.error('Server has closed the connection')
                sys.exit(0)
            except KeyboardInterrupt:
                logging.error('Client terminated')
                sys.exit(0)
            logging.debug('New message : %s', msg)
            if 'action' in msg:
                if(msg['action'] == 'install_fw'):
                    # Firmware update required, extract version from message
                    new_version = msg['version']
                    if new_version:
                        self.install_firmware(new_version)
                if(msg['action'] == 'activateIO'):
                    io_type = msg['type']
                    io_pin = msg['pin'] if 'pin' in msg else 0
                    datastream_id = msg['datastream_id']
                    self.activateIO(datastream_id, io_type, io_pin)
            else:
                ds = [ds['id'] for ds in self.datastream_suscriptions]
                if 'value' in msg and msg['datastream_id'] in ds:
                    self.write_actuator(msg['datastream_id'], msg['value'])

    def install_firmware(self, new_version):
        logging.info('Update firmware request')
        logging.info('Current firmware version: {}'.format(
            self.firmware_version))
        logging.info('Firmware version to install: {}'.format(new_version))
        fw_fname_prefix = 'sensa-%s' % new_version
        fw_check_url = '%sstatic/firmware/%s.chk' % (
            self.api_url, fw_fname_prefix)
        fw_filename = fw_fname_prefix + '.zip'
        fw_url = '%sstatic/firmware/%s' % (self.api_url, fw_filename)
        # Firmware install shell script
        deploy_script = 'deploy.sh'

        # Download firmware
        fw_file = URLopener()
        try:
            fw_file.retrieve(fw_url, fw_filename)
        except IOError:
            logging.error('Error during firmware download')
            return 1
        fw_file.close()

        # Check downloaded firmware integrity
        try:
            fw_checksum_req = requests.get(fw_check_url)
        except requests.exceptions.RequestException:
            logging.error('Error during firmware download')
            return 1
        expected_check = fw_checksum_req.text.split()

        fw_checksum = md5(open(fw_filename, 'rb').read()).hexdigest()
        if(fw_checksum != expected_check[0] and
           fw_filename != expected_check[1]):
            logging.error('Error checking firmware integrity')
            return

        logging.info('Files checked. Updating')
        # Unzip
        try:
            fw_file = ZipFile(fw_filename, 'r')
        except IOError:
            logging.error('Error reading local firmware file')
            return
        fw_file.extractall()
        fw_file.close()

        # Run firmware script
        call(['sh', deploy_script])
        # Remove firmware file
        call(['rm', fw_filename])
        # Remove firmware script
        call(['rm', deploy_script])
        config = SafeConfigParser()
        config.read(self.config_file)
        # Update firmware version on config file
        config.set('device', 'firmware_version', new_version)
        try:
            conf_file = open(self.config, 'wb')
            try:
                parser.write(conf_file)
            finally:
                conf_file.close()
        except IOError:
            logging.error('Error updating version on config file')

        '''
        # Update firmware version on server
        payload = {}
        payload['firmware'] = new_version
        try:
            requests.post(self.firmware_version_url, data=payload)
        except:
            print 'Error updating table version on server'

        print 'FIRMWARE UPDATED. New version', new_version
        '''

    def initialize_switches(self):
        ''' Request the values stored on the API and turn on the corresponding
            switches
        '''
        response = requests.get(self.device_url, headers=self.api_hdrs)
        datastreams = json.loads(response.text)['datastreams']
        try:
            mcu = serial.Serial(self.dev_port, self.dev_baud, timeout=3)
        except serial.SerialException:
            logging.error('MCU can not be found or can not be configured')
            return 0
        for ds in self.datastream_suscriptions:
            if ds['id'] in [d['id'] for d in datastreams]:
                value = [d['current'] for d in datastreams
                         if d['id'] == ds['id']][0]
                if value is None:
                    continue
                value = int(value)
                if ds['type'] == 'BIN_RSWITCH':
                    if(value == 1):
                        value = 0
                    else:
                        value = 1
                elif value != 1:
                    continue
                msg = 'Writing %s on %s in pin %s' % (
                    value, ds['type'], ds['pin'])
                logging.debug(msg)
                cmd = 'd/%s/%s' % (ds['pin'], value)
                mcu.write(cmd.encode())
        mcu.close()


def check_connection():
    # Wait for internet connection
    while(1):
        try:
            requests.get('http://www.google.cl', timeout=3)
            break
        except requests.Timeout:
            time.sleep(15)
            logging.error('Internet connection timeout error')
        except requests.ConnectionError:
            time.sleep(15)
            logging.error('Internet connection error')
    logging.info('Internet connection available')


if __name__ == '__main__':
    # Parse command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output.')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Enable debug output.')
    parser.add_argument('-s', '--store', action='store_true',
                        help='Store registered data on db.')
    args = parser.parse_args()

    # Logging configuration
    logging_level = logging.DEBUG if args.debug else logging.INFO
    if not args.verbose:
        logging.basicConfig(
            level=logging_level,
            format='%(asctime)s %(levelname)s: %(message)s.',
            filename='/root/log/sensa-client.log'
        )
    else:
        logging.basicConfig(
            level=logging_level,
            format='%(asctime)s %(levelname)s: %(message)s.'
        )
    logging.getLogger('requests').setLevel(logging.WARNING)

    check_connection()
    if args.store:
        client = Client(store_data=True)
        logging.debug('Data will be stored on db file')
    else:
        client = Client(store_data=False)
    client.connect_socket()
    client.start_sampling()
